use crate::api;
use crate::components::TeamRegistrationHelpModal;
use crate::Route;
use dioxus::prelude::*;
use wasm_bindgen::JsCast;

fn get_form_value(id: &str) -> String {
    let doc = web_sys::window().and_then(|w| w.document()).unwrap();
    doc.get_element_by_id(id)
        .and_then(|e| e.dyn_into::<web_sys::HtmlInputElement>().ok())
        .map(|e| e.value())
        .unwrap_or_default()
}

fn get_form_select_value(id: &str) -> String {
    let doc = web_sys::window().and_then(|w| w.document()).unwrap();
    doc.get_element_by_id(id)
        .and_then(|e| e.dyn_into::<web_sys::HtmlSelectElement>().ok())
        .map(|e| e.value())
        .unwrap_or_default()
}

#[component]
pub fn LeagueRegister(league_url: String) -> Element {
    let navigator = use_navigator();
    let mut error = use_signal(|| None::<String>);
    let lu = league_url.clone();
    let data = use_resource(move || {
        let u = lu.clone();
        async move { api::league_detail(&u).await.map_err(|e| e.to_string()) }
    });
    let me = use_resource(move || async move { api::me().await });
    let mut show_help_modal = use_signal(|| false);

    rsx! {
        div { class: "row justify-content-center",
            div { class: "col-md-8",
                if let Some(Ok(d)) = data.value().read().as_ref() {
                    div { class: "card",
                            div { class: "card-header",
                                h3 { class: "mb-0", "Register for {d.league.name}" }
                            }
                            div { class: "card-body",
                                p { class: "text-muted mb-3",
                                    "One registration covers all events in this league season."
                                }
                                if let Some(ref err) = error() {
                                    div { class: "alert alert-danger mb-3", "{err}" }
                                }
                                if let Some(Ok(me)) = me.value().read().as_ref() {
                                    if me.user_type == "team" {
                                        form {
                                            onsubmit: move |ev| {
                                                ev.prevent_default();
                                                error.set(None);
                                                let pseudonym = get_form_value("pseudonym");
                                                if pseudonym.is_empty() {
                                                    error.set(Some("Team name is required.".to_string()));
                                                    return;
                                                }
                                                let nav = navigator.clone();
                                                let lu = league_url.clone();
                                                spawn(async move {
                                                    match api::league_register_team(&lu, &pseudonym).await {
                                                        Ok(res) if res.success => {
                                                            let path = format!("/leagues/{}?registered=1", lu);
                                                            let _ = nav.push(path);
                                                        }
                                                        Ok(res) => {
                                                            error.set(Some(res.error.unwrap_or_else(|| "Registration failed.".to_string())));
                                                        }
                                                        Err(e) => error.set(Some(e)),
                                                    }
                                                });
                                            },
                                            div { class: "mb-3",
                                                label { r#for: "pseudonym", class: "form-label", "Team Name" }
                                                input { r#type: "text", class: "form-control", id: "pseudonym", name: "pseudonym", required: true }
                                            }
                                            div { class: "d-grid",
                                                button { r#type: "submit", class: "btn btn-primary", "Register Team" }
                                            }
                                        }
                                    } else if me.user_type == "player" {
                                        form {
                                            onsubmit: move |ev| {
                                                ev.prevent_default();
                                                error.set(None);
                                                let jersey_name = get_form_value("jersey_name");
                                                let jersey_number = get_form_value("jersey_number");
                                                let team_id = get_form_select_value("team");
                                                let team_opt = if team_id.is_empty() { None } else { Some(team_id.clone()) };
                                                let nav = navigator.clone();
                                                let lu = league_url.clone();
                                                spawn(async move {
                                                    match api::league_register_player(&lu, team_opt.as_deref(), &jersey_number, &jersey_name).await {
                                                        Ok(res) if res.success => {
                                                            let path = format!("/leagues/{}?registered=1", lu);
                                                            let _ = nav.push(path);
                                                        }
                                                        Ok(res) => error.set(Some(res.error.unwrap_or_else(|| "Registration failed.".to_string()))),
                                                        Err(e) => error.set(Some(e)),
                                                    }
                                                });
                                            },
                                            div { class: "mb-3",
                                                label { r#for: "jersey_name", class: "form-label", "Jersey Name" }
                                                input { r#type: "text", class: "form-control", id: "jersey_name", name: "jersey_name" }
                                            }
                                            div { class: "mb-3",
                                                label { r#for: "jersey_number", class: "form-label", "Jersey Number" }
                                                input { r#type: "text", class: "form-control", id: "jersey_number", name: "jersey_number" }
                                            }
                                            div { class: "mb-3",
                                                label { r#for: "team", class: "form-label",
                                                    "Team "
                                                    button {
                                                        r#type: "button",
                                                        class: "btn btn-link p-0 ms-2 text-decoration-none border-0 align-baseline",
                                                        onclick: move |_| show_help_modal.set(true),
                                                        small { "(help, my team isn't listed!)" }
                                                    }
                                                }
                                                select { class: "form-select", id: "team", name: "team",
                                                    option { value: "", "No Team (unattached/free merc)" }
                                                    for team in d.teams_with_counts.iter() {
                                                        option { value: "{team.team_id}", "{team.pseudonym.as_deref().unwrap_or(&team.team_name)}" }
                                                    }
                                                }
                                                div { class: "form-text", "If you select a team, they will need to approve your request" }
                                            }
                                            div { class: "d-grid",
                                                button { r#type: "submit", class: "btn btn-primary", "Register Player" }
                                            }
                                        }
                                    }
                                } else {
                                    p { class: "text-muted",
                                        Link { to: Route::Login {}, "Log in" }
                                        " to register."
                                    }
                                }
                        }
                    }
                }
                else if let Some(Err(e)) = data.value().read().as_ref() {
                    div { class: "alert alert-danger", "{e}" }
                } else {
                    p { class: "text-muted", "Loading…" }
                }
                if show_help_modal() {
                    TeamRegistrationHelpModal {
                        context: String::from("league"),
                        on_close: move |_| show_help_modal.set(false),
                    }
                }
            }
        }
    }
}
