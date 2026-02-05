use crate::api;
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn TournamentRegister(url: String) -> Element {
    let url_for_resource = url.clone();
    let data = use_resource(move || {
        let u = url_for_resource.clone();
        async move { api::tournament_detail(&u).await.map_err(|e| e.to_string()) }
    });
    let val = data.value();
    rsx! {
        h1 { "Register for tournament" }
        Link { to: Route::TournamentHome { url: url.clone() }, "← Tournament home" }
        if let Some(Ok(d)) = val.read().as_ref() {
            p { "Event: {d.tournament.name}" }
            if d.is_current_team_registered {
                p { class: "success", "Your team is registered." }
            }
            if d.is_current_player_registered {
                p { class: "success", "You are registered (player)." }
            }
            if !d.is_current_team_registered && !d.is_current_player_registered {
                p { "Register via the legacy page." }
                a { href: "/{url}/register", "Open legacy registration" }
            }
        } else if let Some(Err(e)) = val.read().as_ref() {
            p { class: "error", "{e}" }
        } else {
            p { "Loading…" }
        }
    }
}
