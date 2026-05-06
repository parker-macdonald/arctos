use crate::api;
use crate::types::{CheckinResponse, PlayerListItem};
use crate::Route;
use dioxus::prelude::*;

#[derive(Clone, Copy, Debug, PartialEq)]
enum TabKind {
    Players,
    Teams,
}

#[derive(Clone, Debug, PartialEq)]
enum SessionLogEntry {
    Player {
        player_id: String,
        player_name: String,
        team: Option<String>,
        jersey_name: String,
        jersey_number: String,
    },
    Team {
        team_id: String,
        team_name: String,
        pseudonym: String,
    },
}

#[component]
pub fn OrganizerCheckin(url: String) -> Element {
    let navigator = use_navigator();
    let url_for_data = url.clone();

    let info = use_resource(move || {
        let u = url_for_data.clone();
        async move { api::checkin_info(&u).await }
    });

    // Search state
    let mut search_query = use_signal(String::new);
    let mut search_results = use_signal(Vec::<PlayerListItem>::new);
    let mut searching = use_signal(|| false);

    // Form state
    let mut selected_player = use_signal(|| None::<PlayerListItem>);
    let mut selected_team = use_signal(String::new);
    let mut jersey_number = use_signal(String::new);
    let mut jersey_name_input = use_signal(String::new);
    let mut waiver_signature = use_signal(String::new);

    // Submission state
    let mut submit_error = use_signal(|| None::<String>);
    let mut submitting = use_signal(|| false);
    let mut session_log = use_signal(Vec::<SessionLogEntry>::new);

    // Tab state
    let mut active_tab = use_signal(|| TabKind::Players);

    // Team tab signals
    let mut team_search_query = use_signal(String::new);
    let mut team_search_results = use_signal(Vec::<crate::types::TeamListItem>::new);
    let mut team_searching = use_signal(|| false);
    let mut selected_team_for_register = use_signal(|| None::<crate::types::TeamListItem>);
    let mut team_pseudonym_input = use_signal(String::new);

    // Search effect: refetch whenever the query changes.
    use_effect(move || {
        let q = search_query();
        if q.trim().is_empty() {
            search_results.set(Vec::new());
            return;
        }
        searching.set(true);
        spawn(async move {
            match api::players_list(&q, 1).await {
                Ok(resp) => search_results.set(resp.players),
                Err(_) => search_results.set(Vec::new()),
            }
            searching.set(false);
        });
    });

    // Team search effect: refetch whenever the team query changes.
    use_effect(move || {
        let q = team_search_query();
        if q.trim().is_empty() {
            team_search_results.set(Vec::new());
            return;
        }
        team_searching.set(true);
        spawn(async move {
            match api::teams_list(&q).await {
                Ok(resp) => team_search_results.set(resp.teams),
                Err(_) => team_search_results.set(Vec::new()),
            }
            team_searching.set(false);
        });
    });

    rsx! {
        match info.read().as_ref() {
            None => rsx! { p { class: "text-muted", "Loading..." } },
            Some(Err(e)) => rsx! {
                div { class: "row",
                    div { class: "col-12",
                        div { class: "alert alert-danger", "{e}" }
                    }
                }
            },
            Some(Ok(info)) => {
                if !info.organizer_checkin_enabled {
                    rsx! {
                        div { class: "row",
                            div { class: "col-12",
                                div { class: "alert alert-info",
                                    "This tournament does not use organizer check-in."
                                }
                            }
                        }
                    }
                } else {
                    let teams = info.teams.clone();
                    let waiver_required = info.waiver_required;
                    let waiver_url = info.waiver_url.clone();
                    let backend = api::base_url();
                    let url_submit = url.clone();
                    let url_team_submit = url.clone();

                    rsx! {
                        div { class: "row",
                            div { class: "col-12",
                                h1 { "Event Check-in" }
                                p { class: "text-muted",
                                    "Add players or teams to this event."
                                }
                            }
                        }

                        div { class: "row mb-3",
                            div { class: "col-12",
                                ul { class: "nav nav-tabs",
                                    li { class: "nav-item",
                                        button {
                                            r#type: "button",
                                            class: if active_tab() == TabKind::Players { "nav-link active" } else { "nav-link" },
                                            onclick: move |_| { active_tab.set(TabKind::Players); submit_error.set(None); },
                                            "Players"
                                        }
                                    }
                                    li { class: "nav-item",
                                        button {
                                            r#type: "button",
                                            class: if active_tab() == TabKind::Teams { "nav-link active" } else { "nav-link" },
                                            onclick: move |_| { active_tab.set(TabKind::Teams); submit_error.set(None); },
                                            "Teams"
                                        }
                                    }
                                }
                            }
                        }

                        if let Some(err) = submit_error() {
                            div { class: "row",
                                div { class: "col-12",
                                    div { class: "alert alert-danger", "{err}" }
                                }
                            }
                        }

                        div { class: "row",
                            div { class: "col-md-8",
                                if active_tab() == TabKind::Players {
                                    // Search card
                                    div { class: "card mb-3",
                                        div { class: "card-header", h5 { class: "mb-0", "Find Player" } }
                                        div { class: "card-body",
                                            input {
                                                r#type: "text",
                                                class: "form-control mb-2",
                                                placeholder: "Search by name or username",
                                                value: "{search_query()}",
                                                oninput: move |e| search_query.set(e.value()),
                                            }
                                            if searching() {
                                                p { class: "text-muted small mb-0", "Searching..." }
                                            }
                                            if !search_results().is_empty() {
                                                ul { class: "list-group",
                                                    for p in search_results().iter().cloned() {
                                                        li {
                                                            class: "list-group-item d-flex justify-content-between align-items-center",
                                                            div {
                                                                strong { "{p.name}" }
                                                                span { class: "text-muted ms-2", "@{p.id}" }
                                                            }
                                                            button {
                                                                class: "btn btn-sm btn-primary",
                                                                r#type: "button",
                                                                onclick: move |_| {
                                                                    selected_player.set(Some(p.clone()));
                                                                    search_query.set(String::new());
                                                                    search_results.set(Vec::new());
                                                                },
                                                                "Select"
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }

                                    // Selected player + form
                                    if let Some(player) = selected_player() {
                                        div { class: "card mb-3",
                                            div { class: "card-header d-flex justify-content-between align-items-center",
                                                h5 { class: "mb-0", "Checking In: {player.name}" }
                                                button {
                                                    class: "btn btn-sm btn-outline-secondary",
                                                    r#type: "button",
                                                    onclick: move |_| {
                                                        selected_player.set(None);
                                                        selected_team.set(String::new());
                                                        jersey_number.set(String::new());
                                                        jersey_name_input.set(String::new());
                                                        waiver_signature.set(String::new());
                                                    },
                                                    "Change"
                                                }
                                            }
                                            div { class: "card-body",
                                                form {
                                                    onsubmit: move |ev| {
                                                        ev.prevent_default();
                                                        if submitting() { return; }

                                                        let player = match selected_player() {
                                                            Some(p) => p,
                                                            None => return,
                                                        };
                                                        let u = url_submit.clone();
                                                        let team_val = selected_team();
                                                        let jersey_num = jersey_number();
                                                        let jersey_nm = jersey_name_input();
                                                        let waiver_sig = waiver_signature();

                                                        submit_error.set(None);
                                                        submitting.set(true);

                                                        spawn(async move {
                                                            let team_opt = if team_val.is_empty() {
                                                                None
                                                            } else {
                                                                Some(team_val.as_str())
                                                            };
                                                            let result: Result<CheckinResponse, String> = api::checkin(
                                                                &u,
                                                                &player.id,
                                                                team_opt,
                                                                &jersey_num,
                                                                &jersey_nm,
                                                                &waiver_sig,
                                                            )
                                                            .await;
                                                            submitting.set(false);
                                                            match result {
                                                                Ok(res) if res.success => {
                                                                    session_log.with_mut(|log| {
                                                                        log.insert(0, SessionLogEntry::Player {
                                                                            player_id: res.player_id.unwrap_or_default(),
                                                                            player_name: res.player_name.unwrap_or_default(),
                                                                            team: res.team,
                                                                            jersey_name: res.jersey_name.unwrap_or_else(|| "N/A".into()),
                                                                            jersey_number: res.jersey_number.unwrap_or_else(|| "0".into()),
                                                                        });
                                                                    });
                                                                    selected_player.set(None);
                                                                    selected_team.set(String::new());
                                                                    jersey_number.set(String::new());
                                                                    jersey_name_input.set(String::new());
                                                                    waiver_signature.set(String::new());
                                                                }
                                                                Ok(res) => {
                                                                    submit_error.set(Some(
                                                                        res.error.unwrap_or_else(|| "Check-in failed.".into()),
                                                                    ));
                                                                }
                                                                Err(e) => submit_error.set(Some(e)),
                                                            }
                                                        });
                                                    },

                                                    div { class: "mb-3",
                                                        label { r#for: "team", class: "form-label", "Team" }
                                                        select {
                                                            class: "form-select",
                                                            id: "team",
                                                            value: "{selected_team()}",
                                                            onchange: move |e| selected_team.set(e.value()),
                                                            option { value: "", "Unaffiliated (Merc)" }
                                                            for team in teams.iter() {
                                                                option { value: "{team.id}", "{team.pseudonym}" }
                                                            }
                                                        }
                                                    }
                                                    div { class: "mb-3",
                                                        label { r#for: "jersey_number", class: "form-label", "Jersey Number" }
                                                        input {
                                                            r#type: "text",
                                                            class: "form-control",
                                                            id: "jersey_number",
                                                            placeholder: "0",
                                                            value: "{jersey_number()}",
                                                            oninput: move |e| jersey_number.set(e.value()),
                                                        }
                                                    }
                                                    div { class: "mb-3",
                                                        label { r#for: "jersey_name", class: "form-label", "Jersey Name" }
                                                        input {
                                                            r#type: "text",
                                                            class: "form-control",
                                                            id: "jersey_name",
                                                            placeholder: "N/A",
                                                            value: "{jersey_name_input()}",
                                                            oninput: move |e| jersey_name_input.set(e.value()),
                                                        }
                                                    }
                                                    if waiver_required {
                                                        div { class: "mb-3",
                                                            if let Some(ref wurl) = waiver_url {
                                                                p { class: "form-text mb-2",
                                                                    "Waiver file: "
                                                                    a {
                                                                        href: "{backend}{wurl}",
                                                                        target: "_blank",
                                                                        class: "text-decoration-none",
                                                                        "{backend}{wurl}"
                                                                    }
                                                                }
                                                            }
                                                            p { class: "form-text mb-2",
                                                                "Enter the player's full legal name to record waiver acceptance."
                                                            }
                                                            label { r#for: "waiver_signature", class: "form-label", "Player's Legal Name" }
                                                            input {
                                                                r#type: "text",
                                                                class: "form-control",
                                                                id: "waiver_signature",
                                                                value: "{waiver_signature()}",
                                                                oninput: move |e| waiver_signature.set(e.value()),
                                                                required: true,
                                                                placeholder: "Player's full legal name",
                                                            }
                                                        }
                                                    }
                                                    div { class: "d-grid",
                                                        button {
                                                            r#type: "submit",
                                                            class: "btn btn-primary",
                                                            disabled: submitting(),
                                                            if submitting() { "Checking in..." } else { "Check In" }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }

                                if active_tab() == TabKind::Teams {
                                    // Team search card
                                    div { class: "card mb-3",
                                        div { class: "card-header", h5 { class: "mb-0", "Find Team" } }
                                        div { class: "card-body",
                                            input {
                                                r#type: "text",
                                                class: "form-control mb-2",
                                                placeholder: "Search by team name or username",
                                                value: "{team_search_query()}",
                                                oninput: move |e| team_search_query.set(e.value()),
                                            }
                                            if team_searching() {
                                                p { class: "text-muted small mb-0", "Searching..." }
                                            }
                                            if !team_search_results().is_empty() {
                                                ul { class: "list-group",
                                                    for t in team_search_results().iter().cloned() {
                                                        li {
                                                            class: "list-group-item d-flex justify-content-between align-items-center",
                                                            div {
                                                                strong { "{t.name}" }
                                                                span { class: "text-muted ms-2", "@{t.id}" }
                                                            }
                                                            button {
                                                                class: "btn btn-sm btn-primary",
                                                                r#type: "button",
                                                                onclick: move |_| {
                                                                    team_pseudonym_input.set(t.name.clone());
                                                                    selected_team_for_register.set(Some(t.clone()));
                                                                    team_search_query.set(String::new());
                                                                    team_search_results.set(Vec::new());
                                                                },
                                                                "Select"
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }

                                    // Selected team + pseudonym form
                                    if let Some(team) = selected_team_for_register() {
                                        div { class: "card mb-3",
                                            div { class: "card-header d-flex justify-content-between align-items-center",
                                                h5 { class: "mb-0", "Registering: {team.name}" }
                                                button {
                                                    class: "btn btn-sm btn-outline-secondary",
                                                    r#type: "button",
                                                    onclick: move |_| {
                                                        selected_team_for_register.set(None);
                                                        team_pseudonym_input.set(String::new());
                                                    },
                                                    "Change"
                                                }
                                            }
                                            div { class: "card-body",
                                                form {
                                                    onsubmit: move |ev| {
                                                        ev.prevent_default();
                                                        if submitting() { return; }

                                                        let team = match selected_team_for_register() {
                                                            Some(t) => t,
                                                            None => return,
                                                        };
                                                        let u = url_team_submit.clone();
                                                        let pseudonym = team_pseudonym_input();

                                                        submit_error.set(None);
                                                        submitting.set(true);

                                                        spawn(async move {
                                                            let result = api::checkin_team(&u, &team.id, &pseudonym).await;
                                                            submitting.set(false);
                                                            match result {
                                                                Ok(res) if res.success => {
                                                                    session_log.with_mut(|log| {
                                                                        log.insert(0, SessionLogEntry::Team {
                                                                            team_id: res.team_id.unwrap_or_default(),
                                                                            team_name: res.team_name.unwrap_or_default(),
                                                                            pseudonym: res.pseudonym.unwrap_or_default(),
                                                                        });
                                                                    });
                                                                    selected_team_for_register.set(None);
                                                                    team_pseudonym_input.set(String::new());
                                                                }
                                                                Ok(res) => {
                                                                    submit_error.set(Some(
                                                                        res.error.unwrap_or_else(|| "Team registration failed.".into()),
                                                                    ));
                                                                }
                                                                Err(e) => submit_error.set(Some(e)),
                                                            }
                                                        });
                                                    },

                                                    div { class: "mb-3",
                                                        label { r#for: "team_pseudonym", class: "form-label", "Tournament Pseudonym" }
                                                        input {
                                                            r#type: "text",
                                                            class: "form-control",
                                                            id: "team_pseudonym",
                                                            value: "{team_pseudonym_input()}",
                                                            oninput: move |e| team_pseudonym_input.set(e.value()),
                                                            required: true,
                                                        }
                                                        div { class: "form-text",
                                                            "How this team's name displays for this tournament. Defaults to the team's account name."
                                                        }
                                                    }

                                                    div { class: "d-grid",
                                                        button {
                                                            r#type: "submit",
                                                            class: "btn btn-primary",
                                                            disabled: submitting(),
                                                            if submitting() { "Registering..." } else { "Register Team" }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }

                                // Session log
                                if !session_log().is_empty() {
                                    div { class: "card mb-3",
                                        div { class: "card-header", h5 { class: "mb-0", "Checked in this session" } }
                                        ul { class: "list-group list-group-flush",
                                            for entry in session_log().iter() {
                                                match entry {
                                                    SessionLogEntry::Player { player_name, team, jersey_name, jersey_number, .. } => rsx! {
                                                        li { class: "list-group-item",
                                                            strong { "{player_name}" }
                                                            " ("
                                                            if let Some(team) = team.as_ref() {
                                                                "{team}, "
                                                            } else {
                                                                "Unaffiliated, "
                                                            }
                                                            "#{jersey_number}"
                                                            if jersey_name != "N/A" {
                                                                " "
                                                                span { class: "text-muted", "{jersey_name}" }
                                                            }
                                                            ")"
                                                        }
                                                    },
                                                    SessionLogEntry::Team { team_name, pseudonym, .. } => rsx! {
                                                        li { class: "list-group-item",
                                                            span { class: "badge bg-info me-2", "Team" }
                                                            strong { "{team_name}" }
                                                            if team_name != pseudonym {
                                                                " "
                                                                span { class: "text-muted", "(pseudonym: {pseudonym})" }
                                                            }
                                                        }
                                                    },
                                                }
                                            }
                                        }
                                    }
                                    div { class: "row mb-3",
                                        div { class: "col-12",
                                            button {
                                                class: "btn btn-outline-secondary",
                                                onclick: move |_| {
                                                    let target_url = url.clone();
                                                    navigator.push(Route::TournamentHome { url: target_url });
                                                },
                                                "Back to Tournament"
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
