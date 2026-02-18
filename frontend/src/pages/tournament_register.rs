use crate::api;
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

fn get_form_check(id: &str) -> bool {
    let doc = web_sys::window().and_then(|w| w.document()).unwrap();
    doc.get_element_by_id(id)
        .and_then(|e| e.dyn_into::<web_sys::HtmlInputElement>().ok())
        .map(|e| e.checked())
        .unwrap_or(false)
}

#[component]
pub fn TournamentRegister(url: String) -> Element {
    let navigator = use_navigator();
    let url_for_data = url.clone();
    let data = use_resource(move || {
        let u = url_for_data.clone();
        async move { api::tournament_detail(&u).await.map_err(|e| e.to_string()) }
    });
    let me = use_resource(move || async move { api::me().await });
    let val = data.value();
    let _backend = api::base_url();
    let mut show_help_modal = use_signal(|| false);
    let mut register_error = use_signal(|| None::<String>);
    rsx! {
        if let Some(Ok(d)) = val.read().as_ref() {
            div { class: "row",
                div { class: "col-12",
                    h1 { "{d.tournament.name} - Registration" }
                    nav { aria_label: "breadcrumb",
                        ol { class: "breadcrumb",
                            li { class: "breadcrumb-item", Link { to: Route::TournamentHome { url: url.clone() }, "{d.tournament.name}" } }
                            li { class: "breadcrumb-item active", "Registration" }
                        }
                    }
                }
            }

            div { class: "row",
                div { class: "col-md-8",
                    if let Some(Ok(u)) = me.read().as_ref() {
                        if u.user_type == "player" {
                            div { class: "card",
                                div { class: "card-header", h5 { class: "mb-0", "Player Registration" } }
                                div { class: "card-body",
                                    if let Some(err) = register_error() {
                                        div { class: "alert alert-danger mb-3", "{err}" }
                                    }
                                    form {
                                        id: "player-register-form",
                                        onsubmit: move |ev| {
                                            ev.prevent_default();
                                            register_error.set(None);
                                            let u = url.clone();
                                            spawn(async move {
                                                let jersey_name = get_form_value("jersey_name");
                                                let jersey_number = get_form_value("jersey_number");
                                                let team = get_form_select_value("team");
                                                let agree_terms = get_form_check("agree_terms");
                                                match api::register_player(&u, &jersey_name, &jersey_number, &team, agree_terms).await {
                                                    Ok(res) if res.success => {
                                                        navigator.push(Route::TournamentHome { url: u });
                                                    }
                                                    Ok(res) => {
                                                        register_error.set(Some(res.error.unwrap_or_else(|| "Registration failed.".to_string())));
                                                    }
                                                    Err(e) => {
                                                        register_error.set(Some(e));
                                                    }
                                                }
                                            });
                                        },
                                        div { class: "mb-3",
                                            label { r#for: "jersey_name", class: "form-label", "Jersey Name" }
                                            input { r#type: "text", class: "form-control", id: "jersey_name", name: "jersey_name", required: true }
                                            div { class: "form-text", "Your name for this tournament" }
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
                                        if let Some(fee) = d.tournament.player_reg_fee {
                                            if fee > 0.0 {
                                                div { class: "mb-3",
                                                    div { class: "alert alert-info",
                                                        h6 { "Registration Fee" }
                                                        p {
                                                            strong { "Player Registration: " }
                                                            {format!("${:.2}", fee)}
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                        if let Some(link) = &d.tournament.terms_link {
                                            if !link.is_empty() {
                                                div { class: "mb-3",
                                                    div { class: "form-check",
                                                        input { class: "form-check-input", r#type: "checkbox", id: "agree_terms", name: "agree_terms", required: true }
                                                        label { class: "form-check-label", r#for: "agree_terms",
                                                            "I agree to the "
                                                            a { href: "{link}", target: "_blank", class: "text-decoration-none", "tournament terms and conditions" }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                        div { class: "d-grid",
                                            button { r#type: "submit", class: "btn btn-primary", "Register as Player" }
                                        }
                                    }
                                }
                            }
                        } else if u.user_type == "team" {
                            div { class: "card",
                                div { class: "card-header", h5 { class: "mb-0", "Team Registration" } }
                                div { class: "card-body",
                                    if let Some(err) = register_error() {
                                        div { class: "alert alert-danger mb-3", "{err}" }
                                    }
                                    form {
                                        id: "team-register-form",
                                        onsubmit: move |ev| {
                                            ev.prevent_default();
                                            register_error.set(None);
                                            let u = url.clone();
                                            spawn(async move {
                                                let pseudonym = get_form_value("pseudonym");
                                                let agree_terms = get_form_check("agree_terms_team");
                                                match api::register_team(&u, &pseudonym, agree_terms).await {
                                                    Ok(res) if res.success => {
                                                        navigator.push(Route::TournamentHome { url: u });
                                                    }
                                                    Ok(res) => {
                                                        register_error.set(Some(res.error.unwrap_or_else(|| "Registration failed.".to_string())));
                                                    }
                                                    Err(e) => {
                                                        register_error.set(Some(e));
                                                    }
                                                }
                                            });
                                        },
                                        div { class: "mb-3",
                                            label { r#for: "pseudonym", class: "form-label", "Team Name for This Tournament" }
                                            input { r#type: "text", class: "form-control", id: "pseudonym", name: "pseudonym", required: true }
                                            div { class: "form-text", "This is how your team will be referred to in this tournament" }
                                        }
                                        if let Some(fee) = d.tournament.team_reg_fee {
                                            if fee > 0.0 {
                                                div { class: "mb-3",
                                                    div { class: "alert alert-info",
                                                        h6 { "Registration Fee" }
                                                        p {
                                                            strong { "Team Registration: " }
                                                            {format!("${:.2}", fee)}
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                        if let Some(link) = &d.tournament.terms_link {
                                            if !link.is_empty() {
                                                div { class: "mb-3",
                                                    div { class: "form-check",
                                                        input { class: "form-check-input", r#type: "checkbox", id: "agree_terms_team", name: "agree_terms", required: true }
                                                        label { class: "form-check-label", r#for: "agree_terms_team",
                                                            "I agree to the "
                                                            a { href: "{link}", target: "_blank", class: "text-decoration-none", "tournament terms and conditions" }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                        div { class: "d-grid",
                                            button { r#type: "submit", class: "btn btn-primary", "Register Team" }
                                        }
                                    }
                                }
                            }
                        } else {
                            div { class: "alert alert-warning",
                                h4 { "Login Required" }
                                p { "You need to be logged in to register for this tournament." }
                                div { class: "d-flex gap-2",
                                    Link { to: Route::Login {}, class: "btn btn-primary", "Login as Player" }
                                    Link { to: Route::Login {}, class: "btn btn-outline-primary", "Login as Team" }
                                }
                            }
                        }
                    } else {
                        div { class: "alert alert-warning",
                            h4 { "Login Required" }
                            p { "You need to be logged in to register for this tournament." }
                            div { class: "d-flex gap-2",
                                Link { to: Route::Login {}, class: "btn btn-primary", "Login as Player" }
                                Link { to: Route::Login {}, class: "btn btn-outline-primary", "Login as Team" }
                            }
                        }
                    }
                }
            }

            if show_help_modal() {
                div {
                        class: "modal show d-block",
                        style: "background: rgba(0,0,0,0.5);",
                        tabindex: "-1",
                        role: "dialog",
                        aria_modal: "true",
                        onclick: move |_| show_help_modal.set(false),
                        div {
                            class: "modal-dialog modal-dialog-centered",
                            onclick: move |ev: Event<MouseData>| { ev.stop_propagation(); },
                            div { class: "modal-content",
                                div { class: "modal-header",
                                    h5 { class: "modal-title", id: "teamRegistrationHelpModalLabel", "Registration Help" }
                                    button {
                                        r#type: "button",
                                        class: "btn-close",
                                        aria_label: "Close",
                                        onclick: move |_| show_help_modal.set(false),
                                    }
                                }
                                div { class: "modal-body",
                                    p { "The registration process works in three steps:" }
                                    ol {
                                        li { strong { "Teams register first:" } " A team account must register for the tournament before players can join that team." }
                                        li { strong { "Players register under the team:" } " Once a team is registered, players can select that team from the dropdown and register to join them." }
                                        li { strong { "Team accepts the player:" } " After a player requests to join a team, the team must approve the player's request before they are officially on the roster." }
                                    }
                                    p { class: "mb-0",
                                        strong { "Don't see your team in the dropdown?" }
                                        " They may not have registered yet. Check the tournament homepage to see all registered teams. Ask your team to register the team first, then come back to complete your player registration."
                                    }
                                }
                                div { class: "modal-footer",
                                    button {
                                        r#type: "button",
                                        class: "btn btn-secondary",
                                        onclick: move |_| show_help_modal.set(false),
                                        "Close"
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
