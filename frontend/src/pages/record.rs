//! Point recording page: single MP4 `MediaRecorder`, in-memory chunk queue with keyframe parsing, IndexedDB upload queue, match-status polling.
//! The first chunk of each recording session is normalized to include `ftyp`+`moov` and to start on a video keyframe (`record_mp4::session_first_chunk`).

use crate::api;
use crate::types::{RecordMatchStatusResponse, RecordPointData};
use crate::Route;
use dioxus::core::use_drop;
use dioxus::prelude::*;
use std::cell::RefCell;
use std::collections::{HashMap, HashSet, VecDeque};
use std::rc::Rc;

#[cfg(target_arch = "wasm32")]
use crate::api::RecordChunkMeta;
#[cfg(target_arch = "wasm32")]
use crate::record_idb;
#[cfg(target_arch = "wasm32")]
use wasm_bindgen::JsCast;
#[cfg(target_arch = "wasm32")]
use wasm_bindgen::closure::Closure;
#[cfg(target_arch = "wasm32")]
use crate::record_mp4;

/// Must match MediaRecorder `timeslice` / `RecordChunkMeta.chunk_length_ms` on every enqueue path.
#[cfg(target_arch = "wasm32")]
const RECORD_CHUNK_LENGTH_MS: u32 = 500;

/// High-resolution timestamps and structured `[record]` lines for debugging the recording pipeline in DevTools.
#[cfg(target_arch = "wasm32")]
fn record_now_ms() -> f64 {
    web_sys::window()
        .and_then(|w| w.performance())
        .map(|p| p.now())
        .unwrap_or_else(js_sys::Date::now)
}

#[cfg(target_arch = "wasm32")]
fn record_log(msg: &str) {
    web_sys::console::log_1(&format!("[record] {}", msg).into());
}

#[cfg(target_arch = "wasm32")]
fn record_log_duration(label: &str, t0: f64) {
    let dt = record_now_ms() - t0;
    record_log(&format!("{} → {:.2} ms", label, dt));
}

/// Request screen wake lock and wire `release` to re-acquire (browsers often drop the lock without tab hide).
#[cfg(target_arch = "wasm32")]
fn schedule_screen_wake_lock_acquire(mut sentinel_sig: Signal<Option<wasm_bindgen::JsValue>>) {
    use wasm_bindgen::JsValue;
    wasm_bindgen_futures::spawn_local(async move {
        let window = match web_sys::window() {
            Some(w) => w,
            None => return,
        };
        let navigator = window.navigator();
        let wake_lock_js = match js_sys::Reflect::get(&navigator, &JsValue::from_str("wakeLock")) {
            Ok(v) if !v.is_undefined() && !v.is_null() => v,
            _ => return,
        };
        let request_js = match js_sys::Reflect::get(&wake_lock_js, &JsValue::from_str("request")) {
            Ok(v) if v.is_function() => v,
            _ => return,
        };
        let request_fn = match request_js.dyn_ref::<js_sys::Function>() {
            Some(f) => f,
            None => return,
        };
        let promise = match request_fn
            .call1(&wake_lock_js, &JsValue::from_str("screen"))
            .ok()
            .and_then(|v| v.dyn_into::<js_sys::Promise>().ok())
        {
            Some(p) => p,
            None => return,
        };
        let result = wasm_bindgen_futures::JsFuture::from(promise).await;
        let sentinel = match result {
            Ok(s) => s,
            Err(_) => return,
        };
        sentinel_sig.set(Some(sentinel.clone()));

        let release_cb = Closure::wrap(Box::new({
            let mut sentinel_sig = sentinel_sig.clone();
            move || {
                sentinel_sig.set(None);
                schedule_screen_wake_lock_acquire(sentinel_sig.clone());
            }
        }) as Box<dyn FnMut()>);
        if let Ok(add) = js_sys::Reflect::get(&sentinel, &JsValue::from_str("addEventListener")) {
            if let Some(f) = add.dyn_ref::<js_sys::Function>() {
                let _ = f.call3(
                    &sentinel,
                    &JsValue::from_str("release"),
                    release_cb.as_ref().unchecked_ref(),
                    &JsValue::UNDEFINED,
                );
            }
        }
        release_cb.forget();
    });
}

/// Stop a `MediaRecorder` and wait for its `stop` event before returning.
///
/// Rationale: creating a new recorder too early can overlap cleanup/final `dataavailable` in some browsers.
#[cfg(target_arch = "wasm32")]
async fn stop_media_recorder_fully(rec: web_sys::MediaRecorder) {
    use wasm_bindgen::JsValue;
    use wasm_bindgen_futures::JsFuture;

    let t_stop = record_now_ms();
    record_log("MediaRecorder: stop_media_recorder_fully → begin (requestData + stop + await onstop)");

    let resolve_fn: Rc<RefCell<Option<js_sys::Function>>> = Rc::new(RefCell::new(None));
    let resolve_fn_c = resolve_fn.clone();
    let promise = js_sys::Promise::new(&mut move |resolve, _reject| {
        if let Some(f) = resolve.dyn_ref::<js_sys::Function>() {
            *resolve_fn_c.borrow_mut() = Some(f.clone());
        }
    });

    let resolve_fn_for_stop = resolve_fn.clone();
    let onstop = Closure::wrap(Box::new(move || {
        if let Some(f) = resolve_fn_for_stop.borrow_mut().take() {
            let _ = f.call0(&JsValue::UNDEFINED);
        }
    }) as Box<dyn FnMut()>);
    rec.set_onstop(Some(onstop.as_ref().unchecked_ref()));
    onstop.forget();

    // Best effort: request a final `dataavailable` before stop.
    let _ = rec.request_data();
    let _ = rec.stop();

    // Wait for stop event to fire.
    let _ = JsFuture::from(promise).await;

    // Detach handlers to allow GC and prevent late events calling into stale closures.
    rec.set_onstop(None);
    rec.set_ondataavailable(None);
    record_log_duration("MediaRecorder: stop_media_recorder_fully (total)", t_stop);
}

/// Re-request wake lock when the tab becomes visible (lock is released while hidden) and on first pointer (gesture requirement on many phones).
#[cfg(target_arch = "wasm32")]
fn register_screen_wake_lock_listeners(sentinel_sig: Signal<Option<wasm_bindgen::JsValue>>) {
    use wasm_bindgen::closure::Closure;
    let Some(window) = web_sys::window() else {
        return;
    };
    let Some(doc) = window.document() else {
        return;
    };

    let vis = Closure::wrap(Box::new({
        let mut sentinel_sig = sentinel_sig.clone();
        move || {
            if let Some(w) = web_sys::window() {
                if let Some(d) = w.document() {
                    if !d.hidden() {
                        schedule_screen_wake_lock_acquire(sentinel_sig.clone());
                    }
                }
            }
        }
    }) as Box<dyn FnMut()>);
    let _ = doc.add_event_listener_with_callback("visibilitychange", vis.as_ref().unchecked_ref());
    vis.forget();

    let bootstrapped = std::cell::Cell::new(false);
    let ptr = Closure::wrap(Box::new({
        let mut sentinel_sig = sentinel_sig.clone();
        move || {
            if bootstrapped.replace(true) {
                return;
            }
            schedule_screen_wake_lock_acquire(sentinel_sig.clone());
        }
    }) as Box<dyn FnMut()>);
    let _ = window.add_event_listener_with_callback("pointerdown", ptr.as_ref().unchecked_ref());
    ptr.forget();
}

/// In-memory recording FSM: `Recording` while `in_point_recording_window`; chunks flush to IndexedDB only in `Recording`.
#[cfg(target_arch = "wasm32")]
#[derive(Clone, Copy, PartialEq, Eq)]
enum RecordFsm {
    Idle,
    Recording,
}

#[cfg(target_arch = "wasm32")]
struct MemVideoChunk {
    blob: web_sys::Blob,
    blob_event_timestamp_ms: f64,
    wall_epoch_ms: f64,
    keyframe_wall_times_ms: Vec<f64>,
    sync_samples: Vec<record_mp4::SyncSampleWall>,
    parsed: bool,
}

#[cfg(target_arch = "wasm32")]
enum MemQueueItem {
    Video(MemVideoChunk),
    FinalizeMatch { match_id: String },
}

/// In-memory queue item: key references chunk or finalize in IndexedDB.
#[cfg(target_arch = "wasm32")]
enum QueueItem {
    Chunk { match_id: Option<String> },
    FinalizeMatch { match_id: String },
}

/// Log queue length and indices of items that contain at least one video keyframe (`sync_samples` after parse).
#[cfg(target_arch = "wasm32")]
fn record_log_mem_queue_snapshot(mem_queue: &Rc<RefCell<VecDeque<MemQueueItem>>>) {
    let q = mem_queue.borrow();
    let len = q.len();
    let mut keyframe_indices: Vec<usize> = Vec::new();
    let mut per_slot: Vec<String> = Vec::new();
    for (i, item) in q.iter().enumerate() {
        match item {
            MemQueueItem::Video(ch) => {
                let n = ch.sync_samples.len();
                if n > 0 {
                    keyframe_indices.push(i);
                }
                let tag = if !ch.parsed {
                    "unparsed"
                } else if n > 0 {
                    "keyframes"
                } else {
                    "no_keyframes"
                };
                per_slot.push(format!("{}:{}({} sync)", i, tag, n));
            }
            MemQueueItem::FinalizeMatch { .. } => {
                per_slot.push(format!("{}:finalize", i));
            }
        }
    }
    record_log(&format!(
        "mem_queue: len={} keyframe_chunk_indices={:?} [{}]",
        len,
        keyframe_indices,
        per_slot.join(", ")
    ));
}

/// LocalStorage key for the selected camera device ID (wasm only).
#[cfg(target_arch = "wasm32")]
const RECORD_CAMERA_DEVICE_ID_KEY: &str = "arctos_record_camera_id";

#[cfg(target_arch = "wasm32")]
fn get_stored_camera_device_id() -> Option<String> {
    web_sys::window()
        .and_then(|w| w.local_storage().ok().flatten())
        .and_then(|s| s.get_item(RECORD_CAMERA_DEVICE_ID_KEY).ok().flatten())
        .filter(|s| !s.is_empty())
}

#[cfg(target_arch = "wasm32")]
fn set_stored_camera_device_id(device_id: &str) {
    if let Some(storage) = web_sys::window().and_then(|w| w.local_storage().ok().flatten()) {
        let _ = storage.set_item(RECORD_CAMERA_DEVICE_ID_KEY, device_id);
    }
}

#[cfg(target_arch = "wasm32")]
fn reload_record_page() {
    if let Some(window) = web_sys::window() {
        let _ = window.location().reload();
    }
}

/// Persist camera device ID and do a full page reload so the new camera is used (wasm only).
#[cfg(target_arch = "wasm32")]
fn on_camera_selection_changed(device_id: &str) {
    set_stored_camera_device_id(device_id);
    reload_record_page();
}

#[cfg(not(target_arch = "wasm32"))]
fn on_camera_selection_changed(_device_id: &str) {}

/// Full page reload to the record URL with the new camera_name query param (wasm only).
#[cfg(target_arch = "wasm32")]
fn reload_record_page_with_camera_name(_url: &str, field: &str, camera_key: &str, camera_name: &str) {
    if let Some(window) = web_sys::window() {
        let loc = window.location();
        let pathname: String = loc.pathname().unwrap_or_default();
        let base = pathname
            .trim_end_matches("/record")
            .trim_end_matches('/');
        let new_url = format!(
            "{}/record?field={}&camera_key={}&camera_name={}",
            base,
            urlencoding::encode(field),
            urlencoding::encode(camera_key),
            urlencoding::encode(camera_name),
        );
        let _ = loc.assign(&new_url);
    }
}

#[cfg(not(target_arch = "wasm32"))]
fn reload_record_page_with_camera_name(_url: &str, _field: &str, _camera_key: &str, _camera_name: &str) {
    // No-op on non-wasm; record page is used in browser only.
}

#[component]
pub fn Record(url: String, field: ReadSignal<String>, camera_key: ReadSignal<String>, camera_name: ReadSignal<String>) -> Element {
    let route: Route = use_route();
    let route_clone1 = route.clone();
    let route_clone2 = route.clone();
    let field_opt = use_memo(move || {
        let f = match route_clone1 {
            Route::Record { field: ref f, .. } => f.clone(),
            _ => field(),
        };
        if f.is_empty() { None } else { Some(f) }
    });
    let key_opt = use_memo(move || {
        let k = match route_clone2 {
            Route::Record { camera_key: ref k, .. } => k.clone(),
            _ => camera_key(),
        };
        if k.is_empty() { None } else { Some(k) }
    });
    let _nav = use_navigator();

    let url_for_load = url.clone();
    let mut tournament_name = use_signal(|| None::<String>);
    let _load_tournament = use_resource(move || {
        let url = url_for_load.clone();
        async move {
            match api::tournament_detail(&url).await {
                Ok(d) => Some(d.tournament.name),
                Err(_) => None,
            }
        }
    });
    use_effect(move || {
        if let Some(name) = _load_tournament().flatten() {
            tournament_name.set(Some(name));
        }
    });

    let mut status = use_signal(|| RecordStatus::Checking);
    let mut match_status_data = use_signal(|| None::<RecordMatchStatusResponse>);
    // 1. Create a clone specifically for the initial name memo
    let route_for_memo = route.clone();
    let initial_camera_name = use_memo(move || {
        if let Route::Record { camera_name, .. } = &route_for_memo {
            if !camera_name.is_empty() {
                return camera_name.clone();
            }
        }
        "camera-1".to_string()
    });

    let mut camera_name = use_signal(|| initial_camera_name());
    let mut is_editing_name = use_signal(|| false);
    let mut temp_name = use_signal(|| initial_camera_name()); 

    // 2. The original `route` is still available here to be moved into this closure

    let mut is_recording = use_signal(|| false);
    let mut is_uploading = use_signal(|| false);
    let mut upload_count = use_signal(|| 0u32);
    let mut upload_total = use_signal(|| 0u32);
    let mut available_cameras = use_signal(|| Vec::<(String, String)>::new());
    let mut selected_camera_id = use_signal(|| None::<String>);
    let mut preview_stream = use_signal(|| None::<web_sys::MediaStream>);
    let mut storage_warning = use_signal(|| None::<String>);

    #[cfg(target_arch = "wasm32")]
    {
        let available_cameras_sig = available_cameras.to_owned();
        let selected_camera_id_sig = selected_camera_id.to_owned();
        let preview_stream_sig = preview_stream.to_owned();
        let status_sig = status.to_owned();
        use_effect(move || {
            spawn(async move {
                initialize_camera_and_enumerate(
                    available_cameras_sig,
                    selected_camera_id_sig,
                    preview_stream_sig,
                    status_sig,
                )
                .await;
            });
        });
    }

    // Screen wake lock: keep the device awake the entire time this page is open (wasm only).
    // Initial request may fail without a user gesture; first pointerdown + visibility + release re-acquire.
    #[cfg(target_arch = "wasm32")]
    {
        let wake_lock_sentinel = use_signal(|| None::<wasm_bindgen::JsValue>);
        use_effect(move || {
            let sentinel_sig = wake_lock_sentinel.to_owned();
            schedule_screen_wake_lock_acquire(sentinel_sig.clone());
            register_screen_wake_lock_listeners(sentinel_sig);
        });
        let wake_lock_for_drop = wake_lock_sentinel.to_owned();
        use_drop(move || {
            if let Some(sentinel) = wake_lock_for_drop() {
                let release_js = js_sys::Reflect::get(&sentinel, &wasm_bindgen::JsValue::from_str("release")).ok();
                if let Some(release_fn) = release_js.and_then(|f| f.dyn_ref::<js_sys::Function>().map(|f| f.clone())) {
                    let _ = release_fn.call0(&sentinel);
                }
            }
        });
    }

    // Stop camera and clear video when leaving the record page (wasm only).
    #[cfg(target_arch = "wasm32")]
    {
        let preview_stream_for_drop = preview_stream.to_owned();
        use_drop(move || {
            if let Some(stream) = preview_stream_for_drop() {
                let tracks = stream.get_tracks();
                for i in 0..tracks.length() {
                    if let Some(track) = tracks.get(i).dyn_ref::<web_sys::MediaStreamTrack>() {
                        track.stop();
                    }
                }
            }
            if let Some(window) = web_sys::window() {
                if let Some(doc) = window.document() {
            if let Some(el) = doc.get_element_by_id("record-preview-capture") {
                let _ = el.dyn_into::<web_sys::HtmlMediaElement>().map(|media| {
                    let _ = media.pause();
                    media.set_src_object(None);
                });
            }
                }
            }
        });
    }

    // When we have stream + field + key, start the MP4 recorder and the monitor/upload loop (wasm only).
    #[cfg(target_arch = "wasm32")]
    {
        let poll_url = url.clone();
        let poll_field = field_opt;
        let poll_key = key_opt;
        let status_sig = status.to_owned();
        let match_status_data_sig = match_status_data.to_owned();
        let camera_name_sig = camera_name.to_owned();
        let is_recording_sig = is_recording.to_owned();
        let is_uploading_sig = is_uploading.to_owned();
        let upload_count_sig = upload_count.to_owned();
        let upload_total_sig = upload_total.to_owned();
        let storage_warning_sig = storage_warning.to_owned();
        let preview_stream_sig = preview_stream.to_owned();
        use_effect(move || {
            let stream_opt = preview_stream_sig();
            let field_val = poll_field();
            let key_val = poll_key();
            if stream_opt.is_none() || field_val.is_none() || key_val.is_none() {
                return;
            }
            let stream = stream_opt.unwrap();
            let stream_for_loop = stream.clone();
            let field = field_val.unwrap();
            let key = key_val;
            let tournament_url = poll_url.clone();
            let camera_name_str = camera_name_sig();
            spawn(async move {
                run_recording_loop(
                    stream_for_loop,
                    tournament_url,
                    field,
                    key,
                    camera_name_str.clone(),
                    status_sig,
                    match_status_data_sig,
                    is_recording_sig,
                    is_uploading_sig,
                    upload_count_sig,
                    upload_total_sig,
                    storage_warning_sig,
                )
                .await;
            });
        });
    }

    let field_val = field_opt();
    let key_val = key_opt();
    let title_field = field_val.as_deref().unwrap_or("");
    let error_message = match (&field_val, &key_val) {
        (None, _) => Some("Field name is required."),
        (Some(f), _) if f.is_empty() => Some("Field name is required."),
        (_, None) => Some("Camera access key is required."),
        (_, Some(k)) if k.is_empty() => Some("Camera access key is required."),
        _ => None,
    };

    rsx! {
        div { class: "container mt-4",
            div { class: "row",
                div { class: "col-12",
                    Link { to: Route::TournamentHome { url: url.clone() }, "← Tournament home" }
                    h1 { class: "mt-2", "Point Recording [BETA] - {title_field}" }
                    if let Some(name) = tournament_name() {
                        p { class: "lead", "Tournament: {name}" }
                    } else {
                        p { class: "lead", "Tournament: {url}" }
                    }
                }
            }

            if let Some(msg) = error_message {
                div { class: "row mt-4",
                    div { class: "col-12",
                        div { class: "alert alert-danger",
                            "⚠ {msg}"
                        }
                    }
                }
            } else {
                div { class: "row mt-4",
                    div { class: "col-12",
                        div { class: "card",
                            div { class: "card-body",
                                div { class: "mb-3",
                                    label { class: "form-label", "Camera Name" }
                                    if is_editing_name() {
                                        div { class: "input-group",
                                            input {
                                                r#type: "text",
                                                class: "form-control",
                                                value: "{temp_name()}",
                                                oninput: move |ev| temp_name.set(ev.value()),
                                            }
                                            button { 
                                                class: "btn btn-success", 
                                                onclick: move |_| {
                                                    let new_name = temp_name();
                                                    // Full navigation reloads the app — only when the name actually changes (avoids accidental mobile reloads).
                                                    if new_name.trim() != camera_name().trim() {
                                                        if let Route::Record { url, field, camera_key, .. } = route.clone() {
                                                            reload_record_page_with_camera_name(&url, &field, &camera_key, &new_name.trim());
                                                        }
                                                    }
                                                    is_editing_name.set(false);
                                                },
                                                "Save" 
                                            }
                                            button { 
                                                class: "btn btn-outline-secondary", 
                                                onclick: move |_| {
                                                    is_editing_name.set(false);
                                                    temp_name.set(camera_name()); // Reset
                                                },
                                                "Cancel" 
                                            }
                                        }
                                    } else {
                                        div { class: "d-flex align-items-center gap-2",
                                            span { class: "form-control-plaintext fs-5 fw-bold", "{camera_name()}" }
                                            button { 
                                                class: "btn btn-sm btn-outline-primary",
                                                onclick: move |_| {
                                                    temp_name.set(camera_name());
                                                    is_editing_name.set(true);
                                                },
                                                "Edit"
                                            }
                                        }
                                    }
                                }
                                div { class: "mb-3 d-flex align-items-center gap-2",
                                    span { class: "fw-semibold",
                                        "Current match: {match_status_data().and_then(|d| d.match_name).unwrap_or_else(|| \"None\".to_string())}"
                                    }
                                    if is_recording() {
                                        span { class: "badge bg-danger", "● REC" }
                                    }
                                }
                                div { class: "mb-3",
                                    label { r#for: "camera-select", class: "form-label", "Select Camera:" }
                                    select {
                                        id: "camera-select",
                                        class: "form-select",
                                        onchange: move |ev| {
                                            let value = ev.value();
                                            if !value.is_empty() {
                                                on_camera_selection_changed(&value);
                                            }
                                        },
                                        if available_cameras().is_empty() {
                                            option { value: "", "Loading cameras..." }
                                        } else {
                                            option { value: "", "Select a camera..." }
                                            for (idx, (device_id, label)) in available_cameras().iter().enumerate() {
                                                option {
                                                    value: "{device_id}",
                                                    selected: selected_camera_id().as_ref().map(|id| id == device_id).unwrap_or(idx == 0),
                                                    "{label}"
                                                }
                                            }
                                        }
                                    }
                                }
                                div { class: "alert alert-info", id: "record-status",
                                    status_line { status }
                                }
                                upload_progress_section {
                                    is_uploading,
                                    upload_count,
                                    upload_total,
                                }
                                if let Some(ref msg) = storage_warning() {
                                    div { class: "alert alert-warning", "{msg}" }
                                }
                                if matches!(status(), RecordStatus::NoMatch) && !is_recording() {
                                    div { class: "alert alert-secondary", id: "record-no-match",
                                        "No active match on this field. Waiting for match to start..."
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn upload_progress_section(
    is_uploading: Signal<bool>,
    upload_count: Signal<u32>,
    upload_total: Signal<u32>,
) -> Element {
    let total = upload_total();
    let done = upload_count();
    let remaining = total.saturating_sub(done);
    let pct = if total > 0 {
        (100.0_f64 * f64::from(done) / f64::from(total.max(1))).min(100.0)
    } else {
        0.0
    };
    let status_text = if total == 0 {
        "No uploads queued".to_string()
    } else if remaining == 0 {
        "All data uploaded".to_string()
    } else {
        format!(
            "{done} of {total} finished uploading ({remaining} remaining){}",
            if is_uploading() {
                " — working…"
            } else {
                ""
            }
        )
    };

    rsx! {
        div { class: "mt-3",
            h6 { "Upload progress" }
            p {
                class: "mb-1 small text-muted",
                "{status_text}"
            }
            if total > 0 {
                div {
                    class: "progress",
                    style: "height: 12px;",
                    div {
                        class: "progress-bar bg-success",
                        role: "progressbar",
                        style: format!("width: {pct:.2}%;"),
                    }
                }
            }
        }
    }
}

#[derive(Clone, PartialEq, Debug)]
enum RecordStatus {
    Checking,
    Connected,
    NoMatch,
    Error(String),
}

#[component]
fn status_line(status: Signal<RecordStatus>) -> Element {
    let s = status();
    let (class, text) = match s {
        RecordStatus::Checking => ("alert alert-info", "Checking for active match...".to_string()),
        RecordStatus::Connected => {
            ("alert alert-success", "Camera ready. Waiting for match...".to_string())
        }
        RecordStatus::NoMatch => ("alert alert-secondary", "No active match. Waiting...".to_string()),
        RecordStatus::Error(ref e) => ("alert alert-danger", e.clone()),
    };
    rsx! {
        div { class: "{class}", "{text}" }
    }
}

#[cfg(target_arch = "wasm32")]
async fn initialize_camera_and_enumerate(
    mut available_cameras: Signal<Vec<(String, String)>>,
    mut selected_camera_id: Signal<Option<String>>,
    mut preview_stream: Signal<Option<web_sys::MediaStream>>,
    mut status: Signal<RecordStatus>,
) {
    use wasm_bindgen::JsCast;
    use wasm_bindgen_futures::JsFuture;
    use web_sys::MediaStreamConstraints;

    let t_cam = record_now_ms();
    record_log("initialize_camera: start (getUserMedia + enumerate + device-specific stream)");

    let window = match web_sys::window() {
        Some(w) => w,
        None => return,
    };
    let navigator = window.navigator();
    let media_devices = match navigator.media_devices() {
        Ok(d) => d,
        Err(_) => {
            status.set(RecordStatus::Error("Media devices not available".to_string()));
            return;
        }
    };

    // Use Safari-friendly constraints: start with 1280x720 ideal; Safari/iOS often fails on 1080p+.
    let mut constraints = MediaStreamConstraints::new();
    let mut video_ideal = js_sys::Object::new();
    let w = js_sys::Object::new();
    js_sys::Reflect::set(&w, &"ideal".into(), &3840.into()).ok();
    js_sys::Reflect::set(&video_ideal, &"width".into(), &w.into()).ok();
    let h = js_sys::Object::new();
    js_sys::Reflect::set(&h, &"ideal".into(), &2160.into()).ok();
    js_sys::Reflect::set(&video_ideal, &"height".into(), &h.into()).ok();
    constraints.video(&video_ideal.into());
    constraints.audio(&true.into());

    let promise = match media_devices.get_user_media_with_constraints(&constraints) {
        Ok(p) => p,
        Err(_) => {
            status.set(RecordStatus::Error("Failed to request camera permission".to_string()));
            return;
        }
    };

    let initial_stream = match JsFuture::from(promise).await {
        Ok(stream) => match stream.dyn_into::<web_sys::MediaStream>() {
            Ok(s) => s,
            Err(_) => {
                status.set(RecordStatus::Error("Failed to get camera stream".to_string()));
                return;
            }
        },
        Err(_) => {
            // Safari/iOS may reject with resolution; retry with no video constraints.
            let mut fallback = MediaStreamConstraints::new();
            fallback.video(&true.into());
            fallback.audio(&true.into());
            let fallback_p = match media_devices.get_user_media_with_constraints(&fallback) {
                Ok(p) => p,
                Err(_) => {
                    status.set(RecordStatus::Error("Camera permission denied".to_string()));
                    return;
                }
            };
            match JsFuture::from(fallback_p).await {
                Ok(stream) => match stream.dyn_into::<web_sys::MediaStream>() {
                    Ok(s) => s,
                    Err(_) => {
                        status.set(RecordStatus::Error("Failed to get camera stream".to_string()));
                        return;
                    }
                },
                Err(_) => {
                    status.set(RecordStatus::Error("Camera permission denied".to_string()));
                    return;
                }
            }
        }
    };

    let devices_promise = match media_devices.enumerate_devices() {
        Ok(p) => p,
        Err(_) => {
            status.set(RecordStatus::Error("Failed to enumerate devices".to_string()));
            return;
        }
    };
    let devices_result = JsFuture::from(devices_promise).await;
    let devices = match devices_result {
        Ok(devices) => devices,
        Err(_) => {
            status.set(RecordStatus::Error("Failed to enumerate devices".to_string()));
            return;
        }
    };

    let devices_array = js_sys::Array::from(&devices);
    let mut cameras = Vec::new();
    for i in 0..devices_array.length() {
        let device_js = devices_array.get(i);
        if let Ok(device) = device_js.dyn_into::<web_sys::MediaDeviceInfo>() {
            let kind_js =
                js_sys::Reflect::get(&device, &wasm_bindgen::JsValue::from_str("kind")).unwrap_or_default();
            let kind_str = kind_js.as_string().unwrap_or_default();
            if kind_str == "videoinput" {
                let device_id = device.device_id();
                let label = device.label();
                cameras.push((device_id, label));
            }
        }
    }

    available_cameras.set(cameras.clone());

    let chosen_id = cameras.first().and_then(|(first_id, _)| {
        let stored = get_stored_camera_device_id();
        if let Some(ref id) = stored {
            if cameras.iter().any(|(did, _)| did == id) {
                return Some(id.clone());
            }
        }
        Some(first_id.clone())
    });

    let stream = if let Some(device_id) = chosen_id {
        selected_camera_id.set(Some(device_id.clone()));
        set_stored_camera_device_id(&device_id);
        // Safari/iOS often rejects 4K; try 1080p then 720p then deviceId-only.
        let resolutions: [(u32, u32); 4] = [(3840, 2160), (1920, 1080), (1280, 720), (0, 0)];
        let mut stream_opt: Option<web_sys::MediaStream> = None;
        for (width, height) in resolutions.iter() {
            let mut specific_constraints = MediaStreamConstraints::new();
            let video_constraint = js_sys::Object::new();
            let device_id_obj = js_sys::Object::new();
            js_sys::Reflect::set(&device_id_obj, &"exact".into(), &device_id.clone().into()).ok();
            js_sys::Reflect::set(&video_constraint, &"deviceId".into(), &device_id_obj.into()).ok();
            if *width > 0 && *height > 0 {
                let w = js_sys::Object::new();
                js_sys::Reflect::set(&w, &"ideal".into(), &(*width as i32).into()).ok();
                js_sys::Reflect::set(&video_constraint, &"width".into(), &w.into()).ok();
                let h = js_sys::Object::new();
                js_sys::Reflect::set(&h, &"ideal".into(), &(*height as i32).into()).ok();
                js_sys::Reflect::set(&video_constraint, &"height".into(), &h.into()).ok();
            }
            specific_constraints.video(&video_constraint.into());
            specific_constraints.audio(&true.into());

            let promise = match media_devices.get_user_media_with_constraints(&specific_constraints) {
                Ok(p) => p,
                Err(_) => continue,
            };
            if let Ok(stream_result) = JsFuture::from(promise).await {
                if let Ok(s) = stream_result.dyn_into::<web_sys::MediaStream>() {
                    let tracks = initial_stream.get_tracks();
                    for i in 0..tracks.length() {
                        if let Some(track) = tracks.get(i).dyn_ref::<web_sys::MediaStreamTrack>() {
                            track.stop();
                        }
                    }
                    stream_opt = Some(s);
                    break;
                }
            }
        }
        stream_opt.unwrap_or_else(|| initial_stream)
    } else {
        initial_stream
    };

    preview_stream.set(Some(stream.clone()));
    record_log_duration("initialize_camera: complete (total)", t_cam);
}

/// Parse ISO timestamp string to milliseconds since epoch.
#[cfg(target_arch = "wasm32")]
fn parse_iso_ms(s: Option<&str>) -> Option<f64> {
    let s = s?.trim();
    chrono::DateTime::parse_from_rfc3339(s)
        .ok()
        .map(|dt| dt.timestamp_millis() as f64)
        .or_else(|| {
            let with_z = if s.ends_with('Z') || s.contains('+') || (s.len() > 10 && s.contains('-')) {
                s.to_string()
            } else {
                format!("{}Z", s.trim_end_matches('z').trim_end_matches('Z'))
            };
            chrono::DateTime::parse_from_rfc3339(&with_z).ok().map(|dt| dt.timestamp_millis() as f64)
        })
}

/// True if `now` is during a point or within 3s before start / after end (recording FSM window).
#[cfg(target_arch = "wasm32")]
fn in_point_recording_window(points: &[RecordPointData], now_ms: f64) -> bool {
    points.iter().any(|p| {
        let Some(start_ms) = parse_iso_ms(p.stamp.as_deref()) else {
            return false;
        };
        if now_ms < start_ms - 3000.0 {
            return false;
        }
        match p.end_stamp.as_deref().and_then(|s| parse_iso_ms(Some(s))) {
            Some(end_ms) => now_ms <= end_ms + 3000.0,
            None => true,
        }
    })
}

/// Minimum point start time among points whose ±3s recording window contains `now_ms`.
#[cfg(target_arch = "wasm32")]
fn min_point_start_ms_in_recording_window(points: &[RecordPointData], now_ms: f64) -> Option<f64> {
    let mut min: Option<f64> = None;
    for p in points {
        let Some(start_ms) = parse_iso_ms(p.stamp.as_deref()) else {
            continue;
        };
        if now_ms < start_ms - 3000.0 {
            continue;
        }
        match p.end_stamp.as_deref().and_then(|s| parse_iso_ms(Some(s))) {
            Some(end_ms) if now_ms > end_ms + 3000.0 => continue,
            _ => {}
        }
        min = Some(match min {
            Some(m) => m.min(start_ms),
            None => start_ms,
        });
    }
    min
}

#[cfg(target_arch = "wasm32")]
fn blob_event_wall_epoch_ms(ev: &web_sys::BlobEvent) -> f64 {
    web_sys::window()
        .and_then(|w| w.performance())
        .map(|p| p.time_origin() + ev.time_stamp())
        .unwrap_or_else(|| js_sys::Date::now())
}

#[cfg(target_arch = "wasm32")]
async fn blob_to_bytes(blob: &web_sys::Blob) -> Vec<u8> {
    let promise = blob.array_buffer();
    let ab = wasm_bindgen_futures::JsFuture::from(promise)
        .await
        .unwrap_or_else(|_| wasm_bindgen::JsValue::UNDEFINED);
    let uint8 = js_sys::Uint8Array::new(&ab);
    let mut out = vec![0u8; uint8.length() as usize];
    uint8.copy_to(&mut out);
    out
}

#[cfg(target_arch = "wasm32")]
fn bytes_to_blob(bytes: &[u8]) -> web_sys::Blob {
    let arr = js_sys::Uint8Array::from(bytes);
    let parts = js_sys::Array::new();
    parts.push(&arr);
    web_sys::Blob::new_with_u8_array_sequence(&parts).expect("Blob::new")
}

#[cfg(target_arch = "wasm32")]
async fn parse_mem_video_chunk(
    ch: &mut MemVideoChunk,
    cached_timescale: &Rc<RefCell<Option<u32>>>,
    cached_init: &Rc<RefCell<Option<Vec<u8>>>>,
) {
    if ch.parsed {
        return;
    }
    let t_parse = record_now_ms();
    let t_read = record_now_ms();
    let bytes = blob_to_bytes(&ch.blob).await;
    let read_ms = record_now_ms() - t_read;
    let t_mp4 = record_now_ms();
    if let Some(init) = record_mp4::extract_ftyp_moov(&bytes) {
        *cached_init.borrow_mut() = Some(init);
    }
    let ts = cached_timescale.borrow().as_ref().copied();
    let (sync, new_ts) = record_mp4::sync_sample_wall_times(&bytes, ch.wall_epoch_ms, ts);
    if let Some(t) = new_ts {
        *cached_timescale.borrow_mut() = Some(t);
    }
    ch.sync_samples = sync;
    ch.keyframe_wall_times_ms = ch.sync_samples.iter().map(|s| s.wall_epoch_ms).collect();
    ch.parsed = true;
    let mp4_ms = record_now_ms() - t_mp4;
    let total_ms = record_now_ms() - t_parse;
    record_log(&format!(
        "parse_mem_video_chunk: wall_epoch_ms={:.1} bytes={} blob_read={:.2} ms mp4_sync={:.2} ms total={:.2} ms",
        ch.wall_epoch_ms,
        bytes.len(),
        read_ms,
        mp4_ms,
        total_ms
    ));
}

/// First chunk per session: ensure `ftyp`+`moov` + fragment starting on a video keyframe (see `record_mp4::session_first_chunk`).
#[cfg(target_arch = "wasm32")]
async fn prepare_video_chunk_for_upload(
    mut ch: MemVideoChunk,
    session_id: &str,
    session_first: &Rc<RefCell<record_mp4::SessionFirstChunkState>>,
    cached_init: &Rc<RefCell<Option<Vec<u8>>>>,
    cached_timescale: &Rc<RefCell<Option<u32>>>,
) -> Option<MemVideoChunk> {
    {
        let mut s = session_first.borrow_mut();
        s.sync_session(session_id);
        if s.first_chunk_done {
            return Some(ch);
        }
    }
    let bytes = blob_to_bytes(&ch.blob).await;
    let init_cache = cached_init.borrow();
    let init_slice = init_cache.as_deref();
    let mut out: Option<MemVideoChunk> = None;
    {
        let mut s = session_first.borrow_mut();
        match record_mp4::session_first_chunk(&bytes, init_slice, &mut s) {
            record_mp4::FirstChunkOutcome::Skip => {}
            record_mp4::FirstChunkOutcome::Emit(v) => {
                ch.blob = bytes_to_blob(&v);
                ch.parsed = false;
                out = Some(ch);
            }
        }
    }
    if let Some(mut ch) = out {
        parse_mem_video_chunk(&mut ch, cached_timescale, cached_init).await;
        Some(ch)
    } else {
        None
    }
}

/// Upload drained mem-queue items to IndexedDB (video chunks + finalize rows). Used while Recording **or** Idle with an active match so the in-memory queue does not grow when the FSM is Idle.
#[cfg(target_arch = "wasm32")]
#[allow(clippy::too_many_arguments)]
async fn process_drained_mem_queue_items(
    drained: Vec<MemQueueItem>,
    db: &idb::Database,
    match_id: &str,
    session_id: &str,
    wall: f64,
    tournament_url: String,
    field: String,
    camera_name: String,
    key: Option<String>,
    container: String,
    session_first: &Rc<RefCell<record_mp4::SessionFirstChunkState>>,
    cached_init: &Rc<RefCell<Option<Vec<u8>>>>,
    cached_timescale: &Rc<RefCell<Option<u32>>>,
    pending_chunks_by_match: &Rc<RefCell<HashMap<String, u32>>>,
    upload_queue: &Rc<RefCell<VecDeque<(String, QueueItem)>>>,
) -> (usize, u32) {
    let drained_n = drained.len();
    let mut n_added = 0u32;
    for item in drained {
        match item {
            MemQueueItem::Video(ch) => {
                let Some(ch) = prepare_video_chunk_for_upload(
                    ch,
                    session_id,
                    session_first,
                    cached_init,
                    cached_timescale,
                )
                .await
                else {
                    continue;
                };
                let keyframe_wall_times_json =
                    serde_json::to_string(&ch.keyframe_wall_times_ms)
                        .unwrap_or_else(|_| "[]".to_string());
                let meta = RecordChunkMeta {
                    tournament_url: tournament_url.clone(),
                    field: field.clone(),
                    match_id: match_id.to_string(),
                    session_id: session_id.to_string(),
                    chunk_start_timestamp: ch.wall_epoch_ms,
                    recording_session_start_time: wall,
                    chunk_length_ms: RECORD_CHUNK_LENGTH_MS,
                    camera_name: camera_name.clone(),
                    key: key.clone(),
                    container: container.clone(),
                    blob_event_timestamp_ms: ch.blob_event_timestamp_ms,
                    keyframe_wall_times_json,
                };
                if let Ok(k) = record_idb::get_next_sequence(db).await {
                    if record_idb::put_chunk(db, &k, &meta, &ch.blob).await.is_ok() {
                        n_added += 1;
                        *pending_chunks_by_match
                            .borrow_mut()
                            .entry(match_id.to_string())
                            .or_insert(0) += 1;
                        upload_queue.borrow_mut().push_back((
                            k,
                            QueueItem::Chunk {
                                match_id: Some(match_id.to_string()),
                            },
                        ));
                    }
                }
            }
            MemQueueItem::FinalizeMatch { match_id: fid } => {
                if let Ok(k) = record_idb::get_next_sequence(db).await {
                    if record_idb::put_finalize(db, &k, &fid).await.is_ok() {
                        n_added += 1;
                        upload_queue.borrow_mut().push_back((
                            k,
                            QueueItem::FinalizeMatch { match_id: fid },
                        ));
                    }
                }
            }
        }
    }
    (drained_n, n_added)
}

/// Move `FinalizeMatch` from mem queue to IndexedDB upload queue; evict old video chunks (Idle only).
#[cfg(target_arch = "wasm32")]
async fn mem_queue_idle_finalize_and_evict(
    mem_queue: &Rc<RefCell<VecDeque<MemQueueItem>>>,
    db_holder: &Rc<RefCell<Option<idb::Database>>>,
    upload_queue: &Rc<RefCell<VecDeque<(String, QueueItem)>>>,
    mut upload_total_sig: Signal<u32>,
    now_ms: f64,
) {
    let t_idle = record_now_ms();
    record_log("mem_queue_idle_finalize_and_evict: begin");
    loop {
        let is_finalize = mem_queue
            .borrow()
            .front()
            .map(|it| matches!(it, MemQueueItem::FinalizeMatch { .. }))
            .unwrap_or(false);
        if !is_finalize {
            break;
        }
        let Some(MemQueueItem::FinalizeMatch { match_id: fid }) = mem_queue.borrow_mut().pop_front() else {
            break;
        };
        if let Some(ref db) = *db_holder.borrow() {
            if let Ok(k) = record_idb::get_next_sequence(db).await {
                if record_idb::put_finalize(db, &k, &fid).await.is_ok() {
                    upload_total_sig.set(upload_total_sig() + 1);
                    upload_queue.borrow_mut().push_back((
                        k,
                        QueueItem::FinalizeMatch { match_id: fid },
                    ));
                }
            }
        }
    }

    let should_evict_front = {
        let q = mem_queue.borrow();
        match q.front() {
            Some(MemQueueItem::Video(front)) => {
                let age_ok = now_ms - front.wall_epoch_ms > 10_000.0;
                if !age_ok {
                    false
                } else {
                    let mut other_has_kf = false;
                    let mut kf_outside_ge_10s = false;
                    for (idx, item) in q.iter().enumerate() {
                        if let MemQueueItem::Video(ch) = item {
                            if idx == 0 {
                                continue;
                            }
                            if !ch.keyframe_wall_times_ms.is_empty() {
                                other_has_kf = true;
                            }
                            for t in &ch.keyframe_wall_times_ms {
                                if now_ms - *t >= 10_000.0 {
                                    kf_outside_ge_10s = true;
                                }
                            }
                        }
                    }
                    let cond2 = other_has_kf;
                    age_ok && cond2 && kf_outside_ge_10s
                }
            }
            _ => false,
        }
    };
    if should_evict_front {
        mem_queue.borrow_mut().pop_front();
        record_log("mem_queue_idle_finalize_and_evict: evicted front video chunk (age/keyframe policy)");
    }
    record_log_duration("mem_queue_idle_finalize_and_evict: done (total)", t_idle);
}

/// JPEG encode helper (quality 0.7 via canvas `toBlob`).
#[cfg(target_arch = "wasm32")]
async fn canvas_to_jpeg_bytes(canvas: &web_sys::HtmlCanvasElement) -> Result<bytes::Bytes, String> {
    use wasm_bindgen::closure::Closure;
    use wasm_bindgen::JsCast;

    let promise = js_sys::Promise::new(&mut |resolve, reject| {
        let resolve = resolve.clone();
        let reject = reject.clone();
        let closure = Closure::once(move |blob: wasm_bindgen::JsValue| {
            if blob.is_null() || blob.is_undefined() {
                let _ = reject.call1(&wasm_bindgen::JsValue::NULL, &wasm_bindgen::JsValue::undefined());
            } else {
                let _ = resolve.call1(&wasm_bindgen::JsValue::NULL, &blob);
            }
        });
        let _ = canvas.to_blob_with_type(closure.as_ref().unchecked_ref(), "image/jpeg");
        closure.forget();
    });
    let blob_js =
        wasm_bindgen_futures::JsFuture::from(promise).await.map_err(|_| "toBlob failed".to_string())?;
    let blob = blob_js
        .dyn_into::<web_sys::Blob>()
        .map_err(|_| "blob".to_string())?;
    let ab = wasm_bindgen_futures::JsFuture::from(blob.array_buffer())
        .await
        .map_err(|_| "array_buffer".to_string())?;
    let arr = js_sys::Uint8Array::new(&ab);
    Ok(bytes::Bytes::from(arr.to_vec()))
}

#[cfg(target_arch = "wasm32")]
async fn grab_frame_via_image_capture(
    track: &web_sys::MediaStreamTrack,
) -> Result<web_sys::ImageBitmap, wasm_bindgen::JsValue> {
    use wasm_bindgen::JsCast;
    use wasm_bindgen::JsValue;

    let global = js_sys::global();
    let ic_ctor = js_sys::Reflect::get(&global, &"ImageCapture".into())?;
    if ic_ctor.is_undefined() || ic_ctor.is_null() {
        return Err(JsValue::from_str("no ImageCapture"));
    }
    let ctor = ic_ctor
        .dyn_ref::<js_sys::Function>()
        .ok_or_else(|| JsValue::from_str("not ImageCapture"))?;
    let args = js_sys::Array::new();
    args.push(&JsValue::from(track.clone()));
    let image_capture = js_sys::Reflect::construct(ctor, &args)?;
    let grab = js_sys::Reflect::get(&image_capture, &"grabFrame".into())?;
    let grab_fn = grab
        .dyn_ref::<js_sys::Function>()
        .ok_or_else(|| JsValue::from_str("no grabFrame"))?;
    let p = grab_fn.call0(&image_capture)?;
    let promise = p.dyn_into::<js_sys::Promise>()?;
    let result = wasm_bindgen_futures::JsFuture::from(promise).await?;
    result
        .dyn_into::<web_sys::ImageBitmap>()
        .map_err(|_| JsValue::from_str("not ImageBitmap"))
}

/// Off-screen video used only when `ImageCapture` is unavailable (e.g. some Safari builds). Muted, zero volume, not visible.
#[cfg(target_arch = "wasm32")]
async fn ensure_hidden_capture_video(stream: &web_sys::MediaStream) -> Result<web_sys::HtmlVideoElement, String> {
    use wasm_bindgen::JsCast;
    use wasm_bindgen_futures::JsFuture;

    let window = web_sys::window().ok_or("no window")?;
    let doc = window.document().ok_or("no document")?;
    let body = doc.body().ok_or("no body")?;

    let video: web_sys::HtmlVideoElement = if let Some(el) = doc.get_element_by_id("record-preview-capture") {
        el.dyn_into().map_err(|_| "record-preview-capture")?
    } else {
        let v = doc
            .create_element("video")
            .map_err(|_| "create video")?
            .dyn_into::<web_sys::HtmlVideoElement>()
            .map_err(|_| "video cast")?;
        v.set_id("record-preview-capture");
        v.set_muted(true);
        v.set_volume(0.0);
        let _ = v.set_attribute("playsinline", "");
        let _ = v.set_attribute(
            "style",
            "position:fixed;left:-9999px;width:1px;height:1px;opacity:0;pointer-events:none;",
        );
        body.append_child(&v).map_err(|_| "append")?;
        v
    };

    if video.src_object().is_none() {
        video.set_src_object(Some(stream));
        if let Ok(p) = video.play() {
            let _ = JsFuture::from(p).await;
        }
    }
    Ok(video)
}

#[cfg(target_arch = "wasm32")]
async fn canvas_jpeg_from_image_bitmap(bitmap: &web_sys::ImageBitmap) -> Result<bytes::Bytes, String> {
    use wasm_bindgen::JsCast;

    let vw = bitmap.width() as i32;
    let vh = bitmap.height() as i32;
    if vw <= 0 || vh <= 0 {
        return Err("bitmap empty".to_string());
    }
    let (canvas_w, canvas_h) = if vw > 640 {
        (640u32, (vh as u32 * 640 / vw as u32))
    } else {
        (vw as u32, vh as u32)
    };
    let window = web_sys::window().ok_or("no window")?;
    let doc = window.document().ok_or("no document")?;
    let canvas = doc
        .create_element("canvas")
        .map_err(|_| "create canvas")?
        .dyn_into::<web_sys::HtmlCanvasElement>()
        .map_err(|_| "canvas")?;
    canvas.set_width(canvas_w);
    canvas.set_height(canvas_h);
    let ctx = canvas
        .get_context("2d")
        .map_err(|_| "get context")?
        .ok_or("no context")?
        .dyn_into::<web_sys::CanvasRenderingContext2d>()
        .map_err(|_| "2d")?;
    ctx.draw_image_with_image_bitmap_and_sw_and_sh_and_dx_and_dy_and_dw_and_dh(
        bitmap,
        0.0,
        0.0,
        vw as f64,
        vh as f64,
        0.0,
        0.0,
        canvas_w as f64,
        canvas_h as f64,
    )
    .map_err(|_| "draw".to_string())?;
    canvas_to_jpeg_bytes(&canvas).await
}

#[cfg(target_arch = "wasm32")]
async fn canvas_jpeg_from_video_element(
    video: &web_sys::HtmlVideoElement,
    vw: u32,
    vh: u32,
) -> Result<bytes::Bytes, String> {
    use wasm_bindgen::JsCast;

    let (canvas_w, canvas_h) = if vw > 640 {
        (640u32, vh * 640 / vw)
    } else {
        (vw, vh)
    };
    let window = web_sys::window().ok_or("no window")?;
    let doc = window.document().ok_or("no document")?;
    let canvas = doc
        .create_element("canvas")
        .map_err(|_| "create canvas")?
        .dyn_into::<web_sys::HtmlCanvasElement>()
        .map_err(|_| "canvas")?;
    canvas.set_width(canvas_w);
    canvas.set_height(canvas_h);
    let ctx = canvas
        .get_context("2d")
        .map_err(|_| "get context")?
        .ok_or("no context")?
        .dyn_into::<web_sys::CanvasRenderingContext2d>()
        .map_err(|_| "2d")?;
    ctx.draw_image_with_html_video_element_and_sw_and_sh_and_dx_and_dy_and_dw_and_dh(
        video,
        0.0,
        0.0,
        f64::from(vw),
        f64::from(vh),
        0.0,
        0.0,
        canvas_w as f64,
        canvas_h as f64,
    )
    .map_err(|_| "draw".to_string())?;
    canvas_to_jpeg_bytes(&canvas).await
}

/// Capture one frame as JPEG (max width 640). Prefers `ImageCapture` (no `<video>` playback); falls back to a hidden muted video element.
#[cfg(target_arch = "wasm32")]
async fn capture_preview_frame_from_stream(stream: &web_sys::MediaStream) -> Result<bytes::Bytes, String> {
    use wasm_bindgen::JsCast;

    let t_cap = record_now_ms();
    let tracks = stream.get_video_tracks();
    if tracks.length() == 0 {
        return Err("no video track".to_string());
    }
    let track = tracks
        .get(0)
        .dyn_into::<web_sys::MediaStreamTrack>()
        .map_err(|_| "video track")?;

    if let Ok(bitmap) = grab_frame_via_image_capture(&track).await {
        let t_jpeg = record_now_ms();
        let res = canvas_jpeg_from_image_bitmap(&bitmap).await;
        bitmap.close();
        let jpeg_ms = record_now_ms() - t_jpeg;
        let total_ms = record_now_ms() - t_cap;
        record_log(&format!(
            "preview_frame: path=ImageCapture jpeg_encode={:.2} ms total={:.2} ms",
            jpeg_ms, total_ms
        ));
        return res;
    }

    record_log("preview_frame: ImageCapture unavailable or failed; using hidden <video> fallback");
    let t_vid = record_now_ms();
    let video = ensure_hidden_capture_video(stream).await?;
    record_log_duration("preview_frame: ensure_hidden_capture_video", t_vid);
    let t_wait = record_now_ms();
    for _ in 0..60 {
        if video.video_width() > 0 && video.video_height() > 0 {
            break;
        }
        gloo_timers::future::TimeoutFuture::new(100).await;
    }
    record_log_duration("preview_frame: wait for video dimensions", t_wait);
    let vw = video.video_width();
    let vh = video.video_height();
    if vw == 0 || vh == 0 {
        return Err("video not ready".to_string());
    }
    let t_enc = record_now_ms();
    let out = canvas_jpeg_from_video_element(&video, vw, vh).await;
    let enc_ms = record_now_ms() - t_enc;
    let total_ms = record_now_ms() - t_cap;
    record_log(&format!(
        "preview_frame: path=hidden_video encode={:.2} ms total={:.2} ms ok={}",
        enc_ms,
        total_ms,
        out.is_ok()
    ));
    out
}

/// Parse a JS number or BigInt (or numeric string) to `f64`. Plain `JsValue::as_f64()` misses BigInt.
#[cfg(target_arch = "wasm32")]
fn js_value_to_f64(v: &wasm_bindgen::JsValue) -> Option<f64> {
    use wasm_bindgen::JsCast;
    use wasm_bindgen::JsValue;
    if v.is_undefined() || v.is_null() {
        return None;
    }
    if let Some(n) = v.as_f64() {
        if n.is_finite() {
            return Some(n);
        }
    }
    let number_ctor = js_sys::Reflect::get(&js_sys::global(), &"Number".into()).ok()?;
    let number_fn = number_ctor.dyn_ref::<js_sys::Function>()?;
    let num = number_fn.call1(&JsValue::NULL, v).ok()?;
    let n = num.as_f64()?;
    if n.is_finite() {
        Some(n)
    } else {
        None
    }
}

/// Best-effort bytes used: max of `estimate.usage`, Chrome `usageDetails.indexedDB`, and our queue blob sum.
#[cfg(target_arch = "wasm32")]
async fn effective_storage_usage_bytes(
    estimate_js: &wasm_bindgen::JsValue,
    queue_db: Option<&idb::Database>,
) -> Option<f64> {
    let mut m = 0.0f64;
    let mut any = false;
    if let Ok(u) = js_sys::Reflect::get(estimate_js, &"usage".into()) {
        if let Some(x) = js_value_to_f64(&u) {
            m = m.max(x);
            any = true;
        }
    }
    if let Ok(details) = js_sys::Reflect::get(estimate_js, &"usageDetails".into()) {
        if let Ok(idb) = js_sys::Reflect::get(&details, &"indexedDB".into()) {
            if let Some(x) = js_value_to_f64(&idb) {
                m = m.max(x);
                any = true;
            }
        }
    }
    if let Some(db) = queue_db {
        if let Ok(q) = record_idb::sum_chunk_blob_bytes(db).await {
            m = m.max(q as f64);
            any = true;
        }
    } else if let Ok(db) = record_idb::open_db().await {
        if let Ok(q) = record_idb::sum_chunk_blob_bytes(&db).await {
            m = m.max(q as f64);
            any = true;
        }
    }
    if any {
        Some(m)
    } else {
        None
    }
}

/// Collect device storage (usage/quota in bytes) and battery level (0–1) for preview metadata. Best-effort.
#[cfg(target_arch = "wasm32")]
async fn collect_preview_metadata() -> api::PreviewMetadata {
    let mut storage_usage: Option<f64> = None;
    let mut storage_quota: Option<f64> = None;
    let mut battery_level: Option<f64> = None;
    if let Some(window) = web_sys::window() {
        let nav = window.navigator();
        let storage = nav.storage();
        if let Ok(promise) = storage.estimate() {
            if let Ok(estimate_js) = wasm_bindgen_futures::JsFuture::from(promise).await {
                storage_usage =
                    effective_storage_usage_bytes(&estimate_js, None).await;
                storage_quota = js_sys::Reflect::get(&estimate_js, &"quota".into())
                    .ok()
                    .and_then(|v| js_value_to_f64(&v));
            }
        }
        if let Ok(get_battery) = js_sys::Reflect::get(&nav, &"getBattery".into()) {
            if let Some(get_battery_fn) = get_battery.dyn_ref::<js_sys::Function>() {
                if let Ok(promise_val) = get_battery_fn.call0(&nav) {
                    if let Ok(promise) = promise_val.dyn_into::<js_sys::Promise>() {
                        if let Ok(battery) = wasm_bindgen_futures::JsFuture::from(promise).await {
                            battery_level = js_sys::Reflect::get(&battery, &"level".into())
                                .ok()
                                .and_then(|v| v.as_f64());
                        }
                    }
                }
            }
        }
    }
    api::PreviewMetadata {
        storage_usage,
        storage_quota,
        battery_level,
    }
}

/// Preview sender loop: capture frame, POST, poll consumed until true, repeat. Stops when stop_flag is set.
#[cfg(target_arch = "wasm32")]
async fn run_preview_sender_loop(
    stop_flag: std::sync::Arc<std::sync::atomic::AtomicBool>,
    camera_stream: web_sys::MediaStream,
    tournament_url: String,
    field: String,
    camera_key: String,
    camera_name: String,
) {
    use std::sync::atomic::Ordering;

    while !stop_flag.load(Ordering::SeqCst) {
        let t_cycle = record_now_ms();
        let bytes = match capture_preview_frame_from_stream(&camera_stream).await {
            Ok(b) => b,
            Err(_) => {
                record_log_duration("preview_sender: capture_preview_frame failed (waiting 500ms)", t_cycle);
                gloo_timers::future::TimeoutFuture::new(500).await;
                continue;
            }
        };
        let t_up = record_now_ms();
        if let Err(_) = api::upload_preview_frame(
            &tournament_url,
            &field,
            &camera_key,
            &camera_name,
            bytes,
        )
        .await
        {
            record_log_duration("preview_sender: upload_preview_frame failed (waiting 500ms)", t_up);
            gloo_timers::future::TimeoutFuture::new(500).await;
            continue;
        }
        record_log_duration("preview_sender: upload_preview_frame", t_up);
        let t_meta = record_now_ms();
        let meta = collect_preview_metadata().await;
        record_log_duration("preview_sender: collect_preview_metadata", t_meta);
        let t_umeta = record_now_ms();
        let _ = api::upload_preview_metadata(
            &tournament_url,
            &field,
            &camera_key,
            &camera_name,
            &meta,
        )
        .await;
        record_log_duration("preview_sender: upload_preview_metadata", t_umeta);
        let t_poll = record_now_ms();
        while !stop_flag.load(Ordering::SeqCst) {
            match api::is_preview_frame_consumed(&tournament_url, &field, &camera_name, &camera_key).await {
                Ok(true) => break,
                Ok(false) => {}
                Err(_) => break,
            }
            gloo_timers::future::TimeoutFuture::new(300).await;
        }
        record_log_duration("preview_sender: poll until consumed", t_poll);
        gloo_timers::future::TimeoutFuture::new(200).await;
        record_log_duration("preview_sender: full cycle (until next capture)", t_cycle);
    }
}

#[cfg(target_arch = "wasm32")]
async fn run_recording_loop(
    stream: web_sys::MediaStream,
    tournament_url: String,
    field: String,
    key: Option<String>,
    camera_name: String,
    mut status_sig: Signal<RecordStatus>,
    mut match_status_data_sig: Signal<Option<RecordMatchStatusResponse>>,
    mut is_recording_sig: Signal<bool>,
    mut is_uploading_sig: Signal<bool>,
    mut upload_count_sig: Signal<u32>,
    mut upload_total_sig: Signal<u32>,
    mut storage_warning_sig: Signal<Option<String>>,
) {
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Arc;
    use wasm_bindgen::closure::Closure;
    use wasm_bindgen::JsCast;
    use web_sys::{MediaRecorder, MediaRecorderOptions};

    const MIME_MP4: &[&str] = &[
        "video/mp4; codecs=hvc1.1.6.L93.B0",
        "video/mp4; codecs=hev1.1.6.L93.B0",
        "video/mp4; codecs=hvc1.1.6.L93",
        "video/mp4; codecs=hev1.1.6.L93",
        "video/mp4; codecs=hvc1",
        "video/mp4; codecs=hev1",
        "video/mp4; codecs=avc1.42E01E",
        "video/mp4",
    ];
    /// Keep each fragment small enough for typical reverse-proxy body limits (often 1–10 MB).
    const RECORD_VIDEO_BITS_PER_SECOND: u32 = 50_000_000;
    /// Must match `chunk_length_ms` in `RecordChunkMeta` for every enqueue path.
    const RECORD_TIMESLICE_MS: i32 = 500;

    let key_ref = key.clone();
    let container = "mp4".to_string();

    let mem_queue: Rc<RefCell<VecDeque<MemQueueItem>>> = Rc::new(RefCell::new(VecDeque::new()));
    let fsm: Rc<RefCell<RecordFsm>> = Rc::new(RefCell::new(RecordFsm::Idle));
    let recording_session_uuid: Rc<RefCell<String>> = Rc::new(RefCell::new(String::new()));
    let recording_session_wall_start_ms: Rc<RefCell<f64>> = Rc::new(RefCell::new(0.0));
    let cached_timescale: Rc<RefCell<Option<u32>>> = Rc::new(RefCell::new(None));
    let cached_init_segment: Rc<RefCell<Option<Vec<u8>>>> = Rc::new(RefCell::new(None));
    let session_first_chunk_state: Rc<RefCell<record_mp4::SessionFirstChunkState>> =
        Rc::new(RefCell::new(record_mp4::SessionFirstChunkState::default()));
    let recorder_holder: Rc<RefCell<Option<MediaRecorder>>> = Rc::new(RefCell::new(None));

    let mq_cb = mem_queue.clone();
    let make_recorder = move |stream: &web_sys::MediaStream| -> Option<MediaRecorder> {
        let mut options = MediaRecorderOptions::new();
        options.set_video_bits_per_second(RECORD_VIDEO_BITS_PER_SECOND);
        options.set_audio_bits_per_second(128_000);
        let mut chosen: Option<&str> = None;
        for m in MIME_MP4 {
            if MediaRecorder::is_type_supported(m) {
                options.set_mime_type(m);
                chosen = Some(*m);
                break;
            }
        }
        chosen?;
        let r = MediaRecorder::new_with_media_stream_and_media_recorder_options(stream, &options).ok()?;
        let mq = mq_cb.clone();
        let closure = Closure::wrap(Box::new(move |ev: web_sys::BlobEvent| {
            let Some(blob) = ev.data() else {
                return;
            };
            let wall_epoch_ms = blob_event_wall_epoch_ms(&ev);
            let blob_event_timestamp_ms = ev.time_stamp();
            let sz = blob.size();
            record_log(&format!(
                "MediaRecorder ondataavailable: blob_bytes={:.0} wall_epoch_ms={:.1} blob_event_ts_ms={:.1}",
                sz, wall_epoch_ms, blob_event_timestamp_ms
            ));
            mq.borrow_mut().push_back(MemQueueItem::Video(MemVideoChunk {
                blob,
                blob_event_timestamp_ms,
                wall_epoch_ms,
                keyframe_wall_times_ms: vec![],
                sync_samples: vec![],
                parsed: false,
            }));
        }) as Box<dyn FnMut(web_sys::BlobEvent)>);
        r.set_ondataavailable(Some(closure.as_ref().unchecked_ref()));
        closure.forget();
        Some(r)
    };

    let db_holder: Rc<RefCell<Option<idb::Database>>> = Rc::new(RefCell::new(None));
    if db_holder.borrow().is_none() {
        if let Ok(db) = record_idb::open_db().await {
            *db_holder.borrow_mut() = Some(db);
        }
    }
    let upload_queue: Rc<RefCell<VecDeque<(String, QueueItem)>>> =
        Rc::new(RefCell::new(VecDeque::new()));
    let pending_chunks_by_match: Rc<RefCell<HashMap<String, u32>>> =
        Rc::new(RefCell::new(HashMap::new()));
    if let Some(ref db) = *db_holder.borrow() {
        let t_idb_restore = record_now_ms();
        record_log("IndexedDB: restore pending upload queue (cursor_entries_ordered)");
        if let Ok(entries) = record_idb::cursor_entries_ordered(db).await {
            for (key, value) in entries {
                if let Some(match_id) = record_idb::parse_finalize_value(&value) {
                    upload_queue
                        .borrow_mut()
                        .push_back((key, QueueItem::FinalizeMatch { match_id }));
                } else if let Some((meta, _blob)) = record_idb::parse_chunk_value(&value) {
                    let match_id = meta.match_id.clone();
                    *pending_chunks_by_match
                        .borrow_mut()
                        .entry(match_id.clone())
                        .or_insert(0) += 1;
                    upload_queue.borrow_mut().push_back((
                        key,
                        QueueItem::Chunk {
                            match_id: Some(match_id),
                        },
                    ));
                } else {
                    upload_queue
                        .borrow_mut()
                        .push_back((key, QueueItem::Chunk { match_id: None }));
                }
            }
            let q_ref = upload_queue.borrow();
            let n = q_ref.len() as u32;
            if n > 0 {
                upload_total_sig.set(upload_total_sig() + n);
            }
            record_log_duration(
                &format!("IndexedDB: restore enqueued {} pending item(s)", n),
                t_idb_restore,
            );
        }
        let chunk_match_ids: HashSet<String> = upload_queue
            .borrow()
            .iter()
            .filter_map(|(_, item)| {
                if let QueueItem::Chunk { match_id: Some(id) } = item {
                    Some(id.clone())
                } else {
                    None
                }
            })
            .collect();
        let finalized_in_queue: HashSet<String> = upload_queue
            .borrow()
            .iter()
            .filter_map(|(_, item)| {
                if let QueueItem::FinalizeMatch { match_id } = item {
                    Some(match_id.clone())
                } else {
                    None
                }
            })
            .collect();
        let mut need_finalize: Vec<String> = chunk_match_ids
            .difference(&finalized_in_queue)
            .cloned()
            .collect();
        if !need_finalize.is_empty() {
            if let Ok(status) = api::record_match_status(&tournament_url, &field, None).await {
                let current_match_id = status.match_id.as_deref();
                need_finalize.retain(|id| current_match_id.map(|cur| cur != id.as_str()).unwrap_or(true));
                let mut added = 0u32;
                for match_id in need_finalize {
                    if let Ok(key) = record_idb::get_next_sequence(db).await {
                        if record_idb::put_finalize(db, &key, &match_id).await.is_ok() {
                            upload_queue.borrow_mut().push_back((
                                key,
                                QueueItem::FinalizeMatch {
                                    match_id: match_id.clone(),
                                },
                            ));
                            added += 1;
                        }
                    }
                }
                if added > 0 {
                    upload_total_sig.set(upload_total_sig() + added);
                }
            }
        }
        if let Some(window) = web_sys::window() {
            let storage = window.navigator().storage();
            if let Ok(promise) = storage.estimate() {
                if let Ok(estimate_js) = wasm_bindgen_futures::JsFuture::from(promise).await {
                    let quota = js_sys::Reflect::get(&estimate_js, &"quota".into())
                        .ok()
                        .and_then(|v| js_value_to_f64(&v))
                        .unwrap_or(0.0);
                    let usage = effective_storage_usage_bytes(&estimate_js, Some(db))
                        .await
                        .unwrap_or(0.0);
                    const LOW_STORAGE_BYTES: f64 = 100_000_000.0;
                    if quota > 0.0 && (quota - usage) < LOW_STORAGE_BYTES {
                        storage_warning_sig.set(Some(
                            "Low device storage for recording buffer; uploads may fail if connection is slow."
                                .to_string(),
                        ));
                    }
                }
            }
        }
    }
    const NUM_UPLOAD_WORKERS: u32 = 1;
    for _ in 0..NUM_UPLOAD_WORKERS {
        let q = upload_queue.clone();
        let pending_chunks_by_match_sig = pending_chunks_by_match.clone();
        let tour = tournament_url.clone();
        let f = field.clone();
        let cam = camera_name.clone();
        let k = key_ref.clone();
        let is_up = is_uploading_sig.to_owned();
        let up_cnt = upload_count_sig.to_owned();
        let warn_sig = storage_warning_sig.to_owned();
        spawn(async move {
            let db = match record_idb::open_db().await {
                Ok(d) => d,
                Err(_) => return,
            };
            run_upload_worker(
                q,
                db,
                tour,
                f,
                cam,
                k,
                pending_chunks_by_match_sig,
                is_up,
                up_cnt,
                warn_sig,
            )
            .await;
        });
    }

    let mut current_match: Option<String> = None;
    let mut last_poll_data: Option<RecordMatchStatusResponse> = None;
    let mut preview_stop: Option<Arc<AtomicBool>> = None;
    let mut preview_sender_running = false;

    loop {
        let t_iter = record_now_ms();
        let t_poll = record_now_ms();
        let poll_result = api::record_match_status(
            &tournament_url,
            &field,
            current_match.as_ref().map(|id| id.as_str()),
        )
        .await;
        record_log_duration("record_match_status (HTTP poll)", t_poll);

        let data = match poll_result {
            Ok(d) => {
                last_poll_data = Some(d.clone());
                status_sig.set(if d.hasActiveMatch {
                    RecordStatus::Connected
                } else {
                    RecordStatus::NoMatch
                });
                d
            }
            Err(e) => {
                status_sig.set(RecordStatus::Error(e.clone()));
                if let Some(ref d) = last_poll_data {
                    d.clone()
                } else {
                    gloo_timers::future::TimeoutFuture::new(1000).await;
                    continue;
                }
            }
        };

        if data.preview_requested && !preview_sender_running {
            if let Some(ref key_str) = key {
                let stop = Arc::new(AtomicBool::new(false));
                let stop_c = stop.clone();
                let stream_for_preview = stream.clone();
                let tour = tournament_url.clone();
                let f = field.clone();
                let k = key_str.clone();
                let cam = camera_name.clone();
                dioxus::prelude::spawn(async move {
                    run_preview_sender_loop(stop_c, stream_for_preview, tour, f, k, cam).await;
                });
                preview_stop = Some(stop);
                preview_sender_running = true;
            }
        } else if !data.preview_requested && preview_sender_running {
            if let Some(ref s) = preview_stop {
                s.store(true, Ordering::SeqCst);
            }
            preview_stop = None;
            preview_sender_running = false;
        }

        let now_ms = js_sys::Date::now();
        let points = data.points.as_deref().unwrap_or(&[]);

        {
            let t_parse_batch = record_now_ms();
            let indices: Vec<usize> = mem_queue
                .borrow()
                .iter()
                .enumerate()
                .filter_map(|(i, it)| {
                    if let MemQueueItem::Video(ch) = it {
                        if !ch.parsed {
                            Some(i)
                        } else {
                            None
                        }
                    } else {
                        None
                    }
                })
                .collect();
            let n_unparsed = indices.len();
            for i in indices {
                let mut q = mem_queue.borrow_mut();
                if let Some(MemQueueItem::Video(ref mut ch)) = q.get_mut(i) {
                    parse_mem_video_chunk(ch, &cached_timescale, &cached_init_segment).await;
                }
            }
            if n_unparsed > 0 {
                record_log_duration(
                    &format!("mem_queue parse batch (unparsed chunks={})", n_unparsed),
                    t_parse_batch,
                );
            }
            record_log_mem_queue_snapshot(&mem_queue);
        }

        let in_window = in_point_recording_window(points, now_ms);

        if !data.hasActiveMatch || data.match_id.as_ref().map(|s| s.as_str()) != current_match.as_ref().map(|id| id.as_str())
        {
            if let Some(match_id) = current_match.take() {
                if let Some(r) = recorder_holder.borrow_mut().take() {
                    stop_media_recorder_fully(r).await;
                }
                if let Some(ref db) = *db_holder.borrow() {
                    let sid = recording_session_uuid.borrow().clone();
                    let wall = *recording_session_wall_start_ms.borrow();
                    let session_id = if sid.is_empty() {
                        uuid_style_id()
                    } else {
                        sid
                    };
                    let t_drain = record_now_ms();
                    let drained: Vec<MemQueueItem> = mem_queue.borrow_mut().drain(..).collect();
                    let (drained_n, n_added) = process_drained_mem_queue_items(
                        drained,
                        db,
                        &match_id,
                        &session_id,
                        wall,
                        tournament_url.clone(),
                        field.clone(),
                        camera_name.clone(),
                        key_ref.clone(),
                        container.clone(),
                        &session_first_chunk_state,
                        &cached_init_segment,
                        &cached_timescale,
                        &pending_chunks_by_match,
                        &upload_queue,
                    )
                    .await;
                    if n_added > 0 {
                        upload_total_sig.set(upload_total_sig() + n_added);
                    }
                    record_log(&format!(
                        "flush mem→IndexedDB (match changed / no longer aligned): drained={} put_ok={} in {:.2} ms",
                        drained_n,
                        n_added,
                        record_now_ms() - t_drain
                    ));
                }
                mem_queue
                    .borrow_mut()
                    .push_back(MemQueueItem::FinalizeMatch { match_id });
                *fsm.borrow_mut() = RecordFsm::Idle;
                recording_session_uuid.borrow_mut().clear();
                *cached_timescale.borrow_mut() = None;
                *cached_init_segment.borrow_mut() = None;
                *session_first_chunk_state.borrow_mut() =
                    record_mp4::SessionFirstChunkState::default();
                is_recording_sig.set(false);
            }
            if data.hasActiveMatch {
                if let Some(ref match_id) = data.match_id {
                    current_match = Some(match_id.clone());
                    is_recording_sig.set(true);
                    *cached_timescale.borrow_mut() = None;
                    *cached_init_segment.borrow_mut() = None;
                    *session_first_chunk_state.borrow_mut() =
                        record_mp4::SessionFirstChunkState::default();
                    if recorder_holder.borrow().is_none() {
                        if let Some(r) = make_recorder(&stream) {
                            let _ = r.start_with_time_slice(RECORD_TIMESLICE_MS);
                            *recorder_holder.borrow_mut() = Some(r);
                        }
                    } else if let Some(r) = recorder_holder.borrow().as_ref() {
                        let state_str: String = js_sys::Reflect::get(r.as_ref(), &"state".into())
                            .ok()
                            .and_then(|v| v.as_string())
                            .unwrap_or_default();
                        if state_str != "recording" {
                            let _ = r.start_with_time_slice(RECORD_TIMESLICE_MS);
                        }
                    }
                }
            }
        }

        let poll_aligned_with_match = data.hasActiveMatch
            && current_match.is_some()
            && data.match_id.as_ref().map(|s| s.as_str()) == current_match.as_ref().map(|id| id.as_str());

        if poll_aligned_with_match {
        let match_id = current_match.as_ref().expect("current_match is None").clone();

        if *fsm.borrow() == RecordFsm::Recording && !in_window {
            let sid = recording_session_uuid.borrow().clone();
            let wall = *recording_session_wall_start_ms.borrow();
            let session_id = if sid.is_empty() {
                uuid_style_id()
            } else {
                sid
            };
            if let Some(ref db) = *db_holder.borrow() {
                let t_drain = record_now_ms();
                let drained: Vec<MemQueueItem> = mem_queue.borrow_mut().drain(..).collect();
                let (drained_n, n_added) = process_drained_mem_queue_items(
                    drained,
                    db,
                    &match_id,
                    &session_id,
                    wall,
                    tournament_url.clone(),
                    field.clone(),
                    camera_name.clone(),
                    key_ref.clone(),
                    container.clone(),
                    &session_first_chunk_state,
                    &cached_init_segment,
                    &cached_timescale,
                    &pending_chunks_by_match,
                    &upload_queue,
                )
                .await;
                if n_added > 0 {
                    upload_total_sig.set(upload_total_sig() + n_added);
                }
                record_log(&format!(
                    "flush mem→IndexedDB (left point recording window): drained={} put_ok={} in {:.2} ms",
                    drained_n,
                    n_added,
                    record_now_ms() - t_drain
                ));
            }
            *fsm.borrow_mut() = RecordFsm::Idle;
        }

        if *fsm.borrow() == RecordFsm::Idle && in_window {
            if let Some(point_start_ms) = min_point_start_ms_in_recording_window(points, now_ms) {
                let cutoff = point_start_ms - 3000.0;
                let mut best: Option<(usize, u32)> = None;
                let mut best_kf_wall = f64::NEG_INFINITY;
                for (qi, item) in mem_queue.borrow().iter().enumerate() {
                    if let MemQueueItem::Video(ch) = item {
                        if !ch.parsed {
                            continue;
                        }
                        for s in &ch.sync_samples {
                            if s.wall_epoch_ms <= cutoff && s.wall_epoch_ms > best_kf_wall {
                                best_kf_wall = s.wall_epoch_ms;
                                best = Some((qi, s.sample_index_in_fragment));
                            }
                        }
                    }
                }
                if let Some((qi, sample_idx)) = best {
                    for _ in 0..qi {
                        mem_queue.borrow_mut().pop_front();
                    }
                    let ch_opt = match mem_queue.borrow_mut().pop_front() {
                        Some(MemQueueItem::Video(ch)) => Some(ch),
                        _ => None,
                    };
                    if let Some(mut ch) = ch_opt {
                        let t_trim = record_now_ms();
                        let bytes = blob_to_bytes(&ch.blob).await;
                        let init = cached_init_segment
                            .borrow()
                            .clone()
                            .or_else(|| record_mp4::extract_ftyp_moov(&bytes));
                        let out = if let Some(ref init) = init {
                            record_mp4::trim_fragment_with_init(&bytes, init, sample_idx)
                                .unwrap_or(bytes)
                        } else {
                            bytes
                        };
                        ch.blob = bytes_to_blob(&out);
                        ch.parsed = false;
                        parse_mem_video_chunk(&mut ch, &cached_timescale, &cached_init_segment).await;
                        record_log(&format!(
                            "point window trim+reparse: sample_idx={} out_bytes={} in {:.2} ms",
                            sample_idx,
                            out.len(),
                            record_now_ms() - t_trim
                        ));
                        mem_queue
                            .borrow_mut()
                            .push_front(MemQueueItem::Video(ch));
                        *recording_session_uuid.borrow_mut() = uuid_style_id();
                        *recording_session_wall_start_ms.borrow_mut() = now_ms;
                        *fsm.borrow_mut() = RecordFsm::Recording;
                    } else {
                        *fsm.borrow_mut() = RecordFsm::Idle;
                    }
                }
            }
        }

        if *fsm.borrow() == RecordFsm::Recording && in_window {
            let sid = recording_session_uuid.borrow().clone();
            let wall = *recording_session_wall_start_ms.borrow();
            let session_id = if sid.is_empty() {
                uuid_style_id()
            } else {
                sid
            };
            if let Some(ref db) = *db_holder.borrow() {
                let t_drain = record_now_ms();
                let drained: Vec<MemQueueItem> = mem_queue.borrow_mut().drain(..).collect();
                let (drained_n, n_added) = process_drained_mem_queue_items(
                    drained,
                    db,
                    &match_id,
                    &session_id,
                    wall,
                    tournament_url.clone(),
                    field.clone(),
                    camera_name.clone(),
                    key_ref.clone(),
                    container.clone(),
                    &session_first_chunk_state,
                    &cached_init_segment,
                    &cached_timescale,
                    &pending_chunks_by_match,
                    &upload_queue,
                )
                .await;
                if n_added > 0 {
                    upload_total_sig.set(upload_total_sig() + n_added);
                }
                record_log(&format!(
                    "flush mem→IndexedDB (in point window, periodic): drained={} put_ok={} in {:.2} ms",
                    drained_n,
                    n_added,
                    record_now_ms() - t_drain
                ));
            }
        }

        // MediaRecorder keeps emitting while the match is active, but we only entered Recording-based
        // drains above; while Idle (waiting for keyframe trim, or between windows) chunks must still flush.
        if poll_aligned_with_match && *fsm.borrow() == RecordFsm::Idle {
            if let Some(ref db) = *db_holder.borrow() {
                if !mem_queue.borrow().is_empty() {
                    let sid = recording_session_uuid.borrow().clone();
                    let wall = *recording_session_wall_start_ms.borrow();
                    let session_id = if sid.is_empty() {
                        uuid_style_id()
                    } else {
                        sid
                    };
                    let t_drain = record_now_ms();
                    let drained: Vec<MemQueueItem> = mem_queue.borrow_mut().drain(..).collect();
                    let (drained_n, n_added) = process_drained_mem_queue_items(
                        drained,
                        db,
                        &match_id,
                        &session_id,
                        wall,
                        tournament_url.clone(),
                        field.clone(),
                        camera_name.clone(),
                        key_ref.clone(),
                        container.clone(),
                        &session_first_chunk_state,
                        &cached_init_segment,
                        &cached_timescale,
                        &pending_chunks_by_match,
                        &upload_queue,
                    )
                    .await;
                    if n_added > 0 {
                        upload_total_sig.set(upload_total_sig() + n_added);
                    }
                    record_log(&format!(
                        "flush mem→IndexedDB (Idle, active match): drained={} put_ok={} in {:.2} ms",
                        drained_n,
                        n_added,
                        record_now_ms() - t_drain
                    ));
                }
            }
        }

        if *fsm.borrow() == RecordFsm::Idle {
            mem_queue_idle_finalize_and_evict(
                &mem_queue,
                &db_holder,
                &upload_queue,
                upload_total_sig.to_owned(),
                now_ms,
            )
            .await;
        }

        } else if *fsm.borrow() == RecordFsm::Idle {
            mem_queue_idle_finalize_and_evict(
                &mem_queue,
                &db_holder,
                &upload_queue,
                upload_total_sig.to_owned(),
                now_ms,
            )
            .await;
        }

        if data.hasActiveMatch {
            match_status_data_sig.set(Some(data));
        } else {
            match_status_data_sig.set(None);
        }
        record_log_duration("record loop iteration (total, before 500ms sleep)", t_iter);
        gloo_timers::future::TimeoutFuture::new(500).await;
    }
}

#[cfg(target_arch = "wasm32")]
fn record_upload_error_is_payload_too_large(msg: &str) -> bool {
    let m = msg.to_lowercase();
    m.contains("413")
        || m.contains("too large")
        || m.contains("entity too large")
        || m.contains("payload too large")
}

#[cfg(target_arch = "wasm32")]
async fn run_upload_worker(
    queue: Rc<RefCell<VecDeque<(String, QueueItem)>>>,
    db: idb::Database,
    tournament_url: String,
    field: String,
    camera_name: String,
    key: Option<String>,
    pending_chunks_by_match: Rc<RefCell<HashMap<String, u32>>>,
    mut is_uploading_sig: Signal<bool>,
    mut upload_count_sig: Signal<u32>,
    mut storage_warning_sig: Signal<Option<String>>,
) {
    /// Delay before retrying a failed upload (connection lost, etc.).
    const RETRY_DELAY_MS: u32 = 3000;
    /// After HTTP 413, wait longer before re-queuing the same chunk (same blob cannot succeed until the limit is raised).
    const PAYLOAD_TOO_LARGE_RETRY_MS: u32 = 60_000;
    /// Number of immediate retries for each upload attempt (transient errors).
    const API_RETRY_ATTEMPTS: u32 = 5;
    /// Delay between API retries (ms).
    const API_RETRY_DELAY_MS: u32 = 1500;

    loop {
        gloo_timers::future::TimeoutFuture::new(200).await;
        let item = queue.borrow_mut().pop_front();
        if let Some((key_str, queue_item)) = item {
            is_uploading_sig.set(true);
            let mut success = false;
            let mut payload_too_large = false;
            let t_item = record_now_ms();
            let key_short = if key_str.len() > 12 {
                format!("{}…", &key_str[..12])
            } else {
                key_str.clone()
            };
            match &queue_item {
                QueueItem::Chunk { .. } => {
                    let t_idb = record_now_ms();
                    if let Ok(Some(value)) = record_idb::get_entry(&db, &key_str).await {
                        record_log_duration(
                            &format!("upload_worker chunk idb get_entry key={}", key_short),
                            t_idb,
                        );
                        if let Some((meta, blob)) = record_idb::parse_chunk_value(&value) {
                            let blob_bytes = blob.size();
                            record_log(&format!(
                                "upload_worker chunk: match_id={} blob_bytes={:.0}",
                                meta.match_id, blob_bytes
                            ));
                            for attempt in 0..API_RETRY_ATTEMPTS {
                                let t_up = record_now_ms();
                                match api::record_upload_chunk(&meta, &blob).await {
                                    Ok(()) => {
                                        record_log_duration(
                                            &format!(
                                                "upload_worker record_upload_chunk attempt {} HTTP",
                                                attempt + 1
                                            ),
                                            t_up,
                                        );
                                        let t_del = record_now_ms();
                                        if record_idb::delete_entry(&db, &key_str).await.is_ok() {
                                            record_log_duration(
                                                &format!("upload_worker idb delete_entry key={}", key_short),
                                                t_del,
                                            );
                                            upload_count_sig.set(upload_count_sig() + 1);
                                            success = true;
                                            let mid = meta.match_id.clone();
                                            let mut pending = pending_chunks_by_match.borrow_mut();
                                            if let Some(v) = pending.get_mut(&mid) {
                                                *v = v.saturating_sub(1);
                                                if *v == 0 {
                                                    pending.remove(&mid);
                                                }
                                            }
                                        }
                                        break;
                                    }
                                    Err(e) => {
                                        record_log_duration(
                                            &format!(
                                                "upload_worker record_upload_chunk attempt {} FAILED: {}",
                                                attempt + 1,
                                                e
                                            ),
                                            t_up,
                                        );
                                        if record_upload_error_is_payload_too_large(&e) {
                                            payload_too_large = true;
                                            storage_warning_sig.set(Some(
                                                "Upload rejected: each chunk is larger than the server allows (HTTP 413). The host should raise the upload limit (e.g. nginx client_max_body_size) or set MAX_CONTENT_LENGTH_BYTES; this page will retry slowly."
                                                    .to_string(),
                                            ));
                                            break;
                                        }
                                        if attempt + 1 < API_RETRY_ATTEMPTS {
                                            gloo_timers::future::TimeoutFuture::new(API_RETRY_DELAY_MS)
                                                .await;
                                        }
                                    }
                                }
                            }
                        }
                    } else {
                        record_log(&format!(
                            "upload_worker chunk: get_entry missing or error key={}",
                            key_short
                        ));
                    }
                }
                QueueItem::FinalizeMatch { match_id } => {
                    let t_wait = record_now_ms();
                    // Barrier: wait until all chunk uploads for this match are confirmed successful.
                    loop {
                        let remaining = pending_chunks_by_match
                            .borrow()
                            .get(match_id)
                            .copied()
                            .unwrap_or(0);
                        if remaining == 0 {
                            break;
                        }
                        gloo_timers::future::TimeoutFuture::new(250).await;
                    }
                    record_log_duration(
                        &format!(
                            "upload_worker finalize wait pending_chunks=0 match_id={}",
                            match_id
                        ),
                        t_wait,
                    );
                    for attempt in 0..API_RETRY_ATTEMPTS {
                        let t_fin = record_now_ms();
                        if api::record_finalize(
                            &tournament_url,
                            &field,
                            match_id,
                            &camera_name,
                            key.as_deref(),
                        )
                        .await
                        .is_ok()
                        {
                            record_log_duration(
                                &format!("upload_worker record_finalize attempt {}", attempt + 1),
                                t_fin,
                            );
                            let t_del = record_now_ms();
                            if record_idb::delete_entry(&db, &key_str).await.is_ok() {
                                record_log_duration("upload_worker finalize idb delete_entry", t_del);
                                upload_count_sig.set(upload_count_sig() + 1);
                                success = true;
                            }
                            break;
                        }
                        record_log_duration(
                            &format!("upload_worker record_finalize attempt {} failed", attempt + 1),
                            t_fin,
                        );
                        gloo_timers::future::TimeoutFuture::new(API_RETRY_DELAY_MS).await;
                    }
                }
            }
            record_log_duration(
                &format!(
                    "upload_worker queue item total (key={} success={})",
                    key_short, success
                ),
                t_item,
            );
            if !success {
                let mut q = queue.borrow_mut();
                q.push_front((key_str, queue_item));
                let wait_ms = if payload_too_large {
                    PAYLOAD_TOO_LARGE_RETRY_MS
                } else {
                    RETRY_DELAY_MS
                };
                record_log(&format!(
                    "upload_worker re-queue; backoff {} ms",
                    wait_ms
                ));
                gloo_timers::future::TimeoutFuture::new(wait_ms).await;
            }
            is_uploading_sig.set(false);
        }
    }
}

fn uuid_style_id() -> String {
    uuid::Uuid::new_v4().to_string()
}
