use crate::api;
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

fn get_form_check(id: &str) -> bool {
    let doc = web_sys::window().and_then(|w| w.document()).unwrap();
    doc.get_element_by_id(id)
        .and_then(|e| e.dyn_into::<web_sys::HtmlInputElement>().ok())
        .map(|e| e.checked())
        .unwrap_or(false)
}

#[component]
pub fn NewTournament() -> Element {
    let navigator = use_navigator();
    let mut error = use_signal(|| None::<String>);

    rsx! {
        div { class: "row justify-content-center",
            div { class: "col-md-8",
                div { class: "card",
                    div { class: "card-header",
                        h3 { class: "mb-0", "Create New Tournament" }
                    }
                    div { class: "card-body",
                        if let Some(ref err) = error() {
                            div { class: "alert alert-danger mb-3", "{err}" }
                        }
                        form {
                            onsubmit: move |ev| {
                                ev.prevent_default();
                                error.set(None);
                                let name = get_form_value("name");
                                let url_slug = get_form_value("url");
                                if name.is_empty() || url_slug.is_empty() {
                                    error.set(Some("Name and URL slug are required.".to_string()));
                                    return;
                                }
                                let nav = navigator.clone();
                                spawn(async move {
                                    match api::create_tournament(&name, &url_slug, None).await {
                                        Ok(res) if res.success => {
                                            if let Some(url) = res.url {
                                                nav.push(Route::TournamentHome { url });
                                            } else {
                                                error.set(Some("Tournament created but no URL returned.".to_string()));
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
                                label { r#for: "name", class: "form-label", "Tournament Name" }
                                input { r#type: "text", class: "form-control", id: "name", name: "name", required: true }
                            }
                            div { class: "mb-3",
                                label { r#for: "url", class: "form-label", "URL Slug" }
                                input { r#type: "text", class: "form-control", id: "url", name: "url", required: true }
                                div { class: "form-text", "This will be used in the URL (e.g., /my-tournament)" }
                            }
                            div { class: "d-grid",
                                button { r#type: "submit", class: "btn btn-primary", "Create Tournament" }
                            }
                        }
                    }
                }
            }
        }
    }
}
