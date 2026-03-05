//! Stones Player: globally synchronized stones using a Bayesian filter for time offset.

use crate::api;
use crate::stones_filter::BayesianOffsetFilter;
use crate::types::StonesResponse;
use dioxus::prelude::*;

#[cfg(target_arch = "wasm32")]
use std::cell::RefCell;
#[cfg(target_arch = "wasm32")]
use std::collections::{HashMap, HashSet};
#[cfg(target_arch = "wasm32")]
use std::rc::Rc;
#[cfg(target_arch = "wasm32")]
use wasm_bindgen::JsCast;

const BEAT_INTERVAL: f64 = 1.5;
const SYNC_INTERVAL_MS: u32 = 997;
const SCHEDULE_INTERVAL_MS: u32 = 500;
const SCHEDULE_AHEAD_SEC: f64 = 7.0;
const MIN_GAP_SEC: f64 = 1.0;

#[component]
pub fn Stones() -> Element {
    let stones_data = use_resource(move || async move {
        api::stones_list().await.map_err(|e| e.to_string())
    });
    let stones_val = stones_data.value();

    #[cfg(target_arch = "wasm32")]
    {
        rsx! {
            StonesPlayerWasm {
                stones_val: stones_val.clone(),
            }
        }
    }

    #[cfg(not(target_arch = "wasm32"))]
    {
        rsx! {
            div { class: "container mt-4",
                h1 { "Stones Player" }
                p { "Use the web (WASM) build for the synchronized Stones player." }
            }
        }
    }
}

#[cfg(target_arch = "wasm32")]
#[component]
fn StonesPlayerWasm(stones_val: ReadSignal<Option<Result<StonesResponse, String>>>) -> Element {
    let mut is_playing = use_signal(|| false);
    let mut selected_index = use_signal(|| 0usize);
    let mut filter = use_signal(|| BayesianOffsetFilter::default());
    let rtt_ms = use_signal(|| Option::<f64>::None);
    let mut custom_status = use_signal(|| Option::<String>::None);

    let mut audio_ctx = use_signal(|| Option::<web_sys::AudioContext>::None);
    let mut audio_buffer = use_signal(|| Option::<web_sys::AudioBuffer>::None);
    let custom_buffer = use_signal(|| Option::<web_sys::AudioBuffer>::None);
    let mut ctx_start_time = use_signal(|| Option::<f64>::None);
    let schedule_state = use_signal(|| {
        Rc::new(RefCell::new(ScheduleState {
            times: HashSet::new(),
            sources: HashMap::new(),
            media_dest: None,
        }))
    });

    // Sync loop
    use_effect(move || {
        let mut filter = filter.clone();
        let mut rtt_ms = rtt_ms.clone();
        spawn(async move {
            loop {
                let client_send = js_sys::Date::now() / 1000.0;
                if let Ok(res) = api::server_time().await {
                    let client_receive = js_sys::Date::now() / 1000.0;
                    let rtt = client_receive - client_send;
                    let offset = res.server_time - client_receive + (rtt / 2.0);
                    filter.write().update(offset);
                    rtt_ms.set(Some(rtt * 1000.0));
                }
                gloo_timers::future::TimeoutFuture::new(SYNC_INTERVAL_MS).await;
            }
        });
    });

    // Schedule loop when playing
    use_effect(move || {
        if !is_playing() {
            return;
        }
        let is_playing_sig = is_playing.clone();
        let filter_sig = filter.clone();
        let audio_ctx_sig = audio_ctx.clone();
        let audio_buffer_sig = audio_buffer.clone();
        let ctx_start_time_sig = ctx_start_time.clone();
        let schedule_rc = schedule_state.read().clone();
        spawn(async move {
            while is_playing_sig() {
                let ctx = audio_ctx_sig.read().clone();
                let buf = audio_buffer_sig.read().clone();
                let start_time = ctx_start_time_sig.read();
                if let (Some(ref ctx), Some(ref buf), Some(_start)) =
                    (ctx, buf, *start_time)
                {
                    let now = js_sys::Date::now() / 1000.0;
                    let audio_now = ctx.current_time();
                    let mean = filter_sig.read().get_mean();
                    let mut beat_time = next_beat_time(now, mean);
                    let max_wall = now + SCHEDULE_AHEAD_SEC;
                    let mut scheduled = 0u32;
                    while beat_time <= max_wall && scheduled < 5 {
                        if !is_playing_sig() {
                            break;
                        }
                        let delay = beat_time - now;
                        if delay > 0.05 && delay < 60.0 {
                            let audio_time = audio_now + delay;
                            if schedule_sound_at(
                                ctx.clone(),
                                buf.clone(),
                                audio_time,
                                schedule_rc.clone(),
                            ) {
                                scheduled += 1;
                            }
                        }
                        beat_time += BEAT_INTERVAL;
                    }
                }
                gloo_timers::future::TimeoutFuture::new(SCHEDULE_INTERVAL_MS).await;
            }
        });
    });

    let on_play_pause = move |_| {
        if is_playing() {
            is_playing.set(false);
            clear_scheduled(schedule_state.read().clone());
        } else {
            custom_status.set(None);
            // Create/resume AudioContext synchronously while we're still in the user gesture (required by browsers)
            let existing_ctx = audio_ctx.read().clone();
            let ctx = match existing_ctx {
                Some(c) => c,
                None => {
                    let opts = web_sys::AudioContextOptions::new();
                    let c = match web_sys::AudioContext::new_with_context_options(&opts) {
                        Ok(c) => c,
                        Err(_) => {
                            custom_status.set(Some("Could not create audio context. Try again.".into()));
                            return;
                        }
                    };
                    ctx_start_time.set(Some(js_sys::Date::now() / 1000.0));
                    audio_ctx.set(Some(c.clone()));
                    // On first creation, also create a MediaStream destination and hook it to a hidden audio element.
                    #[cfg(target_arch = "wasm32")]
                    {
                        ensure_media_destination(&c, schedule_state.clone());
                    }
                    if c.state() != web_sys::AudioContextState::Running {
                        if c.resume().is_err() {
                            custom_status.set(Some("Could not start audio. Click Play again.".into()));
                            return;
                        }
                    }
                    c
                }
            };
            if ctx.state() != web_sys::AudioContextState::Running {
                let _ = ctx.resume();
            }
            #[cfg(target_arch = "wasm32")]
            {
                // Ensure MediaStreamDestination is present even if context already existed.
                ensure_media_destination(&ctx, schedule_state.clone());
            }
            let stones_opt = stones_val.read().as_ref().and_then(|r| r.as_ref().ok()).cloned();
            let idx = selected_index();
            let stones_len = stones_opt.as_ref().map(|s| s.stones.len()).unwrap_or(0);
            let is_custom = idx >= stones_len;
            if is_custom && custom_buffer.read().is_none() {
                custom_status.set(Some("Please upload a custom audio file first.".into()));
                return;
            }
            spawn(async move {
                init_and_start_playback(
                    is_playing,
                    audio_ctx,
                    audio_buffer,
                    custom_buffer,
                    stones_opt,
                    idx,
                    custom_status,
                )
                .await;
            });
        }
    };

    let on_reset = move |_| {
        filter.write().reset();
    };

    let stones_ok = stones_val.read().as_ref().and_then(|r| r.as_ref().ok()).cloned();
    let stones_len = stones_ok.as_ref().map(|s| s.stones.len()).unwrap_or(0);
    let base_url = api::base_url();
    let offset_str = format!("{:.6}", filter.read().get_mean());
    let var_str = format!("{:.6}", filter.read().get_variance());
    let rtt_display = match *rtt_ms.read() {
        Some(ms) => format!("{:.1} ms", ms),
        None => "-".to_string(),
    };

    #[cfg(target_arch = "wasm32")]
    fn ensure_media_destination(
        ctx: &web_sys::AudioContext,
        mut schedule_state: Signal<Rc<RefCell<ScheduleState>>>,
    ) {
        use wasm_bindgen::JsCast;
        use wasm_bindgen::JsValue;

        // If we already have a destination, nothing to do.
        if schedule_state
            .read()
            .borrow()
            .media_dest
            .as_ref()
            .is_some()
        {
            return;
        }

        let dest = match ctx.create_media_stream_destination() {
            Ok(d) => d,
            Err(_) => return,
        };

        if let Some(window) = web_sys::window() {
            if let Some(doc) = window.document() {
                if let Some(el) = doc.get_element_by_id("audio-stream") {
                    if let Ok(audio) = el.dyn_into::<web_sys::HtmlAudioElement>() {
                        // audio.srcObject = dest.stream;
                        if let Ok(stream) = js_sys::Reflect::get(
                            &JsValue::from(dest.clone()),
                            &JsValue::from_str("stream"),
                        ) {
                            let _ = js_sys::Reflect::set(
                                &audio,
                                &JsValue::from_str("srcObject"),
                                &stream,
                            );
                        }
                        audio.set_autoplay(true);
                        let _ = audio.play();
                    }
                }
            }
        }

        schedule_state.write().borrow_mut().media_dest = Some(dest);
    }

    #[derive(Clone)]
    struct SoundBtn {
        index: usize,
        key_name: String,
        display_name: String,
        filename_encoded: String,
    }
    let sound_buttons: Vec<SoundBtn> = stones_ok
        .as_ref()
        .map(|d| {
            d.stones
                .iter()
                .enumerate()
                .map(|(i, st)| SoundBtn {
                    index: i,
                    key_name: st.filename.clone(),
                    display_name: st.display_name.clone(),
                    filename_encoded: st.filename_encoded.clone(),
                })
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();

    rsx! {
        div { class: "container mt-4",
            div { class: "row",
                div { class: "col-12",
                    h1 { "Stones Player" }
                    p {
                        "This is a stones player that plays globally synchronized stones: all devices on this page will (eventually) play stones at the same time."
                    }
                    p { strong { "Important Notes:" } }
                    ul {
                        li { "The speed of sound is about 343 m/s (~110 ms to cross a 40 m field). If stones sound out of sync, try standing equidistant from speakers." }
                        li { "It should only take a few (3–5) stones to sync. If not syncing, click \"Reset Sync\" on all devices at roughly the same time." }
                        li { "Bluetooth can add up to ~250 ms delay; prefer wired connections if latency differs between devices." }
                        li { "When changing the audio device, the first few stones may be out of sync while the buffer clears." }
                        li { "Custom files: keep them under 1.5 s and avoid dead space at the start." }
                    }

                    div { class: "card",
                        div { class: "card-body",
                            div { class: "mb-4",
                                label { class: "form-label mb-2", "Sound:" }
                                div { class: "d-flex flex-wrap gap-2", role: "group",
                                    for sound_btn in sound_buttons.iter() {
                                        {
                                            let key_name = sound_btn.key_name.clone();
                                            let display_name = sound_btn.display_name.clone();
                                            let idx = sound_btn.index;
                                            let filename_encoded = sound_btn.filename_encoded.clone();
                                            let base_url = base_url.clone();
                                            let is_selected = selected_index() == idx;
                                            rsx! {
                                                button {
                                                    key: "{key_name}",
                                                    class: if is_selected { "btn btn-primary" } else { "btn btn-outline-primary" },
                                                    onclick: move |_| {
                                                        clear_scheduled(schedule_state.read().clone());
                                                        selected_index.set(idx);
                                                        audio_buffer.set(None);
                                                        let base = base_url.clone();
                                                        let filename = filename_encoded.clone();
                                                        let audio_ctx = audio_ctx.clone();
                                                        let mut audio_buffer = audio_buffer.clone();
                                                        spawn(async move {
                                                            if let Some(ctx) = audio_ctx.read().clone() {
                                                                let url = format!("{}/static/stones/{}", base, filename);
                                                                if let Ok(buf) = load_audio_buffer(&ctx, &url).await {
                                                                    audio_buffer.set(Some(buf));
                                                                }
                                                            }
                                                        });
                                                    },
                                                    "{display_name}"
                                                }
                                            }
                                        }
                                    }
                                    button {
                                        class: if selected_index() >= stones_len { "btn btn-primary" } else { "btn btn-outline-primary" },
                                        onclick: move |_| {
                                            clear_scheduled(schedule_state.read().clone());
                                            selected_index.set(stones_len);
                                            audio_buffer.set(custom_buffer.read().clone());
                                        },
                                        "Custom"
                                    }
                                }
                                if selected_index() >= stones_len {
                                    div { class: "mt-3",
                                        label { class: "form-label", "Upload MP3 (under 1.5 s):" }
                                        input {
                                            id: "stones-custom-file",
                                            r#type: "file",
                                            class: "form-control",
                                            accept: "audio/mpeg,audio/mp3,.mp3",
                                            onchange: move |_evt| {
                                                if let Some(window) = web_sys::window() {
                                                    if let Some(doc) = window.document() {
                                                        if let Some(el) = doc.get_element_by_id("stones-custom-file") {
                                                            if let Ok(input) = el.dyn_into::<web_sys::HtmlInputElement>() {
                                                                if let Some(files) = input.files() {
                                                                    if let Some(file) = files.get(0) {
                                                                        handle_custom_file(file, custom_buffer, audio_ctx, custom_status, audio_buffer);
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                        if let Some(ref msg) = *custom_status.read() {
                                            p { class: "form-text mt-2", "{msg}" }
                                        }
                                    }
                                }
                            }

                            div { class: "mb-3",
                                button {
                                    class: if is_playing() { "btn btn-warning btn-lg mb-3" } else { "btn btn-primary btn-lg mb-3" },
                                    onclick: on_play_pause,
                                    if is_playing() { "Pause" } else { "Play" }
                                }
                                button {
                                    class: "btn btn-danger mb-3 ms-2",
                                    onclick: on_reset,
                                    "Reset Sync"
                                }
                                if let Some(ref msg) = *custom_status.read() {
                                    p { class: "form-text mt-2 text-danger", "{msg}" }
                                }
                            }

                        // Hidden audio element used as a MediaStream sink so that
                        // mobile browsers treat playback as regular media and keep
                        // playing reliably when the screen locks or app is backgrounded.
                        audio {
                            id: "audio-stream",
                            autoplay: true,
                            style: "display: none;",
                        }

                            div { class: "mb-3",
                                h5 { "Stats" }
                                p { "Offset (x\u{0302}): {offset_str} s" }
                                p { "Variance (P): {var_str} s\u{00B2}" }
                                p { "Round trip time: {rtt_display}" }
                            }
                        }
                    }
                }
            }
        }

        if let Some(Err(e)) = stones_val.read().as_ref() {
            p { class: "text-danger", "{e}" }
        }
    }
}

fn next_beat_time(now: f64, offset: f64) -> f64 {
    let server_now = now + offset;
    let next_server = (server_now / BEAT_INTERVAL).ceil() * BEAT_INTERVAL;
    next_server - offset
}

#[cfg(target_arch = "wasm32")]
struct ScheduleState {
    times: HashSet<i64>,
    sources: HashMap<i64, web_sys::AudioBufferSourceNode>,
    media_dest: Option<web_sys::MediaStreamAudioDestinationNode>,
}

#[cfg(target_arch = "wasm32")]
fn schedule_sound_at(
    ctx: web_sys::AudioContext,
    buf: web_sys::AudioBuffer,
    audio_time: f64,
    state_rc: Rc<RefCell<ScheduleState>>,
) -> bool {
    let rounded_ms = (audio_time * 1000.0).round() as i64;
    let min_gap_ms = (MIN_GAP_SEC * 1000.0) as i64;
    {
        let state = state_rc.borrow();
        for &t_ms in state.times.iter() {
            if (t_ms - rounded_ms).abs() < min_gap_ms {
                return false;
            }
        }
    }
    let current = ctx.current_time();
    let delay = audio_time - current;
    if delay <= 0.0 || delay >= 60.0 {
        return false;
    }
    let source = match ctx.create_buffer_source() {
        Ok(s) => s,
        Err(_) => return false,
    };
    let _ = source.set_buffer(Some(&buf));
    {
        let state = state_rc.borrow();
        if let Some(ref media_dest) = state.media_dest {
            if source.connect_with_audio_node(media_dest).is_err() {
                return false;
            }
        } else {
            let destination = ctx.destination();
            if source.connect_with_audio_node(&destination).is_err() {
                return false;
            }
        }
    }
    let state_rc2 = state_rc.clone();
    let rounded2 = rounded_ms;
    let closure = wasm_bindgen::closure::Closure::once(Box::new(move || {
        state_rc2.borrow_mut().sources.remove(&rounded2);
        state_rc2.borrow_mut().times.remove(&rounded2);
    }) as Box<dyn FnOnce()>);
    #[allow(deprecated)]
    let _ = source.set_onended(Some(closure.as_ref().unchecked_ref()));
    closure.forget();
    if source.start_with_when(audio_time).is_err() {
        return false;
    }
    state_rc.borrow_mut().times.insert(rounded_ms);
    state_rc.borrow_mut().sources.insert(rounded_ms, source);
    true
}

#[cfg(target_arch = "wasm32")]
fn clear_scheduled(state_rc: Rc<RefCell<ScheduleState>>) {
    // Drain sources and clear times inside the borrow, then stop/disconnect
    // outside so that any onended callback can safely borrow the RefCell.
    let to_stop: Vec<web_sys::AudioBufferSourceNode> = {
        let mut state = state_rc.borrow_mut();
        state.times.clear();
        state.sources.drain().map(|(_, s)| s).collect()
    };
    for source in to_stop {
        #[allow(deprecated)]
        let _ = source.stop();
        let _ = source.disconnect();
    }
}

#[cfg(target_arch = "wasm32")]
async fn init_and_start_playback(
    mut is_playing: Signal<bool>,
    audio_ctx: Signal<Option<web_sys::AudioContext>>,
    mut audio_buffer: Signal<Option<web_sys::AudioBuffer>>,
    custom_buffer: Signal<Option<web_sys::AudioBuffer>>,
    stones: Option<StonesResponse>,
    selected_index: usize,
    mut custom_status: Signal<Option<String>>,
) {
    let ctx = match audio_ctx.read().clone() {
        Some(c) => c,
        None => {
            custom_status.set(Some("Audio context not ready. Click Play again.".into()));
            return;
        }
    };
    // Ensure context is running (resume() is async; without awaiting, scheduling can fail silently)
    if ctx.state() != web_sys::AudioContextState::Running {
        let promise = match ctx.resume() {
            Ok(p) => p,
            Err(_) => {
                custom_status.set(Some("Could not resume audio.".into()));
                return;
            }
        };
        if wasm_bindgen_futures::JsFuture::from(promise).await.is_err() {
            custom_status.set(Some("Could not start audio.".into()));
            return;
        }
    }
    let stones_len = stones.as_ref().map(|s| s.stones.len()).unwrap_or(0);
    let buf = if selected_index >= stones_len {
        custom_buffer.read().clone()
    } else {
        let stone = stones.as_ref().and_then(|s| s.stones.get(selected_index));
        match stone {
            Some(s) => {
                let url = format!("{}/static/stones/{}", api::base_url(), s.filename_encoded);
                match load_audio_buffer(&ctx, &url).await {
                    Ok(b) => Some(b),
                    Err(e) => {
                        custom_status.set(Some(format!("Failed to load audio: {}", e)));
                        return;
                    }
                }
            }
            None => {
                custom_status.set(Some("No sound selected.".into()));
                return;
            }
        }
    };
    if let Some(b) = buf {
        audio_buffer.set(Some(b));
        custom_status.set(None);
        is_playing.set(true);
    }
}

#[cfg(target_arch = "wasm32")]
async fn load_audio_buffer(
    ctx: &web_sys::AudioContext,
    url: &str,
) -> Result<web_sys::AudioBuffer, String> {
    use js_sys::Uint8Array;
    use wasm_bindgen::JsCast;
    let bytes = api::fetch_bytes(url).await?;
    let len = bytes.len();
    let arr = Uint8Array::new_with_length(len as u32);
    arr.copy_from(bytes.as_slice());
    let array_buffer = arr
        .buffer()
        .dyn_into::<js_sys::ArrayBuffer>()
        .map_err(|_| "not ArrayBuffer")?;
    let promise = ctx
        .decode_audio_data(&array_buffer)
        .map_err(|_| "decode_audio_data failed".to_string())?;
    let result = wasm_bindgen_futures::JsFuture::from(promise)
        .await
        .map_err(|_| "decode_audio_data failed".to_string())?;
    let buffer = result.dyn_into::<web_sys::AudioBuffer>().map_err(|_| "not AudioBuffer")?;
    Ok(buffer)
}

#[cfg(target_arch = "wasm32")]
fn handle_custom_file(
    file: web_sys::File,
    custom_buffer: Signal<Option<web_sys::AudioBuffer>>,
    audio_ctx: Signal<Option<web_sys::AudioContext>>,
    custom_status: Signal<Option<String>>,
    audio_buffer: Signal<Option<web_sys::AudioBuffer>>,
) {
    use wasm_bindgen::JsCast;

    let mut custom_buffer = custom_buffer.clone();
    let audio_ctx = audio_ctx.clone();
    let mut custom_status = custom_status.clone();
    let mut audio_buffer = audio_buffer.clone();
    spawn(async move {
        let ctx = match audio_ctx.read().clone() {
            Some(c) => c,
            None => {
                let opts = web_sys::AudioContextOptions::new();
                web_sys::AudioContext::new_with_context_options(&opts).unwrap()
            }
        };
        let array_buffer_promise = file.array_buffer();
        let array_buffer_js = wasm_bindgen_futures::JsFuture::from(array_buffer_promise)
            .await
            .ok();
        let array_buffer = match array_buffer_js {
            Some(ab) => match ab.dyn_into::<js_sys::ArrayBuffer>() {
                Ok(ab) => ab,
                Err(_) => {
                    custom_status.set(Some("Failed to read file.".into()));
                    return;
                }
            },
            None => {
                custom_status.set(Some("Failed to read file.".into()));
                return;
            }
        };
        let promise = match ctx.decode_audio_data(&array_buffer) {
            Ok(p) => p,
            Err(_) => {
                custom_status.set(Some("Could not decode audio.".into()));
                return;
            }
        };
        let decoded = wasm_bindgen_futures::JsFuture::from(promise).await;
        let buffer: Option<web_sys::AudioBuffer> = match decoded {
            Ok(buf) => buf.dyn_into::<web_sys::AudioBuffer>().ok(),
            Err(_) => {
                custom_status.set(Some("Could not decode audio. Try a different file.".into()));
                return;
            }
        };
        let buffer = match buffer {
            Some(b) => b,
            None => return,
        };
        let duration = buffer.duration();
        if duration >= 1.5 {
            custom_status.set(Some(format!(
                "File is {:.2} s. Must be under 1.5 s.",
                duration
            )));
            return;
        }
        custom_buffer.set(Some(buffer.clone()));
        audio_buffer.set(Some(buffer));
        custom_status.set(Some(format!("Loaded ({:.2} s).", duration)));
    });
}
