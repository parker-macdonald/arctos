//! Point recording page: two media recorders with storage/upload queues, match-status polling.

use crate::api;
use crate::types::{RecordMatchStatusResponse, RecordPointData};
use crate::Route;
use dioxus::prelude::*;
use std::cell::RefCell;
use std::collections::VecDeque;
use std::rc::Rc;

#[cfg(target_arch = "wasm32")]
use crate::api::RecordChunkMeta;

#[cfg(target_arch = "wasm32")]
#[derive(Clone, Copy, PartialEq, Eq)]
enum RecorderStatus {
    Idle,
    Recording,
}

#[cfg(target_arch = "wasm32")]
struct StoredChunk {
    blob: web_sys::Blob,
    chunk_start_timestamp: f64,
    chunk_duration_ms: u32,
    recording_session_start_time: f64,
    /// Point in progress when this chunk was recorded (set at capture time, not drain time).
    point_id: Option<String>,
}

#[cfg(target_arch = "wasm32")]
enum UploadQueueItem {
    Chunk {
        meta: RecordChunkMeta,
        blob: web_sys::Blob,
    },
    FinalizeMatch { match_id: String },
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
    let mut available_cameras = use_signal(|| Vec::<(String, String)>::new());
    let mut selected_camera_id = use_signal(|| None::<String>);
    let mut preview_stream = use_signal(|| None::<web_sys::MediaStream>);

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
                                    div { class: "mt-2",
                                        if is_recording() {
                                            div { class: "alert alert-danger",
                                                "● Recording... "
                                            }
                                        }
                                        if is_uploading() {
                                            div { class: "alert alert-info",
                                                "↑ Uploading video chunks... ({upload_count()})"
                                            }
                                        }
                                    }
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

    let mut constraints = MediaStreamConstraints::new();
    constraints.video(&true.into());
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
            status.set(RecordStatus::Error("Camera permission denied".to_string()));
            return;
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
        let mut specific_constraints = MediaStreamConstraints::new();
        let mut video_constraint = js_sys::Object::new();
        let device_id_obj = js_sys::Object::new();
        js_sys::Reflect::set(&device_id_obj, &"exact".into(), &device_id.into()).ok();
        js_sys::Reflect::set(&video_constraint, &"deviceId".into(), &device_id_obj.into()).ok();
        specific_constraints.video(&video_constraint.into());
        specific_constraints.audio(&true.into());

        let promise = match media_devices.get_user_media_with_constraints(&specific_constraints) {
            Ok(p) => p,
            Err(_) => {
                preview_stream.set(Some(initial_stream));
                return;
            }
        };

        if let Ok(stream_result) = JsFuture::from(promise).await {
            if let Ok(s) = stream_result.dyn_into::<web_sys::MediaStream>() {
                let tracks = initial_stream.get_tracks();
                for i in 0..tracks.length() {
                    if let Some(track) = tracks.get(i).dyn_ref::<web_sys::MediaStreamTrack>() {
                        track.stop();
                    }
                }
                s
            } else {
                initial_stream
            }
        } else {
            initial_stream
        }
    } else {
        initial_stream
    };

    preview_stream.set(Some(stream.clone()));

    if let Some(doc) = window.document() {
        if let Some(video_el) = doc.get_element_by_id("record-preview") {
            if let Ok(media_el) = video_el.dyn_into::<web_sys::HtmlMediaElement>() {
                media_el.set_src_object(Some(&stream));
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
) {
    use std::sync::atomic::{AtomicU32, Ordering};
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
    // point_id is read at chunk capture time so chunks get the point that was in progress when recorded, not when drained.
    let container_for_recorder = container_ref.clone();
    let make_recorder = |stream: &web_sys::MediaStream,
                        storage_queue: Rc<RefCell<Vec<StoredChunk>>>,
                        session_start: Rc<RefCell<f64>>,
                        chunk_count: Rc<RefCell<u32>>,
                        current_point_id: Rc<RefCell<Option<String>>>| {
        let mut options = MediaRecorderOptions::new();
        options.set_video_bits_per_second(50_000_000);
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
        let cpid = current_point_id.clone();
        let closure = Closure::wrap(Box::new(move |ev: web_sys::BlobEvent| {
            let blob = match ev.data() {
                Some(b) => b,
                None => return,
            };
            let start = *ss.borrow();
            let chunk_start = start + (*cc.borrow() as f64) * 1000.0;
            *cc.borrow_mut() += 1;
            let point_id = cpid.borrow().clone();
            sq.borrow_mut().push(StoredChunk {
                blob,
                chunk_start_timestamp: chunk_start,
                chunk_duration_ms: 1000,
                recording_session_start_time: start,
                point_id,
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
    let storage2 = Rc::new(RefCell::new(Vec::<StoredChunk>::new()));
    let session_start2 = Rc::new(RefCell::new(0.0f64));
    let chunk_count2 = Rc::new(RefCell::new(0u32));
    let current_point_id = Rc::new(RefCell::new(None::<String>));

    if let Some(r) = make_recorder(
        &stream,
        storage1.clone(),
        session_start1.clone(),
        chunk_count1.clone(),
        current_point_id.clone(),
    ) {
        state1.borrow_mut().recorder = Some(r);
    }
    if let Some(r) = make_recorder(
        &stream,
        storage2.clone(),
        session_start2.clone(),
        chunk_count2.clone(),
        current_point_id.clone(),
    ) {
        state2.borrow_mut().recorder = Some(r);
    }

    let upload_queue: Rc<RefCell<VecDeque<UploadQueueItem>>> = Rc::new(RefCell::new(VecDeque::new()));
    let upload_queue_worker = upload_queue.clone();
    let tournament_url_upload = tournament_url.clone();
    let field_upload = field.clone();
    let camera_name_upload = camera_name.clone();
    let key_upload = key_ref.clone();
    spawn(async move {
        run_upload_worker(
            upload_queue_worker,
            tournament_url_upload,
            field_upload,
            camera_name_upload,
            key_upload,
            is_uploading_sig,
            upload_count_sig,
        )
        .await;
    });

    let mut current_match: Option<String> = None; // match_id
    let mut last_poll_data: Option<RecordMatchStatusResponse> = None;
    let mut point_was_in_progress = false;
    let chunk_index_global = AtomicU32::new(0);

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

        let now_ms = js_sys::Date::now();
        let points = data.points.as_deref().unwrap_or(&[]);
        let point_in_progress_now = points
            .iter()
            .any(|p| point_in_progress(p, now_ms));
        let latest_point = latest_point_in_progress(points, now_ms);
        let point_id_opt = latest_point.map(|p| p.uuid.clone());
        *current_point_id.borrow_mut() = point_id_opt.clone();
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
                upload_queue.borrow_mut().push_back(UploadQueueItem::FinalizeMatch { match_id });
                is_recording_sig.set(false);
            }
            if data.hasActiveMatch {
                if let Some(ref match_id) = data.match_id {
                    current_match = Some(match_id.clone());
                    is_recording_sig.set(true);
                    *current_point_id.borrow_mut() = point_id_opt.clone();
                    *session_start1.borrow_mut() = now_ms;
                    *chunk_count1.borrow_mut() = 0;
                    state1.borrow_mut().started_at = Some(now_ms);
                    state1.borrow_mut().current_session_id = uuid_style_id();
                    if let Some(r) = state1.borrow().recorder.as_ref() {
                        let state_str: String = js_sys::Reflect::get(r.as_ref(), &"state".into())
                            .ok()
                            .and_then(|v| v.as_string())
                            .unwrap_or_default();
                        if state_str == "inactive" {
                            let _ = r.start_with_time_slice(1000);
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
            point_id: None, // overridden per chunk from st.point_id
            chunk_start_timestamp: 0.0,
            recording_session_start_time: 0.0,
            chunk_length_ms: 1000,
            camera_name: camera_name.clone(),
            key: key_ref.clone(),
            container: container_ref.borrow().clone(),
        };
        for (state, storage_rc) in [
            (&state1, storage1.clone()),
            (&state2, storage2.clone()),
        ] {
            if state.borrow().status == RecorderStatus::Recording {
                let chunk_session_id = state.borrow().current_session_id.clone();
                let drained: Vec<StoredChunk> = storage_rc.borrow_mut().drain(..).collect();
                for st in drained {
                    let _idx = chunk_index_global.fetch_add(1, Ordering::Relaxed);
                    let meta = RecordChunkMeta {
                        session_id: chunk_session_id.clone(),
                        chunk_start_timestamp: st.chunk_start_timestamp,
                        recording_session_start_time: st.recording_session_start_time,
                        chunk_length_ms: st.chunk_duration_ms,
                        point_id: st.point_id.clone(),
                        ..base_meta.clone()
                    };
                    upload_queue
                        .borrow_mut()
                        .push_back(UploadQueueItem::Chunk { meta, blob: st.blob });
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
                *session_start_longer.borrow_mut() = now_ms;
                *chunk_count_longer.borrow_mut() = 0;
                if let Some(new_r) = make_recorder(
                    &stream,
                    if std::ptr::eq(longer.as_ref(), state1.as_ref()) {
                        storage1.clone()
                    } else {
                        storage2.clone()
                    },
                    session_start_longer,
                    chunk_count_longer,
                    current_point_id.clone(),
                ) {
                    let _ = new_r.start_with_time_slice(1000);
                    longer.borrow_mut().recorder = Some(new_r);
                    longer.borrow_mut().started_at = Some(now_ms);
                    longer.borrow_mut().current_session_id = uuid_style_id();
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
                    web_sys::console::log_1(&format!("shorter recorder is inactive, starting it").into());
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
                    *session_start_shorter.borrow_mut() = now_ms;
                    *chunk_count_shorter.borrow_mut() = 0;
                    if let Some(r) = shorter.borrow().recorder.as_ref() {
                        let _ = r.start_with_time_slice(1000);
                    }
                    shorter.borrow_mut().started_at = Some(now_ms);
                    shorter.borrow_mut().current_session_id = uuid_style_id();
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

        match_status_data_sig.set(Some(data));
        gloo_timers::future::TimeoutFuture::new(500).await;
    }
}

#[cfg(target_arch = "wasm32")]
async fn run_upload_worker(
    queue: Rc<RefCell<VecDeque<UploadQueueItem>>>,
    tournament_url: String,
    field: String,
    camera_name: String,
    key: Option<String>,
    mut is_uploading_sig: Signal<bool>,
    mut upload_count_sig: Signal<u32>,
) {
    loop {
        gloo_timers::future::TimeoutFuture::new(200).await;
        let item = queue.borrow_mut().pop_front();
        if let Some(item) = item {
            is_uploading_sig.set(true);
            match item {
                UploadQueueItem::Chunk { meta, blob } => {
                    let _ = api::record_upload_chunk(&meta, &blob).await;
                    upload_count_sig.set(upload_count_sig() + 1);
                }
                UploadQueueItem::FinalizeMatch { match_id } => {
                    let _ = api::record_finalize(
                        &tournament_url,
                        &field,
                        &match_id,
                        &camera_name,
                        key.as_deref(),
                    )
                    .await;
                }
            }
            is_uploading_sig.set(false);
        }
    }
}

fn uuid_style_id() -> String {
    uuid::Uuid::new_v4().to_string()
}
