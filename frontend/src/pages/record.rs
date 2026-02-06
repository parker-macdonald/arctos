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
pub fn Record(url: String) -> Element {
    let field = get_query_param("field");
    let legacy_url = field
        .as_deref()
        .map(|f| format!("{}/{}/record?field={}", api::base_url(), url, f))
        .unwrap_or_else(|| format!("{}/{}/record", api::base_url(), url));
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
        h1 { "Record" }
        Link { to: Route::TournamentHome { url: url.clone() }, "← Tournament home" }
        p { "Redirecting to recording page..." }
        a { href: "{legacy_url}", class: "btn btn-outline-primary", "Open record" }
    }
}
