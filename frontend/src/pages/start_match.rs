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
pub fn StartMatch(url: String) -> Element {
    let match_id = get_query_param("id");
    rsx! {
        h1 { "Start match" }
        Link { to: Route::Schedule { url: url.clone() }, "← Schedule" }
        if let Some(id) = &match_id {
            p { "Match id: {id}" }
            p { class: "muted", "Use the legacy start-match page to select players and start." }
            a { href: "/{url}/start-match?id={id}", "Open legacy start match" }
        } else {
            p { "Add ?id=<match-uuid> to the URL, or go to Schedule and click Start on a match." }
        }
    }
}
