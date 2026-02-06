use crate::api;
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn TournamentSetup(url: String) -> Element {
    let legacy_url = format!("{}/{}/setup", api::base_url(), url);
    #[cfg(target_arch = "wasm32")]
    {
        let legacy_url = legacy_url.clone();
        use_effect(move || {
            if let Some(window) = web_sys::window() {
                let _ = window.location().set_href(&legacy_url);
            }
        });
    }

    rsx! {
        h1 { "Setup Matches" }
        Link { to: Route::TournamentHome { url: url.clone() }, "← Tournament home" }
        p { "Redirecting to match setup..." }
        a { href: "{legacy_url}", class: "btn btn-outline-primary", "Open setup" }
    }
}
