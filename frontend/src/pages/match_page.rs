use crate::api;
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

#[component]
pub fn MatchPage(url: String) -> Element {
    let match_id = get_query_param("id");
    let match_name = get_query_param("name");
    match_page_inner(url, match_id, match_name)
}

#[component]
pub fn MatchPageById(url: String, match_id: String) -> Element {
    match_page_inner(url, Some(match_id), None)
}

fn match_page_inner(url: String, match_id: Option<String>, match_name: Option<String>) -> Element {
    let url_for_resource = url.clone();
    let id_for_resource = match_id.clone();
    let name_for_resource = match_name.clone();
    let data = use_resource(move || {
        let u = url_for_resource.clone();
        let id = id_for_resource.clone();
        let name = name_for_resource.clone();
        async move {
            if id.is_some() || name.is_some() {
                api::match_detail(&u, id.as_deref(), name.as_deref())
                    .await
                    .map_err(|e| e.to_string())
            } else {
                Err("id or name query param required".to_string())
            }
        }
    });
    let val = data.value();
    rsx! {
        if let Some(Ok(d)) = val.read().as_ref() {
            div { class: "row",
                div { class: "col-12",
                    h1 { "{d.match_data.name}" }
                    nav { "aria-label": "breadcrumb",
                        ol { class: "breadcrumb",
                            li { class: "breadcrumb-item",
                                Link { to: Route::TournamentHome { url: url.clone() }, "{url}" }
                            }
                            li { class: "breadcrumb-item",
                                Link { to: Route::Schedule { url: url.clone() }, "Schedule" }
                            }
                            li { class: "breadcrumb-item active", "{d.match_data.name}" }
                        }
                    }
                }
            }

            div { class: "row",
                div { class: "col-md-8",
                    div { class: "card",
                        div { class: "card-header",
                            h5 { class: "mb-0", "Match Information" }
                        }
                        div { class: "card-body",
                            div { class: "row",
                                div { class: "col-md-4",
                                    div { class: "d-flex align-items-center mb-2",
                                        strong { class: "me-2", "Teams:" }
                                        div {
                                            span { "{d.match_data.team1_name}" }
                                            if d.match_data.match_winner.as_deref() == Some("TEAM1") {
                                                span { class: "badge bg-success ms-2", "Winner" }
                                            }
                                            span { class: "mx-2", "vs" }
                                            span { "{d.match_data.team2_name}" }
                                            if d.match_data.match_winner.as_deref() == Some("TEAM2") {
                                                span { class: "badge bg-success ms-2", "Winner" }
                                            }
                                        }
                                    }
                                }
                                div { class: "col-md-4",
                                    div { class: "d-flex align-items-center mb-2",
                                        strong { class: "me-2", "Status:" }
                                        span {
                                            class: format!(
                                                "badge {}",
                                                match d.match_data.status.as_str() {
                                                    "COMPLETED" => "bg-success",
                                                    "IN_PROGRESS" => "bg-warning",
                                                    _ => "bg-secondary",
                                                }
                                            ),
                                            "{d.match_data.status}"
                                        }
                                    }
                                    if let Some(field) = &d.match_data.field {
                                        div { class: "d-flex align-items-center mb-2",
                                            strong { class: "me-2", "Field:" }
                                            span { "{field}" }
                                        }
                                    }
                                    div { class: "d-flex align-items-center mb-2",
                                        strong { class: "me-2", "Start:" }
                                        span { "{d.match_data.confirmed_start_time.as_deref().or(d.match_data.nominal_start_time.as_deref()).unwrap_or(\"TBA\")}" }
                                    }
                                    div { class: "d-flex align-items-center mb-2",
                                        strong { class: "me-2", "End:" }
                                        span { "{d.match_data.completed_time.as_deref().unwrap_or(\"TBA\")}" }
                                    }
                                }
                                div { class: "col-md-4" }
                            }

                            if let Some(set_type) = &d.match_data.set_type {
                                div { class: "row mt-3",
                                    div { class: "col-md-6",
                                        h6 { "Type" }
                                        p { "{set_type}" }
                                    }
                                    if let Some(length) = d.match_data.nominal_length {
                                        div { class: "col-md-6",
                                            h6 { "Length" }
                                            p { "{length} minutes" }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            div { class: "row mt-3",
                div { class: "col-12",
                    h3 { "Points" }
                    if d.points.is_empty() {
                        p { class: "text-muted", "No points recorded yet." }
                    } else {
                        div { class: "table-responsive",
                            table { class: "table table-striped",
                                thead {
                                    tr {
                                        th { "Set" }
                                        th { "Winner" }
                                    }
                                }
                                tbody {
                                    for pt in d.points.iter() {
                                        tr { key: "{pt.uuid}",
                                            td { "{pt.set_number.unwrap_or(0)}" }
                                            td { "{pt.winner.as_deref().unwrap_or(\"-\")}" }
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
        } else if match_id.is_none() && match_name.is_none() {
            p { "Add ?id=... or ?name=... to the URL" }
        } else {
            p { "Loading…" }
        }
    }
}
