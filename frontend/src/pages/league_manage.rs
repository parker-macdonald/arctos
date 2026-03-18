use crate::api;
use crate::Route;
use dioxus::prelude::*;
use wasm_bindgen::JsCast;

#[component]
pub fn LeagueManage(league_url: String) -> Element {
    let mut search = use_signal(|| String::new());
    let mut search_type = use_signal(|| "both".to_string());
    let mut submitted_search = use_signal(|| String::new());
    let mut submitted_type = use_signal(|| "both".to_string());
    let mut refresh = use_signal(|| 0u32);
    let url_for_data = league_url.clone();
    let data = use_resource(move || {
        let u = url_for_data.clone();
        let s = submitted_search().clone();
        let t = submitted_type().clone();
        let _r = refresh();
        async move { api::league_manage(&u, &s, &t).await.map_err(|e| e.to_string()) }
    });
    let val = data.value();
    rsx! {
        if let Some(Ok(d)) = val.read().as_ref() {
            div { class: "row",
                div { class: "col-12",
                    h1 { "{d.tournament.name} - Registration Management" }
                    nav { aria_label: "breadcrumb",
                        ol { class: "breadcrumb",
                            li { class: "breadcrumb-item", Link { to: Route::LeagueHome { league_url: league_url.clone() }, "{d.tournament.name}" } }
                            li { class: "breadcrumb-item active", "Registration Management" }
                        }
                    }
                }
            }

            div { class: "row mb-3",
                div { class: "col-12",
                    form { class: "row g-2",
                        onsubmit: move |ev| {
                            ev.prevent_default();
                            submitted_search.set(search().clone());
                            submitted_type.set(search_type().clone());
                        },
                        div { class: "col-md-6",
                            input {
                                r#type: "text",
                                class: "form-control",
                                name: "search",
                                placeholder: "Search teams or players by name",
                                value: "{search()}",
                                oninput: move |ev| search.set(ev.value().clone()),
                            }
                        }
                        div { class: "col-md-4",
                            select {
                                class: "form-select",
                                name: "type",
                                value: "{search_type()}",
                                onchange: move |ev| search_type.set(ev.value().clone()),
                                option { value: "both", "Teams and Players" }
                                option { value: "teams", "Teams" }
                                option { value: "players", "Players" }
                            }
                        }
                        div { class: "col-md-2 d-grid",
                            button { r#type: "submit", class: "btn btn-primary", "Search" }
                        }
                    }
                }
            }

            div { class: "row",
                div { class: "col-12",
                    div { class: "card",
                        div { class: "card-header", h5 { class: "mb-0", "Team Registrations" } }
                        div { class: "card-body",
                            div { class: "table-responsive",
                                table { class: "table table-striped",
                                    thead {
                                        tr {
                                            th { "Team Name" }
                                            th { "Status" }
                                            th { "Registration Date" }
                                            th { "Actions" }
                                        }
                                    }
                                    tbody {
                                        for (url_dereg, url_save, team_id_dereg, reg_id_save, team_data) in d.team_registrations.iter().map(|t| (league_url.clone(), league_url.clone(), t.registration.team.clone(), t.registration.id, t)) {
                                            tr { key: "{team_data.registration.id}",
                                                td {
                                                    a { href: "/teams/{team_data.registration.team}", class: "text-decoration-none",
                                                        strong { "{team_data.registration.pseudonym}" }
                                                    }
                                                }
                                                td {
                                                    span {
                                                        class: format!(
                                                            "badge {}",
                                                            match team_data.registration.status.as_str() {
                                                                "CONFIRMED" => "bg-success",
                                                                "CANCELLED" => "bg-danger",
                                                                _ => "bg-warning",
                                                            }
                                                        ),
                                                        "{team_data.registration.status}"
                                                    }
                                                    if team_data.registration.paid {
                                                        span { class: "badge bg-primary ms-1", "Paid" }
                                                    } else {
                                                        span { class: "badge bg-secondary ms-1", "Unpaid" }
                                                    }
                                                }
                                                td { "{team_data.registration.registered_at.as_deref().unwrap_or(\"-\")}" }
                                                td {
                                                    if team_data.registration.status == "CONFIRMED" {
                                                        button {
                                                            r#type: "button",
                                                            class: "btn btn-sm btn-outline-danger",
                                                            onclick: move |_| {
                                                                let u = url_dereg.clone();
                                                                let tid = team_id_dereg.clone();
                                                                spawn(async move {
                                                                    let _ = api::league_deregister_any_team(&u, &tid).await;
                                                                    refresh.set(refresh() + 1);
                                                                });
                                                            },
                                                            "Deregister"
                                                        }
                                                    }
                                                    div { class: "d-inline ms-2",
                                                        div { class: "input-group input-group-sm", style: "max-width: 420px;",
                                                            span { class: "input-group-text", "$" }
                                                            input {
                                                                r#type: "number",
                                                                step: "0.01",
                                                                min: "0",
                                                                class: "form-control",
                                                                id: "team-amount-{team_data.registration.id}",
                                                                placeholder: "Amount",
                                                                value: format!("{:.2}", team_data.registration.amount_paid)
                                                            }
                                                            div { class: "input-group-text",
                                                                input {
                                                                    class: "form-check-input mt-0",
                                                                    r#type: "checkbox",
                                                                    id: "team-paid-{team_data.registration.id}",
                                                                    checked: team_data.registration.paid
                                                                }
                                                            }
                                                            button {
                                                                r#type: "button",
                                                                class: "btn btn-sm btn-outline-primary",
                                                                onclick: move |_| {
                                                                    let u = url_save.clone();
                                                                    let rid = reg_id_save;
                                                                    spawn(async move {
                                                                        let amount: f64 = web_sys::window()
                                                                            .and_then(|w| w.document())
                                                                            .and_then(|d| d.get_element_by_id(&format!("team-amount-{}", rid)))
                                                                            .and_then(|e| e.dyn_into::<web_sys::HtmlInputElement>().ok())
                                                                            .map(|e: web_sys::HtmlInputElement| e.value().parse().unwrap_or(0.0))
                                                                            .unwrap_or(0.0);
                                                                        let paid = web_sys::window()
                                                                            .and_then(|w| w.document())
                                                                            .and_then(|d| d.get_element_by_id(&format!("team-paid-{}", rid)))
                                                                            .and_then(|e| e.dyn_into::<web_sys::HtmlInputElement>().ok())
                                                                            .map(|e: web_sys::HtmlInputElement| e.checked())
                                                                            .unwrap_or(false);
                                                                        let _ = api::league_mark_team_paid(&u, rid, amount, paid, "", "", "").await;
                                                                        refresh.set(refresh() + 1);
                                                                    });
                                                                },
                                                                "Save"
                                                            }
                                                        }
                                                        if let Some(paid_at) = &team_data.registration.paid_at {
                                                            div { class: "form-text", "Paid at {paid_at}" }
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
            }

            div { class: "row mt-4",
                div { class: "col-12",
                    div { class: "card",
                        div { class: "card-header", h5 { class: "mb-0", "Player Registrations" } }
                        div { class: "card-body",
                            div { class: "table-responsive",
                                table { class: "table table-striped",
                                    thead {
                                        tr {
                                            th { "Player Name" }
                                            th { "Team" }
                                            th { "Jersey" }
                                            th { "Status" }
                                            th { "Registration Date" }
                                            th { "Actions" }
                                        }
                                    }
                                    tbody {
                                        for (url_dereg, url_save, player_id_dereg, reg_id_save, player_data) in d.player_registrations.iter().map(|p| (league_url.clone(), league_url.clone(), p.registration.player.clone(), p.registration.id, p)) {
                                            tr { key: "{player_data.registration.id}",
                                                td {
                                                    a { href: "/players/{player_data.registration.player}", class: "text-decoration-none",
                                                        strong { "{player_data.player.name}" }
                                                    }
                                                }
                                                td {
                                                    if let Some(team) = &player_data.team {
                                                        a { href: "/teams/{team.id}", class: "text-decoration-none", "{team.name}" }
                                                    } else {
                                                        span { class: "text-muted", "Unattached" }
                                                    }
                                                }
                                                td {
                                                    if player_data.registration.jersey_name.is_some()
                                                        && player_data.registration.jersey_number.is_some()
                                                    {
                                                        "#{player_data.registration.jersey_number.as_deref().unwrap_or(\"\")} {player_data.registration.jersey_name.as_deref().unwrap_or(\"\")}"
                                                    } else if let Some(name) = &player_data.registration.jersey_name {
                                                        "{name}"
                                                    } else if let Some(num) = &player_data.registration.jersey_number {
                                                        "#{num}"
                                                    } else {
                                                        span { class: "text-muted", "No jersey info" }
                                                    }
                                                }
                                                td {
                                                    span {
                                                        class: format!(
                                                            "badge {}",
                                                            match player_data.registration.status.as_str() {
                                                                "CONFIRMED" => "bg-success",
                                                                "CANCELLED" => "bg-danger",
                                                                "PENDING_TEAM_APPROVAL" => "bg-warning",
                                                                _ => "bg-secondary",
                                                            }
                                                        ),
                                                        "{player_data.registration.status}"
                                                    }
                                                    if player_data.registration.paid {
                                                        span { class: "badge bg-primary ms-1", "Paid" }
                                                    } else {
                                                        span { class: "badge bg-secondary ms-1", "Unpaid" }
                                                    }
                                                }
                                                td { "{player_data.registration.registered_at.as_deref().unwrap_or(\"-\")}" }
                                                td {
                                                    if player_data.registration.status == "PENDING_TEAM_APPROVAL"
                                                        || player_data.registration.status == "CONFIRMED"
                                                    {
                                                        button {
                                                            r#type: "button",
                                                            class: "btn btn-sm btn-outline-danger",
                                                            onclick: move |_| {
                                                                let u = url_dereg.clone();
                                                                let pid = player_id_dereg.clone();
                                                                spawn(async move {
                                                                    let _ = api::league_deregister_any_player(&u, &pid).await;
                                                                    refresh.set(refresh() + 1);
                                                                });
                                                            },
                                                            "Deregister"
                                                        }
                                                    }
                                                    div { class: "d-inline ms-2",
                                                        div { class: "input-group input-group-sm", style: "max-width: 420px;",
                                                            span { class: "input-group-text", "$" }
                                                            input {
                                                                r#type: "number",
                                                                step: "0.01",
                                                                min: "0",
                                                                class: "form-control",
                                                                id: "player-amount-{player_data.registration.id}",
                                                                placeholder: "Amount",
                                                                value: format!("{:.2}", player_data.registration.amount_paid)
                                                            }
                                                            div { class: "input-group-text",
                                                                input {
                                                                    class: "form-check-input mt-0",
                                                                    r#type: "checkbox",
                                                                    id: "player-paid-{player_data.registration.id}",
                                                                    checked: player_data.registration.paid
                                                                }
                                                            }
                                                            button {
                                                                r#type: "button",
                                                                class: "btn btn-sm btn-outline-primary",
                                                                onclick: move |_| {
                                                                    let u = url_save.clone();
                                                                    let rid = reg_id_save;
                                                                    spawn(async move {
                                                                        let amount: f64 = web_sys::window()
                                                                            .and_then(|w| w.document())
                                                                            .and_then(|d| d.get_element_by_id(&format!("player-amount-{}", rid)))
                                                                            .and_then(|e| e.dyn_into::<web_sys::HtmlInputElement>().ok())
                                                                            .map(|e: web_sys::HtmlInputElement| e.value().parse().unwrap_or(0.0))
                                                                            .unwrap_or(0.0);
                                                                        let paid = web_sys::window()
                                                                            .and_then(|w| w.document())
                                                                            .and_then(|d| d.get_element_by_id(&format!("player-paid-{}", rid)))
                                                                            .and_then(|e| e.dyn_into::<web_sys::HtmlInputElement>().ok())
                                                                            .map(|e: web_sys::HtmlInputElement| e.checked())
                                                                            .unwrap_or(false);
                                                                        let _ = api::league_mark_player_paid(&u, rid, amount, paid, "", "", "").await;
                                                                        refresh.set(refresh() + 1);
                                                                    });
                                                                },
                                                                "Save"
                                                            }
                                                        }
                                                        if let Some(paid_at) = &player_data.registration.paid_at {
                                                            div { class: "form-text", "Paid at {paid_at}" }
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
            }
        } else if let Some(Err(e)) = val.read().as_ref() {
            p { class: "text-danger", "{e}" }
        } else {
            p { "Loading…" }
        }
    }
}
