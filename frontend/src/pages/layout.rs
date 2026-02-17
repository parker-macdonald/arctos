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
            .markdown-content {{ line-height: 1.6; }}
            .markdown-content h1, .markdown-content h2, .markdown-content h3, .markdown-content h4, .markdown-content h5, .markdown-content h6 {{ margin-top: 1em; margin-bottom: 0.5em; font-weight: 600; }}
            .markdown-content h1 {{ font-size: 1.5em; }} .markdown-content h2 {{ font-size: 1.3em; }} .markdown-content h3 {{ font-size: 1.15em; }}
            .markdown-content p {{ margin-bottom: 0.75em; }}
            .markdown-content ul, .markdown-content ol {{ margin-bottom: 0.75em; padding-left: 1.5em; }}
            .markdown-content li {{ margin-bottom: 0.25em; }}
            .markdown-content blockquote {{ border-left: 4px solid var(--bs-secondary, #6c757d); padding-left: 1em; margin: 0.75em 0; color: var(--bs-secondary); }}
            .markdown-content code {{ padding: 0.2em 0.4em; font-size: 0.9em; background: rgba(0,0,0,0.06); border-radius: 4px; }}
            .markdown-content pre {{ padding: 0.75em; overflow-x: auto; background: rgba(0,0,0,0.06); border-radius: 4px; margin-bottom: 0.75em; }}
            .markdown-content pre code {{ padding: 0; background: none; }}
            .markdown-content table {{ border-collapse: collapse; margin-bottom: 0.75em; width: 100%; }}
            .markdown-content th, .markdown-content td {{ border: 1px solid var(--bs-border-color, #dee2e6); padding: 0.4em 0.6em; text-align: left; }}
            .markdown-content th {{ font-weight: 600; background: rgba(0,0,0,0.04); }}
            .markdown-content a {{ color: var(--bs-link-color, #0d6efd); text-decoration: none; }}
            .markdown-content a:hover {{ text-decoration: underline; }}
            .markdown-content img {{ max-width: 100%; height: auto; }}
            .markdown-content hr {{ margin: 1em 0; border: 0; border-top: 1px solid var(--bs-border-color, #dee2e6); }}
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
                                                    to: Route::PlayerProfilePage { id: u.id.clone() },
                                                    class: "dropdown-item",
                                                    "Profile"
                                                }
                                            } else {
                                                Link {
                                                    to: Route::TeamProfilePage { id: u.id.clone() },
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
                                            Link { to: Route::RegisterPlayer {}, class: "dropdown-item", "Register as Player" }
                                        }
                                        li {
                                            Link { to: Route::RegisterTeam {}, class: "dropdown-item", "Register as Team" }
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
