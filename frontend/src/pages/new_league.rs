use crate::api;
use crate::url_slug::{is_valid_url_slug, URL_SLUG_ALLOWED_HINT};
use crate::Route;
use dioxus::prelude::*;
use wasm_bindgen::JsCast;

fn get_form_value(id: &str) -> String {
    let doc = web_sys::window().and_then(|w| w.document()).unwrap();
    doc.get_element_by_id(id)
        .and_then(|e| e.dyn_into::<web_sys::HtmlInputElement>().ok())
        .map(|e| e.value())
        .unwrap_or_default()
}

#[component]
pub fn NewLeague() -> Element {
    let navigator = use_navigator();
    let mut error = use_signal(|| None::<String>);

    rsx! {
        div { class: "row justify-content-center",
            div { class: "col-md-8",
                div { class: "card",
                    div { class: "card-header",
                        h3 { class: "mb-0", "Create New League" }
                    }
                    div { class: "card-body",
                        if let Some(ref err) = error() {
                            div { class: "alert alert-danger mb-3", "{err}" }
                        }
                        form {
                            onsubmit: move |ev| {
                                ev.prevent_default();
                                error.set(None);
                                let league_name = get_form_value("league_name").trim().to_string();
                                let league_url = get_form_value("league_url").trim().to_string();
                                if league_name.is_empty() || league_url.is_empty() {
                                    error.set(Some("League name and URL slug are required.".to_string()));
                                    return;
                                }
                                if !is_valid_url_slug(&league_url) {
                                    error.set(Some(URL_SLUG_ALLOWED_HINT.to_string()));
                                    return;
                                }
                                let nav = navigator.clone();
                                spawn(async move {
                                    match api::create_league(&league_name, &league_url).await {
                                        Ok(res) if res.success => {
                                            if let Some(lu) = res.league_url {
                                                nav.push(Route::LeagueHome { league_url: lu });
                                            } else {
                                                error.set(Some("League created but no URL returned.".to_string()));
                                            }
                                        }
                                        Ok(res) => {
                                            error.set(Some(res.error.unwrap_or_else(|| "Creation failed.".to_string())));
                                        }
                                        Err(e) => {
                                            error.set(Some(e));
                                        }
                                    }
                                });
                            },
                            div { class: "mb-3",
                                label { r#for: "league_name", class: "form-label", "League Name" }
                                input { r#type: "text", class: "form-control", id: "league_name", name: "league_name", required: true }
                                div { class: "form-text", "e.g. CAJA NorCal 2025" }
                            }
                            div { class: "mb-3",
                                label { r#for: "league_url", class: "form-label", "League URL Slug" }
                                input {
                                    r#type: "text",
                                    class: "form-control",
                                    id: "league_url",
                                    name: "league_url",
                                    required: true,
                                    pattern: r"[A-Za-z0-9\.\_\~\-]+",
                                    title: URL_SLUG_ALLOWED_HINT,
                                }
                                div { class: "form-text", "Used in the URL, e.g. /leagues/norcal-2025. {URL_SLUG_ALLOWED_HINT}" }
                            }
                            div { class: "d-grid",
                                button { r#type: "submit", class: "btn btn-primary", "Create League" }
                            }
                        }
                    }
                }
            }
        }
    }
}
