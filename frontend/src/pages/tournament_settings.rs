use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn TournamentSettings(url: String) -> Element {
    rsx! {
        h1 { "Tournament settings" }
        p { "Tournament: {url}" }
        Link { to: Route::TournamentHome { url: url.clone() }, "← Tournament home" }
        p { class: "muted", "Edit settings via the legacy page." }
        a { href: "/{url}/settings", "Open legacy settings" }
    }
}
