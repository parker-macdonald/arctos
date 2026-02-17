use crate::api;
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn TeamsList() -> Element {
    let mut search = use_signal(|| String::new());
    let mut submitted_search = use_signal(|| String::new());
    let data = use_resource(move || {
        let s = submitted_search().clone();
        async move { api::teams_list(&s).await.map_err(|e| e.to_string()) }
    });
    let val = data.value();
    let backend = api::base_url();
    rsx! {
        style { r#"
        .team-card-link {{
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .team-card-link:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }}
        "# }
        div { class: "row",
            div { class: "col-12",
                h1 { "Teams" }
                p { class: "lead", "Browse all registered teams" }
                div { class: "row mb-3",
                    div { class: "col-md-6",
                        form {
                            class: "d-flex",
                            onsubmit: move |ev| {
                                ev.prevent_default();
                                submitted_search.set(search().clone());
                            },
                            input {
                                r#type: "text",
                                class: "form-control me-2",
                                placeholder: "Search teams...",
                                value: "{search()}",
                                oninput: move |ev| search.set(ev.value().clone()),
                            }
                            button { class: "btn btn-outline-primary", r#type: "submit", "Search" }
                        }
                    }
                }
            }
        }
        if let Some(Ok(d)) = val.read().as_ref() {
            div { class: "row",
                if d.teams.is_empty() {
                    div { class: "col-12", p { "No teams found." } }
                } else {
                    for t in d.teams.iter() {
                        div { key: "{t.id}", class: "col-md-6 col-lg-4 mb-4",
                            Link { to: Route::TeamProfilePage { id: t.id.clone() }, class: "text-decoration-none text-reset",
                                div { class: "card h-100 team-card-link",
                                    div { class: "card-body",
                                        div { class: "d-flex",
                                            div { class: "flex-shrink-0 me-3",
                                                if let Some(photo) = &t.profile_photo {
                                                    img { src: "{backend}/static/{photo}", alt: "{t.name}", class: "rounded", style: "width: 80px; height: 80px; object-fit: cover;" }
                                                } else {
                                                    div { class: "d-flex align-items-center justify-content-center bg-secondary rounded-circle", style: "width: 80px; height: 80px;",
                                                        i { class: "fas fa-users fa-2x text-white" }
                                                    }
                                                }
                                            }
                                            div { class: "flex-grow-1",
                                                h5 { class: "card-title mb-2", "{t.name}" }
                                                if let Some(loc) = &t.location {
                                                    p { class: "card-text mb-0",
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
        } else if let Some(Err(e)) = val.read().as_ref() {
            p { class: "text-danger", "{e}" }
        } else {
            p { "Loading…" }
        }
    }
}
