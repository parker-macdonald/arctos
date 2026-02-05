use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn TournamentSetup(url: String) -> Element {
    rsx! {
        h1 { "Schedule setup" }
        p { "Tournament: {url}" }
        Link { to: Route::TournamentHome { url: url.clone() }, "← Tournament home" }
        p { class: "muted", "Add matches, fields, and manage schedule via the legacy page." }
        a { href: "/{url}/setup", "Open legacy setup" }
    }
}
