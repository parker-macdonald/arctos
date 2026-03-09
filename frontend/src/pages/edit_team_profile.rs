use crate::api;
use crate::components::ChangePasswordCard;
use crate::types::{UpdateTeamProfileRequest};
use dioxus::prelude::*;
use dioxus::prelude::use_navigator;
use crate::Route;

#[component]
pub fn EditTeamProfile(team_id: String) -> Element {
    let nav = use_navigator();
    let mut name = use_signal(|| "".to_string());
    let mut location = use_signal(|| "".to_string());
    let mut email = use_signal(|| "".to_string());
    let mut website = use_signal(|| "".to_string());
    let mut about = use_signal(|| "".to_string());
    let mut profile_photo = use_signal(|| None::<String>);
    let mut error = use_signal(|| None::<String>);
    let mut loading = use_signal(|| true);
    let mut photo_upload_error = use_signal(|| None::<String>);
    let mut photo_uploading = use_signal(|| false);
    let mut photo_removing = use_signal(|| false);

    let me = use_resource(move || async move { api::me().await });

    let _fetch = use_resource(use_reactive(&team_id, move |id| async move {
        loading.set(true);
        match api::team_profile(&id).await {
            Ok(res) => {
                let t = res.team;
                name.set(t.name);
                location.set(t.location.unwrap_or_default());
                email.set(t.email.unwrap_or_default());
                website.set(t.website.unwrap_or_default());
                about.set(t.about.unwrap_or_default());
                profile_photo.set(t.profile_photo);
            }
            Err(e) => error.set(Some(e)),
        }
        loading.set(false);
    }));

    let team_id_for_submit = team_id.clone();
    let team_id_for_remove = team_id.clone();
    let onsubmit = move |_evt: Event<FormData>| {
        let team_id = team_id_for_submit.clone();
        async move {
            loading.set(true);
            error.set(None);
            
            let req = UpdateTeamProfileRequest {
                name: Some(name()),
                location: Some(location()),
                email: Some(email()),
                website: Some(website()),
                about: Some(about()),
            };

            match api::update_team_profile(&team_id, &req).await {
                Ok(_) => {
                    nav.push(Route::TeamProfilePage { id: team_id.clone() });
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
                    h1 { "Edit Team Profile" }
                    nav { "aria-label": "breadcrumb",
                        ol { class: "breadcrumb",
                            li { class: "breadcrumb-item",
                                Link { to: Route::TeamProfilePage { id: team_id.clone() }, "{name}" }
                            }
                            li { class: "breadcrumb-item active", "Edit Profile" }
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
                            h5 { class: "mb-0", "Team Information" }
                        }
                        div { class: "card-body",
                            if let Some(err) = error() {
                                div { class: "alert alert-danger", "{err}" }
                            }
                            if let Some(err) = photo_upload_error() {
                                div { class: "alert alert-warning", "Photo: {err}" }
                            }
                            div { class: "mb-3",
                                label { class: "form-label", "Profile Picture" }
                                if let Some(photo) = profile_photo() {
                                    div { class: "d-flex align-items-center gap-3 mb-2",
                                        img {
                                            src: "{api::base_url()}/static/{photo}",
                                            alt: "Team",
                                            class: "rounded",
                                            style: "width: 80px; height: 80px; object-fit: cover;"
                                        }
                                        div { class: "d-flex flex-column gap-1",
                                            span { class: "text-muted", "Upload a new image to replace." }
                                            button {
                                                class: "btn btn-outline-danger btn-sm align-self-start",
                                                r#type: "button",
                                                disabled: photo_removing(),
                                                onclick: move |_| {
                                                    let tid = team_id_for_remove.clone();
                                                    photo_upload_error.set(None);
                                                    photo_removing.set(true);
                                                    spawn(async move {
                                                        match api::delete_team_profile_photo(&tid).await {
                                                            Ok(()) => profile_photo.set(None),
                                                            Err(e) => photo_upload_error.set(Some(e)),
                                                        }
                                                        photo_removing.set(false);
                                                    });
                                                },
                                                if photo_removing() {
                                                    span { class: "spinner-border spinner-border-sm me-1", role: "status" }
                                                }
                                                "Remove picture"
                                            }
                                        }
                                    }
                                } else {
                                    p { class: "text-muted small mb-2", "No profile picture set." }
                                }
                                input {
                                    class: "form-control",
                                    r#type: "file",
                                    accept: "image/*",
                                    disabled: photo_uploading(),
                                    onchange: move |evt| {
                                        let tid = team_id.clone();
                                        #[cfg(target_arch = "wasm32")]
                                        {
                                            use dioxus::html::HasFileData;
                                            let files = evt.files();
                                            if let Some(file) = files.into_iter().next() {
                                                photo_upload_error.set(None);
                                                photo_uploading.set(true);
                                                spawn(async move {
                                                    match file.read_bytes().await {
                                                        Ok(bytes) => {
                                                            match api::upload_team_profile_photo(&tid, bytes).await {
                                                                Ok(path) => {
                                                                    profile_photo.set(Some(path));
                                                                }
                                                                Err(e) => {
                                                                    photo_upload_error.set(Some(e));
                                                                }
                                                            }
                                                        }
                                                        Err(_) => {
                                                            photo_upload_error.set(Some("Failed to read file".to_string()));
                                                        }
                                                    }
                                                    photo_uploading.set(false);
                                                });
                                            }
                                        }
                                    }
                                }
                                if photo_uploading() {
                                    span { class: "spinner-border spinner-border-sm ms-2", role: "status" }
                                }
                            }
                            form {
                                onsubmit: onsubmit,
                                div { class: "row",
                                        div { class: "col-md-6",
                                            div { class: "mb-3",
                                                label { class: "form-label", "Team Name" }
                                                input {
                                                    class: "form-control",
                                                    "type": "text",
                                                    value: "{name}",
                                                    oninput: move |e| name.set(e.value()),
                                                    required: true
                                                }
                                            }
                                        }
                                        div { class: "col-md-6",
                                            div { class: "mb-3",
                                                label { class: "form-label", "Location" }
                                                input {
                                                    class: "form-control",
                                                    "type": "text",
                                                    value: "{location}",
                                                    oninput: move |e| location.set(e.value())
                                                }
                                            }
                                        }
                                    }
                                    
                                    div { class: "row",
                                        div { class: "col-md-6",
                                            div { class: "mb-3",
                                                label { class: "form-label", "Email" }
                                                input {
                                                    class: "form-control",
                                                    "type": "email",
                                                    value: "{email}",
                                                    oninput: move |e| email.set(e.value())
                                                }
                                            }
                                        }
                                        div { class: "col-md-6",
                                            div { class: "mb-3",
                                                label { class: "form-label", "Website" }
                                                input {
                                                    class: "form-control",
                                                    "type": "url",
                                                    value: "{website}",
                                                    oninput: move |e| website.set(e.value())
                                                }
                                            }
                                        }
                                    }
                                    
                                    div { class: "mb-3",
                                        label { class: "form-label", "About" }
                                        textarea {
                                            class: "form-control",
                                            rows: "4",
                                            value: "{about}",
                                            oninput: move |e| about.set(e.value()),
                                            placeholder: "Tell people about your team"
                                        }
                                    }
                                    
                                    div { class: "d-grid gap-2",
                                        button { class: "btn btn-primary", "type": "submit", "Update Team Profile" }
                                        Link {
                                            class: "btn btn-outline-secondary",
                                            to: Route::TeamProfilePage { id: team_id.clone() },
                                            "Cancel"
                                        }
                                    }
                            }
                        }
                    }

                    if me.read().as_ref().and_then(|r| r.as_ref().ok()).map(|u| u.has_password).unwrap_or(false) {
                        ChangePasswordCard {}
                    }

                }
            }
        }
    }
}
