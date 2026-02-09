use crate::api;
use crate::Route;
use dioxus::prelude::*;

/// Signal bumped when login/logout succeeds so the layout refetches user.
pub fn use_auth_invalidate() -> Signal<u32> {
    use_context::<Signal<u32>>()
}

#[component]
pub fn Layout() -> Element {
    let auth_version = use_signal(|| 0u32);
    provide_context(auth_version);

    let user = use_resource(move || {
        let av = auth_version;
        async move {
            let _ = av();
            api::me().await
        }
    });
    let mut user_dropdown_open = use_signal(|| false);
    let mut register_dropdown_open = use_signal(|| false);
    let navigator = use_navigator();

    rsx! {
        link { rel: "stylesheet", href: "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" }
        link { rel: "stylesheet", href: "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" }
        style { r#"
            .navbar-brand {{ font-weight: bold; }}
            .tournament-card {{ margin-bottom: 1rem; }}
            .status-badge {{ font-size: 0.8em; }}
            .container-wide {{ max-width: 1600px; margin-left: auto; margin-right: auto; padding-left: 15px; padding-right: 15px; width: 100%; }}
            .error {{ color: var(--bs-danger); }}
            .muted {{ color: var(--bs-secondary); }}
            .layout-nav .nav-link {{ color: rgba(255,255,255,.85) !important; }}
            .layout-nav .nav-link:hover {{ color: #fff !important; }}
            .dropdown-menu {{ position: absolute; z-index: 1050; }}
        "# }

        nav { class: "navbar navbar-expand-lg navbar-dark bg-dark",
            div { class: "container",
                Link { to: Route::Index {}, class: "navbar-brand", "Home" }
                button {
                    class: "navbar-toggler",
                    r#type: "button",
                    "data-bs-toggle": "collapse",
                    "data-bs-target": "#navbarNav",
                    span { class: "navbar-toggler-icon" }
                }
                div { class: "collapse navbar-collapse", id: "navbarNav",
                    ul { class: "navbar-nav me-auto",
                        li { class: "nav-item",
                            Link { to: Route::TeamsList {}, class: "nav-link", "Teams" }
                        }
                        li { class: "nav-item",
                            Link { to: Route::PlayersList {}, class: "nav-link", "Players" }
                        }
                        li { class: "nav-item",
                            Link { to: Route::Stones {}, class: "nav-link", "Stones" }
                        }
                        if let Some(Ok(_u)) = user.read().as_ref() {
                            li { class: "nav-item",
                                Link { to: Route::NewTournament {}, class: "nav-link", "Create Tournament" }
                            }
                        }
                        li { class: "nav-item",
                            Link { to: Route::About {}, class: "nav-link", "About" }
                        }
                    }
                    ul { class: "navbar-nav",
                        if let Some(Ok(u)) = user.read().as_ref() {
                            li { class: "nav-item dropdown",
                                button {
                                    class: "nav-link dropdown-toggle btn btn-link",
                                    style: "color: rgba(255,255,255,.85); text-decoration: none;",
                                    onclick: move |_| user_dropdown_open.toggle(),
                                    "{u.name}"
                                }
                                if user_dropdown_open() {
                                    ul { class: "dropdown-menu dropdown-menu-end show",
                                        li {
                                            if u.user_type == "player" {
                                                Link {
                                                    to: Route::PlayerProfile { id: u.id.clone() },
                                                    class: "dropdown-item",
                                                    "Profile"
                                                }
                                            } else {
                                                Link {
                                                    to: Route::TeamProfile { id: u.id.clone() },
                                                    class: "dropdown-item",
                                                    "Profile"
                                                }
                                            }
                                        }
                                        li { hr { class: "dropdown-divider" } }
                                        li {
                                            button {
                                                class: "dropdown-item",
                                                onclick: move |_| {
                                                    let nav = navigator.clone();
                                                    let mut auth_version = auth_version;
                                                    spawn(async move {
                                                        let _ = api::logout().await;
                                                        auth_version.set(auth_version() + 1);
                                                        nav.push("/");
                                                    });
                                                },
                                                "Logout"
                                            }
                                        }
                                    }
                                }
                            }
                        } else {
                            li { class: "nav-item",
                                Link { to: Route::Login {}, class: "nav-link", "Login" }
                            }
                            li { class: "nav-item dropdown",
                                button {
                                    class: "nav-link dropdown-toggle btn btn-link",
                                    style: "color: rgba(255,255,255,.85); text-decoration: none;",
                                    onclick: move |_| register_dropdown_open.toggle(),
                                    "Register"
                                }
                                if register_dropdown_open() {
                                    ul { class: "dropdown-menu dropdown-menu-end show",
                                        li {
                                            Link { to: Route::Register {}, class: "dropdown-item", "Register as Player" }
                                        }
                                        li {
                                            Link { to: Route::Register {}, class: "dropdown-item", "Register as Team" }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        main { class: "container-wide mt-4",
            Outlet::<Route> {}
        }

        footer { class: "container-wide mt-4",
            div { id: "footer", class: "text-center py-4 text-muted",
                p {
                    "Arctos is "
                    a { href: "https://github.com/reid23/arctos", "open source" }
                    ". Help improve it!"
                }
                p {
                    Link { to: Route::About {}, "About" }
                    " - "
                    Link { to: Route::Thanks {}, "Thanks" }
                    " - "
                    Link { to: Route::Docs {}, "User Docs" }
                    " - "
                    Link { to: Route::Privacy {}, "Privacy" }
                    " - "
                    Link { to: Route::License {}, "License" }
                    " - "
                    Link { to: Route::Terms {}, "Terms" }
                }
                p { style: "font-size: 0.8em;", "Arctos is an independent project and does not belong to nor represent CAJA in any way." }
            }
        }
    }
}
