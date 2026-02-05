use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn Bracket(url: String) -> Element {
    rsx! {
        h1 { "Bracket" }
        p { "Tournament: {url}" }
        Link { to: Route::TournamentHome { url: url.clone() }, "← Tournament home" }
        p { class: "muted", "Bracket view: use the legacy bracket page for full editing." }
        a { href: "/{url}/bracket", "Open legacy bracket" }
    }
}
