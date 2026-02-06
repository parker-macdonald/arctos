use crate::api;
use crate::types::{UpdatePlayerRegistrationRequest};
use dioxus::prelude::*;
use dioxus::prelude::use_navigator;
use crate::Route;

#[component]
pub fn EditPlayerRegistration(tournament_url: String) -> Element {
    let nav = use_navigator();
    let mut jersey_name = use_signal(|| "".to_string());
    let mut jersey_number = use_signal(|| "".to_string());
    let mut team = use_signal(|| "".to_string());
    let mut current_team_name = use_signal(|| "".to_string());
    let mut status = use_signal(|| "".to_string());
    
    let mut teams = use_signal(|| vec![]);
    
    let mut error = use_signal(|| None::<String>);
    let mut loading = use_signal(|| true);

    let _fetch = use_resource(use_reactive(&tournament_url, move |url| async move {
        loading.set(true);
        let reg_res = api::get_my_player_registration(&url).await;
        let detail_res = api::tournament_detail(&url).await;
        
        match (reg_res, detail_res) {
            (Ok(res), Ok(detail)) => {
                jersey_name.set(res.registration.jersey_name.unwrap_or_default());
                jersey_number.set(res.registration.jersey_number.unwrap_or_default());
                let reg_team = res.registration.team.unwrap_or_default();
                if reg_team.is_empty() {
                    if let Some(ct) = res.current_team.as_ref() {
                        team.set(ct.id.clone());
                    } else {
                        team.set(reg_team);
                    }
                } else {
                    team.set(reg_team);
                }
                status.set(res.registration.status);
                
                if let Some(ct) = res.current_team {
                    current_team_name.set(ct.pseudonym.unwrap_or(ct.id));
                }
                
                // Extract teams from detail
                let mut t_list = vec![];
                for t in detail.teams_with_counts {
                    t_list.push((t.team_id, t.pseudonym.unwrap_or(t.team_name)));
                }
                teams.set(t_list);
            }
            (Err(e), _) => error.set(Some(format!("Failed to load registration: {}", e))),
            (_, Err(e)) => error.set(Some(format!("Failed to load tournament details: {}", e))),
        }
        loading.set(false);
    }));

    let tournament_url_for_submit = tournament_url.clone();
    let onsubmit = move |_evt: Event<FormData>| {
        let tournament_url = tournament_url_for_submit.clone();
        async move {
            loading.set(true);
            error.set(None);
            
            let t_val = team();
            let team_opt = if t_val.is_empty() { None } else { Some(t_val) };
            
            let req = UpdatePlayerRegistrationRequest {
                jersey_name: Some(jersey_name()),
                jersey_number: Some(jersey_number()),
                team: team_opt,
            };

            match api::update_my_player_registration(&tournament_url, &req).await {
                Ok(_) => {
                    nav.push(Route::TournamentHome { url: tournament_url.clone() });
                }
                Err(e) => {
                    error.set(Some(e));
                    loading.set(false);
                }
            }
        }
    };

    rsx! {
        div { class: "row",
                div { class: "col-12",
                    h1 { "Edit Player Registration" }
                    nav { "aria-label": "breadcrumb",
                        ol { class: "breadcrumb",
                            li { class: "breadcrumb-item",
                                Link { to: Route::TournamentHome { url: tournament_url.clone() }, "{tournament_url}" }
                            }
                            li { class: "breadcrumb-item active", "Edit Registration" }
                        }
                    }
                }
            }
            
        if loading() {
            div { class: "d-flex justify-content-center",
                div { class: "spinner-border", role: "status",
                    span { class: "visually-hidden", "Loading..." }
                }
            }
        } else {
            div { class: "row justify-content-center",
                div { class: "col-md-8",
                    div { class: "card",
                        div { class: "card-header",
                            h5 { class: "mb-0", "Player Registration" }
                        }
                        div { class: "card-body",
                            if let Some(err) = error() {
                                div { class: "alert alert-danger", "{err}" }
                            }
                            form {
                                onsubmit: onsubmit,
                                div { class: "mb-3",
                                        label { class: "form-label", "Jersey Name" }
                                        input {
                                            class: "form-control",
                                            "type": "text",
                                            value: "{jersey_name}",
                                            oninput: move |e| jersey_name.set(e.value()),
                                            required: true
                                        }
                                        div { class: "form-text", "Your name for this tournament" }
                                    }
                                    
                                    div { class: "mb-3",
                                        label { class: "form-label", "Jersey Number" }
                                        input {
                                            class: "form-control",
                                            "type": "text",
                                            value: "{jersey_number}",
                                            oninput: move |e| jersey_number.set(e.value())
                                        }
                                    }
                                    
                                    div { class: "mb-3",
                                        label { class: "form-label", "Team" }
                                        select {
                                            class: "form-select",
                                            value: "{team}",
                                            onchange: move |e| team.set(e.value()),
                                            option { value: "", "No Team (unattached/free merc)" }
                                            for (id, name) in teams() {
                                                option { value: "{id}", "{name}" }
                                            }
                                        }
                                        div { class: "form-text",
                                            if !current_team_name().is_empty() {
                                                span { "Current team: {current_team_name} " }
                                                if status() == "PENDING_TEAM_APPROVAL" {
                                                    span { class: "badge bg-warning", "Pending Approval" }
                                                }
                                            }
                                            br {}
                                            "If you change teams, your new team must approve your request."
                                        }
                                    }
                                    
                                    div { class: "d-grid gap-2 d-md-flex justify-content-md-end",
                                        Link {
                                            class: "btn btn-outline-secondary",
                                            to: Route::TournamentHome { url: tournament_url.clone() },
                                            "Cancel"
                                        }
                                        button { class: "btn btn-primary", "type": "submit", "Update Registration" }
                                    }
                            }
                        }
                    }
                }
            }
        }
    }
}
