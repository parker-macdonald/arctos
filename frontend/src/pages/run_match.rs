use crate::api;
use crate::Route;
use dioxus::prelude::*;
use serde_json::Value;
#[cfg(target_arch = "wasm32")]
use gloo_timers::callback::Interval;

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

    let poll_tick = use_signal(|| 0u32);
    let poll_started = use_signal(|| false);
    #[cfg(target_arch = "wasm32")]
    {
        let mut poll_tick = poll_tick;
        let mut poll_started = poll_started;
        use_effect(move || {
            if !poll_started() {
                let handle = Interval::new(2000, move || {
                    poll_tick.set(poll_tick() + 1);
                });
                poll_started.set(true);
                std::mem::forget(handle);
            }
        });
    }

    let url_for_state = url.clone();
    let id_for_state = match_id.clone();
    let state_signal = use_signal(|| None as Option<Result<Value, String>>);
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
        spawn(async move {
            if let Some(id) = id {
                err_out.set(None);
                match api::add_point(&u, &id, set, None, None).await {
                    Ok(resp) => {
                        let point_id = resp.get("point_id").and_then(|v| v.as_str()).unwrap_or("");
                        if !point_id.is_empty() {
                            let upd = serde_json::json!({ "point_id": point_id, "winner": "TEAM1" });
                            let _ = api::update_point(&u, point_id, &upd).await;
                        }
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
        spawn(async move {
            if let Some(id) = id {
                err_out.set(None);
                match api::add_point(&u, &id, set, None, None).await {
                    Ok(resp) => {
                        let point_id = resp.get("point_id").and_then(|v| v.as_str()).unwrap_or("");
                        if !point_id.is_empty() {
                            let upd = serde_json::json!({ "point_id": point_id, "winner": "TEAM2" });
                            let _ = api::update_point(&u, point_id, &upd).await;
                        }
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
        spawn(async move {
            if let Some(id) = id {
                err_out.set(None);
                match api::complete_match(&u, &id).await {
                    Ok(_) => {}
                    Err(e) => err_out.set(Some(e)),
                }
            }
        });
    };

    rsx! {
        if match_id.is_none() {
            h1 { "Run Match" }
            Link { to: Route::Schedule { url: url.clone() }, "← Schedule" }
            p { class: "text-muted", "Add ?id=<match-uuid> to the URL." }
        } else if let Some(Ok(d)) = detail.value().read().as_ref() {
            div { class: "container mt-4",
                div { class: "row",
                    div { class: "col-md-12",
                        h2 { "Run Match: {d.match_data.name}" }
                        p { class: "mb-0",
                            strong { "Teams: " }
                            "{d.match_data.team1_name} vs {d.match_data.team2_name}"
                        }
                        div { class: "row mt-3",
                            div { class: "col-md-4",
                                p { class: "mb-0", strong { "Field: " } "{d.match_data.field.as_deref().unwrap_or(\"TBA\")}" }
                            }
                            div { class: "col-md-4",
                                p { class: "mb-0", strong { "Status: " } "{d.match_data.status}" }
                            }
                            div { class: "col-md-4",
                                p { class: "mb-0", strong { "Set Type: " } "{d.match_data.set_type.as_deref().unwrap_or(\"-\")}" }
                            }
                        }
                        if let Some(e) = action_error() {
                            div { class: "alert alert-danger mt-2", "{e}" }
                        }
                        if let Some(state) = state_signal() {
                            match state {
                                Ok(v) => {
                                    let status = v.get("status").and_then(|s| s.as_str()).unwrap_or("-");
                                    let t1 = v.get("team1_score").and_then(|n| n.as_u64()).unwrap_or(0);
                                    let t2 = v.get("team2_score").and_then(|n| n.as_u64()).unwrap_or(0);
                                    let points = v.get("points").and_then(|p| p.as_array()).cloned().unwrap_or_default();
                                    let finalized = v.get("finalized_at").and_then(|f| f.as_str()).is_some();
                                    rsx! {
                                        div { class: "card mt-3",
                                            div { class: "card-body",
                                                p { strong { "Status: " } "{status}" }
                                                p { strong { "Score: " } "{t1} - {t2}" }
                                                if !finalized {
                                                    div { class: "mb-2",
                                                        label { class: "form-label me-2", "Current set:" }
                                                        input {
                                                            r#type: "number",
                                                            min: "1",
                                                            class: "form-control d-inline-block",
                                                            style: "width: 120px;",
                                                            value: "{current_set()}",
                                                            oninput: move |ev| {
                                                                if let Ok(n) = ev.value().parse::<u32>() {
                                                                    current_set.set(n);
                                                                }
                                                            }
                                                        }
                                                    }
                                                    div { class: "btn-group mb-2",
                                                        button { class: "btn btn-outline-primary", onclick: on_point_team1, "Point Team 1" }
                                                        button { class: "btn btn-outline-primary", onclick: on_point_team2, "Point Team 2" }
                                                        button { class: "btn btn-outline-success", onclick: on_complete, "Complete Match" }
                                                    }
                                                } else {
                                                    p { class: "text-success", "Match finalized." }
                                                }
                                            }
                                        }

                                        div { class: "card mt-3",
                                            div { class: "card-header",
                                                h5 { class: "mb-0", "Points" }
                                            }
                                            div { class: "card-body",
                                                if points.is_empty() {
                                                    p { class: "text-muted", "No points recorded yet." }
                                                } else {
                                                    div { class: "table-responsive",
                                                        table { class: "table table-striped",
                                                            thead {
                                                                tr {
                                                                    th { "Set" }
                                                                    th { "Winner" }
                                                                    th { "Rerun?" }
                                                                    th { "Actions" }
                                                                }
                                                            }
                                                            tbody {
                                                                for pt in points.iter() {
                                                                    {
                                                                        let point_id = pt.get("uuid").and_then(|v| v.as_str()).unwrap_or("");
                                                                        let set_number = pt.get("set_number").and_then(|v| v.as_u64()).unwrap_or(0);
                                                                        let winner = pt.get("winner").and_then(|v| v.as_str()).unwrap_or("-");
                                                                        let rerolled = pt.get("rerolled").and_then(|v| v.as_bool()).unwrap_or(false);
                                                                        let u = url.clone();
                                                                        let pid = point_id.to_string();
                                                                        let u_for_reroll = u.clone();
                                                                        let u_for_delete = u.clone();
                                                                        let pid_for_reroll = pid.clone();
                                                                        let pid_for_delete = pid.clone();
                                                                        rsx! {
                                                                            tr { key: "{point_id}",
                                                                                td { "{set_number}" }
                                                                                td { "{winner}" }
                                                                                td {
                                                                                    if rerolled {
                                                                                        span { class: "badge bg-warning", "Rerun" }
                                                                                    } else {
                                                                                        span { class: "badge bg-success", "Valid" }
                                                                                    }
                                                                                }
                                                                                td {
                                                                                    div { class: "btn-group btn-group-sm",
                                                                                        button {
                                                                                            class: "btn btn-outline-secondary",
                                                                                            onclick: move |_| {
                                                                                                let u = u_for_reroll.clone();
                                                                                                let pid = pid_for_reroll.clone();
                                                                                                spawn(async move {
                                                                                                    let upd = serde_json::json!({ "point_id": pid, "rerolled": !rerolled });
                                                                                                    let _ = api::update_point(&u, &pid, &upd).await;
                                                                                                });
                                                                                            },
                                                                                            if rerolled { "Un-rerun" } else { "Rerun" }
                                                                                        }
                                                                                        button {
                                                                                            class: "btn btn-outline-danger",
                                                                                            onclick: move |_| {
                                                                                                let u = u_for_delete.clone();
                                                                                                let pid = pid_for_delete.clone();
                                                                                                spawn(async move {
                                                                                                    let _ = api::delete_point(&u, &pid).await;
                                                                                                });
                                                                                            },
                                                                                            "Delete"
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
                                        }
                                    }
                                }
                                Err(e) => rsx! { p { class: "text-danger", "{e}" } }
                            }
                        } else {
                            p { "Loading state..." }
                        }
                    }
                }
            }
        } else if let Some(Err(e)) = detail.value().read().as_ref() {
            p { class: "text-danger", "{e}" }
        } else {
            p { "Loading…" }
        }
    }
}
