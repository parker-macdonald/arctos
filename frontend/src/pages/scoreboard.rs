use crate::api;
use crate::Route;
use dioxus::prelude::*;

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
    let url_for_poll = url.clone();
    let field_for_poll = field.clone();
    let data = use_resource(move || {
        let u = url_for_poll.clone();
        let f = field_for_poll.clone();
        async move {
            match (&u, &f) {
                (u, Some(f)) => api::scoreboard_state(u, f).await.map_err(|e| e.to_string()),
                _ => Err("field query param required".to_string()),
            }
        }
    });
    let val = data.value();
    rsx! {
        h1 { "Scoreboard" }
        Link { to: Route::TournamentHome { url: url.clone() }, "← Tournament home" }
        if field.is_none() {
            p { "Add ?field=<field_name> to the URL." }
        } else if let Some(Ok(s)) = val.read().as_ref() {
            p { "Field: {field.as_deref().unwrap_or(\"\")} — {s.timestamp}" }
            if s.has_active_match {
                if let (Some(t1), Some(t2)) = (&s.team1_name, &s.team2_name) {
                    div { class: "scoreboard-teams",
                        div { class: "team", "{t1}" }
                        div { class: "vs", "vs" }
                        div { class: "team", "{t2}" }
                    }
                }
                if let Some(sets) = &s.scores_by_set {
                    ul { class: "scores-by-set",
                        for (set_num, scores) in sets.iter() {
                            li { key: "{set_num}",
                                "Set {set_num}: {scores.get(\"team1_score\").copied().unwrap_or(0)} - {scores.get(\"team2_score\").copied().unwrap_or(0)}"
                            }
                        }
                    }
                }
                if let Some(stones) = &s.stones_info {
                    p { "Stones: {stones.stones_remaining.unwrap_or(0)} / {stones.stones_per_set} remaining" }
                }
            } else {
                p { "No active match on this field." }
                if let Some(prev) = &s.prev_match {
                    {
                        let prev_line = format!(
                            "Previous: {} vs {}{}",
                            prev.team1_name,
                            prev.team2_name,
                            prev.winner.as_ref().map(|w| format!(" — winner: {}", w)).unwrap_or_default()
                        );
                        rsx! { p { "{prev_line}" } }
                    }
                }
                if let Some(next) = &s.next_match {
                    p { "Next: {next.team1_name} vs {next.team2_name}" }
                }
            }
        } else if let Some(Err(e)) = val.read().as_ref() {
            p { class: "error", "{e}" }
        } else {
            p { "Loading…" }
        }
    }
}
