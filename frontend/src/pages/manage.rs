use crate::api;
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn Manage(url: String) -> Element {
    let url_for_resource = url.clone();
    let data = use_resource(move || {
        let u = url_for_resource.clone();
        async move { api::tournament_detail(&u).await.map_err(|e| e.to_string()) }
    });
    let val = data.value();
    rsx! {
        h1 { "Manage tournament" }
        Link { to: Route::TournamentHome { url: url.clone() }, "← Tournament home" }
        if let Some(Ok(d)) = val.read().as_ref() {
            p { "Event: {d.tournament.name}" }
            h3 { "Registered teams" }
            ul {
                for t in d.teams_with_counts.iter() {
                    {
                        let line = format!(
                            "{}{} — {} players",
                            t.team_name,
                            t.pseudonym.as_ref().map(|p| format!(" ({})", p)).unwrap_or_default(),
                            t.player_count
                        );
                        rsx! { li { key: "{t.team_id}", "{line}" } }
                    }
                }
            }
            p { class: "muted", "Full manage (payments, deregister) via legacy page." }
            a { href: "/{url}/manage", "Open legacy manage" }
        } else if let Some(Err(e)) = val.read().as_ref() {
            p { class: "error", "{e}" }
        } else {
            p { "Loading…" }
        }
    }
}
