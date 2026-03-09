//! Change password form card for use on own player/team profile pages.

use crate::api;
use dioxus::prelude::*;

#[component]
pub fn ChangePasswordCard() -> Element {
    let mut current_password = use_signal(|| String::new());
    let mut new_password = use_signal(|| String::new());
    let mut confirm_password = use_signal(|| String::new());
    let mut error = use_signal(|| None::<String>);
    let mut success = use_signal(|| false);
    let mut loading = use_signal(|| false);

    rsx! {
        div { class: "card mt-3",
            div { class: "card-header",
                h5 { class: "mb-0", "Change password" }
            }
            div { class: "card-body",
                if let Some(ref e) = error() {
                    div { class: "alert alert-danger py-2", "{e}" }
                }
                form {
                    onsubmit: move |ev| {
                        ev.prevent_default();
                        let cur = current_password().trim().to_string();
                        let new_pw = new_password().trim().to_string();
                        let conf = confirm_password().trim().to_string();
                        if cur.is_empty() {
                            error.set(Some("Current password is required.".into()));
                            return;
                        }
                        if new_pw != conf {
                            error.set(Some("New password and confirmation do not match.".into()));
                            return;
                        }
                        error.set(None);
                        loading.set(true);
                        let mut loading_sig = loading;
                        let mut error_sig = error;
                        let mut success_sig = success;
                        let mut cur_sig = current_password;
                        let mut new_sig = new_password;
                        let mut conf_sig = confirm_password;
                        spawn(async move {
                            match api::change_password(&cur, &new_pw).await {
                                Ok(()) => {
                                    success_sig.set(true);
                                    cur_sig.set(String::new());
                                    new_sig.set(String::new());
                                    conf_sig.set(String::new());
                                }
                                Err(e) => error_sig.set(Some(e)),
                            }
                            loading_sig.set(false);
                        });
                    },
                    div { class: "mb-2",
                        label { class: "form-label", "Current password" }
                        input {
                            class: "form-control",
                            r#type: "password",
                            placeholder: "Current password",
                            value: "{current_password()}",
                            oninput: move |ev| current_password.set(ev.value().clone()),
                            disabled: loading(),
                        }
                    }
                    div { class: "mb-2",
                        label { class: "form-label", "New password" }
                        input {
                            class: "form-control",
                            r#type: "password",
                            placeholder: "New password",
                            value: "{new_password()}",
                            oninput: move |ev| new_password.set(ev.value().clone()),
                            disabled: loading(),
                        }
                    }
                    div { class: "mb-3",
                        label { class: "form-label", "Confirm new password" }
                        input {
                            class: "form-control",
                            r#type: "password",
                            placeholder: "Confirm new password",
                            value: "{confirm_password()}",
                            oninput: move |ev| confirm_password.set(ev.value().clone()),
                            disabled: loading(),
                        }
                    }
                    button {
                        class: "btn btn-primary",
                        r#type: "submit",
                        disabled: loading(),
                        if loading() { "Changing…" } else { "Change password" }
                    }
                }
                if success() {
                    p { class: "text-success mb-0 mt-3", "Password changed successfully." }
                }
            }
        }
    }
}
