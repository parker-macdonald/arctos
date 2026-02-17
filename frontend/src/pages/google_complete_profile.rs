use crate::api;
use crate::pages::layout::use_auth_invalidate;
use crate::types::GoogleCompleteProfileRequest;
use crate::Route;
use dioxus::prelude::*;
use dioxus::prelude::use_navigator;

fn validate_username(username: &str) -> Result<(), String> {
    let u = username.trim();
    if u.is_empty() {
        return Err("Username is required".into());
    }
    if u.len() > 50 {
        return Err("Username must be 50 characters or less".into());
    }
    let mut chars = u.chars().peekable();
    let first = chars.next().ok_or_else(|| "Username is required".to_string())?;
    let last = u.chars().last().unwrap_or(first);
    let valid_edge = |c: char| c.is_ascii_alphanumeric();
    if !valid_edge(first) || !valid_edge(last) {
        return Err("Username must be URL-safe: only letters, numbers, hyphens, and underscores. Cannot start or end with hyphen or underscore.".into());
    }
    for c in u.chars() {
        if !(c.is_ascii_alphanumeric() || c == '-' || c == '_') {
            return Err("Username must be URL-safe: only letters, numbers, hyphens, and underscores. Cannot start or end with hyphen or underscore.".into());
        }
    }
    Ok(())
}

#[component]
pub fn GoogleCompleteProfile() -> Element {
    let nav = use_navigator();
    let mut auth_invalidate = use_auth_invalidate();
    let mut email = use_signal(|| "".to_string());
    let mut user_type = use_signal(|| "".to_string());
    let mut username = use_signal(|| "".to_string());
    let mut display_name = use_signal(|| "".to_string());
    let mut error = use_signal(|| None::<String>);
    let mut loading = use_signal(|| true);
    let mut username_status = use_signal(|| None::<String>);

    let _fetch = use_resource(move || async move {
        loading.set(true);
        match api::google_complete_profile_info().await {
            Ok(res) => {
                email.set(res.email);
                user_type.set(res.user_type);
                display_name.set(res.suggested_name);
            }
            Err(e) => error.set(Some(e)),
        }
        loading.set(false);
    });

    let on_check_username = move |_| async move {
        let u = username();
        if let Err(msg) = validate_username(&u) {
            username_status.set(Some(msg));
            return;
        }
        match api::check_username(&u).await {
            Ok(res) => {
                if res.available {
                    username_status.set(Some("Username is available".into()));
                } else {
                    username_status.set(Some(res.message));
                }
            }
            Err(e) => username_status.set(Some(e)),
        }
    };

    let onsubmit = move |evt: Event<FormData>| async move {
        evt.prevent_default();
        loading.set(true);
        error.set(None);

        if let Err(msg) = validate_username(&username()) {
            error.set(Some(msg));
            loading.set(false);
            return;
        }
        if display_name().trim().is_empty() {
            error.set(Some("Display name is required".into()));
            loading.set(false);
            return;
        }

        let req = GoogleCompleteProfileRequest {
            username: username(),
            display_name: display_name(),
        };
        match api::google_complete_profile(&req).await {
            Ok(_) => {
                auth_invalidate.set(auth_invalidate() + 1);
                nav.push(Route::Index {});
            }
            Err(e) => {
                error.set(Some(e));
                loading.set(false);
            }
        }
    };

    rsx! {
        div { class: "row justify-content-center",
            div { class: "col-md-6",
                div { class: "card",
                    div { class: "card-header",
                        h3 { class: "mb-0", "Complete Your Profile" }
                        p { class: "mb-0 text-muted",
                            small { "Creating a {user_type()} account" }
                        }
                    }
                    div { class: "card-body",
                        p { class: "text-muted",
                            "You're signing in with Google as "
                            strong { "{email}" }
                            ". Please choose your username and display name to complete your account setup."
                        }
                        if let Some(err) = error() {
                            div { class: "alert alert-danger", "{err}" }
                        }
                        form {
                            onsubmit: onsubmit,
                            div { class: "mb-3",
                                label { class: "form-label", "Username *" }
                                input {
                                    class: "form-control",
                                    "type": "text",
                                    value: "{username}",
                                    oninput: move |e| username.set(e.value()),
                                    onblur: on_check_username,
                                    required: true
                                }
                                div { class: "form-text",
                                    strong { "This is your permanent URL identifier. " }
                                    "Must be URL-safe: only letters, numbers, hyphens, and underscores. Cannot start or end with hyphen or underscore."
                                }
                                if let Some(msg) = username_status() {
                                    div { class: "form-text", "{msg}" }
                                }
                            }
                            div { class: "mb-3",
                                label { class: "form-label", "Display Name *" }
                                input {
                                    class: "form-control",
                                    "type": "text",
                                    value: "{display_name}",
                                    oninput: move |e| display_name.set(e.value()),
                                    required: true
                                }
                                div { class: "form-text", "This is your public display name that others will see." }
                            }
                            div { class: "d-grid",
                                button { class: "btn btn-primary", "type": "submit", disabled: "{loading}", "Create Account" }
                            }
                        }
                    }
                }
            }
        }
    }
}
