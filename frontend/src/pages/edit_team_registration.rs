use crate::api;
use crate::types::{UpdateTeamRegistrationRequest};
use dioxus::prelude::*;
use dioxus::prelude::use_navigator;
use crate::Route;

#[component]
pub fn EditTeamRegistration(tournament_url: String) -> Element {
    let nav = use_navigator();
    let mut pseudonym = use_signal(|| "".to_string());
    let mut error = use_signal(|| None::<String>);
    let mut loading = use_signal(|| true);

    let _fetch = use_resource(use_reactive(&tournament_url, move |url| async move {
        loading.set(true);
        match api::get_my_team_registration(&url).await {
            Ok(res) => {
                pseudonym.set(res.registration.pseudonym.unwrap_or_default());
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
            
            let req = UpdateTeamRegistrationRequest {
                pseudonym: Some(pseudonym()),
            };

            match api::update_my_team_registration(&tournament_url, &req).await {
                Ok(_) => {
                    nav.push(Route::TournamentHome { url: tournament_url.clone() });
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
                    h1 { "Edit Team Registration" }
                    nav { "aria-label": "breadcrumb",
                        ol { class: "breadcrumb",
                            li { class: "breadcrumb-item",
                                Link { to: Route::TournamentHome { url: tournament_url.clone() }, "{tournament_url}" }
                            }
                            li { class: "breadcrumb-item active", "Edit Registration" }
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
                div { class: "col-md-8",
                    div { class: "card",
                        div { class: "card-header",
                            h5 { class: "mb-0", "Team Registration" }
                        }
                        div { class: "card-body",
                            if let Some(err) = error() {
                                div { class: "alert alert-danger", "{err}" }
                            }
                            form {
                                onsubmit: onsubmit,
                                div { class: "mb-3",
                                        label { class: "form-label", "Team Name for This Tournament" }
                                        input {
                                            class: "form-control",
                                            "type": "text",
                                            value: "{pseudonym}",
                                            oninput: move |e| pseudonym.set(e.value()),
                                            required: true
                                        }
                                        div { class: "form-text", "This is how your team will be referred to in this tournament" }
                                    }
                                    
                                    div { class: "d-grid gap-2 d-md-flex justify-content-md-end",
                                        Link {
                                            class: "btn btn-outline-secondary",
                                            to: Route::TournamentHome { url: tournament_url.clone() },
                                            "Cancel"
                                        }
                                        button { class: "btn btn-primary", "type": "submit", "Update Registration" }
                                    }
                            }
                        }
                    }
                }
            }
        }
    }
}
