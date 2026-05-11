use crate::api;
use crate::pages::layout::use_auth_invalidate;
use crate::Route;
use dioxus::prelude::*;

fn get_query_param(name: &str) -> Option<String> {
    #[cfg(target_arch = "wasm32")]
    {
        let window = web_sys::window()?;
        let search = window.location().search().ok()?;
        let params = web_sys::UrlSearchParams::new_with_str(&search).ok()?;
        params.get(name)
    }
    #[cfg(not(target_arch = "wasm32"))]
    {
        let _ = name;
        None
    }
}

fn initial_user_type_from_query() -> String {
    match get_query_param("type").as_deref() {
        Some("team") => "team".to_string(),
        _ => "player".to_string(),
    }
}

fn register_title(user_type: &str) -> String {
    match user_type {
        "team" => "Register as Team".to_string(),
        _ => "Register as Player".to_string(),
    }
}

/// Initial account type from route: None = use query param (default player).
fn resolve_initial_type(account_type: Option<String>) -> String {
    match account_type.as_deref() {
        Some("team") => "team".to_string(),
        Some("player") => "player".to_string(),
        _ => initial_user_type_from_query(),
    }
}

#[component]
pub fn Register() -> Element {
    rsx! { RegisterPage { account_type: None } }
}

#[component]
pub fn RegisterPlayer() -> Element {
    rsx! { RegisterPage { account_type: Some("player".to_string()) } }
}

#[component]
pub fn RegisterTeam() -> Element {
    rsx! { RegisterPage { account_type: Some("team".to_string()) } }
}

#[component]
fn RegisterPage(account_type: Option<String>) -> Element {
    let initial = resolve_initial_type(account_type.clone());
    let mut username = use_signal(|| String::new());
    let mut password = use_signal(|| String::new());
    let mut confirm_password = use_signal(|| String::new());
    let mut name = use_signal(|| String::new());
    let mut user_type = use_signal(move || initial);
    let mut err = use_signal(|| None::<String>);
    let navigator = use_navigator();
    let auth_invalidate = use_auth_invalidate();
    let google_base = format!("{}/_api/auth/google/login", api::base_url());

    rsx! {
        div { class: "row justify-content-center",
            div { class: "col-md-6",
                div { class: "card",
                    div { class: "card-header",
                        div { class: "d-flex justify-content-between align-items-center",
                            h3 { class: "mb-0", "{register_title(&user_type())}" }
                            div { class: "btn-group btn-group-sm", role: "group",
                                Link {
                                    to: Route::RegisterPlayer {},
                                    class: if user_type() == "player" { "btn btn-primary" } else { "btn btn-outline-primary" },
                                    "Player"
                                }
                                Link {
                                    to: Route::RegisterTeam {},
                                    class: if user_type() == "team" { "btn btn-primary" } else { "btn btn-outline-primary" },
                                    "Team"
                                }
                            }
                        }
                    }
                    div { class: "card-body",
                        form {
                            onsubmit: move |ev| {
                                ev.prevent_default();
                                let u = username().clone();
                                let p = password().clone();
                                let cp = confirm_password().clone();
                                let n = name().clone();
                                let t = user_type().clone();
                                if u.is_empty() || p.is_empty() || n.is_empty() {
                                    err.set(Some("Username, password, and display name required".into()));
                                    return;
                                }
                                if p != cp {
                                    err.set(Some("Passwords do not match".into()));
                                    return;
                                }
                                err.set(None);
                                let nav = navigator.clone();
                                let mut auth_invalidate = auth_invalidate;
                                let next = get_query_param("next").filter(|s| s.starts_with('/'));
                                spawn(async move {
                                    match api::register(&u, &p, &n, &t).await {
                                        Ok(_) => {
                                            auth_invalidate.set(auth_invalidate() + 1);
                                            let _ = nav.push(next.as_deref().unwrap_or("/"));
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
                                    pattern: "[a-zA-Z0-9][a-zA-Z0-9_-]*[a-zA-Z0-9]|[a-zA-Z0-9]",
                                }
                                div { class: "form-text",
                                    "This will be your unique identifier. "
                                    strong { "It is permanent." }
                                    " Must be URL-safe: only letters, numbers, hyphens, and underscores. Cannot start or end with hyphen or underscore."
                                }
                            }
                            div { class: "mb-3",
                                label { r#for: "name", class: "form-label", "Display Name" }
                                input {
                                    r#type: "text",
                                    class: "form-control",
                                    id: "name",
                                    name: "name",
                                    value: "{name()}",
                                    oninput: move |ev| name.set(ev.value().clone()),
                                    required: true,
                                }
                                div { class: "form-text", "Your public display name" }
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
                            div { class: "mb-3",
                                label { r#for: "confirm_password", class: "form-label", "Confirm Password" }
                                input {
                                    r#type: "password",
                                    class: "form-control",
                                    id: "confirm_password",
                                    name: "confirm_password",
                                    value: "{confirm_password()}",
                                    oninput: move |ev| confirm_password.set(ev.value().clone()),
                                    required: true,
                                }
                            }
                            div { class: "d-grid",
                                button { r#type: "submit", class: "btn btn-primary", id: "submitBtn", "Register" }
                            }
                        }
                        hr {}
                        div { class: "text-center mb-3",
                            p { class: "text-muted", "Or" }
                        }
                        div { class: "d-grid mb-3",
                            a { href: "{google_base}?type={user_type()}", class: "btn btn-outline-secondary",
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
                            p { "Already have an account? " Link { to: Route::Login {}, "Login here" } }
                            p {
                                "Or register as a "
                                Link { to: Route::RegisterPlayer {}, class: "text-decoration-none", "player" }
                                " or "
                                Link { to: Route::RegisterTeam {}, class: "text-decoration-none", "team" }
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
