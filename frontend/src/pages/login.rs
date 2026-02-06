use crate::api;
use crate::pages::layout::use_auth_invalidate;
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn Login() -> Element {
    let mut username = use_signal(|| String::new());
    let mut password = use_signal(|| String::new());
    let mut err = use_signal(|| None::<String>);
    let navigator = use_navigator();
    let auth_invalidate = use_auth_invalidate();
    let google_url = format!("{}/auth/google/login", api::base_url());

    rsx! {
        div { class: "row justify-content-center",
            div { class: "col-md-6",
                div { class: "card",
                    div { class: "card-header",
                        h3 { class: "mb-0", "Login" }
                    }
                    div { class: "card-body",
                        form {
                            onsubmit: move |ev| {
                                ev.prevent_default();
                                let u = username().clone();
                                let p = password().clone();
                                if u.is_empty() || p.is_empty() {
                                    err.set(Some("Username and password required".into()));
                                    return;
                                }
                                err.set(None);
                                let nav = navigator.clone();
                                let mut auth_invalidate = auth_invalidate;
                                spawn(async move {
                                    match api::login(&u, &p).await {
                                        Ok(_) => {
                                            auth_invalidate.set(auth_invalidate() + 1);
                                            let _ = nav.push("/");
                                        }
                                        Err(e) => err.set(Some(e)),
                                    }
                                });
                            },
                            div { class: "mb-3",
                                label { r#for: "username", class: "form-label", "Username" }
                                input {
                                    r#type: "text",
                                    class: "form-control",
                                    id: "username",
                                    name: "username",
                                    value: "{username()}",
                                    oninput: move |ev| username.set(ev.value().clone()),
                                    required: true,
                                }
                                div { class: "form-text", "Enter your username (works for both players and teams)" }
                            }
                            div { class: "mb-3",
                                label { r#for: "password", class: "form-label", "Password" }
                                input {
                                    r#type: "password",
                                    class: "form-control",
                                    id: "password",
                                    name: "password",
                                    value: "{password()}",
                                    oninput: move |ev| password.set(ev.value().clone()),
                                    required: true,
                                }
                            }
                            div { class: "d-grid",
                                button { r#type: "submit", class: "btn btn-primary", "Login" }
                            }
                        }
                        hr {}
                        div { class: "text-center mb-3",
                            p { class: "text-muted", "Or" }
                        }
                        div { class: "d-grid mb-3",
                            a { href: "{google_url}", class: "btn btn-outline-secondary",
                                span { style: "margin-right: 8px; vertical-align: middle; display: inline-block; width: 18px; height: 18px;",
                                    svg { width: "18", height: "18", view_box: "0 0 18 18",
                                        path { fill: "#4285F4", d: "M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z" }
                                        path { fill: "#34A853", d: "M9 18c2.43 0 4.467-.806 5.96-2.184l-2.908-2.258c-.806.54-1.837.86-3.052.86-2.347 0-4.33-1.585-5.04-3.715H.957v2.332C2.438 15.983 5.482 18 9 18z" }
                                        path { fill: "#FBBC05", d: "M3.96 10.703c-.18-.54-.282-1.117-.282-1.703s.102-1.163.282-1.703V4.965H.957C.348 6.175 0 7.55 0 9s.348 2.825.957 4.035l3.003-2.332z" }
                                        path { fill: "#EA4335", d: "M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0 5.482 0 2.438 2.017.957 4.965L3.96 7.297C4.67 5.167 6.653 3.58 9 3.58z" }
                                    }
                                }
                                "Sign in with Google"
                            }
                        }
                        hr {}
                        div { class: "text-center",
                            p {
                                "Don't have an account? "
                                a { href: "/app/register?type=player", "Register as Player" }
                                " or "
                                a { href: "/app/register?type=team", "Register as Team" }
                            }
                        }
                        if let Some(e) = err.read().as_ref() {
                            div { class: "alert alert-danger mt-3 mb-0", "{e}" }
                        }
                    }
                }
            }
        }
    }
}
