use crate::api;
use crate::types::SideCompSummary;
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn SideCompsList(url: String) -> Element {
    let url_for_data = url.clone();
    let comps = use_resource(move || {
        let u = url_for_data.clone();
        async move { api::sidecomps_list(&u).await }
    });

    rsx! {
        div { class: "row",
            div { class: "col-12",
                h1 { "Side Competitions" }
                div { class: "mb-3",
                    Link {
                        to: Route::TournamentHome { url: url.clone() },
                        class: "btn btn-link",
                        "<- Back to tournament"
                    }
                    Link {
                        to: Route::SideCompNew { url: url.clone() },
                        class: "btn btn-primary",
                        "Create side competition"
                    }
                }

                match comps.read().as_ref() {
                    Some(Ok(rows)) => rsx! {
                        if rows.is_empty() {
                            p { class: "text-muted", "No side competitions yet." }
                        } else {
                            ul { class: "list-group",
                                for row in rows.iter() {
                                    SideCompRow { url: url.clone(), row: row.clone() }
                                }
                            }
                        }
                    },
                    Some(Err(e)) => rsx! { div { class: "alert alert-danger", "Error: {e}" } },
                    None => rsx! { div { class: "spinner-border" } },
                }
            }
        }
    }
}

#[component]
fn SideCompRow(url: String, row: SideCompSummary) -> Element {
    let comp_id = row.id;
    rsx! {
        li {
            class: "list-group-item d-flex justify-content-between align-items-center p-0",
            Link {
                to: Route::SideCompDetail { url: url.clone(), comp_id },
                class: "text-decoration-none text-reset p-3 flex-grow-1",
                div {
                    strong { "{row.name}" }
                    span { class: "badge bg-secondary ms-2", "{row.type_}" }
                    if row.registration_open {
                        span { class: "badge bg-success ms-2", "Open" }
                    } else {
                        span { class: "badge bg-secondary ms-2", "Closed" }
                    }
                    span { class: "text-muted ms-2", "({row.registrant_count} registered)" }
                }
            }
        }
    }
}
