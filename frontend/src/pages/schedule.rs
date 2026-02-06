use crate::api;
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn Schedule(url: String) -> Element {
    let url_for_data = url.clone();
    let data = use_resource(move || {
        let u = url_for_data.clone();
        async move { api::schedule(&u).await.map_err(|e| e.to_string()) }
    });
    let val = data.value();
    rsx! {
        if let Some(Ok(d)) = val.read().as_ref() {
            div { class: "row",
                div { class: "col-12",
                    h1 { "{d.tournament.name} - Schedule" }
                    nav { "aria-label": "breadcrumb",
                        ol { class: "breadcrumb",
                            li { class: "breadcrumb-item",
                                Link { to: Route::TournamentHome { url: url.clone() }, "{d.tournament.name}" }
                            }
                            li { class: "breadcrumb-item active", "Schedule" }
                        }
                    }
                    p { class: "text-muted", "All match times are in your local timezone." }
                }
            }
            div { class: "card",
                div { class: "card-body",
                    div { class: "table-responsive",
                        table { class: "table table-striped align-middle",
                            thead {
                                tr {
                                    th { "Match" }
                                    th { "Field" }
                                    th { "Team 1" }
                                    th { "Team 2" }
                                    th { "Time" }
                                    th { "Status" }
                                    th { "Actions" }
                                }
                            }
                            tbody {
                                for m in d.matches.iter() {
                                    tr { key: "{m.uuid}",
                                        td {
                                            Link { to: Route::MatchPageById { url: url.clone(), match_id: m.uuid.clone() }, class: "text-decoration-none", "{m.name}" }
                                        }
                                        td { "{m.field.as_deref().unwrap_or(\"-\")}" }
                                        td { "{m.team1_initial.as_deref().or(m.team1.as_deref()).unwrap_or(\"-\")}" }
                                        td { "{m.team2_initial.as_deref().or(m.team2.as_deref()).unwrap_or(\"-\")}" }
                                        td { "{m.nominal_start_time.as_deref().unwrap_or(\"-\")}" }
                                        td { "{m.status}" }
                                        td {
                                            div { class: "btn-group btn-group-sm",
                                                a { href: "/app/{url}/run-match?id={m.uuid}", class: "btn btn-outline-primary", "Run" }
                                                a { href: "/app/{url}/start-match?id={m.uuid}", class: "btn btn-outline-secondary", "Start" }
                                                a { href: "/app/{url}/finalize-match?id={m.uuid}", class: "btn btn-outline-secondary", "Finalize" }
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
