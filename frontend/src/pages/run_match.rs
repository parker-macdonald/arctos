use crate::api;
use crate::Route;
use dioxus::prelude::*;
use serde_json::Value;

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

#[component]
pub fn RunMatch(url: String) -> Element {
    let match_id = get_query_param("id");
    let url_for_detail = url.clone();
    let id_for_detail = match_id.clone();
    let detail = use_resource(move || {
        let u = url_for_detail.clone();
        let id = id_for_detail.clone();
        async move {
            if let Some(id) = id {
                api::match_detail(&u, Some(&id), None)
                    .await
                    .map_err(|e| e.to_string())
            } else {
                Err("id param required".to_string())
            }
        }
    });

    let url_for_state = url.clone();
    let id_for_state = match_id.clone();
    let state_signal = use_signal(|| None as Option<Result<Value, String>>);
    let poll_tick = use_signal(|| 0u32);

    use_effect(move || {
        let u = url_for_state.clone();
        let id = id_for_state.clone();
        let _tick = poll_tick();
        if id.is_none() {
            return;
        }
        let id = id.unwrap();
        let mut state_signal = state_signal;
        spawn(async move {
            match api::match_state(&u, &id).await {
                Ok(v) => state_signal.set(Some(Ok(v))),
                Err(e) => state_signal.set(Some(Err(e))),
            }
        });
    });

    let mut current_set = use_signal(|| 1u32);
    let action_error = use_signal(|| Option::<String>::None);
    let url1 = url.clone();
    let id1 = match_id.clone();
    let url2 = url.clone();
    let id2 = match_id.clone();
    let url_complete = url.clone();
    let id_complete = match_id.clone();

    let on_point_team1 = move |_| {
        let u = url1.clone();
        let id = id1.clone();
        let set = current_set();
        let mut err_out = action_error;
        let mut poll_tick = poll_tick;
        spawn(async move {
            if let Some(id) = id {
                err_out.set(None);
                let ts = api::server_time()
                    .await
                    .ok()
                    .map(|t| (t.server_time * 1000.0) as u64)
                    .unwrap_or(0);
                match api::add_point(&u, &id, set, Some(ts), None).await {
                    Ok(resp) => {
                        let point_id = resp.get("point_id").and_then(|v| v.as_str()).unwrap_or("");
                        if !point_id.is_empty() {
                            let upd = serde_json::json!({ "winner": "TEAM1" });
                            let _ = api::update_point(&u, point_id, &upd).await;
                        }
                        poll_tick.set(poll_tick() + 1);
                    }
                    Err(e) => err_out.set(Some(e)),
                }
            }
        });
    };

    let on_point_team2 = move |_| {
        let u = url2.clone();
        let id = id2.clone();
        let set = current_set();
        let mut err_out = action_error;
        let mut poll_tick = poll_tick;
        spawn(async move {
            if let Some(id) = id {
                err_out.set(None);
                let ts = api::server_time()
                    .await
                    .ok()
                    .map(|t| (t.server_time * 1000.0) as u64)
                    .unwrap_or(0);
                match api::add_point(&u, &id, set, Some(ts), None).await {
                    Ok(resp) => {
                        let point_id = resp.get("point_id").and_then(|v| v.as_str()).unwrap_or("");
                        if !point_id.is_empty() {
                            let upd = serde_json::json!({ "winner": "TEAM2" });
                            let _ = api::update_point(&u, point_id, &upd).await;
                        }
                        poll_tick.set(poll_tick() + 1);
                    }
                    Err(e) => err_out.set(Some(e)),
                }
            }
        });
    };

    let on_complete = move |_| {
        let u = url_complete.clone();
        let id = id_complete.clone();
        let mut err_out = action_error;
        let mut poll_tick = poll_tick;
        spawn(async move {
            if let Some(id) = id {
                err_out.set(None);
                match api::complete_match(&u, &id).await {
                    Ok(_) => poll_tick.set(poll_tick() + 1),
                    Err(e) => err_out.set(Some(e)),
                }
            }
        });
    };

    rsx! {
        h1 { "Run match" }
        Link { to: Route::Schedule { url: url.clone() }, "← Schedule" }
        if match_id.is_none() {
            p { "Add ?id=<match-uuid> to the URL." }
        } else if let Some(Ok(d)) = detail.value().read().as_ref() {
            p { "Match: {d.match_data.name} — {d.match_data.team1_name} vs {d.match_data.team2_name}" }
            if let Some(e) = action_error() {
                p { class: "error", "{e}" }
            }
            if let Some(state) = state_signal() {
                match state {
                    Ok(v) => {
                        let status = v.get("status").and_then(|s| s.as_str()).unwrap_or("-");
                        let t1 = v.get("team1_score").and_then(|n| n.as_u64()).unwrap_or(0);
                        let t2 = v.get("team2_score").and_then(|n| n.as_u64()).unwrap_or(0);
                        let finalized = v.get("finalized_at").and_then(|f| f.as_str()).is_some();
                        rsx! {
                            p { "Status: {status} — Score: {t1} - {t2}" }
                            if !finalized {
                                p { "Current set: " input { r#type: "number", min: "1", value: "{current_set()}", oninput: move |ev| { if let Ok(n) = ev.value().parse::<u32>() { current_set.set(n) } } } }
                                button { onclick: on_point_team1, "Point Team 1" }
                                button { onclick: on_point_team2, "Point Team 2" }
                                button { onclick: on_complete, "Complete match" }
                            } else {
                                p { class: "success", "Match finalized." }
                            }
                        }
                    }
                    Err(e) => rsx! { p { class: "error", "{e}" } }
                }
            } else {
                p { "Loading state..." }
            }
        } else if let Some(Err(e)) = detail.value().read().as_ref() {
            p { class: "error", "{e}" }
        } else {
            p { "Loading…" }
        }
    }
}
