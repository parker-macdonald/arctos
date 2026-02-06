use crate::api;
use crate::types::{UpdateFieldRequest};
use dioxus::prelude::*;
use dioxus::prelude::use_navigator;
use crate::Route;

#[component]
pub fn EditField(tournament_url: String, field_id: u32) -> Element {
    let nav = use_navigator();
    let mut name = use_signal(|| "".to_string());
    let mut camera_urls = use_signal(|| vec!["".to_string()]);
    let mut error = use_signal(|| None::<String>);
    let mut loading = use_signal(|| true);

    let _fetch = use_resource(use_reactive((&tournament_url, &field_id), move |(url, id)| async move {
        loading.set(true);
        match api::get_field(&url, id).await {
            Ok(f) => {
                name.set(f.name);
                if f.camera_urls.is_empty() {
                    camera_urls.set(vec!["".to_string()]);
                } else {
                    camera_urls.set(f.camera_urls);
                }
            }
            Err(e) => error.set(Some(e)),
        }
        loading.set(false);
    }));

    let tournament_url_for_submit = tournament_url.clone();
    let onsubmit = move |evt: Event<FormData>| {
        let tournament_url = tournament_url_for_submit.clone();
        async move {
            loading.set(true);
            error.set(None);
            
            let req = UpdateFieldRequest {
                name: name(),
                camera_urls: camera_urls().iter().filter(|s| !s.trim().is_empty()).cloned().collect(),
            };

            match api::update_field(&tournament_url, field_id, &req).await {
                Ok(_) => {
                    nav.push(Route::TournamentSetup { url: tournament_url.clone() });
                }
                Err(e) => {
                    error.set(Some(e));
                    loading.set(false);
                }
            }
        }
    };

    rsx! {
        div { class: "row",
                div { class: "col-12",
                    h1 { "Edit Field" }
                    nav { "aria-label": "breadcrumb",
                        ol { class: "breadcrumb",
                            li { class: "breadcrumb-item",
                                Link { to: Route::TournamentHome { url: tournament_url.clone() }, "{tournament_url}" }
                            }
                            li { class: "breadcrumb-item",
                                Link { to: Route::TournamentSetup { url: tournament_url.clone() }, "Setup" }
                            }
                            li { class: "breadcrumb-item active", "Edit Field" }
                        }
                    }
                }
            }
            
        if loading() {
            div { class: "d-flex justify-content-center",
                div { class: "spinner-border", role: "status",
                    span { class: "visually-hidden", "Loading..." }
                }
            }
        } else {
            div { class: "row justify-content-center",
                div { class: "col-md-6",
                    div { class: "card",
                        div { class: "card-header",
                            h5 { class: "mb-0", "Field Information" }
                        }
                        div { class: "card-body",
                            if let Some(err) = error() {
                                div { class: "alert alert-danger", "{err}" }
                            }
                            form {
                                onsubmit: onsubmit,
                                div { class: "mb-3",
                                    label { class: "form-label", "Field Name" }
                                    input {
                                        class: "form-control",
                                        "type": "text",
                                        value: "{name}",
                                        oninput: move |e| name.set(e.value()),
                                        required: true
                                    }
                                }
                                
                                div { class: "mb-3",
                                    label { class: "form-label", "Camera/Stream URLs" }
                                    div {
                                        for (i, url) in camera_urls().iter().enumerate() {
                                            div { class: "input-group mb-2", key: "{i}",
                                                input {
                                                    class: "form-control",
                                                    "type": "text",
                                                    value: "{url}",
                                                    placeholder: "(Optional) YouTube stream URL",
                                                    oninput: move |e| {
                                                        let mut urls = camera_urls();
                                                        urls[i] = e.value();
                                                        camera_urls.set(urls);
                                                    }
                                                }
                                                button {
                                                    class: "btn btn-outline-danger",
                                                    "type": "button",
                                                    onclick: move |_| {
                                                        let mut urls = camera_urls();
                                                        urls.remove(i);
                                                        if urls.is_empty() {
                                                            urls.push("".to_string());
                                                        }
                                                        camera_urls.set(urls);
                                                    },
                                                    i { class: "bi bi-x" }
                                                }
                                            }
                                        }
                                        button {
                                            class: "btn btn-sm btn-outline-secondary",
                                            "type": "button",
                                            onclick: move |_| {
                                                let mut urls = camera_urls();
                                                urls.push("".to_string());
                                                camera_urls.set(urls);
                                            },
                                            i { class: "bi bi-plus" }
                                            " Add Another Camera"
                                        }
                                    }
                                    div { class: "form-text mt-2",
                                        "Go to share → Embed and get the link inside "
                                        code { "src=\"...\"" }
                                        "."
                                    }
                                }
                                
                                div { class: "d-grid gap-2",
                                    button { class: "btn btn-primary", "type": "submit", "Update Field" }
                                    Link {
                                        class: "btn btn-outline-secondary",
                                        to: Route::TournamentSetup { url: tournament_url.clone() },
                                        "Cancel"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
