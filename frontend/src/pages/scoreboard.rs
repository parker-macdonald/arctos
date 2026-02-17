use crate::api;
use dioxus::prelude::*;
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
pub fn Scoreboard(url: String) -> Element {
    let field = get_query_param("field");
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
    let url_for_poll = url.clone();
    let field_for_poll = field.clone();
    let data = use_resource(move || {
        let u = url_for_poll.clone();
        let f = field_for_poll.clone();
        let _tick = poll_tick();
        async move {
            if let Some(f) = &f {
                api::scoreboard_state(&u, f).await.map_err(|e| e.to_string())
            } else {
                Err("field query param required".to_string())
            }
        }
    });
    let val = data.value();
    rsx! {
        style { r#"
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background: transparent; color: #fff; overflow: hidden; }}
        .scoreboard-container {{ background: rgba(0, 0, 0, 0.85); padding: 12px 30px; border-radius: 8px; min-width: 600px; backdrop-filter: blur(10px); }}
        .error-message {{ color: #ff6b6b; padding: 20px; text-align: center; font-size: 18px; }}
        .scoreboard-table {{ width: 100%; border-collapse: collapse; }}
        .team-row {{ height: 60px; }}
        .team-cell {{ padding: 6px 15px; vertical-align: middle; }}
        .team-info {{ display: flex; align-items: center; gap: 12px; }}
        .team-photo {{ width: 50px; height: 50px; border-radius: 50%; object-fit: cover; border: 2px solid rgba(255, 255, 255, 0.3); }}
        .team-name {{ font-size: 24px; font-weight: 600; min-width: 200px; }}
        .score-cell {{ text-align: center; padding: 6px 20px; font-size: 32px; font-weight: bold; border-left: 1px solid rgba(255, 255, 255, 0.2); min-width: 80px; }}
        .score-cell:first-of-type {{ border-left: none; }}
        .stones-info {{ margin-top: 10px; padding-top: 10px; border-top: 1px solid rgba(255, 255, 255, 0.2); }}
        .stones-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; font-size: 18px; }}
        .stones-count {{ font-weight: bold; font-size: 24px; }}
        .progress-bar-container {{ width: 100%; height: 8px; background: rgba(255, 255, 255, 0.2); border-radius: 4px; overflow: hidden; }}
        .progress-bar {{ height: 100%; background: linear-gradient(90deg, #4ecdc4, #44a08d); transition: width 0.3s ease; }}
        .between-matches-label {{ font-size: 24px; color: rgba(255, 255, 255, 0.9); font-weight: 600; margin-right: 15px; }}
        .winner-badge {{ display: inline-block; background: #4ecdc4; color: #000; font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 12px; margin-left: 8px; text-transform: uppercase; letter-spacing: 0.5px; }}
        .vs-text {{ margin: 0 15px; font-size: 24px; font-weight: 600; color: rgba(255, 255, 255, 0.7); }}
        "# }

        if field.is_none() {
            div { class: "error-message", "Add ?field=<field_name> to the URL." }
        } else if let Some(Ok(s)) = val.read().as_ref() {
            if s.has_active_match {
                div { class: "scoreboard-container",
                    table { class: "scoreboard-table",
                        tbody {
                            tr { class: "team-row",
                                td { class: "team-cell",
                                    div { class: "team-info",
                                        if let Some(photo) = &s.team1_photo {
                                            img { src: "{api::base_url()}/static/{photo}", alt: "{s.team1_name.as_deref().unwrap_or(\"\")}", class: "team-photo" }
                                        }
                                        span { class: "team-name", "{s.team1_name.as_deref().unwrap_or(\"-\")}" }
                                    }
                                }
                                if let Some(sets) = &s.sets {
                                    for set_num in sets.iter() {
                                        {
                                            let score = s
                                                .scores_by_set
                                                .as_ref()
                                                .and_then(|m| m.get(&set_num.to_string()))
                                                .and_then(|v| v.get("team1_score"))
                                                .copied()
                                                .unwrap_or(0);
                                            rsx! { td { class: "score-cell", "{score}" } }
                                        }
                                    }
                                }
                            }
                            tr { class: "team-row",
                                td { class: "team-cell",
                                    div { class: "team-info",
                                        if let Some(photo) = &s.team2_photo {
                                            img { src: "{api::base_url()}/static/{photo}", alt: "{s.team2_name.as_deref().unwrap_or(\"\")}", class: "team-photo" }
                                        }
                                        span { class: "team-name", "{s.team2_name.as_deref().unwrap_or(\"-\")}" }
                                    }
                                }
                                if let Some(sets) = &s.sets {
                                    for set_num in sets.iter() {
                                        {
                                            let score = s
                                                .scores_by_set
                                                .as_ref()
                                                .and_then(|m| m.get(&set_num.to_string()))
                                                .and_then(|v| v.get("team2_score"))
                                                .copied()
                                                .unwrap_or(0);
                                            rsx! { td { class: "score-cell", "{score}" } }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    if let Some(stones) = &s.stones_info {
                        {
                            let pct = if stones.stones_per_set == 0 {
                                0.0
                            } else {
                                let remaining = stones.stones_remaining.unwrap_or(0) as f64;
                                (remaining / stones.stones_per_set as f64) * 100.0
                            };
                            rsx! {
                                div { class: "stones-info",
                                    div { class: "stones-header",
                                        span { "Stones remaining" }
                                        span { class: "stones-count", "{stones.stones_remaining.unwrap_or(0)} / {stones.stones_per_set}" }
                                    }
                                    div { class: "progress-bar-container",
                                        div { class: "progress-bar", style: "width: {pct}%;" }
                                    }
                                }
                            }
                        }
                    }
                }
            } else {
                div { class: "scoreboard-container",
                    table { class: "scoreboard-table",
                        tbody {
                            if let Some(prev) = &s.prev_match {
                                tr { class: "team-row",
                                    td { class: "team-cell",
                                        div { class: "team-info",
                                            span { class: "between-matches-label", "Previous match:" }
                                            if let Some(photo) = &prev.team1_photo {
                                                img { src: "{api::base_url()}/static/{photo}", alt: "{prev.team1_name}", class: "team-photo" }
                                            }
                                            span { class: "team-name",
                                                "{prev.team1_name}"
                                                if prev.winner.as_deref() == Some("TEAM1") {
                                                    span { class: "winner-badge", "Winner" }
                                                }
                                            }
                                            span { class: "vs-text", "vs" }
                                            if let Some(photo) = &prev.team2_photo {
                                                img { src: "{api::base_url()}/static/{photo}", alt: "{prev.team2_name}", class: "team-photo" }
                                            }
                                            span { class: "team-name",
                                                "{prev.team2_name}"
                                                if prev.winner.as_deref() == Some("TEAM2") {
                                                    span { class: "winner-badge", "Winner" }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                            if let Some(next) = &s.next_match {
                                tr { class: "team-row",
                                    td { class: "team-cell",
                                        div { class: "team-info",
                                            span { class: "between-matches-label", "Next match:" }
                                            if let Some(photo) = &next.team1_photo {
                                                img { src: "{api::base_url()}/static/{photo}", alt: "{next.team1_name}", class: "team-photo" }
                                            }
                                            span { class: "team-name", "{next.team1_name}" }
                                            span { class: "vs-text", "vs" }
                                            if let Some(photo) = &next.team2_photo {
                                                img { src: "{api::base_url()}/static/{photo}", alt: "{next.team2_name}", class: "team-photo" }
                                            }
                                            span { class: "team-name", "{next.team2_name}" }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } else if let Some(Err(e)) = val.read().as_ref() {
            div { class: "error-message", "{e}" }
        } else {
            div { class: "error-message", "Loading…" }
        }
    }
}
