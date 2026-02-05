use crate::api;
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn Results(url: String) -> Element {
    let url_for_data = url.clone();
    let data = use_resource(move || {
        let u = url_for_data.clone();
        async move { api::results(&u).await.map_err(|e| e.to_string()) }
    });
    let val = data.value();
    rsx! {
        if let Some(Ok(d)) = val.read().as_ref() {
            h1 { "Results — {d.tournament.name}" }
            Link { to: Route::TournamentHome { url: url.clone() }, "← Tournament" }
            ul { class: "results-list",
                for m in d.matches.iter() {
                    li { key: "{m.uuid}",
                        a {
                            href: "/app/{url}/match?id={m.uuid}",
                            "{m.name}: {m.team1.as_deref().unwrap_or(\"TBD\")} vs {m.team2.as_deref().unwrap_or(\"TBD\")}"
                        }
                        if let Some(w) = &m.match_winner {
                            span { " — Winner: {w}" }
                        }
                    }
                }
            }
        } else if let Some(Err(e)) = val.read().as_ref() {
            p { class: "error", "{e}" }
        } else {
            p { "Loading…" }
        }
    }
}
