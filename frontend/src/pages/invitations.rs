use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn Invitations(url: String) -> Element {
    rsx! {
        h1 { "Invitations" }
        p { "Tournament: {url}" }
        Link { to: Route::TournamentHome { url: url.clone() }, "← Tournament home" }
        p { class: "muted", "View and respond to invitations via the legacy page." }
        a { href: "/{url}/invitations", "Open legacy invitations" }
    }
}
