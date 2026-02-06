use crate::api;
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn TournamentSettings(url: String) -> Element {
    let url_for_data = url.clone();
    let data = use_resource(move || {
        let u = url_for_data.clone();
        async move { api::tournament_detail(&u).await.map_err(|e| e.to_string()) }
    });
    let val = data.value();
    let backend = api::base_url();
    let update_url = format!("{}/{}/update-settings", backend, url);
    rsx! {
        if let Some(Ok(d)) = val.read().as_ref() {
            div { class: "row",
                div { class: "col-12",
                    h1 { "{d.tournament.name} - Settings" }
                    nav { aria_label: "breadcrumb",
                        ol { class: "breadcrumb",
                            li { class: "breadcrumb-item", Link { to: Route::TournamentHome { url: url.clone() }, "{d.tournament.name}" } }
                            li { class: "breadcrumb-item active", "Settings" }
                        }
                    }
                }
            }

            div { class: "row",
                div { class: "col-md-8",
                    div { class: "card",
                        div { class: "card-header",
                            h5 { class: "mb-0", "Tournament Information" }
                        }
                        div { class: "card-body",
                            form { method: "POST", action: "{update_url}",
                                div { class: "row",
                                    div { class: "col-md-6",
                                        div { class: "mb-3",
                                            label { r#for: "name", class: "form-label", "Tournament Name" }
                                            input { r#type: "text", class: "form-control", id: "name", name: "name", value: "{d.tournament.name}", required: true }
                                        }
                                    }
                                    div { class: "col-md-6",
                                        div { class: "mb-3",
                                            label { r#for: "location", class: "form-label", "Location" }
                                            input { r#type: "text", class: "form-control", id: "location", name: "location", value: "{d.tournament.location.as_deref().unwrap_or(\"\")}" }
                                        }
                                    }
                                }

                                div { class: "row",
                                    div { class: "col-md-6",
                                        div { class: "mb-3",
                                            label { r#for: "start_date", class: "form-label", "Start Date" }
                                            input { r#type: "date", class: "form-control", id: "start_date", name: "start_date", value: "{d.tournament.start_date.split('T').next().unwrap_or(&d.tournament.start_date)}", required: true }
                                        }
                                    }
                                    div { class: "col-md-6",
                                        div { class: "mb-3",
                                            label { r#for: "end_date", class: "form-label", "End Date" }
                                            input { r#type: "date", class: "form-control", id: "end_date", name: "end_date", value: "{d.tournament.end_date.as_deref().unwrap_or(\"\")}" }
                                        }
                                    }
                                    div { class: "col-md-6",
                                        div { class: "mb-3",
                                            label { r#for: "num_fields", class: "form-label", "Number of Fields" }
                                            input { r#type: "number", class: "form-control", id: "num_fields", name: "num_fields", value: "{d.tournament.num_fields.unwrap_or(1)}", min: "1" }
                                        }
                                    }
                                }

                                div { class: "row",
                                    div { class: "col-md-6",
                                        div { class: "mb-3",
                                            label { r#for: "n_max_teams", class: "form-label", "Max Teams" }
                                            input { r#type: "number", class: "form-control", id: "n_max_teams", name: "n_max_teams", value: "{d.tournament.n_max_teams.map(|v| v.to_string()).unwrap_or_default()}", min: "1" }
                                        }
                                    }
                                    div { class: "col-md-6",
                                        div { class: "mb-3",
                                            label { r#for: "max_team_size_roster", class: "form-label", "Max Team Size (Roster)" }
                                            input { r#type: "number", class: "form-control", id: "max_team_size_roster", name: "max_team_size_roster", value: "{d.tournament.max_team_size_roster.map(|v| v.to_string()).unwrap_or_default()}", min: "1" }
                                            div { class: "form-text", "Maximum players on team roster" }
                                        }
                                    }
                                }

                                div { class: "row",
                                    div { class: "col-md-6",
                                        div { class: "mb-3",
                                            label { r#for: "max_team_size_field", class: "form-label", "Max Team Size (Field)" }
                                            input { r#type: "number", class: "form-control", id: "max_team_size_field", name: "max_team_size_field", value: "{d.tournament.max_team_size_field.map(|v| v.to_string()).unwrap_or_default()}", min: "1" }
                                            div { class: "form-text", "Maximum players on field at once" }
                                        }
                                    }
                                }

                                div { class: "row",
                                    div { class: "col-md-6",
                                        div { class: "mb-3",
                                            label { r#for: "team_reg_fee", class: "form-label", "Team Registration Fee" }
                                            div { class: "input-group",
                                                span { class: "input-group-text", "$" }
                                                input { r#type: "number", class: "form-control", id: "team_reg_fee", name: "team_reg_fee", value: "{d.tournament.team_reg_fee.unwrap_or(0.0)}", step: "0.01", min: "0" }
                                            }
                                        }
                                    }
                                    div { class: "col-md-6",
                                        div { class: "mb-3",
                                            label { r#for: "player_reg_fee", class: "form-label", "Player Registration Fee" }
                                            div { class: "input-group",
                                                span { class: "input-group-text", "$" }
                                                input { r#type: "number", class: "form-control", id: "player_reg_fee", name: "player_reg_fee", value: "{d.tournament.player_reg_fee.unwrap_or(0.0)}", step: "0.01", min: "0" }
                                            }
                                        }
                                    }
                                }

                                div { class: "mb-3",
                                    label { r#for: "about", class: "form-label", "About" }
                                    textarea { class: "form-control", id: "about", name: "about", rows: "4", "{d.tournament.about.as_deref().unwrap_or(\"\")}" }
                                    div { class: "form-text",
                                        "supports "
                                        a { href: "https://www.markdownguide.org/basic-syntax/", "markdown" }
                                        ", including most of the "
                                        a { href: "https://www.markdownguide.org/extended-syntax/", "extended syntax" }
                                        ". Images can be inserted with "
                                        code { "![alt text](https://image_url)" }
                                        ", and links with "
                                        code { "[text](link)" }
                                        "."
                                    }
                                }

                                div { class: "mb-3",
                                    label { r#for: "terms_link", class: "form-label", "Terms and Conditions Link" }
                                    input { r#type: "url", class: "form-control", id: "terms_link", name: "terms_link", value: "{d.tournament.terms_link.as_deref().unwrap_or(\"\")}", placeholder: "https://example.com/terms" }
                                    div { class: "form-text", "If given, teams and players must agree to these terms upon registration." }
                                }

                                h3 { "Head Ref Options" }
                                p {
                                    "This website was designed around having dedicated head refs. However, this is not always feasible, so there are a few other options. "
                                    "If you do any of these, please make sure to communicate to players how the system works, in particular that "
                                    i { "you cannot un-start a match!" }
                                    br {}
                                    "Explicitly listed player usernames will always be allowed, regardless of their registration status. "
                                    "Anyone else must be registered if they want to head ref."
                                    br {}
                                    b { "Please note that only players are allowed to head ref, not teams. This is to enforce accountability for ref responsibilities, as team accounts are/can be shared." }
                                }
                                div { class: "mb-3",
                                    label { r#for: "head_refs_allowed_list", class: "form-label", "Explicit List of Allowed Usernames" }
                                    input { r#type: "text", class: "form-control", id: "head_refs_allowed_list", name: "head_refs_allowed_list", value: "{d.tournament.head_refs_allowed_list.as_deref().unwrap_or(\"\")}", placeholder: "player1,player2,player3" }
                                    div { class: "form-text", "Comma-separated list of player IDs who can ref matches" }
                                }
                                div { class: "mb-3",
                                    div { class: "form-check",
                                        input { class: "form-check-input", r#type: "checkbox", id: "head_refs_allow_anyone", name: "head_refs_allow_anyone", checked: d.tournament.head_refs_allow_anyone }
                                        label { class: "form-check-label", r#for: "head_refs_allow_anyone", "Allow anyone to run matches" }
                                        div { class: "form-text", "When enabled, players who are registered for the tournament can head ref all matches." }
                                    }
                                }
                                div { id: "head_ref_specific_options",
                                    div { class: "mb-3",
                                        div { class: "form-check",
                                            input { class: "form-check-input", r#type: "checkbox", id: "head_refs_allow_reffing_teams", name: "head_refs_allow_reffing_teams", checked: d.tournament.head_refs_allow_reffing_teams }
                                            label { class: "form-check-label", r#for: "head_refs_allow_reffing_teams", "Allow reffing teams to head ref" }
                                            div { class: "form-text", "When enabled, players on teams assigned to ref a match can head ref that match." }
                                        }
                                    }
                                }

                                h3 { "Publication Status" }
                                div { class: "mb-3",
                                    div { class: "form-check",
                                        input { class: "form-check-input", r#type: "checkbox", id: "published", name: "published", checked: d.tournament.published }
                                        label { class: "form-check-label", r#for: "published", "Published" }
                                        div { class: "form-text", "show this tournament on the homepage!" }
                                    }
                                }
                                div { class: "mb-3",
                                    div { class: "form-check",
                                        input { class: "form-check-input", r#type: "checkbox", id: "schedule_published", name: "schedule_published", checked: d.tournament.schedule_published }
                                        label { class: "form-check-label", r#for: "schedule_published", "Schedule Published (schedule visible to public)" }
                                        div { class: "form-text", "show the schedule will be visible to all users. Still visible to TOs and head refs if unchecked." }
                                    }
                                }
                                div { class: "mb-3",
                                    div { class: "form-check",
                                        input { class: "form-check-input", r#type: "checkbox", id: "registration_open", name: "registration_open", checked: d.tournament.registration_open }
                                        label { class: "form-check-label", r#for: "registration_open", "Registration Open" }
                                    }
                                }

                                div { class: "d-grid",
                                    button { r#type: "submit", class: "btn btn-primary", "Save Settings" }
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
