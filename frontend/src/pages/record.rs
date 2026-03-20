//! Point recording page: two media recorders with storage/upload queues, match-status polling.

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
#[derive(Clone, Copy, PartialEq, Eq)]
enum RecorderStatus {
    Idle,
    Recording,
}

#[cfg(target_arch = "wasm32")]
struct StoredChunk {
    blob: web_sys::Blob,
    /// Session ID when this chunk was recorded (set at capture time so drain order can't mix sessions).
    session_id: String,
    chunk_start_timestamp: f64,
    chunk_duration_ms: u32,
    recording_session_start_time: f64,
}

/// In-memory queue item: key references chunk or finalize in IndexedDB.
#[cfg(target_arch = "wasm32")]
enum QueueItem {
    Chunk { match_id: Option<String> },
    FinalizeMatch { match_id: String },
}

#[cfg(target_arch = "wasm32")]
#[derive(Clone)]
struct UploadBarItem {
    match_id: Option<String>,
    is_finalize: bool,
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
    let mut upload_bar_items = use_signal(|| Vec::<UploadBarItem>::new());

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

    // Screen wake lock: keep the device awake while the record page is open (wasm only).
    #[cfg(target_arch = "wasm32")]
    {
        let wake_lock_sentinel = use_signal(|| None::<wasm_bindgen::JsValue>);
        use_effect(move || {
            let mut sentinel_sig = wake_lock_sentinel.to_owned();
            wasm_bindgen_futures::spawn_local(async move {
                let window = match web_sys::window() {
                    Some(w) => w,
                    None => return,
                };
                let navigator = window.navigator();
                let wake_lock_js = match js_sys::Reflect::get(&navigator, &wasm_bindgen::JsValue::from_str("wakeLock")) {
                    Ok(v) if !v.is_undefined() && !v.is_null() => v,
                    _ => return,
                };
                let request_js = match js_sys::Reflect::get(&wake_lock_js, &wasm_bindgen::JsValue::from_str("request")) {
                    Ok(v) if v.is_function() => v,
                    _ => return,
                };
                let request_fn = match request_js.dyn_ref::<js_sys::Function>() {
                    Some(f) => f,
                    None => return,
                };
                let type_arg = wasm_bindgen::JsValue::from_str("screen");
                let promise = request_fn.call1(&wake_lock_js, &type_arg).ok().and_then(|v| v.dyn_into::<js_sys::Promise>().ok());
                let promise = match promise {
                    Some(p) => p,
                    None => return,
                };
                let result = wasm_bindgen_futures::JsFuture::from(promise).await;
                if let Ok(sentinel) = result {
                    sentinel_sig.set(Some(sentinel));
                }
            });
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
                    if let Some(el) = doc.get_element_by_id("record-preview") {
                        let _ = el.dyn_into::<web_sys::HtmlMediaElement>().map(|media| media.set_src_object(None));
                    }
                }
            }
        });
    }

    // When we have stream + field + key, start the two recorders and the monitor/upload loop (wasm only).
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
        let upload_bar_items_sig = upload_bar_items.to_owned();
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
                    upload_bar_items_sig,
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
                                                    if let Route::Record { url, field, camera_key, .. } = route.clone() {
                                                        reload_record_page_with_camera_name(&url, &field, &camera_key, &new_name);
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
                                    upload_bar_items,
                                }
                                if let Some(ref msg) = storage_warning() {
                                    div { class: "alert alert-warning", "{msg}" }
                                }
                                div {
                                    id: "record-video-container",
                                    style: format!("display: {};", if matches!(status(), RecordStatus::Connected) { "block" } else { "none" }),
                                    div { class: "mb-2",
                                        video {
                                            id: "record-preview",
                                            autoplay: true,
                                            muted: true,
                                            playsinline: true,
                                            style: "width: 100%; max-width: 640px; border: 2px solid #333; background: #000;",
                                        }
                                    }
                                    // Recording indicator is now part of the match header above.
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
    upload_bar_items: Signal<Vec<UploadBarItem>>,
) -> Element {
    let remaining = {
        let total = upload_total();
        let done = upload_count();
        total.saturating_sub(done)
    };
    let status_text = if remaining == 0 {
        "All data uploaded".to_string()
    } else {
        format!("{remaining} chunks remaining to be uploaded")
    };

    let items = upload_bar_items();

    rsx! {
        div { class: "mt-3",
            h6 { "Upload progress" }
            p {
                class: "mb-1 small text-muted",
                "{status_text}"
            }
            if !items.is_empty() {
                div {
                    class: "d-flex",
                    style: "height: 10px; border-radius: 4px; overflow: hidden; background: #e9ecef;",
                    for (idx, item) in items.iter().enumerate() {
                        div {
                            key: "{idx}",
                            style: format!(
                                "flex: 0 0 {}; background: {}; position: relative;{}",
                                upload_bar_width(items.len()),
                                upload_bar_color(item.match_id.as_deref()),
                                if idx < items.len().saturating_sub(1) {
                                    " border-right: 1px solid rgba(0,0,0,0.25);"
                                } else {
                                    ""
                                }
                            ),
                            if item.is_finalize {
                                span {
                                    style: "position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; font-size: 9px; color: #fff;",
                                    "F"
                                }
                            }
                        }
                    }
                }
            } else {
                div {
                    class: "progress",
                    style: "height: 6px;",
                    div {
                        class: "progress-bar bg-success",
                        style: "width: 100%;",
                    }
                }
            }
        }
    }
}

fn upload_bar_width(count: usize) -> String {
    format!("{:.4}%", 100.0 / (count.max(1) as f32))
}

fn upload_bar_color(match_id: Option<&str>) -> String {
    if let Some(id) = match_id {
        if id.len() >= 6 {
            if let Ok(val) = u32::from_str_radix(&id[..6].replace('-', ""), 16) {
                let h = (val % 360) as i32;
                return format!("hsl({h}, 70%, 55%)");
            }
        }
    }
    "#0d6efd".to_string()
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

    if let Some(doc) = window.document() {
        if let Some(video_el) = doc.get_element_by_id("record-preview") {
            if let Ok(media_el) = video_el.dyn_into::<web_sys::HtmlMediaElement>() {
                media_el.set_src_object(Some(&stream));
                // Safari (especially iOS) often won't show the preview until play() is called.
                let play_promise = media_el.play();
                if let Ok(p) = play_promise {
                    let _ = wasm_bindgen_futures::JsFuture::from(p).await;
                }
            }
        }
    }
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

/// Returns true if current time (ms) is between point start and 10s after point end.
#[cfg(target_arch = "wasm32")]
fn point_in_progress(point: &RecordPointData, now_ms: f64) -> bool {
    let start_ms = match parse_iso_ms(point.stamp.as_deref()) {
        Some(t) => t,
        None => return false,
    };
    if now_ms < start_ms {
        web_sys::console::log_1(&format!("point not in progress: now_ms < start_ms: {} < {}", now_ms, start_ms).into());
        return false;
    }
    let end_plus_10 = point
        .end_stamp
        .as_deref()
        .and_then(|s| parse_iso_ms(Some(s)))
        .map(|end_ms| end_ms + 10_000.0);
    match end_plus_10 {
        Some(limit) => now_ms <= limit,
        None => true, // no end yet, point still in progress
    }
}

/// Among points that are in progress, return the one that started latest (by stamp).
#[cfg(target_arch = "wasm32")]
fn latest_point_in_progress(points: &[RecordPointData], now_ms: f64) -> Option<&RecordPointData> {
    points
        .iter()
        .filter(|p| point_in_progress(*p, now_ms))
        .max_by(|a, b| {
            let ta = parse_iso_ms(a.stamp.as_deref()).unwrap_or(0.0);
            let tb = parse_iso_ms(b.stamp.as_deref()).unwrap_or(0.0);
            ta.partial_cmp(&tb).unwrap_or(std::cmp::Ordering::Equal)
        })
}

/// Capture one frame from #record-preview video as JPEG (max width 640, quality 0.7). WASM only.
#[cfg(target_arch = "wasm32")]
async fn capture_preview_frame() -> Result<bytes::Bytes, String> {
    use wasm_bindgen::closure::Closure;
    use wasm_bindgen::JsCast;

    let window = web_sys::window().ok_or("no window")?;
    let doc = window.document().ok_or("no document")?;
    let video_el = doc
        .get_element_by_id("record-preview")
        .ok_or("no record-preview element")?;
    let video = video_el
        .dyn_ref::<web_sys::HtmlVideoElement>()
        .ok_or("record-preview is not a video")?
        .clone();
    let vw = video.video_width();
    let vh = video.video_height();
    if vw == 0 || vh == 0 {
        return Err("video not ready".to_string());
    }
    let (canvas_w, canvas_h) = if vw > 640 {
        (640u32, (vh as u32 * 640 / vw as u32))
    } else {
        (vw as u32, vh as u32)
    };
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
        &video,
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
    let vec = arr.to_vec();
    Ok(bytes::Bytes::from(vec))
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
                storage_usage = js_sys::Reflect::get(&estimate_js, &"usage".into())
                    .ok()
                    .and_then(|v| v.as_f64());
                storage_quota = js_sys::Reflect::get(&estimate_js, &"quota".into())
                    .ok()
                    .and_then(|v| v.as_f64());
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
    tournament_url: String,
    field: String,
    camera_key: String,
    camera_name: String,
) {
    use std::sync::atomic::Ordering;

    while !stop_flag.load(Ordering::SeqCst) {
        let bytes = match capture_preview_frame().await {
            Ok(b) => b,
            Err(_) => {
                gloo_timers::future::TimeoutFuture::new(500).await;
                continue;
            }
        };
        if let Err(_) = api::upload_preview_frame(
            &tournament_url,
            &field,
            &camera_key,
            &camera_name,
            bytes,
        )
        .await
        {
            gloo_timers::future::TimeoutFuture::new(500).await;
            continue;
        }
        let meta = collect_preview_metadata().await;
        let _ = api::upload_preview_metadata(
            &tournament_url,
            &field,
            &camera_key,
            &camera_name,
            &meta,
        )
        .await;
        while !stop_flag.load(Ordering::SeqCst) {
            match api::is_preview_frame_consumed(&tournament_url, &field, &camera_name, &camera_key).await {
                Ok(true) => break,
                Ok(false) => {}
                Err(_) => break,
            }
            gloo_timers::future::TimeoutFuture::new(300).await;
        }
        gloo_timers::future::TimeoutFuture::new(200).await;
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
    mut upload_bar_items_sig: Signal<Vec<UploadBarItem>>,
) {
    use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
    use std::sync::Arc;
    use wasm_bindgen::closure::Closure;
    use wasm_bindgen::JsCast;
    use web_sys::{MediaRecorder, MediaRecorderOptions};

    // Prefer H.265/HEVC (mp4), fall back to WebM. Use full codec strings (like avc1.42E01E for H.264).
    // HEVC: hvc1/hev1 + profile.compat.level.constraint (e.g. 1.6.L93.B0 = Main profile, level 3.1).
    const MIME_PREFERENCE: &[(&str, &str)] = &[
        ("video/mp4; codecs=hvc1.1.6.L93.B0", "mp4"),
        ("video/mp4; codecs=hev1.1.6.L93.B0", "mp4"),
        ("video/mp4; codecs=hvc1.1.6.L93", "mp4"),
        ("video/mp4; codecs=hev1.1.6.L93", "mp4"),
        ("video/mp4; codecs=hvc1", "mp4"),
        ("video/mp4; codecs=hev1", "mp4"),
        ("video/mp4; codecs=avc1.42E01E", "mp4"),
        ("video/mp4", "mp4"),
        ("video/webm; codecs=vp9", "webm"),
        ("video/webm", "webm"),
    ];

    let key_ref = key.clone();
    let container_ref: Rc<RefCell<String>> = Rc::new(RefCell::new("webm".to_string()));

    // Recorder state: recorder, status, started_at (ms), current_session_id (new id each time this recorder is started).
    struct RecorderState {
        recorder: Option<MediaRecorder>,
        status: RecorderStatus,
        started_at: Option<f64>,
        current_session_id: String,
    }

    // Use a persistent chunk_count for chunk_start_timestamp (storage is drained often so queue length is not a valid index).
    let container_for_recorder = container_ref.clone();
    let make_recorder = |stream: &web_sys::MediaStream,
                        storage_queue: Rc<RefCell<Vec<StoredChunk>>>,
                        session_start: Rc<RefCell<f64>>,
                        chunk_count: Rc<RefCell<u32>>,
                        session_id_ref: Rc<RefCell<String>>| {
        let mut options = MediaRecorderOptions::new();
        options.set_video_bits_per_second(70_000_000);
        options.set_audio_bits_per_second(128_000);
        let mut chosen_container = "webm";
        for (mime, container) in MIME_PREFERENCE {
            if MediaRecorder::is_type_supported(mime) {
                options.set_mime_type(mime);
                chosen_container = container;
                break;
            }
        }
        *container_for_recorder.borrow_mut() = chosen_container.to_string();
        let r = MediaRecorder::new_with_media_stream_and_media_recorder_options(stream, &options)
            .ok()?;
        let sq = storage_queue.clone();
        let ss = session_start.clone();
        let cc = chunk_count.clone();
        let sid_ref = session_id_ref.clone();
        let closure = Closure::wrap(Box::new(move |ev: web_sys::BlobEvent| {
            let blob = match ev.data() {
                Some(b) => b,
                None => return,
            };
            let start = *ss.borrow();
            let chunk_start = start + (*cc.borrow() as f64) * 1000.0;
            *cc.borrow_mut() += 1;
            let session_id = sid_ref.borrow().clone();
            sq.borrow_mut().push(StoredChunk {
                blob,
                session_id,
                chunk_start_timestamp: chunk_start,
                chunk_duration_ms: 1000,
                recording_session_start_time: start,
            });
        }) as Box<dyn FnMut(web_sys::BlobEvent)>);
        r.set_ondataavailable(Some(closure.as_ref().unchecked_ref()));
        closure.forget();
        Some(r)
    };

    let state1 = Rc::new(RefCell::new(RecorderState {
        recorder: None,
        status: RecorderStatus::Idle,
        started_at: None,
        current_session_id: String::new(),
    }));
    let state2 = Rc::new(RefCell::new(RecorderState {
        recorder: None,
        status: RecorderStatus::Idle,
        started_at: None,
        current_session_id: String::new(),
    }));

    let storage1 = Rc::new(RefCell::new(Vec::<StoredChunk>::new()));
    let session_start1 = Rc::new(RefCell::new(0.0f64));
    let chunk_count1 = Rc::new(RefCell::new(0u32));
    let session_id1 = Rc::new(RefCell::new(String::new()));
    let storage2 = Rc::new(RefCell::new(Vec::<StoredChunk>::new()));
    let session_start2 = Rc::new(RefCell::new(0.0f64));
    let chunk_count2 = Rc::new(RefCell::new(0u32));
    let session_id2 = Rc::new(RefCell::new(String::new()));

    if let Some(r) = make_recorder(
        &stream,
        storage1.clone(),
        session_start1.clone(),
        chunk_count1.clone(),
        session_id1.clone(),
    ) {
        state1.borrow_mut().recorder = Some(r);
    }
    if let Some(r) = make_recorder(
        &stream,
        storage2.clone(),
        session_start2.clone(),
        chunk_count2.clone(),
        session_id2.clone(),
    ) {
        state2.borrow_mut().recorder = Some(r);
    }

    let db_holder: Rc<RefCell<Option<idb::Database>>> = Rc::new(RefCell::new(None));
    if db_holder.borrow().is_none() {
        if let Ok(db) = record_idb::open_db().await {
            *db_holder.borrow_mut() = Some(db);
        }
    }
    let upload_queue: Rc<RefCell<VecDeque<(String, QueueItem)>>> = Rc::new(RefCell::new(VecDeque::new()));
    // Barrier tracking for finalize ordering:
    // For each match_id, keep a count of chunk uploads that have not yet been confirmed successful.
    // A FinalizeMatch item must not run until this reaches 0.
    let pending_chunks_by_match: Rc<RefCell<HashMap<String, u32>>> = Rc::new(RefCell::new(HashMap::new()));
    if let Some(ref db) = *db_holder.borrow() {
        if let Ok(entries) = record_idb::cursor_entries_ordered(db).await {
            for (key, value) in entries {
                if let Some(match_id) = record_idb::parse_finalize_value(&value) {
                    upload_queue
                        .borrow_mut()
                        .push_back((key, QueueItem::FinalizeMatch { match_id }));
                } else if let Some((meta, _blob)) = record_idb::parse_chunk_value(&value) {
                    let match_id = meta.match_id.clone();
                    *pending_chunks_by_match.borrow_mut().entry(match_id.clone()).or_insert(0) += 1;
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
            update_upload_bar_from_queue(&q_ref, upload_bar_items_sig.to_owned());
        }
        // Reconcile: add FinalizeMatch for matches that have chunks but no finalize in queue and are no longer active
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
                need_finalize.retain(|id| {
                    current_match_id.map(|cur| cur != id.as_str()).unwrap_or(true)
                });
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
                    let q_ref = upload_queue.borrow();
                    update_upload_bar_from_queue(&q_ref, upload_bar_items_sig.to_owned());
                }
            }
        }
        // Check storage quota; warn if low (e.g. < 100 MB free).
        if let Some(window) = web_sys::window() {
            let storage = window.navigator().storage();
            if let Ok(promise) = storage.estimate() {
                    if let Ok(estimate_js) = wasm_bindgen_futures::JsFuture::from(promise).await {
                        let quota = js_sys::Reflect::get(&estimate_js, &"quota".into())
                            .ok().and_then(|v| v.as_f64()).unwrap_or(0.0);
                        let usage = js_sys::Reflect::get(&estimate_js, &"usage".into())
                            .ok().and_then(|v| v.as_f64()).unwrap_or(0.0);
                        const LOW_STORAGE_BYTES: f64 = 100_000_000.0; // 100 MB
                        if quota > 0.0 && (quota - usage) < LOW_STORAGE_BYTES {
                            storage_warning_sig.set(Some(
                                "Low device storage for recording buffer; uploads may fail if connection is slow.".to_string(),
                            ));
                        }
                    }
                }
        }
    }
    const NUM_UPLOAD_WORKERS: u32 = 3;
    for _ in 0..NUM_UPLOAD_WORKERS {
        let q = upload_queue.clone();
            let pending_chunks_by_match_sig = pending_chunks_by_match.clone();
        let tour = tournament_url.clone();
        let f = field.clone();
        let cam = camera_name.clone();
        let k = key_ref.clone();
        let is_up = is_uploading_sig.to_owned();
        let up_cnt = upload_count_sig.to_owned();
        let bar_items = upload_bar_items_sig.to_owned();
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
                    bar_items,
                )
                .await;
        });
    }

    let mut current_match: Option<String> = None; // match_id
    let mut last_poll_data: Option<RecordMatchStatusResponse> = None;
    let mut point_was_in_progress = false;
    let chunk_index_global = AtomicU32::new(0);
    let mut preview_stop: Option<Arc<AtomicBool>> = None;
    let mut preview_sender_running = false;

    loop {
        let poll_result = api::record_match_status(
            &tournament_url,
            &field,
            current_match.as_ref().map(|id| id.as_str()),
        )
        .await;

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

        // Start or stop the preview sender task based on data.preview_requested.
        if data.preview_requested && !preview_sender_running {
            if let Some(ref key_str) = key {
                let stop = Arc::new(AtomicBool::new(false));
                let stop_c = stop.clone();
                let tour = tournament_url.clone();
                let f = field.clone();
                let k = key_str.clone();
                let cam = camera_name.clone();
                dioxus::prelude::spawn(async move {
                    run_preview_sender_loop(stop_c, tour, f, k, cam).await;
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
        let point_in_progress_now = points
            .iter()
            .any(|p| point_in_progress(p, now_ms));
        let _latest_point = latest_point_in_progress(points, now_ms);
        // web_sys::console::log_1(&format!("data match id: {:?}", data.match_id).into());
        // web_sys::console::log_1(&format!("current match: {:?}", current_match).into());
        if !data.hasActiveMatch || data.match_id.as_ref().map(|s| s.as_str()) != current_match.as_ref().map(|id| id.as_str()) {
            if let Some(match_id) = current_match.take() {
                if let Some(r1) = state1.borrow_mut().recorder.take() {
                    let _ = r1.stop();
                }
                if let Some(r2) = state2.borrow_mut().recorder.take() {
                    let _ = r2.stop();
                }
                storage1.borrow_mut().clear();
                storage2.borrow_mut().clear();
                state1.borrow_mut().status = RecorderStatus::Idle;
                state2.borrow_mut().status = RecorderStatus::Idle;
                state1.borrow_mut().started_at = None;
                state2.borrow_mut().started_at = None;
                if let Some(ref db) = *db_holder.borrow() {
                    if let Ok(key) = record_idb::get_next_sequence(db).await {
                                match record_idb::put_finalize(db, &key, &match_id).await {
                            Ok(()) => {
                                let mut q = upload_queue.borrow_mut();
                                q.push_back((key, QueueItem::FinalizeMatch { match_id: match_id.clone() }));
                                update_upload_bar_from_queue(&q, upload_bar_items_sig.to_owned());
                            }
                            Err(ref e) => {
                                if let idb::Error::DomException(ref dom) = e {
                                    if dom.name() == "QuotaExceededError" {
                                        storage_warning_sig.set(Some(
                                            "Recording buffer full. Free device storage or wait for uploads to catch up.".to_string(),
                                        ));
                                    }
                                }
                            }
                        }
                    }
                }
                is_recording_sig.set(false);
            }
            if data.hasActiveMatch {
                if let Some(ref match_id) = data.match_id {
                    current_match = Some(match_id.clone());
                    is_recording_sig.set(true);
                    *session_start1.borrow_mut() = now_ms;
                    *chunk_count1.borrow_mut() = 0;
                    state1.borrow_mut().started_at = Some(now_ms);
                    let new_sid = uuid_style_id();
                    state1.borrow_mut().current_session_id = new_sid.clone();
                    *session_id1.borrow_mut() = new_sid.clone();
                    // After a match ends we take and stop both recorders, so they are None for the next match. Recreate if needed.
                    if state1.borrow().recorder.is_none() {
                        if let Some(r) = make_recorder(
                            &stream,
                            storage1.clone(),
                            session_start1.clone(),
                            chunk_count1.clone(),
                            session_id1.clone(),
                        ) {
                            let _ = r.start_with_time_slice(1000);
                            state1.borrow_mut().recorder = Some(r);
                        }
                    } else if let Some(r) = state1.borrow().recorder.as_ref() {
                        let state_str: String = js_sys::Reflect::get(r.as_ref(), &"state".into())
                            .ok()
                            .and_then(|v| v.as_string())
                            .unwrap_or_default();
                        // Start unless already recording (some browsers may not report "inactive")
                        if state_str != "recording" {
                            let _ = r.start_with_time_slice(1000);
                        }
                    }
                    if state2.borrow().recorder.is_none() {
                        *session_start2.borrow_mut() = now_ms;
                        *chunk_count2.borrow_mut() = 0;
                        let sid2 = uuid_style_id();
                        *session_id2.borrow_mut() = sid2.clone();
                        state2.borrow_mut().current_session_id = sid2;
                        if let Some(r) = make_recorder(
                            &stream,
                            storage2.clone(),
                            session_start2.clone(),
                            chunk_count2.clone(),
                            session_id2.clone(),
                        ) {
                            state2.borrow_mut().recorder = Some(r);
                        }
                    }
                }
            }
            gloo_timers::future::TimeoutFuture::new(500).await;
            continue;
        }
        let match_id = current_match.as_ref().expect("current_match is None").clone();

        // 1. Handle storage queues: if RECORDING, drain storage into upload queue (use this recorder's session_id)
        let base_meta = RecordChunkMeta {
            tournament_url: tournament_url.clone(),
            field: field.clone(),
            match_id: match_id.clone(),
            session_id: String::new(), // overridden per state below
            chunk_start_timestamp: 0.0,
            recording_session_start_time: 0.0,
            chunk_length_ms: 1000,
            camera_name: camera_name.clone(),
            key: key_ref.clone(),
            container: container_ref.borrow().clone(),
        };
        for (_state, storage_rc) in [
            (&state1, storage1.clone()),
            (&state2, storage2.clone()),
        ] {
            if _state.borrow().status == RecorderStatus::Recording {
                let drained: Vec<StoredChunk> = storage_rc.borrow_mut().drain(..).collect();
                let n = drained.len();
                if n > 0 {
                    if let Some(ref db) = *db_holder.borrow() {
                                for st in drained {
                            let _idx = chunk_index_global.fetch_add(1, Ordering::Relaxed);
                            let meta = RecordChunkMeta {
                                session_id: st.session_id.clone(),
                                chunk_start_timestamp: st.chunk_start_timestamp,
                                recording_session_start_time: st.recording_session_start_time,
                                chunk_length_ms: st.chunk_duration_ms,
                                ..base_meta.clone()
                            };
                            if let Ok(key) = record_idb::get_next_sequence(db).await {
                                match record_idb::put_chunk(db, &key, &meta, &st.blob).await {
                                    Ok(()) => {
                                        let mut q = upload_queue.borrow_mut();
                                                    *pending_chunks_by_match.borrow_mut().entry(match_id.clone()).or_insert(0) += 1;
                                        q.push_back((
                                            key,
                                            QueueItem::Chunk {
                                                match_id: Some(match_id.clone()),
                                            },
                                        ));
                                        update_upload_bar_from_queue(&q, upload_bar_items_sig.to_owned());
                                    }
                                    Err(ref e) => {
                                        if let idb::Error::DomException(ref dom) = e {
                                            if dom.name() == "QuotaExceededError" {
                                                storage_warning_sig.set(Some(
                                                    "Recording buffer full. Free device storage or wait for uploads to catch up.".to_string(),
                                                ));
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    upload_total_sig.set(upload_total_sig() + n as u32);
                }
            }
        }

        // 2. already computed point_in_progress_now

        // 3. No point in progress: cycle recorders
        if !point_in_progress_now {
            let t1 = state1.borrow().started_at.unwrap_or(now_ms);
            let t2 = state2.borrow().started_at.unwrap_or(now_ms);
            let (longer, shorter) = if t1 <= t2 {
                (&state1, &state2)
            } else {
                (&state2, &state1)
            };
            let longer_run_secs = (now_ms - longer.borrow().started_at.unwrap_or(0.0)) / 1000.0;
            let shorter_run_secs = (now_ms - shorter.borrow().started_at.unwrap_or(0.0)) / 1000.0;

            if longer_run_secs > 10.0 {
                web_sys::console::log_1(&format!("longer recorder running for too long: {}s (t1: {}s, t2: {}s)", longer_run_secs, now_ms-t1, now_ms-t2).into());
                if let Some(r) = longer.borrow_mut().recorder.take() {
                    let _ = r.stop();
                }
                if std::ptr::eq(longer.as_ref(), state1.as_ref()) {
                    storage1.borrow_mut().clear();
                } else {
                    storage2.borrow_mut().clear();
                }
                longer.borrow_mut().status = RecorderStatus::Idle;
                longer.borrow_mut().started_at = None;
                let session_start_longer = if std::ptr::eq(longer.as_ref(), state1.as_ref()) {
                    session_start1.clone()
                } else {
                    session_start2.clone()
                };
                let chunk_count_longer = if std::ptr::eq(longer.as_ref(), state1.as_ref()) {
                    chunk_count1.clone()
                } else {
                    chunk_count2.clone()
                };
                let session_id_longer = if std::ptr::eq(longer.as_ref(), state1.as_ref()) {
                    session_id1.clone()
                } else {
                    session_id2.clone()
                };
                *session_start_longer.borrow_mut() = now_ms;
                *chunk_count_longer.borrow_mut() = 0;
                let new_sid = uuid_style_id();
                longer.borrow_mut().current_session_id = new_sid.clone();
                if std::ptr::eq(longer.as_ref(), state1.as_ref()) {
                    *session_id1.borrow_mut() = new_sid.clone();
                } else {
                    *session_id2.borrow_mut() = new_sid.clone();
                }
                if let Some(new_r) = make_recorder(
                    &stream,
                    if std::ptr::eq(longer.as_ref(), state1.as_ref()) {
                        storage1.clone()
                    } else {
                        storage2.clone()
                    },
                    session_start_longer,
                    chunk_count_longer,
                    session_id_longer,
                ) {
                    let _ = new_r.start_with_time_slice(1000);
                    longer.borrow_mut().recorder = Some(new_r);
                    longer.borrow_mut().started_at = Some(now_ms);
                }
            } else if longer_run_secs > 5.0 {
                let is_inactive = shorter
                    .borrow()
                    .recorder
                    .as_ref()
                    .map(|r| {
                        js_sys::Reflect::get(r.as_ref(), &"state".into())
                            .ok()
                            .and_then(|v| v.as_string())
                            .as_deref()
                            == Some("inactive")
                    })
                    .unwrap_or(true);
                if is_inactive {
                    web_sys::console::log_1(&format!("shorter recorder is inactive, replacing with new recorder for fresh init segment").into());
                    if let Some(old_r) = shorter.borrow_mut().recorder.take() {
                        let _ = old_r.stop();
                    }
                    if std::ptr::eq(shorter.as_ref(), state1.as_ref()) {
                        storage1.borrow_mut().clear();
                    } else {
                        storage2.borrow_mut().clear();
                    }
                    let session_start_shorter = if std::ptr::eq(shorter.as_ref(), state1.as_ref()) {
                        session_start1.clone()
                    } else {
                        session_start2.clone()
                    };
                    let chunk_count_shorter = if std::ptr::eq(shorter.as_ref(), state1.as_ref()) {
                        chunk_count1.clone()
                    } else {
                        chunk_count2.clone()
                    };
                    let session_id_shorter = if std::ptr::eq(shorter.as_ref(), state1.as_ref()) {
                        session_id1.clone()
                    } else {
                        session_id2.clone()
                    };
                    *session_start_shorter.borrow_mut() = now_ms;
                    *chunk_count_shorter.borrow_mut() = 0;
                    let new_sid = uuid_style_id();
                    shorter.borrow_mut().current_session_id = new_sid.clone();
                    if std::ptr::eq(shorter.as_ref(), state1.as_ref()) {
                        *session_id1.borrow_mut() = new_sid.clone();
                    } else {
                        *session_id2.borrow_mut() = new_sid.clone();
                    }
                    if let Some(new_r) = make_recorder(
                        &stream,
                        if std::ptr::eq(shorter.as_ref(), state1.as_ref()) {
                            storage1.clone()
                        } else {
                            storage2.clone()
                        },
                        session_start_shorter,
                        chunk_count_shorter,
                        session_id_shorter,
                    ) {
                        let _ = new_r.start_with_time_slice(1000);
                        shorter.borrow_mut().recorder = Some(new_r);
                    }
                    shorter.borrow_mut().started_at = Some(now_ms);
                }
            }
        }

        // 4. Point in progress and new: set longest to RECORDING, stop the other
        if point_in_progress_now && !point_was_in_progress {
            let t1 = state1.borrow().started_at.unwrap_or(now_ms);
            let t2 = state2.borrow().started_at.unwrap_or(now_ms);
            let (recording_state, other_state) = if t1 <= t2 {
                (&state1, &state2)
            } else {
                (&state2, &state1)
            };
            recording_state.borrow_mut().status = RecorderStatus::Recording;
            if let Some(r) = other_state.borrow().recorder.as_ref() {
                let _ = r.stop();
            }
            if std::ptr::eq(other_state.as_ref(), state1.as_ref()) {
                storage1.borrow_mut().clear();
            } else {
                storage2.borrow_mut().clear();
            }
            other_state.borrow_mut().status = RecorderStatus::Idle;
            other_state.borrow_mut().started_at = None;
        }

        if !point_in_progress_now {
            state1.borrow_mut().status = RecorderStatus::Idle;
            state2.borrow_mut().status = RecorderStatus::Idle;
        }

        point_was_in_progress = point_in_progress_now;

        if data.hasActiveMatch {
            match_status_data_sig.set(Some(data));
        } else {
            match_status_data_sig.set(None);
        }
        gloo_timers::future::TimeoutFuture::new(500).await;
    }
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
    mut upload_bar_items_sig: Signal<Vec<UploadBarItem>>,
) {
    /// Delay before retrying a failed upload (connection lost, etc.).
    const RETRY_DELAY_MS: u32 = 3000;
    /// Number of immediate retries for each upload attempt (any error).
    const API_RETRY_ATTEMPTS: u32 = 5;
    /// Delay between API retries (ms).
    const API_RETRY_DELAY_MS: u32 = 1500;

    loop {
        gloo_timers::future::TimeoutFuture::new(200).await;
        let item = queue.borrow_mut().pop_front();
        if let Some((key_str, queue_item)) = item {
            is_uploading_sig.set(true);
            let mut success = false;
            match &queue_item {
                QueueItem::Chunk { .. } => {
                    if let Ok(Some(value)) = record_idb::get_entry(&db, &key_str).await {
                        if let Some((meta, blob)) = record_idb::parse_chunk_value(&value) {
                            for _ in 0..API_RETRY_ATTEMPTS {
                                if api::record_upload_chunk(&meta, &blob).await.is_ok() {
                                    if record_idb::delete_entry(&db, &key_str).await.is_ok() {
                                        upload_count_sig.set(upload_count_sig() + 1);
                                        success = true;
                                        // Confirmed success: decrement pending chunk count for this match.
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
                                gloo_timers::future::TimeoutFuture::new(API_RETRY_DELAY_MS).await;
                            }
                        }
                    }
                }
                QueueItem::FinalizeMatch { match_id } => {
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
                    for _ in 0..API_RETRY_ATTEMPTS {
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
                            let _ = record_idb::delete_entry(&db, &key_str).await;
                            success = true;
                            break;
                        }
                        gloo_timers::future::TimeoutFuture::new(API_RETRY_DELAY_MS).await;
                    }
                }
            }
            if !success {
                let mut q = queue.borrow_mut();
                q.push_front((key_str, queue_item));
                update_upload_bar_from_queue(&q, upload_bar_items_sig.to_owned());
                gloo_timers::future::TimeoutFuture::new(RETRY_DELAY_MS).await;
            } else {
                let q = queue.borrow();
                update_upload_bar_from_queue(&q, upload_bar_items_sig.to_owned());
            }
            is_uploading_sig.set(false);
        }
    }
}

fn update_upload_bar_from_queue(
    queue: &VecDeque<(String, QueueItem)>,
    mut items_sig: Signal<Vec<UploadBarItem>>,
) {
    let mut items = Vec::with_capacity(queue.len());
    for (_key, qitem) in queue.iter() {
        match qitem {
            QueueItem::Chunk { match_id } => items.push(UploadBarItem {
                match_id: match_id.clone(),
                is_finalize: false,
            }),
            QueueItem::FinalizeMatch { match_id } => items.push(UploadBarItem {
                match_id: Some(match_id.clone()),
                is_finalize: true,
            }),
        }
    }
    items_sig.set(items);
}

fn uuid_style_id() -> String {
    uuid::Uuid::new_v4().to_string()
}
