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
    let url_for_camera = url.clone();
    let field_for_camera = field.clone();
    let camera_result = use_resource(move || {
        let u = url_for_camera.clone();
        let f = field_for_camera.clone();
        async move {
            match (&u, &f) {
                (u, Some(f)) => api::camera_url(u, f).await,
                _ => Err("field param required".to_string()),
            }
        }
    });
    let val = camera_result.value();
    rsx! {
        h1 { "Record (field)" }
        Link { to: Route::TournamentHome { url: url.clone() }, "← Tournament home" }
        if field.is_none() {
            p { "Add ?field=<field_name> to the URL. Recording requires a camera URL with key from the legacy record page." }
            a { href: "/{url}/record", "Open legacy record (with field and key)" }
        } else if let Some(Ok(camera_url)) = val.read().as_ref() {
            p { "Field: {field.as_deref().unwrap_or(\"\")}" }
            p { "Recording URL (open in new tab or use legacy page for full UI):" }
            a { href: "{camera_url}", target: "_blank", rel: "noopener", "{camera_url}" }
        } else if let Some(Err(e)) = val.read().as_ref() {
            p { class: "error", "{e}" }
            a { href: "/{url}/record", "Open legacy record" }
        } else {
            p { "Loading camera URL…" }
        }
    }
}
