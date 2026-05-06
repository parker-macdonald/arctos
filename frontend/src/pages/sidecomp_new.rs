use crate::api;
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn SideCompNew(url: String) -> Element {
    let navigator = use_navigator();
    let mut name = use_signal(String::new);
    let mut type_ = use_signal(|| "DUELING".to_string());
    let mut error = use_signal(|| None::<String>);
    let mut submitting = use_signal(|| false);

    let url_for_back = url.clone();
    let url_for_submit = url.clone();

    rsx! {
        div { class: "row",
            div { class: "col-12",
                h1 { "Create side competition" }
                div { class: "mb-3",
                    Link {
                        to: Route::SideCompsList { url: url_for_back },
                        class: "btn btn-link",
                        "<- Back"
                    }
                }
                form {
                    onsubmit: move |evt| {
                        evt.prevent_default();
                        let url_inner = url_for_submit.clone();
                        let n = name();
                        let t = type_();
                        submitting.set(true);
                        error.set(None);
                        spawn(async move {
                            match api::sidecomp_create(&url_inner, &n, &t, None).await {
                                Ok(_) => {
                                    navigator.push(Route::SideCompsList { url: url_inner });
                                }
                                Err(e) => {
                                    error.set(Some(e));
                                    submitting.set(false);
                                }
                            }
                        });
                    },
                    div { class: "mb-3",
                        label { class: "form-label", "Name" }
                        input {
                            class: "form-control",
                            r#type: "text",
                            value: "{name}",
                            oninput: move |evt| name.set(evt.value()),
                            required: true,
                        }
                    }
                    div { class: "mb-3",
                        label { class: "form-label", "Type" }
                        select {
                            class: "form-select",
                            value: "{type_}",
                            onchange: move |evt| type_.set(evt.value()),
                            option { value: "DUELING", "Dueling" }
                            option { value: "CHAIN_BREAKING", "Chain / Breaking" }
                            option { value: "OTHER", "Other" }
                        }
                    }
                    if let Some(err) = error() {
                        div { class: "alert alert-danger", "{err}" }
                    }
                    button {
                        class: "btn btn-primary",
                        r#type: "submit",
                        disabled: submitting(),
                        "Create"
                    }
                }
            }
        }
    }
}
