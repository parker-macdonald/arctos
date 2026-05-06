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
                            table { class: "table",
                                thead {
                                    tr {
                                        th { "Name" }
                                        th { "Type" }
                                        th { "Registrants" }
                                        th { "" }
                                    }
                                }
                                tbody {
                                    for row in rows.iter() {
                                        SideCompRow { url: url.clone(), row: row.clone() }
                                    }
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
    rsx! {
        tr {
            td { "{row.name}" }
            td { span { class: "badge bg-secondary", "{row.type_}" } }
            td { "{row.registrant_count}" }
            td {
                Link {
                    to: Route::SideCompDetail { url: url.clone(), comp_id: row.id },
                    class: "btn btn-sm btn-outline-primary",
                    "View"
                }
            }
        }
    }
}
