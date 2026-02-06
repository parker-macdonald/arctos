use crate::api;
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn Results(url: String) -> Element {
    let url_for_data = url.clone();
    let data = use_resource(move || {
        let u = url_for_data.clone();
        async move { api::results(&u).await.map_err(|e| e.to_string()) }
    });
    let val = data.value();
    rsx! {
        if let Some(Ok(d)) = val.read().as_ref() {
            div { class: "row",
                div { class: "col-12",
                    h1 { "{d.tournament.name} - Results" }
                    nav { "aria-label": "breadcrumb",
                        ol { class: "breadcrumb",
                            li { class: "breadcrumb-item",
                                Link { to: Route::TournamentHome { url: url.clone() }, "{d.tournament.name}" }
                            }
                            li { class: "breadcrumb-item active", "Results" }
                        }
                    }
                }
            }
            div { class: "card",
                div { class: "card-body",
                    if d.matches.is_empty() {
                        p { class: "text-muted", "No completed matches yet." }
                    } else {
                        div { class: "table-responsive",
                            table { class: "table table-striped align-middle",
                                thead {
                                    tr {
                                        th { "Match" }
                                        th { "Teams" }
                                        th { "Winner" }
                                    }
                                }
                                tbody {
                                    for m in d.matches.iter() {
                                        tr { key: "{m.uuid}",
                                            td {
                                                Link { to: Route::MatchPageById { url: url.clone(), match_id: m.uuid.clone() }, class: "text-decoration-none", "{m.name}" }
                                            }
                                            td {
                                                "{m.team1.as_deref().unwrap_or(\"TBD\")} vs {m.team2.as_deref().unwrap_or(\"TBD\")}"
                                            }
                                            td {
                                                if let Some(w) = &m.match_winner {
                                                    span { class: "badge bg-success", "{w}" }
                                                } else {
                                                    span { class: "text-muted", "TBD" }
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
