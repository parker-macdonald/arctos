use crate::api;
use crate::Route;
use crate::stones_filter::BayesianOffsetFilter;
use crate::types::{PointData, PointTimestamp};
use dioxus::prelude::*;
use serde_json::Value;
#[cfg(target_arch = "wasm32")]
use gloo_timers::callback::Interval;
#[cfg(target_arch = "wasm32")]
use chrono;
#[cfg(target_arch = "wasm32")]
use wasm_bindgen::JsCast;

/// Resolve in-video start time for a point: by uuid if present, else by index (legacy).
fn in_video_start_for_point(
    ts: &[PointTimestamp],
    points: &[PointData],
    point_index: usize,
) -> Option<f64> {
    let uuid = points.get(point_index).map(|p| &p.uuid)?;
    for t in ts {
        if t.point_uuid.as_ref() == Some(uuid) {
            return Some(t.in_video_start);
        }
    }
    // Legacy: no uuids, use index
    ts.get(point_index).map(|t| t.in_video_start)
}

/// Compute seek time in the new camera to match "same time in real life" from current camera.
/// Returns None if we can't resolve (e.g. legacy data without uuids, or point not in new camera).
fn same_time_seek_target(
    current_ts: &[PointTimestamp],
    new_ts: Option<&[PointTimestamp]>,
    current_video_time_secs: f64,
) -> Option<f64> {
    let new_ts = new_ts?;
    // Latest point (by in_video_start) that we're at or past
    let entry = current_ts
        .iter()
        .filter(|t| t.in_video_start <= current_video_time_secs)
        .last()?;
    let point_uuid = entry.point_uuid.as_ref()?;
    let offset = current_video_time_secs - entry.in_video_start;
    let new_entry = new_ts
        .iter()
        .find(|t| t.point_uuid.as_ref() == Some(point_uuid))?;
    Some(new_entry.in_video_start + offset)
}

fn get_query_param(name: &str) -> Option<String> {
    #[cfg(target_arch = "wasm32")]
    {
        let window = web_sys::window()?;
        let search = window.location().search().ok()?;
        let params = web_sys::UrlSearchParams::new_with_str(&search).ok()?;
        params.get(name)
    }
#[cfg(not(target_arch = "wasm32"))]
{
    let _ = name;
    None
}
}

/// Seek the local video player to the given time in seconds (wasm only).
#[cfg(target_arch = "wasm32")]
fn seek_video_to(secs: f64) {
    if let Some(doc) = web_sys::window().and_then(|w| w.document()) {
        if let Some(el) = doc.get_element_by_id("local-video-player") {
            if let Ok(media) = el.dyn_into::<web_sys::HtmlMediaElement>() {
                media.set_current_time(secs);
            }
        }
    }
}

/// Step the local video player forward or backward by one frame (~1/30s) (wasm only).
#[cfg(target_arch = "wasm32")]
fn step_video_frame(forward: bool) {
    if let Some(doc) = web_sys::window().and_then(|w| w.document()) {
        if let Some(el) = doc.get_element_by_id("local-video-player") {
            if let Ok(media) = el.dyn_into::<web_sys::HtmlMediaElement>() {
                let t: f64 = media.current_time();
                let delta = if forward { 1.0 / 30.0 } else { -1.0 / 30.0 };
                media.set_current_time((t + delta).max(0.0));
            }
        }
    }
}

/// Toggle play/pause on the local video player (wasm only).
#[cfg(target_arch = "wasm32")]
fn toggle_video_play_pause() {
    if let Some(doc) = web_sys::window().and_then(|w| w.document()) {
        if let Some(el) = doc.get_element_by_id("local-video-player") {
            if let Ok(media) = el.dyn_into::<web_sys::HtmlMediaElement>() {
                if media.paused() {
                    let _ = media.play();
                } else {
                    let _ = media.pause();
                }
            }
        }
    }
}

/// Set the local video player playback rate (wasm only).
#[cfg(target_arch = "wasm32")]
fn set_video_playback_speed(rate: f64) {
    if let Some(doc) = web_sys::window().and_then(|w| w.document()) {
        if let Some(el) = doc.get_element_by_id("local-video-player") {
            if let Ok(media) = el.dyn_into::<web_sys::HtmlMediaElement>() {
                media.set_playback_rate(rate);
            }
        }
    }
}

#[cfg(not(target_arch = "wasm32"))]
fn seek_video_to(_secs: f64) {}

#[cfg(not(target_arch = "wasm32"))]
fn step_video_frame(_forward: bool) {}

#[cfg(not(target_arch = "wasm32"))]
fn toggle_video_play_pause() {}

#[cfg(not(target_arch = "wasm32"))]
fn set_video_playback_speed(_rate: f64) {}

/// Get current time in seconds of the local video player (wasm only).
#[cfg(target_arch = "wasm32")]
fn get_video_current_time() -> Option<f64> {
    let doc = web_sys::window()?.document()?;
    let el = doc.get_element_by_id("local-video-player")?;
    let media = el.dyn_into::<web_sys::HtmlMediaElement>().ok()?;
    Some(media.current_time())
}

#[cfg(not(target_arch = "wasm32"))]
fn get_video_current_time() -> Option<f64> {
    None
}

/// Seek the YouTube iframe player to the given time in seconds (wasm only).
#[cfg(target_arch = "wasm32")]
fn seek_youtube_to(secs: f64) {
    let script = format!(
        r#"if (window.__arctosYtPlayer && window.__arctosYtPlayer.seekTo) {{ window.__arctosYtPlayer.seekTo({}, true); }}"#,
        secs
    );
    spawn(async move {
        let _ = dioxus::prelude::document::eval(&script).await;
    });
}

#[cfg(not(target_arch = "wasm32"))]
fn seek_youtube_to(_secs: f64) {}

/// Compute seek time in seconds for YouTube: (point_stamp - stream_start_time). Returns None if missing/invalid.
fn youtube_seek_seconds(point_stamp: Option<&str>, stream_start_time: Option<&str>) -> Option<f64> {
    let point_str = point_stamp?.trim();
    let stream_str = stream_start_time?.trim();
    if point_str.is_empty() || stream_str.is_empty() {
        return None;
    }
    let ensure_z = |s: &str| -> String {
        if s.ends_with('Z') || s.contains('+') {
            s.to_string()
        } else {
            format!("{}Z", s)
        }
    };
    let point_parsed = chrono::DateTime::parse_from_rfc3339(&ensure_z(point_str))
        .or_else(|_| chrono::DateTime::parse_from_rfc3339(point_str))
        .ok()?;
    let stream_parsed = chrono::DateTime::parse_from_rfc3339(&ensure_z(stream_str))
        .or_else(|_| chrono::DateTime::parse_from_rfc3339(stream_str))
        .ok()?;
    let diff = point_parsed.signed_duration_since(stream_parsed);
    let secs = diff.num_milliseconds() as f64 / 1000.0;
    web_sys::console::log_1(&format!("point_parsed: {:?}, stream_parsed: {:?}, diff: {:?}, secs: {:?}", point_parsed, stream_parsed, diff, secs).into());
    Some(secs.max(0.0))
}

/// Compute stones elapsed for a point using Bayesian filter for server time
#[cfg(target_arch = "wasm32")]
fn compute_stones_elapsed(
    start_stamp: Option<&str>,
    end_stamp: Option<&str>,
    filter: &Signal<BayesianOffsetFilter>,
) -> String {
    const BEAT_INTERVAL: f64 = 1.5;
    
    let start = if let Some(s) = start_stamp {
        // Parse ISO 8601 timestamp
        if let Ok(parsed) = chrono::DateTime::parse_from_rfc3339(s) {
            parsed.timestamp_millis() as f64 / 1000.0
        } else {
            return "0".to_string();
        }
    } else {
        return "0".to_string();
    };
    
    let end = if let Some(e) = end_stamp {
        // Parse ISO 8601 timestamp
        if let Ok(parsed) = chrono::DateTime::parse_from_rfc3339(e) {
            parsed.timestamp_millis() as f64 / 1000.0
        } else {
            // Ongoing point - use server time
            let client_time = js_sys::Date::now() / 1000.0;
            let offset = filter.read().get_mean();
            client_time + offset
        }
    } else {
        // Ongoing point - use server time
        let client_time = js_sys::Date::now() / 1000.0;
        let offset = filter.read().get_mean();
        client_time + offset
    };
    
    let start_count = (start / BEAT_INTERVAL).floor() as i64;
    let end_count = (end / BEAT_INTERVAL).floor() as i64;
    let elapsed = (end_count - start_count).max(0);
    elapsed.to_string()
}

/// Compute stones remaining from points list
#[cfg(target_arch = "wasm32")]
fn compute_stones_remaining(
    points: &[&crate::types::PointData],
    filter: &Signal<BayesianOffsetFilter>,
) -> String {
    if points.is_empty() {
        return "??".to_string();
    }
    
    // Find the last point
    let last_point = points[points.len() - 1];
    
    // If last point is ongoing (no end_stamp), compute from it
    let last_point_is_ongoing = last_point.end_stamp.is_none();
    if last_point_is_ongoing {
        if let Some(stones_at_start) = last_point.stones_at_start {
            if let Some(start_stamp) = &last_point.stamp {
                let elapsed_str = compute_stones_elapsed(Some(start_stamp), None, filter);
                if let Ok(elapsed) = elapsed_str.parse::<u32>() {
                    let remaining = stones_at_start.saturating_sub(elapsed);
                    return remaining.to_string();
                }
            }
        }
    }
    
    // Last point is completed, find the last completed point with stones_at_start
    for pt in points.iter().rev() {
        if pt.end_stamp.is_some() {
            if let Some(stones_at_start) = pt.stones_at_start {
                if let (Some(start_stamp), Some(end_stamp)) = (&pt.stamp, &pt.end_stamp) {
                    let elapsed_str = compute_stones_elapsed(Some(start_stamp), Some(end_stamp), filter);
                    if let Ok(elapsed) = elapsed_str.parse::<u32>() {
                        let remaining = stones_at_start.saturating_sub(elapsed);
                        return remaining.to_string();
                    }
                }
            }
        }
    }
    
    "??".to_string()
}

/// Parse team display name to check if it's a match reference (e.g., "MatchName::winner" or "MatchName winner")
fn parse_team_reference(display: &str) -> Option<(String, String)> {
    // Check for "::winner" or "::loser"
    if let Some(pos) = display.find("::") {
        let match_name = display[..pos].to_string();
        let suffix = display[pos..].to_string();
        if suffix == "::winner" || suffix == "::loser" {
            return Some((match_name, display.replace("::", " ")));
        }
    }
    // Check for " winner" or " loser" at the end
    if display.ends_with(" winner") || display.ends_with(" loser") {
        if let Some(pos) = display.rfind(' ') {
            let match_name = display[..pos].to_string();
            return Some((match_name, display.to_string()));
        }
    }
    None
}

#[component]
pub fn MatchPage(url: String) -> Element {
    let match_id = get_query_param("id");
    let match_name = get_query_param("name");
    match_page_inner(url, match_id, match_name)
}

#[component]
pub fn MatchPageById(url: String, match_id: String) -> Element {
    match_page_inner(url, Some(match_id), None)
}

fn match_page_inner(url: String, match_id: Option<String>, match_name: Option<String>) -> Element {
    let url_for_resource = url.clone();
    let id_for_resource = match_id.clone();
    let name_for_resource = match_name.clone();
    
    // Main match data
    let data = use_resource(move || {
        let u = url_for_resource.clone();
        let id = id_for_resource.clone();
        let name = name_for_resource.clone();
        async move {
            if id.is_some() || name.is_some() {
                api::match_detail(&u, id.as_deref(), name.as_deref())
                    .await
                    .map_err(|e| e.to_string())
            } else {
                Err("id or name query param required".to_string())
            }
        }
    });
    
    // Polling for live match state updates
    let poll_tick = use_signal(|| 0u32);
    let poll_started = use_signal(|| false);
    let url_for_poll = url.clone();
    let match_id_for_poll = match_id.clone();
    
    #[cfg(target_arch = "wasm32")]
    {
        let mut poll_tick = poll_tick;
        let mut poll_started = poll_started;
        use_effect(move || {
            if let Some(Ok(d)) = data.value().read().as_ref() {
                if d.match_data.status == "IN_PROGRESS" && !poll_started() {
                    let handle = Interval::new(1000, move || {
                        poll_tick.set(poll_tick() + 1);
                    });
                    poll_started.set(true);
                    std::mem::forget(handle);
                }
            }
        });
    }
    
    // Match state from polling
    let state_signal = use_signal(|| None as Option<Result<Value, String>>);
    use_effect(move || {
        let u = url_for_poll.clone();
        let id = match_id_for_poll.clone();
        let _tick = poll_tick();
        let mut state_signal = state_signal;
        if let Some(id) = id {
            if let Some(Ok(d)) = data.value().read().as_ref() {
                if d.match_data.status == "IN_PROGRESS" {
                    spawn(async move {
                        match api::match_state(&u, &id).await {
                            Ok(v) => state_signal.set(Some(Ok(v))),
                            Err(e) => state_signal.set(Some(Err(e))),
                        }
                    });
                }
            }
        }
    });
    
    // User info for permissions
    let user_info = use_resource(move || async move {
        api::me().await.ok()
    });
    
    
    // Bayesian filter for server time sync (for stones elapsed calculation)
    #[cfg(target_arch = "wasm32")]
    let time_filter = use_signal(|| BayesianOffsetFilter::default());
    
    #[cfg(target_arch = "wasm32")]
    {
        use_effect(move || {
            if let Some(Ok(d)) = data.value().read().as_ref() {
                if d.match_data.status == "IN_PROGRESS" && d.match_data.set_type.as_deref() == Some("STONES") {
                    let mut filter = time_filter;
                    spawn(async move {
                        loop {
                            let client_send = js_sys::Date::now() / 1000.0;
                            if let Ok(res) = api::server_time().await {
                                let client_receive = js_sys::Date::now() / 1000.0;
                                let rtt = client_receive - client_send;
                                let offset = res.server_time - client_receive + (rtt / 2.0);
                                filter.write().update(offset);
                            }
                            gloo_timers::future::TimeoutFuture::new(997).await;
                        }
                    });
                }
            }
        });
    }
    
    // Stones elapsed update interval (for ongoing points)
    #[cfg(target_arch = "wasm32")]
    let stones_update_tick = use_signal(|| 0u32);
    #[cfg(target_arch = "wasm32")]
    {
        let mut stones_update_tick = stones_update_tick;
        use_effect(move || {
            if let Some(Ok(d)) = data.value().read().as_ref() {
                if d.match_data.status == "IN_PROGRESS" && d.match_data.set_type.as_deref() == Some("STONES") {
                    let handle = Interval::new(100, move || {
                        stones_update_tick.set(stones_update_tick() + 1);
                    });
                    std::mem::forget(handle);
                }
            }
        });
    }
    
    let val = data.value();
    let base_url = api::base_url();
    let navigator = use_navigator();
    let mut selected_camera_idx = use_signal(|| 0usize);
    let mut camera_dropdown_open = use_signal(|| false);
    let mut selected_point_index = use_signal(|| 0usize);
    let mut point_timestamps_for_keys = use_signal(|| Vec::<PointTimestamp>::new());
    let mut n_cameras_for_keys = use_signal(|| 0usize);
    let mut n_points_for_keys = use_signal(|| 0usize);
    let mut playback_speed = use_signal(|| "1".to_string());
    // Throttle frame step to 5 fps when holding f/b (min 200ms between steps).
    let mut last_frame_step_time_ms = use_signal(|| 0.0f64);
    // When switching camera, seek to this time (secs) once the new video is ready.
    let mut pending_seek_time = use_signal(|| None::<f64>);
    // Fetched YouTube stream start times per camera index (when API does not provide them).
    let fetched_stream_starts = use_signal(|| Vec::<Option<String>>::new());
    // Match UUID we have already triggered stream-start fetches for (so we only query once per load).
    let stream_starts_fetched_for_match = use_signal(|| None::<String>);

    use_effect(move || {
        let _ = (val.read().as_ref(), selected_camera_idx());
        if let Some(Ok(d)) = val.read().as_ref() {
            let idx = selected_camera_idx().min(d.available_cameras.len().saturating_sub(1));
            if let Some(cam) = d.available_cameras.get(idx) {
                point_timestamps_for_keys.set(cam.point_timestamps.clone().unwrap_or_default());
            } else {
                point_timestamps_for_keys.set(Vec::new());
            }
            n_cameras_for_keys.set(d.available_cameras.len());
            n_points_for_keys.set(d.points.len());
        } else {
            point_timestamps_for_keys.set(Vec::new());
            n_cameras_for_keys.set(0);
            n_points_for_keys.set(0);
        }
    });

    // Fetch YouTube stream start for each camera that has a URL but no stream_start_time from API.
    // Only runs once when the match page loads (keyed by match uuid).
    #[cfg(target_arch = "wasm32")]
    {
        let val_fetch = val.clone();
        let mut fetched_stream_starts = fetched_stream_starts;
        let mut stream_starts_fetched_for_match = stream_starts_fetched_for_match;
        use_effect(move || {
            let match_uuid = val_fetch.read().as_ref()
                .and_then(|r| r.as_ref().ok())
                .map(|d| d.match_data.uuid.clone());
            let Some(match_uuid) = match_uuid else { return };
            if stream_starts_fetched_for_match().as_deref() == Some(match_uuid.as_str()) {
                return;
            }
            stream_starts_fetched_for_match.set(Some(match_uuid.clone()));
            let cameras = val_fetch.read().as_ref()
                .and_then(|r| r.as_ref().ok())
                .map(|d| d.available_cameras.clone());
            let Some(cameras) = cameras else { return };
            let n = cameras.len();
            if n == 0 {
                fetched_stream_starts.set(vec![]);
                return;
            }
            let mut current = vec![None::<String>; n];
            fetched_stream_starts.set(current.clone());
            for (idx, cam) in cameras.iter().enumerate() {
                let url = match &cam.url {
                    Some(u) if !u.trim().is_empty() => u.clone(),
                    _ => continue,
                };
                if cam.stream_start_time.is_some() {
                    continue;
                }
                if cam.camera_type == "recorded" {
                    continue;
                }
                let mut set_fetched = fetched_stream_starts;
                spawn(async move {
                    if let Ok(Some(iso)) = api::youtube_stream_start(&url).await {
                        let mut v = set_fetched();
                        if v.len() <= idx {
                            v.resize(idx + 1, None);
                        }
                        v[idx] = Some(iso);
                        set_fetched.set(v);
                    }
                });
            }
        });
    }

    // When switching camera with pending same-time seek, poll video until ready then seek.
    #[cfg(target_arch = "wasm32")]
    {
        let pending_seek_time_eff = pending_seek_time;
        use_effect(move || {
            let pending = pending_seek_time_eff();
            let _ = selected_camera_idx();
            if let Some(secs) = pending {
                let mut set_pending = pending_seek_time_eff;
                spawn(async move {
                    const HAVE_CURRENT_DATA: u16 = 2;
                    for _ in 0..100 {
                        gloo_timers::future::TimeoutFuture::new(100).await;
                        if let Some(doc) = web_sys::window().and_then(|w| w.document()) {
                            if let Some(el) = doc.get_element_by_id("local-video-player") {
                                if let Ok(media) = el.dyn_into::<web_sys::HtmlMediaElement>() {
                                    if media.ready_state() >= HAVE_CURRENT_DATA {
                                        media.set_current_time(secs);
                                        set_pending.set(None);
                                        break;
                                    }
                                }
                            }
                        }
                    }
                });
            }
        });
    }

    // Initialize YouTube iframe player when selected camera is YouTube and has a URL.
    #[cfg(target_arch = "wasm32")]
    {
        let val_yt = val.clone();
        use_effect(move || {
            let _ = selected_camera_idx();
            let binding = val_yt.read();
            let camera_url: Option<String> = binding
                .as_ref()
                .and_then(|r| r.as_ref().ok())
                .and_then(|d| {
                    let idx = selected_camera_idx().min(d.available_cameras.len().saturating_sub(1));
                    let cam = d.available_cameras.get(idx)?;
                    if cam.camera_type != "recorded" {
                        cam.url.clone()
                    } else {
                        None
                    }
                });
            if let Some(url) = camera_url {
                let url_escaped = url.replace('\\', "\\\\").replace('\'', "\\'").replace('\n', " ");
                let script = format!(
                    r#"
(function() {{
  var url = '{}';
  function extractVideoId(u) {{
    if (!u) return null;
    var m = u.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/|youtube\.com\/v\/)([^&\n?#]+)/) || u.match(/^([a-zA-Z0-9_-]{{11}})$/);
    return m ? m[1] : null;
  }}
  var videoId = extractVideoId(url);
  if (!videoId) {{ console.warn('Arctos: no YouTube video ID in', url); return; }}
  function createNew() {{
    var el = document.getElementById('youtube-player');
    if (!el) return;
    if (window.__arctosYtPlayer) {{
      try {{ window.__arctosYtPlayer.loadVideoById(videoId); return; }} catch (e) {{ window.__arctosYtPlayer = null; }}
    }}
    window.__arctosYtPlayer = new YT.Player('youtube-player', {{
      videoId: videoId,
      host: 'https://www.youtube-nocookie.com',
      playerVars: {{ autoplay: 1, controls: 1, rel: 0, modestbranding: 1, enablejsapi: 1, origin: window.location.origin, iv_load_policy: 1, playsinline: 1 }},
      events: {{ onReady: function() {{}}, onError: function(e) {{ console.error('YouTube player error', e.data); }} }}
    }});
  }}
  window.onYouTubeIframeAPIReady = function() {{ createNew(); }};
  if (window.YT && window.YT.Player) createNew();
}})();
"#,
                    url_escaped
                );
                spawn(async move {
                    let _ = dioxus::prelude::document::eval(&script).await;
                });
            }
        });
    }

    // When match is not completed and we have a YouTube stream start, seek to live (end of stream) after player loads.
    #[cfg(target_arch = "wasm32")]
    {
        let val_live = val.clone();
        use_effect(move || {
            let _ = selected_camera_idx();
            let _ = fetched_stream_starts();
            if let Some(Ok(d)) = val_live.read().as_ref() {
                if d.match_data.status == "COMPLETED" {
                    return;
                }
                let idx = selected_camera_idx().min(d.available_cameras.len().saturating_sub(1));
                let cam = match d.available_cameras.get(idx) {
                    Some(c) if c.camera_type != "recorded" => c,
                    _ => return,
                };
                let stream_start = cam
                    .stream_start_time
                    .clone()
                    .or_else(|| fetched_stream_starts().get(idx).cloned().flatten());
                let Some(stream_start) = stream_start else { return };
                spawn(async move {
                    gloo_timers::future::TimeoutFuture::new(3000).await;
                    let now_iso = chrono::Utc::now().to_rfc3339();
                    if let Some(secs) = youtube_seek_seconds(Some(&now_iso), Some(&stream_start)) {
                        seek_youtube_to(secs);
                    }
                });
            }
        });
    }

    // Initialize video player JavaScript when cameras are available
    #[cfg(target_arch = "wasm32")]
    {
        let val_for_effect = val.clone();
        let match_id_for_effect = match_id.clone();
        let url_for_effect = url.clone();
        use_effect(move || {
            if let Some(Ok(d)) = val_for_effect.read().as_ref() {
                if !d.available_cameras.is_empty() {
                    let cameras = d.available_cameras.clone();
                    let points = d.points.clone();
                    let match_id_str = match_id_for_effect.clone();
                    let url_str = url_for_effect.clone();
                    spawn(async move {

                        // Initialize video player (placeholder - full implementation requires YouTube IFrame API)
                        let cameras_json = serde_json::to_string(&cameras).unwrap_or_else(|_| "[]".to_string());
                        let points_json = serde_json::to_string(&points.iter().map(|p| serde_json::json!({
                            "uuid": p.uuid,
                            "stamp": p.stamp,
                            "end_stamp": p.end_stamp,
                            "stones_at_start": p.stones_at_start,
                        })).collect::<Vec<_>>()).unwrap_or_else(|_| "[]".to_string());
                        let match_id_val = match_id_str.as_ref().map(|s| s.as_str()).unwrap_or("");
                        let url_val = url_str.as_str();
                        
                        let js_init = format!(
                            r#"
                            console.log('Match page video player initialized ' + JSON.stringify({{ matchId: '{}', tournamentUrl: '{}', availableCameras: {}, pointsData: {} }}));
                            "#,
                            match_id_val.replace('\'', "\\'"),
                            url_val.replace('\'', "\\'"),
                            cameras_json,
                            points_json
                        );
                        let _ = dioxus::prelude::document::eval(&js_init).await;
                    });
                }
            }
        });
    }

    let keydown_handler = move |ev: Event<KeyboardData>| {
        #[cfg(target_arch = "wasm32")]
        {
            if let Some(doc) = web_sys::window().and_then(|w| w.document()) {
                if let Some(active) = doc.active_element() {
                    if let Ok(html_el) = active.dyn_into::<web_sys::HtmlElement>() {
                        let tag = html_el.tag_name().to_uppercase();
                        if tag == "INPUT" || tag == "TEXTAREA" || tag == "SELECT" {
                            return;
                        }
                    }
                }
            }
        }
        let key = ev.key().to_string();
        let shift = ev.modifiers().contains(Modifiers::SHIFT);
        match key.as_str() {
            "g" | "G" => {
                ev.prevent_default();
                if let Some(Ok(d)) = val.read().as_ref() {
                    let pi = selected_point_index().min(d.points.len().saturating_sub(1));
                    let idx = selected_camera_idx().min(d.available_cameras.len().saturating_sub(1));
                    let cam = d.available_cameras.get(idx);
                    if cam.map(|c| c.camera_type == "recorded").unwrap_or(false) {
                        let ts = point_timestamps_for_keys();
                        if let Some(t) = in_video_start_for_point(&ts, &d.points, pi) {
                            seek_video_to(t);
                        }
                    } else if let Some(cam) = cam {
                        let stamp = d.points.get(pi).and_then(|p| p.stamp.as_deref());
                        if let Some(secs) = youtube_seek_seconds(stamp, cam.stream_start_time.as_deref()) {
                            seek_youtube_to(secs);
                        }
                    }
                }
            }
            "p" | "P" => {
                ev.prevent_default();
                let new_idx = selected_point_index().saturating_sub(1);
                selected_point_index.set(new_idx);
                if let Some(Ok(d)) = val.read().as_ref() {
                    let idx = selected_camera_idx().min(d.available_cameras.len().saturating_sub(1));
                    let cam = d.available_cameras.get(idx);
                    if cam.map(|c| c.camera_type == "recorded").unwrap_or(false) {
                        let ts = point_timestamps_for_keys();
                        if let Some(t) = in_video_start_for_point(&ts, &d.points, new_idx) {
                            seek_video_to(t);
                        }
                    } else if let Some(cam) = cam {
                        let stamp = d.points.get(new_idx).and_then(|p| p.stamp.as_deref());
                        if let Some(secs) = youtube_seek_seconds(stamp, cam.stream_start_time.as_deref()) {
                            seek_youtube_to(secs);
                        }
                    }
                }
            }
            "n" | "N" => {
                ev.prevent_default();
                let n = n_points_for_keys();
                let new_idx = (selected_point_index() + 1).min(n.saturating_sub(1));
                selected_point_index.set(new_idx);
                if let Some(Ok(d)) = val.read().as_ref() {
                    let idx = selected_camera_idx().min(d.available_cameras.len().saturating_sub(1));
                    let cam = d.available_cameras.get(idx);
                    if cam.map(|c| c.camera_type == "recorded").unwrap_or(false) {
                        let ts = point_timestamps_for_keys();
                        if let Some(t) = in_video_start_for_point(&ts, &d.points, new_idx) {
                            seek_video_to(t);
                        }
                    } else if let Some(cam) = cam {
                        let stamp = d.points.get(new_idx).and_then(|p| p.stamp.as_deref());
                        if let Some(secs) = youtube_seek_seconds(stamp, cam.stream_start_time.as_deref()) {
                            seek_youtube_to(secs);
                        }
                    }
                }
            }
            " " => {
                ev.prevent_default();
                toggle_video_play_pause();
            }
            "f" | "F" => {
                ev.prevent_default();
                #[cfg(target_arch = "wasm32")]
                {
                    let now = js_sys::Date::now();
                    if now - last_frame_step_time_ms() >= 100.0 {
                        last_frame_step_time_ms.set(now);
                        step_video_frame(true);
                    }
                }
                #[cfg(not(target_arch = "wasm32"))]
                step_video_frame(true);
            }
            "b" | "B" => {
                ev.prevent_default();
                #[cfg(target_arch = "wasm32")]
                {
                    let now = js_sys::Date::now();
                    if now - last_frame_step_time_ms() >= 100.0 {
                        last_frame_step_time_ms.set(now);
                        step_video_frame(false);
                    }
                }
                #[cfg(not(target_arch = "wasm32"))]
                step_video_frame(false);
            }
            "c" | "C" => {
                ev.prevent_default();
                let n = n_cameras_for_keys();
                if n > 1 {
                    let current_idx = selected_camera_idx();
                    let new_idx = if shift {
                        (current_idx + n - 1) % n
                    } else {
                        (current_idx + 1) % n
                    };
                    if new_idx != current_idx {
                        #[cfg(target_arch = "wasm32")]
                        if let Some(Ok(d)) = val.read().as_ref() {
                            let current_ts = point_timestamps_for_keys();
                            let new_cam = d.available_cameras.get(new_idx);
                            let new_ts = new_cam.and_then(|c| c.point_timestamps.as_deref());
                            if let Some(t) = get_video_current_time()
                                .and_then(|now| same_time_seek_target(&current_ts, new_ts, now))
                            {
                                pending_seek_time.set(Some(t));
                            }
                        }
                        selected_camera_idx.set(new_idx);
                    }
                }
            }
            _ => {}
        }
    };

    rsx! {
        style { "#match-page-keyboard:focus {{ outline: none; }}" }
        div {
            id: "match-page-keyboard",
            tabindex: "-1",
            onkeydown: keydown_handler,
            onmounted: move |ev: Event<MountedData>| {
                spawn(async move {
                    let _ = ev.data().set_focus(true).await;
                });
            },
        if let Some(Ok(d)) = val.read().as_ref() {
            {
                let has_cameras = d.available_cameras.len() > 0 || d.camera_url.is_some();
                let cameras = d.available_cameras.clone();
                let points_for_footage = d.points.clone();
                let base_url_footage = base_url.clone();
                let footage_section = has_cameras.then(move || {
                    let points = points_for_footage.clone();
                    let points_go = points.clone();
                    let points_prev = points.clone();
                    let points_next = points.clone();
                    let idx = selected_camera_idx().min(cameras.len().saturating_sub(1));
                    let current = cameras.get(idx);
                    let is_recorded = current.map(|c| c.camera_type == "recorded").unwrap_or(false);
                    let stream_start_time = current
                        .and_then(|c| c.stream_start_time.clone())
                        .or_else(|| fetched_stream_starts().get(idx).cloned().flatten());
                    let stream_start_go = stream_start_time.clone();
                    let stream_start_prev = stream_start_time.clone();
                    let stream_start_next = stream_start_time.clone();
                    let video_src = current.and_then(|c| c.video_path.as_ref()).map(|p| {
                        let base = base_url_footage.trim_end_matches('/');
                        let path = p.trim_start_matches('/');
                        format!("{}/{}", base, path)
                    });
                    rsx! {
                        div { class: "card mt-3",
                        div { class: "card-header d-flex justify-content-between align-items-center",
                            h5 { class: "mb-0", "Match Footage" }
                            if cameras.len() > 1 {
                                div { class: "dropdown",
                                    button {
                                        class: "btn btn-sm btn-outline-secondary dropdown-toggle",
                                        "type": "button",
                                        id: "camera-selector-dropdown",
                                        "aria-expanded": "{camera_dropdown_open()}",
                                        onclick: move |_| camera_dropdown_open.toggle(),
                                        {
                                            if let Some(cam) = current {
                                                if cam.camera_type == "recorded" {
                                                    { format!("📹 Camera: {}", cam.camera_id.as_deref().unwrap_or("unknown")) }
                                                } else {
                                                    { format!("📹 Camera: {}", cam.index + 1) }
                                                }
                                            } else {
                                                "📹 Camera".to_string()
                                            }
                                        }
                                    }
                                    if camera_dropdown_open() {
                                        ul {
                                            class: "dropdown-menu dropdown-menu-end show",
                                            style: "z-index: 9999;",
                                            "aria-labelledby": "camera-selector-dropdown",
                                            {
                                                cameras
                                                    .iter()
                                                    .enumerate()
                                                    .map(|(idx, cam)| {
                                                        let idx = idx;
                                                        let new_ts = cam.point_timestamps.clone();
                                                        rsx! {
                                                            li { key: "{cam.index}",
                                                                a {
                                                                    class: "dropdown-item",
                                                                    href: "#",
                                                                    onclick: move |ev| {
                                                                        ev.prevent_default();
                                                                        let current_idx = selected_camera_idx();
                                                                        if idx != current_idx {
                                                                            #[cfg(target_arch = "wasm32")]
                                                                            {
                                                                                let current_ts = point_timestamps_for_keys();
                                                                                let new_ts_ref = new_ts.as_deref();
                                                                                if let Some(t) = get_video_current_time()
                                                                                    .and_then(|now| same_time_seek_target(&current_ts, new_ts_ref, now))
                                                                                {
                                                                                    pending_seek_time.set(Some(t));
                                                                                }
                                                                            }
                                                                            selected_camera_idx.set(idx);
                                                                        }
                                                                        camera_dropdown_open.set(false);
                                                                    },
                                                                    {
                                                                        if cam.camera_type == "recorded" {
                                                                            format!(
                                                                                "Camera: {}",
                                                                                cam.camera_id.as_deref().unwrap_or("unknown"),
                                                                            )
                                                                        } else {
                                                                            format!("Camera {}", cam.index + 1)
                                                                        }
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    })
                                            }
                                        }
                                    }
                                }
                            } else if let Some(cam) = current {
                                span { class: "text-muted small",
                                    if cam.camera_type == "recorded" {
                                        { format!("📹 Camera: {}", cam.camera_id.as_deref().unwrap_or("unknown")) }
                                    } else {
                                        { format!("📹 Camera {}", cam.index + 1) }
                                    }
                                }
                            }
                        }
                        div { class: "card-body",
                            div { id: "video-stream-container",
                                if is_recorded {
                                    if let Some(ref src) = video_src {
                                        div {
                                            id: "local-video-container",
                                            video {
                                                id: "local-video-player",
                                                src: "{src}",
                                                controls: true,
                                                style: "width: 100%; max-width: 100%; aspect-ratio: 16/9;",
                                                "Your browser does not support the video tag."
                                            }
                                        }
                                    } else {
                                        p { class: "text-muted", "No video path" }
                                    }
                                } else {
                                    div {
                                        id: "youtube-player-container",
                                        style: "width: 100%; max-width: 100%; aspect-ratio: 16/9;",
                                        div {
                                            id: "youtube-player",
                                            style: "width: 100%; height: 100%;",
                                            "Loading YouTube player…"
                                        }
                                    }
                                }
                                div { class: "mt-3 d-flex align-items-center flex-wrap gap-2",
                                    span { "Seek to point:" }
                                    select {
                                        id: "points-dropdown",
                                        class: "form-select form-select-sm",
                                        style: "width: auto;",
                                        value: "{selected_point_index().min(points.len().saturating_sub(1))}",
                                        onchange: move |ev| {
                                            if let Ok(i) = ev.value().parse::<usize>() {
                                                selected_point_index.set(i);
                                            }
                                        },
                                        option { value: "", "Select point..." }
                                        {
                                            points
                                                .iter()
                                                .enumerate()
                                                .map(|(idx, pt)| {
                                                    rsx! {
                                                        option { key: "{pt.uuid}", value: "{idx}", "Point {idx + 1}" }
                                                    }
                                                })
                                        }
                                    }
                                    button {
                                        id: "seek-go-btn",
                                        class: "btn btn-sm btn-primary",
                                        onclick: move |_| {
                                            let pi = selected_point_index().min(points_go.len().saturating_sub(1));
                                            if is_recorded {
                                                let ts = point_timestamps_for_keys();
                                                if let Some(t) = in_video_start_for_point(&ts, &points_go, pi) {
                                                    seek_video_to(t);
                                                }
                                            } else {
                                                let stamp = points_go.get(pi).and_then(|p| p.stamp.as_deref());
                                                if let Some(secs) = youtube_seek_seconds(stamp, stream_start_go.as_deref()) {
                                                    seek_youtube_to(secs);
                                                }
                                            }
                                        },
                                        "Go (g)"
                                    }
                                    button {
                                        id: "seek-prev-btn",
                                        class: "btn btn-sm btn-secondary",
                                        onclick: move |_| {
                                            let new_idx = selected_point_index().saturating_sub(1);
                                            selected_point_index.set(new_idx);
                                            if is_recorded {
                                                let ts = point_timestamps_for_keys();
                                                if let Some(t) = in_video_start_for_point(&ts, &points_prev, new_idx) {
                                                    seek_video_to(t);
                                                }
                                            } else {
                                                let stamp = points_prev.get(new_idx).and_then(|p| p.stamp.as_deref());
                                                if let Some(secs) = youtube_seek_seconds(stamp, stream_start_prev.as_deref()) {
                                                    seek_youtube_to(secs);
                                                }
                                            }
                                        },
                                        "Previous Point (p)"
                                    }
                                    button {
                                        id: "seek-next-btn",
                                        class: "btn btn-sm btn-secondary",
                                        onclick: move |_| {
                                            let n = n_points_for_keys();
                                            let new_idx = (selected_point_index() + 1).min(n.saturating_sub(1));
                                            selected_point_index.set(new_idx);
                                            if is_recorded {
                                                let ts = point_timestamps_for_keys();
                                                if let Some(t) = in_video_start_for_point(&ts, &points_next, new_idx) {
                                                    seek_video_to(t);
                                                }
                                            } else {
                                                let stamp = points_next.get(new_idx).and_then(|p| p.stamp.as_deref());
                                                if let Some(secs) = youtube_seek_seconds(stamp, stream_start_next.as_deref()) {
                                                    seek_youtube_to(secs);
                                                }
                                            }
                                        },
                                        "Next Point (n)"
                                    }
                                    span { class: "ms-2", "Speed:" }
                                    select {
                                        id: "playback-speed",
                                        class: "form-select form-select-sm",
                                        style: "width: auto;",
                                        value: "{playback_speed()}",
                                        onchange: move |ev| {
                                            let v = ev.value();
                                            playback_speed.set(v.clone());
                                            if let Ok(rate) = v.parse::<f64>() {
                                                set_video_playback_speed(rate);
                                            }
                                        },
                                        option { value: "0.25", "0.25x" }
                                        option { value: "0.5", "0.5x" }
                                        option { value: "0.75", "0.75x" }
                                        option { value: "1", "1x" }
                                        option { value: "1.25", "1.25x" }
                                        option { value: "1.5", "1.5x" }
                                        option { value: "1.75", "1.75x" }
                                        option { value: "2", "2x" }
                                    }
                                }
                            }
                        }
                    }
                }
            });
                rsx! {
            div { class: "row",
                div { class: "col-12",
                    h1 { "{d.match_data.name}" }
                    nav { "aria-label": "breadcrumb",
                        ol { class: "breadcrumb",
                            li { class: "breadcrumb-item",
                                Link {
                                    to: Route::TournamentHome {
                                        url: url.clone(),
                                    },
                                    "{url}"
                                }
                            }
                            li { class: "breadcrumb-item",
                                Link {
                                    to: Route::Schedule {
                                        url: url.clone(),
                                    },
                                    "Schedule"
                                }
                            }
                            li { class: "breadcrumb-item active", "{d.match_data.name}" }
                        }
                    }
                }
            }

            div { class: "row",
                div { class: "col-md-8",
                    // Match Information Card
                    div { class: "card",
                        div { class: "card-header",
                            h5 { class: "mb-0", "Match Information" }
                        }
                        div { class: "card-body",
                            div { class: "row",
                                div { class: "col-md-4",
                                    div { class: "d-flex align-items-center mb-2",
                                        strong { class: "me-2", "Teams:" }
                                        div {
                                            // Team 1
                                            if let Some((match_name, display_text)) = parse_team_reference(
                                                &d.match_data.team1_name,
                                            )
                                            {
                                                Link {
                                                    to: Route::MatchPage {
                                                        url: url.clone(),
                                                    },
                                                    class: "text-decoration-none",
                                                    "{display_text}"
                                                }
                                            } else if let Some(team1_id) = &d.match_data.team1 {
                                                Link {
                                                    to: Route::TeamProfile {
                                                        id: team1_id.clone(),
                                                    },
                                                    class: "text-decoration-none",
                                                    "{d.match_data.team1_name}"
                                                }
                                            } else {
                                                span { "{d.match_data.team1_name}" }
                                            }
                                            if d.match_data.status == "COMPLETED"
                                                && d.match_data.match_winner.as_deref() == Some("TEAM1")
                                            {
                                                span { class: "badge bg-success ms-2",
                                                    "Winner"
                                                }
                                            }
                                            span { class: "mx-2", "vs" }
                                            // Team 2
                                            if let Some((match_name, display_text)) = parse_team_reference(
                                                &d.match_data.team2_name,
                                            )
                                            {
                                                Link {
                                                    to: Route::MatchPage {
                                                        url: url.clone(),
                                                    },
                                                    class: "text-decoration-none",
                                                    "{display_text}"
                                                }
                                            } else if let Some(team2_id) = &d.match_data.team2 {
                                                Link {
                                                    to: Route::TeamProfile {
                                                        id: team2_id.clone(),
                                                    },
                                                    class: "text-decoration-none",
                                                    "{d.match_data.team2_name}"
                                                }
                                            } else {
                                                span { "{d.match_data.team2_name}" }
                                            }
                                            if d.match_data.status == "COMPLETED"
                                                && d.match_data.match_winner.as_deref() == Some("TEAM2")
                                            {
                                                span { class: "badge bg-success ms-2",
                                                    "Winner"
                                                }
                                            }
                                        }
                                    }
                                    // Refs display
                                    if let Some(refs) = &d.match_data.refs_initial {
                                        if !refs.is_empty() {
                                            div { class: "d-flex align-items-center mb-2",
                                                strong { class: "me-2", "Refs:" }
                                                span {
                                                    {
                                                        refs.split(',')
                                                            .filter_map(|ref_trimmed| {
                                                                let ref_trimmed = ref_trimmed.trim();
                                                                if ref_trimmed.is_empty() {
                                                                    return None;
                                                                }
                                                                Some(ref_trimmed)
                                                            })
                                                            .enumerate()
                                                            .map(|(idx, ref_trimmed)| {
                                                                let refs_vec: Vec<&str> = refs
                                                                    .split(',')
                                                                    .filter(|s| !s.trim().is_empty())
                                                                    .collect();
                                                                let is_last = idx == refs_vec.len() - 1;
                                                                rsx! {
                                                                    if let Some((match_name, display_text)) = parse_team_reference(ref_trimmed) {
                                                                        Link {
                                                                            to: Route::MatchPage {
                                                                                url: url.clone(),
                                                                            },
                                                                            class: "text-decoration-none",
                                                                            "{display_text}"
                                                                        }
                                                                        if !is_last {
                                                                            ", "
                                                                        }
                                                                    } else {
                                                                        span { "{ref_trimmed}" }
                                                                        if !is_last {
                                                                            ", "
                                                                        }
                                                                    }
                                                                }
                                                            })
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                                div { class: "col-md-4",
                                    div { class: "d-flex align-items-center mb-2",
                                        strong { class: "me-2", "Status:" }
                                        span {
                                            id: "match-status",
                                            class: format!(
                                                "badge {}",
                                                match d.match_data.status.as_str() {
                                                    "COMPLETED" => "bg-success",
                                                    "IN_PROGRESS" => "bg-warning",
                                                    _ => "bg-secondary",
                                                },
                                            ),
                                            {
                                                match d.match_data.status.as_str() {
                                                    "COMPLETED" => "Completed",
                                                    "IN_PROGRESS" => "In Progress",
                                                    _ => "Scheduled",
                                                }
                                            }
                                        }
                                    }
                                    if let Some(field) = &d.match_data.field {
                                        div { class: "d-flex align-items-center mb-2",
                                            strong { class: "me-2", "Field:" }
                                            span { "{field}" }
                                        }
                                    }
                                    div { class: "d-flex align-items-center mb-2",
                                        strong { class: "me-2", "Start:" }
                                        span {
                                            {
                                                d.match_data
                                                    .confirmed_start_time
                                                    .as_deref()
                                                    .or(d.match_data.nominal_start_time.as_deref())
                                                    .unwrap_or("TBA")
                                            }
                                        }
                                    }
                                    div { class: "d-flex align-items-center mb-2",
                                        strong { class: "me-2", "End:" }
                                        span { {d.match_data.completed_time.as_deref().unwrap_or("TBA")} }
                                    }
                                }
                                div { class: "col-md-4" }
                            }

                            if let Some(set_type) = &d.match_data.set_type {
                                div { class: "row mt-3",
                                    div { class: "col-md-6",
                                        h6 { "Type" }
                                        p { "{set_type}" }
                                    }
                                    if let Some(length) = d.match_data.nominal_length {
                                        div { class: "col-md-6",
                                            h6 { "Length" }
                                            p { "{length} minutes" }
                                        }
                                    }
                                }
                            }

                            // Action buttons
                            if let Some(Some(user)) = user_info.value().read().as_ref() {
                                if user.user_type == "player" {
                                    // Head ref actions
                                    if d.match_data.status == "READY_TO_START" {
                                        div { class: "row mt-3",
                                            div { class: "col-12",
                                                div { class: "d-flex gap-2",
                                                    Link {
                                                        to: Route::StartMatch {
                                                            url: url.clone(),
                                                            match_id: d.match_data.uuid.clone(),
                                                        },
                                                        class: "btn btn-success",
                                                        "Start Match"
                                                    }
                                                }
                                            }
                                        }
                                    } else if d.match_data.status == "IN_PROGRESS" {
                                        div { class: "row mt-3",
                                            div { class: "col-12",
                                                div { class: "d-flex gap-2",
                                                    Link {
                                                        to: Route::RunMatch {
                                                            url: url.clone(),
                                                            match_id: d.match_data.uuid.clone(),
                                                        },
                                                        class: "btn btn-warning",
                                                        "Run Match"
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // Live Match Status Card
                    div { class: "card mt-3",
                        div { class: "card-header",
                            h5 { class: "mb-0",
                                "Match Status: "
                                span {
                                    id: "live-status-message",
                                    class: match d.match_data.status.as_str() {
                                        "COMPLETED" => "text-success",
                                        "IN_PROGRESS" => "text-success",
                                        _ => "text-muted",
                                    },
                                    {
                                        match d.match_data.status.as_str() {
                                            "COMPLETED" => "✓ completed",
                                            "IN_PROGRESS" => "● live",
                                            _ => "○ not started",
                                        }
                                    }
                                }
                            }
                        }
                        div { class: "card-body",
                            // Stones remaining (for STONES matches) - compute from points
                            if d.match_data.set_type.as_deref() == Some("STONES") {
                                div { class: "row mb-3",
                                    div { class: "col-md-6",
                                        p {
                                            strong { "Stones Remaining: " }
                                            span { id: "live-stones-remaining",
                                                {
                                                    {
                                                        #[cfg(target_arch = "wasm32")]
                                                        {
                                                            let _update_tick = stones_update_tick();
                                                            let points_to_use = if let Some(Ok(_state)) = state_signal
                                                                .read()
                                                                .as_ref()
                                                            {
                                                                d.points.iter().collect::<Vec<_>>()
                                                            } else {
                                                                d.points.iter().collect::<Vec<_>>()
                                                            };
                                                            compute_stones_remaining(&points_to_use, &time_filter)
                                                        }
                                                        #[cfg(not(target_arch = "wasm32"))]
                                                        {
                                                            d.match_data
                                                                .stones_remaining
                                                                .map(|s| s.to_string())
                                                                .unwrap_or_else(|| "??".to_string())
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            // Score by Set - update from state
                            div { class: "mb-3",
                                h6 { "Score by Set" }
                                div { id: "score-by-set",
                                    {
                                        // Get scores from state if available, otherwise from match data
                                        {
                                            let scores_by_set: std::collections::BTreeMap<u32, (u32, u32)> = if let Some(
                                                Ok(state),
                                            ) = state_signal.read().as_ref()
                                            {
                                                if let Some(scores) = state
                                                    .get("scores_by_set")
                                                    .and_then(|v| v.as_object()) // Fallback: compute from points
                                                {
                                                    let mut map = std::collections::BTreeMap::new();
                                                    for (set_str, scores_obj) in scores {
                                                        if let (Ok(set_num), Some(team1), Some(team2)) = (
                                                            set_str.parse::<u32>(),
                                                            scores_obj.get("team1_score").and_then(|v| v.as_u64()),
                                                            scores_obj.get("team2_score").and_then(|v| v.as_u64()),
                                                        ) { // Compute from match data points
                                                            map.insert(set_num, (team1 as u32, team2 as u32));
                                                        }
                                                    }
                                                    map
                                                } else {
                                                    let mut sets: std::collections::BTreeMap<u32, (u32, u32)> = std::collections::BTreeMap::new();
                                                    for pt in &d.points {
                                                        if !pt.rerolled {
                                                            let set_num = pt.set_number.unwrap_or(1);
                                                            let entry = sets.entry(set_num).or_insert((0, 0));
                                                            match pt.winner.as_deref() {
                                                                Some("TEAM1") => entry.0 += 1,
                                                                Some("TEAM2") => entry.1 += 1,
                                                                _ => {}
                                                            }
                                                        }
                                                    }
                                                    sets
                                                }
                                            } else {
                                                let mut sets: std::collections::BTreeMap<u32, (u32, u32)> = std::collections::BTreeMap::new();
                                                for pt in &d.points {
                                                    if !pt.rerolled {
                                                        let set_num = pt.set_number.unwrap_or(1);
                                                        let entry = sets.entry(set_num).or_insert((0, 0));
                                                        match pt.winner.as_deref() {
                                                            Some("TEAM1") => entry.0 += 1,
                                                            Some("TEAM2") => entry.1 += 1,
                                                            _ => {}
                                                        }
                                                    }
                                                }
                                                sets
                                            };
                                            if !scores_by_set.is_empty() {
                                                rsx! {
                                                    // Team names header
                                                    div { class: "row mb-2",
                                                        div { class: "col-5 text-center",
                                                            small { class: "text-muted", "{d.match_data.team1_name}" }
                                                        }
                                                        div { class: "col-2" }
                                                        div { class: "col-5 text-center",
                                                            small { class: "text-muted", "{d.match_data.team2_name}" }
                                                        }
                                                    }
                                                    // Scores for each set
                                                    {
                                                        scores_by_set
                                                            .iter()
                                                            .map(|(set_num, (team1_score, team2_score))| {
                                                                rsx! {
                                                                    div { class: "row mb-1", key: "{set_num}",
                                                                        div { class: "col-5 text-center",
                                                                            strong { id: "live-team1-set-{set_num}-score", "{team1_score}" }
                                                                        }
                                                                        div { class: "col-2 text-center",
                                                                            small { class: "text-muted", "Set {set_num}" }
                                                                        }
                                                                        div { class: "col-5 text-center",
                                                                            strong { id: "live-team2-set-{set_num}-score", "{team2_score}" }
                                                                        }
                                                                    }
                                                                }
                                                            })
                                                    }
                                                }
                                            } else {
                                                rsx! {
                                                    div { class: "text-muted text-center", "No points yet" }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // Points Table - update from state
                    div { class: "card mt-3",
                        div { class: "card-header",
                            h5 { class: "mb-0", "Points" }
                        }
                        div { class: "card-body",
                            {
                                let points_to_display: Vec<&crate::types::PointData> = d
                                    .points
                                    .iter()
                                    .collect();
                                if points_to_display.is_empty() {
                                    rsx! {
                                        p { class: "text-muted", "No points recorded yet." }
                                    }
                                } else {
                                    rsx! {
                                        div { class: "table-responsive",
                                            table { class: "table table-sm",
                                                thead {
                                                    tr {
                                                        th { "#" }
                                                        th { "Set" }
                                                        th { "Stones Elapsed" }
                                                        th { "Winner" }
                                                        th { "Rerun" }
                                                    }
                                                }
                                                tbody { id: "live-points-table",
                                                    for (idx, pt) in points_to_display.iter().enumerate() {
                                                        tr { key: "{pt.uuid}", id: "live-point-row-{pt.uuid}",
                                                            td { "{idx + 1}" }
                                                            td { "{pt.set_number.unwrap_or(1)}" }
                                                            td {
                                                                id: "live-stones-{pt.uuid}",
                                                                "data-stamp": pt.stamp.as_deref().unwrap_or(""),
                                                                "data-end": pt.end_stamp.as_deref().unwrap_or(""),
                                                                "data-stones-at-start": pt.stones_at_start.map(|s: u32| s.to_string()).unwrap_or_default(),
                                                                        {
                                                                            {
                                                                                #[cfg(target_arch = "wasm32")]
                                                                                {
                                                                                    let _update_tick = stones_update_tick();
                                                                                    compute_stones_elapsed(
                                                                                        pt.stamp.as_deref(),
                                                                                        pt.end_stamp.as_deref(),
                                                                                        &time_filter,
                                                                                    )
                                                                                }
                                                                                #[cfg(not(target_arch = "wasm32"))] { "0" }
                                                                            }
                                                                        }
                                                                    }
                                                                    td {
                                                                        {
                                                                            match pt.winner.as_deref() {
                                                                                Some("TEAM1") => d.match_data.team1_name.clone(),
                                                                                Some("TEAM2") => d.match_data.team2_name.clone(),
                                                                                _ => "-".to_string(),
                                                                            }
                                                                        }
                                                                    }
                                                                    td {
                                                                        if pt.rerolled {
                                                                            span { class: "badge bg-warning", "Rerun" }
                                                                        } else {
                                                                            span { class: "badge bg-success", "Normal" }
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
                        }
                    }

                    // Match Footage Section (rendered via footage_section above)
                    { footage_section }

                    // YouTube IFrame API (script from youtube.com; use host: youtube-nocookie.com when creating player)
                        script { src: "https://www.youtube.com/iframe_api" }
                        script { src: "https://polyfill.io/v3/polyfill.min.js?features=es6" }

                        {
                            {
                                let cameras = d.available_cameras.clone();
                                let points = d.points.clone();
                                let match_id_str = match_id.as_ref().map(|s| s.as_str()).unwrap_or("");
                                let url_str = url.as_str();
                                if !cameras.is_empty() {
                                    let cameras_json = serde_json::to_string(&cameras)
                                        .unwrap_or_else(|_| "[]".to_string());
                                    let points_json = serde_json::to_string(
                                            &points
                                                .iter()
                                                .map(|p| {
                                                    serde_json::json!(
                                                        { "uuid" : p.uuid, "stamp" : p.stamp, "end_stamp" : p
                                                        .end_stamp, "stones_at_start" : p.stones_at_start, }
                                                    )
                                                })
                                                .collect::<Vec<_>>(),
                                        )
                                        .unwrap_or_else(|_| "[]".to_string());
                                    #[cfg(target_arch = "wasm32")]
                                    {
                                        let cameras_json_for_effect = cameras_json.clone();
                                        let points_json_for_effect = points_json.clone();
                                        let match_id_str_for_effect = match_id_str.to_string();
                                        let url_str_for_effect = url_str.to_string();
                                        use_effect(move || {
                                            let cameras_json = cameras_json_for_effect.clone();
                                            let points_json = points_json_for_effect.clone();
                                            let match_id_str = match_id_str_for_effect.clone();
                                            let url_str = url_str_for_effect.clone();
                                            spawn(async move {
                                                let js_init = format!(
                                                    r#"
                                                                                        console.log('Match page video player initialized ' + JSON.stringify({{ matchId: '{}', tournamentUrl: '{}', availableCameras: {}, pointsData: {} }}));
                                                                                        "#,
                                                    match_id_str.replace('\'', "\\'"),
                                                    url_str.replace('\'', "\\'"),
                                                    cameras_json,
                                                    points_json,
                                                );
                                                let _ = dioxus::prelude::document::eval(&js_init).await;
                                            });
                                        });
                                    }
                                }
                                rsx! {}
                            }
                        }
                    }

                // Head Ref Notes Sidebar
                div { class: "col-md-4",
                    div { class: "card",
                        div { class: "card-header",
                            h5 { class: "mb-0", "Head Ref Notes" }
                        }
                        div { class: "card-body",
                            div { class: "mb-3",
                                h6 { class: "mb-1", "Start Notes" }
                                if let Some(notes) = &d.match_data.initial_notes {
                                    if !notes.is_empty() {
                                        div { class: "small text-muted border-start border-3 ps-2",
                                            "{notes}"
                                        }
                                    } else {
                                        div { class: "text-muted small", "None" }
                                    }
                                } else {
                                    div { class: "text-muted small", "None" }
                                }
                            }
                            div { class: "mb-3",
                                h6 { class: "mb-1", "Finalize Notes" }
                                if let Some(notes) = &d.match_data.final_notes {
                                    if !notes.is_empty() {
                                        div { class: "small text-muted border-start border-3 ps-2",
                                            "{notes}"
                                        }
                                    } else {
                                        div { class: "text-muted small", "None" }
                                    }
                                } else {
                                    div { class: "text-muted small", "None" }
                                }
                            }
                            if d.is_head_ref && !d.match_notes.is_empty() {
                                div {
                                    h6 { class: "mb-1", "Match Notes" }
                                    div { style: "max-height: 300px; overflow-y: auto;",
                                        {
                                            d.match_notes
                                                .iter()
                                                .map(|note| {
                                                    let target_display = match note.target.as_str() {
                                                        "team1" => d.match_data.team1_name.clone(),
                                                        "team2" => d.match_data.team2_name.clone(),
                                                        "match" => "".to_string(),
                                                        _ => {
                                                            note.player_display
                                                                .as_ref()
                                                                .or(note.player_name.as_ref())
                                                                .cloned()
                                                                .unwrap_or_else(|| note.target.clone())
                                                        }
                                                    };
                                                    let prefix = if note.target == "match" {
                                                        "".to_string()
                                                    } else {
                                                        format!("{}: ", target_display)
                                                    };
                                                    rsx! {
                                                        div {
                                                            class: "small text-muted border-start border-3 ps-2 mb-2",
                                                            key: "{note.created_at.as_deref().unwrap_or(\"\")}",
                                                            {
                                                                if !target_display.is_empty()
                                                                    && (note.team_id.is_some() || note.player_id.is_some())
                                                                {
                                                                    rsx! {
                                                                        Link {
                                                                            to: if note.team_id.is_some() { Route::TeamProfile {
                                                                                id: note.team_id.as_ref().unwrap().clone(),
                                                                            } } else { Route::PlayerProfile {
                                                                                id: note.player_id.as_ref().unwrap().clone(),
                                                                            } },
                                                                            class: "text-decoration-none",
                                                                            "{target_display}"
                                                                        }
                                                                        ": {note.text}"
                                                                    }
                                                                } else {
                                                                    rsx! { "{prefix}{note.text}" }
                                                                }
                                                            }
                                                            if let Some(created) = &note.created_at {
                                                                div { class: "text-muted", style: "font-size: 0.75rem;",
                                                                    "{created.chars().take(16).collect::<String>().replace('T', \" \")}"
                                                                }
                                                            }
                                                        }
                                                    }
                                                })
                                        }
                                    }
                                }
                            } else if d.is_head_ref {
                                div {
                                    h6 { class: "mb-1", "Match Notes" }
                                    div { class: "text-muted small", "None" }
                                }
                            }
                        }
                    }
                }
            }
                }
            }
        } else if let Some(Err(e)) = val.read().as_ref() {
            p { class: "text-danger", "{e}" }
        } else if match_id.is_none() && match_name.is_none() {
            p { "Add ?id=... or ?name=... to the URL" }
        } else {
            p { "Loading…" }
        }
        }
    }
}
