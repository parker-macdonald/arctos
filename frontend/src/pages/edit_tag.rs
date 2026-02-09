use crate::api;
use crate::types::{UpdateTagRequest};
use dioxus::prelude::*;
use dioxus::prelude::use_navigator;
use crate::Route;

#[component]
pub fn EditTag(tournament_url: String, tag_id: u32) -> Element {
    let nav = use_navigator();
    let mut name = use_signal(|| "".to_string());
    let mut error = use_signal(|| None::<String>);
    let mut loading = use_signal(|| true);

    let _fetch = use_resource(use_reactive((&tournament_url, &tag_id), move |(url, id)| async move {
        loading.set(true);
        match api::get_tag(&url, id).await {
            Ok(t) => {
                name.set(t.name);
            }
            Err(e) => error.set(Some(e)),
        }
        loading.set(false);
    }));

    let tournament_url_for_submit = tournament_url.clone();
    let onsubmit = move |_evt: Event<FormData>| {
        let tournament_url = tournament_url_for_submit.clone();
        async move {
            loading.set(true);
            error.set(None);
            
            let req = UpdateTagRequest {
                name: name(),
            };

            match api::update_tag(&tournament_url, tag_id, &req).await {
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
                    h1 { "Edit Tag" }
                    nav { "aria-label": "breadcrumb",
                        ol { class: "breadcrumb",
                            li { class: "breadcrumb-item",
                                Link { to: Route::TournamentHome { url: tournament_url.clone() }, "{tournament_url}" }
                            }
                            li { class: "breadcrumb-item",
                                Link { to: Route::TournamentSetup { url: tournament_url.clone() }, "Setup" }
                            }
                            li { class: "breadcrumb-item active", "Edit Tag" }
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
                            h5 { class: "mb-0", "Tag Information" }
                        }
                        div { class: "card-body",
                            if let Some(err) = error() {
                                div { class: "alert alert-danger", "{err}" }
                            }
                            form {
                                onsubmit: onsubmit,
                                div { class: "mb-3",
                                    label { class: "form-label", "Tag Name" }
                                    input {
                                        class: "form-control",
                                        "type": "text",
                                        value: "{name}",
                                        oninput: move |e| name.set(e.value()),
                                        required: true,
                                        maxlength: "50"
                                    }
                                }
                                
                                div { class: "d-grid gap-2",
                                    button { class: "btn btn-primary", "type": "submit", "Update Tag" }
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
