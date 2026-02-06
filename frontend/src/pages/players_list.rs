use crate::api;
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn PlayersList() -> Element {
    let mut search = use_signal(|| String::new());
    let mut page = use_signal(|| 1u32);
    let mut submitted_search = use_signal(|| String::new());
    let data = use_resource(move || {
        let s = submitted_search().clone();
        let p = page();
        async move { api::players_list(&s, p).await.map_err(|e| e.to_string()) }
    });
    let val = data.value();
    let backend = api::base_url();
    rsx! {
        style { r#"
        .player-card-link {{
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .player-card-link:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }}
        "# }
        div { class: "row",
            div { class: "col-12",
                h1 { "Players" }
                p { class: "lead", "Browse all registered players" }
                div { class: "row mb-3",
                    div { class: "col-md-6",
                        form {
                            class: "d-flex",
                            onsubmit: move |ev| {
                                ev.prevent_default();
                                submitted_search.set(search().clone());
                                page.set(1);
                            },
                            input {
                                r#type: "text",
                                class: "form-control me-2",
                                placeholder: "Search players...",
                                value: "{search()}",
                                oninput: move |ev| search.set(ev.value().clone()),
                            }
                            button { class: "btn btn-outline-primary", r#type: "submit", "Search" }
                        }
                    }
                    if let Some(Ok(d)) = val.read().as_ref() {
                        if d.total > 0 {
                            div { class: "col-md-6 text-end",
                                p { class: "text-muted mb-0",
                                    "Showing {((d.page - 1) * 50) + 1} - {std::cmp::min(d.page * 50, d.total)} of {d.total} players"
                                }
                            }
                        }
                    }
                }
            }
        }
        if let Some(Ok(d)) = val.read().as_ref() {
            div { class: "row",
                if d.players.is_empty() {
                    div { class: "col-12", p { "No players found." } }
                } else {
                    for p in d.players.iter() {
                        div { key: "{p.id}", class: "col-md-6 col-lg-4 mb-4",
                            Link { to: Route::PlayerProfile { id: p.id.clone() }, class: "text-decoration-none text-reset",
                                div { class: "card h-100 player-card-link",
                                    div { class: "card-body",
                                        div { class: "d-flex",
                                            div { class: "flex-shrink-0 me-3",
                                                if let Some(photo) = &p.profile_photo {
                                                    img { src: "{backend}/static/{photo}", alt: "{p.name}", class: "rounded-circle", style: "width: 80px; height: 80px; object-fit: cover;" }
                                                } else {
                                                    div { class: "d-flex align-items-center justify-content-center bg-secondary rounded-circle", style: "width: 80px; height: 80px;",
                                                        i { class: "fas fa-user fa-2x text-white" }
                                                    }
                                                }
                                            }
                                            div { class: "flex-grow-1",
                                                h5 { class: "card-title mb-2", "{p.name}" }
                                                p { class: "card-text mb-0",
                                                    i { class: "fas fa-user" }
                                                    " @{p.id}"
                                                    if let Some(loc) = &p.location {
                                                        br {}
                                                        i { class: "fas fa-map-marker-alt" }
                                                        " {loc}"
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            if d.total_pages > 1 {
                nav { aria_label: "Players pagination",
                    ul { class: "pagination justify-content-center",
                        if d.page > 1 {
                            li { class: "page-item",
                                a {
                                    class: "page-link",
                                    href: "#",
                                    onclick: move |ev| {
                                        ev.prevent_default();
                                        page.set(page().saturating_sub(1));
                                    },
                                    "Previous"
                                }
                            }
                        } else {
                            li { class: "page-item disabled", span { class: "page-link", "Previous" } }
                        }

                        for pnum in 1..=d.total_pages {
                            {
                                let show = pnum == 1
                                    || pnum == d.total_pages
                                    || (pnum + 2 >= d.page && pnum <= d.page + 2);
                                let is_ellipsis = pnum + 3 == d.page || pnum == d.page + 3;
                                rsx! {
                                    if pnum == d.page {
                                        li { class: "page-item active", span { class: "page-link", "{pnum}" } }
                                    } else if show {
                                        li { class: "page-item",
                                            a {
                                                class: "page-link",
                                                href: "#",
                                                onclick: move |ev| {
                                                    ev.prevent_default();
                                                    page.set(pnum);
                                                },
                                                "{pnum}"
                                            }
                                        }
                                    } else if is_ellipsis {
                                        li { class: "page-item disabled", span { class: "page-link", "..." } }
                                    }
                                }
                            }
                        }

                        if d.page < d.total_pages {
                            li { class: "page-item",
                                a {
                                    class: "page-link",
                                    href: "#",
                                    onclick: move |ev| {
                                        ev.prevent_default();
                                        page.set(page() + 1);
                                    },
                                    "Next"
                                }
                            }
                        } else {
                            li { class: "page-item disabled", span { class: "page-link", "Next" } }
                        }
                    }
                }
            }
        } else if let Some(Err(e)) = val.read().as_ref() {
            p { class: "text-danger", "{e}" }
        } else {
            p { "Loading…" }
        }
    }
}
