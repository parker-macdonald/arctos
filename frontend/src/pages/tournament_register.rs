use crate::api;
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn TournamentRegister(url: String) -> Element {
    let url_for_data = url.clone();
    let data = use_resource(move || {
        let u = url_for_data.clone();
        async move { api::tournament_detail(&u).await.map_err(|e| e.to_string()) }
    });
    let me = use_resource(move || async move { api::me().await });
    let val = data.value();
    let backend = api::base_url();
    let register_player_action = format!("{}/{}/register-player", backend, url);
    let register_team_action = format!("{}/{}/register-team", backend, url);
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
                                    form { method: "POST", action: "{register_player_action}",
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
                                                a { href: "#", class: "text-decoration-none ms-2", "data-bs-toggle": "modal", "data-bs-target": "#teamRegistrationHelpModal",
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
                                    form { method: "POST", action: "{register_team_action}",
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

                div { class: "col-md-4",
                    div { class: "card",
                        div { class: "card-header", h5 { class: "mb-0", "Tournament Information" } }
                        div { class: "card-body",
                            p { strong { "Date: " }
                                if let Some(end) = &d.tournament.end_date {
                                    if end != &d.tournament.start_date {
                                        "{d.tournament.start_date} - {end}"
                                    } else {
                                        "{d.tournament.start_date}"
                                    }
                                } else {
                                    "{d.tournament.start_date}"
                                }
                            }
                            p { strong { "Location: " } "{d.tournament.location.as_deref().unwrap_or(\"TBA\")}" }
                            p { strong { "Fields: " } "{d.tournament.num_fields.unwrap_or(1)}" }
                            if let Some(max) = d.tournament.n_max_teams {
                                p { strong { "Max Teams: " } "{max}" }
                            }
                            if let Some(max_team) = d.tournament.max_team_size_roster {
                                p { strong { "Max Team Size: " } "{max_team}" }
                            }
                        }
                    }

                    if let Some(about) = &d.tournament.about {
                        if !about.is_empty() {
                            div { class: "card mt-3",
                                div { class: "card-header", h5 { class: "mb-0", "About" } }
                                div { class: "card-body", "{about}" }
                            }
                        }
                    }
                }
            }

            div { class: "modal fade", id: "teamRegistrationHelpModal", tabindex: "-1", aria_labelledby: "teamRegistrationHelpModalLabel", aria_hidden: "true",
                div { class: "modal-dialog",
                    div { class: "modal-content",
                        div { class: "modal-header",
                            h5 { class: "modal-title", id: "teamRegistrationHelpModalLabel", "Registration Help" }
                            button { r#type: "button", class: "btn-close", "data-bs-dismiss": "modal", aria_label: "Close" }
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
                            button { r#type: "button", class: "btn btn-secondary", "data-bs-dismiss": "modal", "Close" }
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
