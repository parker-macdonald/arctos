use crate::api;
use dioxus::prelude::*;

fn sidecomps_tab_href(url: &str) -> String {
    format!("/{url}?tab=sidecomps")
}

#[component]
pub fn SideCompNew(url: String) -> Element {
    let mut name = use_signal(String::new);
    let mut type_ = use_signal(|| "DUELING".to_string());
    let mut description = use_signal(String::new);
    let mut error = use_signal(|| None::<String>);
    let mut submitting = use_signal(|| false);

    let back_href = sidecomps_tab_href(&url);
    let url_for_submit = url.clone();

    rsx! {
        div { class: "row",
            div { class: "col-12",
                h1 { "Create side competition" }
                div { class: "mb-3",
                    a {
                        href: "{back_href}",
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
                        let d = description();
                        let d_opt = if d.trim().is_empty() { None } else { Some(d) };
                        submitting.set(true);
                        error.set(None);
                        spawn(async move {
                            match api::sidecomp_create(&url_inner, &n, &t, d_opt.as_deref()).await {
                                Ok(_) => {
                                    if let Some(window) = web_sys::window() {
                                        let _ = window.location().assign(&sidecomps_tab_href(&url_inner));
                                    }
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
                    div { class: "mb-3",
                        label { class: "form-label", "Description" }
                        textarea {
                            class: "form-control",
                            rows: "4",
                            value: "{description}",
                            oninput: move |evt| description.set(evt.value()),
                        }
                        div { class: "form-text", "Optional. Shown on the side competition page." }
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
