use crate::api;
use crate::components::ChangePasswordCard;
use crate::types::{UpdatePlayerProfileRequest};
use dioxus::prelude::*;
use dioxus::prelude::use_navigator;
use crate::Route;

#[component]
pub fn EditPlayerProfile(player_id: String) -> Element {
    let nav = use_navigator();
    let mut name = use_signal(|| "".to_string());
    let mut phone = use_signal(|| "".to_string());
    let mut location = use_signal(|| "".to_string());
    let mut bio = use_signal(|| "".to_string());
    let mut profile_photo = use_signal(|| None::<String>);
    let mut error = use_signal(|| None::<String>);
    let mut loading = use_signal(|| true);
    let mut photo_upload_error = use_signal(|| None::<String>);
    let mut photo_uploading = use_signal(|| false);
    let mut photo_removing = use_signal(|| false);

    let _fetch = use_resource(use_reactive(&player_id, move |id| async move {
        loading.set(true);
        match api::player_profile(&id).await {
            Ok(res) => {
                let p = res.player;
                name.set(p.name);
                phone.set(p.phone.unwrap_or_default());
                location.set(p.location.unwrap_or_default());
                bio.set(p.bio.unwrap_or_default());
                profile_photo.set(p.profile_photo);
            }
            Err(e) => error.set(Some(e)),
        }
        loading.set(false);
    }));

    let player_id_for_submit = player_id.clone();
    let player_id_for_remove = player_id.clone();
    let onsubmit = move |_evt: Event<FormData>| {
        let player_id = player_id_for_submit.clone();
        async move {
            loading.set(true);
            error.set(None);
            
            let req = UpdatePlayerProfileRequest {
                name: Some(name()),
                phone: Some(phone()),
                location: Some(location()),
                bio: Some(bio()),
            };

            match api::update_player_profile(&player_id, &req).await {
                Ok(_) => {
                    nav.push(Route::PlayerProfilePage { id: player_id.clone() });
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
                    h1 { "Edit Player Profile" }
                    nav { "aria-label": "breadcrumb",
                        ol { class: "breadcrumb",
                            li { class: "breadcrumb-item",
                                Link { to: Route::PlayerProfilePage { id: player_id.clone() }, "{name}" }
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
                div { class: "col-md-6",
                    div { class: "card",
                        div { class: "card-header",
                            h5 { class: "mb-0", "Player Information" }
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
                                            alt: "Profile",
                                            class: "rounded-circle",
                                            style: "width: 80px; height: 80px; object-fit: cover;"
                                        }
                                        div { class: "d-flex flex-column gap-1",
                                            span { class: "text-muted", "Upload a new image to replace." }
                                            button {
                                                class: "btn btn-outline-danger btn-sm align-self-start",
                                                r#type: "button",
                                                disabled: photo_removing(),
                                                onclick: move |_| {
                                                    let pid = player_id_for_remove.clone();
                                                    photo_upload_error.set(None);
                                                    photo_removing.set(true);
                                                    spawn(async move {
                                                        match api::delete_player_profile_photo(&pid).await {
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
                                        let pid = player_id.clone();
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
                                                            match api::upload_player_profile_photo(&pid, bytes).await {
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
                                div { class: "mb-3",
                                        label { class: "form-label", "Display Name" }
                                        input {
                                            class: "form-control",
                                            "type": "text",
                                            value: "{name}",
                                            oninput: move |e| name.set(e.value()),
                                            required: true
                                        }
                                    }
                                    
                                    div { class: "mb-3",
                                        label { class: "form-label", "Phone Number" }
                                        input {
                                            class: "form-control",
                                            "type": "text",
                                            value: "{phone}",
                                            oninput: move |e| phone.set(e.value())
                                        }
                                        div { class: "form-text", "Optional - for notifications (not public)" }
                                    }
                                    
                                    div { class: "mb-3",
                                        label { class: "form-label", "Location" }
                                        input {
                                            class: "form-control",
                                            "type": "text",
                                            value: "{location}",
                                            oninput: move |e| location.set(e.value()),
                                            placeholder: "e.g., Seattle, WA"
                                        }
                                        div { class: "form-text", "Optional - your general location" }
                                    }
                                    
                                    div { class: "mb-3",
                                        label { class: "form-label", "Bio" }
                                        textarea {
                                            class: "form-control",
                                            rows: "3",
                                            value: "{bio}",
                                            oninput: move |e| bio.set(e.value()),
                                            placeholder: "Tell us about yourself..."
                                        }
                                        div { class: "form-text", "Optional - a brief description about yourself" }
                                    }
                                    
                                    div { class: "d-grid gap-2",
                                        button { class: "btn btn-primary", "type": "submit", "Update Profile" }
                                        Link {
                                            class: "btn btn-outline-secondary",
                                            to: Route::PlayerProfilePage { id: player_id.clone() },
                                            "Cancel"
                                        }
                                    }
                            }
                        }
                    }

                    ChangePasswordCard {}

                }
            }
        }
    }
}
