use crate::api;
use crate::types::GoogleChooseAccountTypeRequest;
use crate::Route;
use dioxus::prelude::*;
use dioxus::prelude::use_navigator;

#[component]
pub fn GoogleChooseAccountType() -> Element {
    let nav = use_navigator();
    let mut email = use_signal(|| "".to_string());
    let mut user_type = use_signal(|| "player".to_string());
    let mut error = use_signal(|| None::<String>);
    let mut loading = use_signal(|| true);

    let _fetch = use_resource(move || async move {
        loading.set(true);
        match api::google_choose_account_type_info().await {
            Ok(res) => {
                email.set(res.email);
            }
            Err(e) => error.set(Some(e)),
        }
        loading.set(false);
    });

    let onsubmit = move |evt: Event<FormData>| async move {
        evt.prevent_default();
        loading.set(true);
        error.set(None);
        let req = GoogleChooseAccountTypeRequest {
            user_type: user_type(),
        };
        match api::google_choose_account_type(&req).await {
            Ok(_) => {
                nav.push(Route::GoogleCompleteProfile {});
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
                        h3 { class: "mb-0", "Choose Account Type" }
                    }
                    div { class: "card-body",
                        p { class: "text-muted",
                            "You're signing in with Google as "
                            strong { "{email}" }
                            ". Please choose whether you'd like to create a Player or Team account."
                        }
                        if let Some(err) = error() {
                            div { class: "alert alert-danger", "{err}" }
                        }
                        form {
                            onsubmit: onsubmit,
                            div { class: "mb-3",
                                div { class: "btn-group-vertical w-100", role: "group",
                                    input {
                                        class: "btn-check",
                                        "type": "radio",
                                        name: "user_type",
                                        id: "user_type_player",
                                        value: "player",
                                        checked: user_type() == "player",
                                        onchange: move |_| user_type.set("player".to_string())
                                    }
                                    label { class: "btn btn-outline-primary btn-lg", r#for: "user_type_player",
                                        strong { "Player" }
                                        br {}
                                        small { "For individual players" }
                                    }

                                    input {
                                        class: "btn-check",
                                        "type": "radio",
                                        name: "user_type",
                                        id: "user_type_team",
                                        value: "team",
                                        checked: user_type() == "team",
                                        onchange: move |_| user_type.set("team".to_string())
                                    }
                                    label { class: "btn btn-outline-primary btn-lg", r#for: "user_type_team",
                                        strong { "Team" }
                                        br {}
                                        small { "For teams/organizations" }
                                    }
                                }
                            }
                            div { class: "d-grid",
                                button { class: "btn btn-primary btn-lg", "type": "submit", disabled: "{loading}", "Continue" }
                            }
                        }
                    }
                }
            }
        }
    }
}
