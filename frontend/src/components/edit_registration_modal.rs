//! Edit registration modal for league or tournament context.
//! Shared between league home, tournament home (league events), etc.

use crate::api;
use crate::types::{UpdatePlayerRegistrationRequest, UpdateTeamRegistrationRequest};
use dioxus::prelude::*;

/// Context for the edit registration modal: league or tournament.
#[derive(Clone, PartialEq)]
pub enum EditRegistrationContext {
    League { league_url: String },
    Tournament { tournament_url: String },
}

impl EditRegistrationContext {
    fn league_url(&self) -> Option<String> {
        match self {
            EditRegistrationContext::League { league_url } => Some(league_url.clone()),
            _ => None,
        }
    }
    fn tournament_url(&self) -> Option<String> {
        match self {
            EditRegistrationContext::Tournament { tournament_url } => Some(tournament_url.clone()),
            _ => None,
        }
    }
}

#[component]
pub fn EditRegistrationModal(
    context: EditRegistrationContext,
    user_type: String,
    on_close: EventHandler<()>,
    on_success: EventHandler<()>,
) -> Element {
    let mut show_deregister_confirm = use_signal(|| false);
    let is_team = user_type == "team";

    rsx! {
        div {
            class: "modal show d-block",
            style: "background: rgba(0,0,0,0.5);",
            tabindex: "-1",
            role: "dialog",
            onclick: move |_| {
                on_close.call(());
                show_deregister_confirm.set(false);
            },
            div {
                class: "modal-dialog modal-dialog-centered",
                onclick: move |ev: Event<MouseData>| { ev.stop_propagation(); },
                div { class: "modal-content",
                    div { class: "modal-header",
                        h5 { class: "modal-title",
                            if is_team { "Edit Team Registration" } else { "Edit Player Registration" }
                        }
                        button {
                            r#type: "button",
                            class: "btn-close",
                            aria_label: "Close",
                            onclick: move |_| {
                                on_close.call(());
                                show_deregister_confirm.set(false);
                            },
                        }
                    }
                    div { class: "modal-body", style: "position: relative;",
                        if is_team {
                            EditTeamRegistrationContent {
                                context: context.clone(),
                                on_close: on_close.clone(),
                                on_success: on_success.clone(),
                            }
                        } else {
                            EditPlayerRegistrationContent {
                                context: context.clone(),
                                on_close: on_close.clone(),
                                on_success: on_success.clone(),
                            }
                        }
                        if show_deregister_confirm() {
                            DeregisterConfirmOverlay {
                                context: context.clone(),
                                is_team,
                                on_close: on_close.clone(),
                                on_success: on_success.clone(),
                                on_cancel: move |_| show_deregister_confirm.set(false),
                            }
                        }
                    }
                    div { class: "modal-footer",
                        button {
                            r#type: "button",
                            class: "btn btn-outline-danger",
                            onclick: move |_| show_deregister_confirm.set(true),
                            if is_team { "Deregister Team" } else { "Deregister Player" }
                        }
                        button {
                            r#type: "submit",
                            form: if is_team { "edit-team-registration-form" } else { "edit-player-registration-form" },
                            class: "btn btn-primary",
                            "Save"
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn DeregisterConfirmOverlay(
    context: EditRegistrationContext,
    is_team: bool,
    on_close: EventHandler<()>,
    on_success: EventHandler<()>,
    on_cancel: EventHandler<()>,
) -> Element {
    let league_url = context.league_url();
    let tournament_url = context.tournament_url();
    rsx! {
        div {
            class: "position-absolute top-0 start-0 w-100 h-100 d-flex align-items-center justify-content-center",
            style: "background: rgba(0,0,0,0.3); z-index: 1050; border-radius: 0.25rem;",
            onclick: move |_| on_cancel.call(()),
            div {
                class: "card shadow",
                onclick: move |ev: Event<MouseData>| { ev.stop_propagation(); },
                div { class: "card-body",
                    p { class: "mb-3",
                        if is_team {
                            "Are you sure you want to deregister your team? Your team will be removed."
                        } else {
                            "Are you sure you want to deregister? You will be removed."
                        }
                    }
                    div { class: "d-flex gap-2 justify-content-end",
                        button {
                            r#type: "button",
                            class: "btn btn-secondary",
                            onclick: move |_| on_cancel.call(()),
                            "Cancel"
                        }
                        button {
                            r#type: "button",
                            class: "btn btn-danger",
                            onclick: move |_| {
                                on_close.call(());
                                if let Some(lu) = league_url.clone() {
                                    if is_team {
                                        spawn(async move {
                                            let _ = api::league_deregister_team(&lu).await;
                                            on_success.call(());
                                        });
                                    } else {
                                        spawn(async move {
                                            let _ = api::league_deregister_player(&lu).await;
                                            on_success.call(());
                                        });
                                    }
                                } else if let Some(tu) = tournament_url.clone() {
                                    if is_team {
                                        spawn(async move {
                                            let _ = api::deregister_team(&tu).await;
                                            on_success.call(());
                                        });
                                    } else {
                                        spawn(async move {
                                            let _ = api::deregister_player(&tu).await;
                                            on_success.call(());
                                        });
                                    }
                                }
                            },
                            "Deregister"
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn EditPlayerRegistrationContent(
    context: EditRegistrationContext,
    on_close: EventHandler<()>,
    on_success: EventHandler<()>,
) -> Element {
    let mut jersey_name = use_signal(|| "".to_string());
    let mut jersey_number = use_signal(|| "".to_string());
    let mut team = use_signal(|| "".to_string());
    let mut current_team_name = use_signal(|| "".to_string());
    let mut status = use_signal(|| "".to_string());
    let mut teams = use_signal(|| vec![]);
    let mut error = use_signal(|| None::<String>);
    let mut loading = use_signal(|| true);

    let context_clone = context.clone();
    let _fetch = use_resource(move || {
        let ctx = context_clone.clone();
        async move {
            loading.set(true);
            let (reg_res, teams_res) = match &ctx {
                EditRegistrationContext::League { league_url } => (
                    api::get_my_player_registration_league(league_url).await,
                    api::league_detail(league_url).await.map(|d| d.teams_with_counts),
                ),
                EditRegistrationContext::Tournament { tournament_url } => (
                    api::get_my_player_registration(tournament_url).await,
                    api::tournament_detail(tournament_url)
                        .await
                        .map(|d| d.teams_with_counts),
                ),
            };

            match (reg_res, teams_res) {
                (Ok(res), Ok(teams_list)) => {
                    jersey_name.set(res.registration.jersey_name.unwrap_or_default());
                    jersey_number.set(res.registration.jersey_number.unwrap_or_default());
                    status.set(res.registration.status.clone());
                    if let Some(ref ct) = res.current_team {
                        current_team_name.set(ct.pseudonym.clone().unwrap_or_else(|| ct.id.clone()));
                    }
                    let mut t_list = vec![];
                    for t in teams_list {
                        t_list.push((
                            t.team_id.clone(),
                            t.pseudonym.unwrap_or(t.team_name),
                        ));
                    }
                    teams.set(t_list);
                    let selected_team = res
                        .registration
                        .team
                        .clone()
                        .or_else(|| res.current_team.as_ref().map(|c| c.id.clone()))
                        .unwrap_or_default();
                    team.set(selected_team);
                }
                (Err(e), _) => error.set(Some(format!("Failed to load registration: {}", e))),
                (_, Err(e)) => error.set(Some(format!("Failed to load details: {}", e))),
            }
            loading.set(false);
        }
    });

    let context_for_submit = context.clone();
    let onsubmit = move |_evt: Event<FormData>| {
        let ctx = context_for_submit.clone();
        let on_close = on_close.clone();
        let on_success = on_success.clone();
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
            let res = match &ctx {
                EditRegistrationContext::League { league_url } => {
                    api::update_my_player_registration_league(league_url, &req).await
                }
                EditRegistrationContext::Tournament { tournament_url } => {
                    api::update_my_player_registration(tournament_url, &req).await
                }
            };
            match res {
                Ok(_) => {
                    on_close.call(());
                    on_success.call(());
                }
                Err(e) => {
                    error.set(Some(e));
                    loading.set(false);
                }
            }
        }
    };

    rsx! {
        if loading() {
            div { class: "d-flex justify-content-center",
                div { class: "spinner-border", role: "status",
                    span { class: "visually-hidden", "Loading..." }
                }
            }
        } else {
            if let Some(err) = error() {
                div { class: "alert alert-danger mb-3", "{err}" }
            }
            form {
                id: "edit-player-registration-form",
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
                        option { value: "", selected: team().is_empty(), "No Team (unattached/free merc)" }
                        for (id, name) in teams() {
                            option { value: "{id}", selected: id == team(), "{name}" }
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
            }
        }
    }
}

#[component]
fn EditTeamRegistrationContent(
    context: EditRegistrationContext,
    on_close: EventHandler<()>,
    on_success: EventHandler<()>,
) -> Element {
    let mut pseudonym = use_signal(|| "".to_string());
    let mut error = use_signal(|| None::<String>);
    let mut loading = use_signal(|| true);

    let context_clone = context.clone();
    let _fetch = use_resource(move || {
        let ctx = context_clone.clone();
        async move {
            loading.set(true);
            let res = match &ctx {
                EditRegistrationContext::League { league_url } => {
                    api::get_my_team_registration_league(league_url).await
                }
                EditRegistrationContext::Tournament { tournament_url } => {
                    api::get_my_team_registration(tournament_url).await
                }
            };
            match res {
                Ok(r) => pseudonym.set(r.registration.pseudonym.unwrap_or_default()),
                Err(e) => error.set(Some(e)),
            }
            loading.set(false);
        }
    });

    let context_for_submit = context.clone();
    let onsubmit = move |_evt: Event<FormData>| {
        let ctx = context_for_submit.clone();
        let on_close = on_close.clone();
        let on_success = on_success.clone();
        async move {
            loading.set(true);
            error.set(None);
            let req = UpdateTeamRegistrationRequest {
                pseudonym: Some(pseudonym()),
            };
            let res = match &ctx {
                EditRegistrationContext::League { league_url } => {
                    api::update_my_team_registration_league(league_url, &req).await
                }
                EditRegistrationContext::Tournament { tournament_url } => {
                    api::update_my_team_registration(tournament_url, &req).await
                }
            };
            match res {
                Ok(_) => {
                    on_close.call(());
                    on_success.call(());
                }
                Err(e) => {
                    error.set(Some(e));
                    loading.set(false);
                }
            }
        }
    };

    rsx! {
        if loading() {
            div { class: "d-flex justify-content-center",
                div { class: "spinner-border", role: "status",
                    span { class: "visually-hidden", "Loading..." }
                }
            }
        } else {
            if let Some(err) = error() {
                div { class: "alert alert-danger mb-3", "{err}" }
            }
            form {
                id: "edit-team-registration-form",
                onsubmit: onsubmit,
                div { class: "mb-3",
                    label { class: "form-label", "Team Name for This Tournament" }
                    input {
                        class: "form-control",
                        "type": "text",
                        value: "{pseudonym}",
                        oninput: move |e| pseudonym.set(e.value()),
                        required: true
                    }
                }
            }
        }
    }
}
