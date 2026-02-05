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
            h1 { "Schedule — {d.tournament.name}" }
            Link { to: Route::TournamentHome { url: url.clone() }, "← Tournament" }
            table { class: "schedule-table",
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
                                a { href: "/app/{url}/match?id={m.uuid}", "{m.name}" }
                            }
                            td { "{m.field.as_deref().unwrap_or(\"-\")}" }
                            td { "{m.team1_initial.as_deref().or(m.team1.as_deref()).unwrap_or(\"-\")}" }
                            td { "{m.team2_initial.as_deref().or(m.team2.as_deref()).unwrap_or(\"-\")}" }
                            td { "{m.nominal_start_time.as_deref().unwrap_or(\"-\")}" }
                            td { "{m.status}" }
                            td {
                                a { href: "/app/{url}/run-match?id={m.uuid}", "Run" }
                                " | "
                                a { href: "/app/{url}/start-match?id={m.uuid}", "Start" }
                                " | "
                                a { href: "/app/{url}/finalize-match?id={m.uuid}", "Finalize" }
                            }
                        }
                    }
                }
            }
        } else if let Some(Err(e)) = val.read().as_ref() {
            p { class: "error", "{e}" }
        } else {
            p { "Loading…" }
        }
    }
}
