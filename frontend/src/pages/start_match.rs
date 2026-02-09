use crate::api;
use crate::types::StartMatchPlayer;
use crate::Route;
use dioxus::prelude::*;
use std::collections::HashSet;

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
pub fn StartMatch(url: String) -> Element {
    let match_id = get_query_param("id");
    let match_id_for_data = match_id.clone();
    let url_for_data = url.clone();
    let data = use_resource(move || {
        let u = url_for_data.clone();
        let id = match_id_for_data.clone();
        async move {
            if let Some(id) = id {
                api::start_match_data(&u, &id).await.map_err(|e| e.to_string())
            } else {
                Err("Match ID required".to_string())
            }
        }
    });
    let val = data.value();
    let mut team1_all = use_signal(Vec::<String>::new);
    let mut team2_all = use_signal(Vec::<String>::new);
    let mut team1_selected = use_signal(HashSet::<String>::new);
    let mut team2_selected = use_signal(HashSet::<String>::new);
    let mut team1_search = use_signal(String::new);
    let mut team2_search = use_signal(String::new);
    let team1_notes = use_signal(Vec::<String>::new);
    let team2_notes = use_signal(Vec::<String>::new);
    let mut match_notes = use_signal(String::new);
    let navigator = use_navigator();
    let submit_url = url.clone();
    let notes_url_team1 = url.clone();
    let notes_url_team2 = url.clone();
    let schedule_url = url.clone();
    let home_url = url.clone();
    let data_snapshot = val.read().clone();

    use_effect(move || {
        if let Some(Ok(d)) = val.read().as_ref() {
            if team1_all().is_empty() {
                team1_all.set(d.team1_players.iter().map(|p| p.id.clone()).collect());
            }
            if team2_all().is_empty() {
                team2_all.set(d.team2_players.iter().map(|p| p.id.clone()).collect());
            }
        }
    });

    if match_id.is_none() {
        return rsx! {
            h1 { "Start Match" }
            Link { to: Route::Schedule { url: schedule_url.clone() }, "← Schedule" }
            p { class: "text-muted", "Add ?id=<match-uuid> to the URL, or go to Schedule and click Start on a match." }
        };
    }

    match data_snapshot {
        Some(Ok(d)) => {
            let match_uuid = d.match_info.uuid.clone();
            let match_uuid_submit = match_uuid.clone();
            let match_uuid_notes1 = match_uuid.clone();
            let match_uuid_notes2 = match_uuid.clone();
            let all_players_team1 = d.all_players.clone();
            let all_players_team2 = d.all_players.clone();
            rsx! {
                div { class: "row",
                    div { class: "col-12",
                        h1 { "Start Match" }
                        nav { aria_label: "breadcrumb",
                            ol { class: "breadcrumb",
                                li { class: "breadcrumb-item", Link { to: Route::TournamentHome { url: home_url.clone() }, "{d.tournament.name}" } }
                                li { class: "breadcrumb-item", Link { to: Route::Schedule { url: schedule_url.clone() }, "Schedule" } }
                                li { class: "breadcrumb-item active", "Start Match" }
                            }
                        }
                    }
                }

                div { class: "row",
                    div { class: "col-md-8",
                        div { class: "card",
                            div { class: "card-header", h5 { class: "mb-0", "Match Setup" } }
                            div { class: "card-body",
                                form {
                                    onsubmit: move |ev| {
                                        ev.prevent_default();
                                        let nav = navigator.clone();
                                        let team1_players: Vec<String> = team1_selected().iter().cloned().collect();
                                        let team2_players: Vec<String> = team2_selected().iter().cloned().collect();
                                        let match_notes = match_notes().clone();
                                        let u = submit_url.clone();
                                        let match_id = match_uuid_submit.clone();
                                        spawn(async move {
                                            let req = crate::types::StartMatchRequest {
                                                match_id,
                                                team1_players,
                                                team2_players,
                                                match_notes,
                                                stones_per_set: None,
                                            };
                                            if let Ok(resp) = api::start_match(&u, &req).await {
                                                let _ = nav.push(format!("/{}/run-match?id={}", u, resp.match_id));
                                            }
                                        });
                                    },
                                    input { r#type: "hidden", name: "match_id", value: "{match_uuid}" }
                                    div { class: "row mb-4",
                                        div { class: "col-md-6",
                                            div { class: "d-flex justify-content-between align-items-center",
                                                h6 { class: "mb-0", "Team 1: {d.match_info.team1_name}" }
                                                button {
                                                    r#type: "button",
                                                    class: "btn btn-sm btn-outline-info",
                                                    onclick: move |_| {
                                                        let u = notes_url_team1.clone();
                                                        let match_id = match_uuid_notes1.clone();
                                                        let ids = team1_selected().iter().cloned().collect::<Vec<_>>().join(",");
                                                        let mut team1_notes = team1_notes;
                                                        spawn(async move {
                                                            let url = format!(
                                                                "{}/{}/get-selection-notes?match_id={}&team=team1&player_ids={}",
                                                                api::base_url(),
                                                                u,
                                                                match_id,
                                                                urlencoding::encode(&ids)
                                                            );
                                                            if let Ok(resp) = reqwest::Client::new().get(url).send().await {
                                                                if let Ok(val) = resp.json::<serde_json::Value>().await {
                                                                    let notes = val.get("notes").cloned().unwrap_or_default();
                                                                    let mut texts = Vec::new();
                                                                    if let Some(arr) = notes.as_array() {
                                                                        for n in arr {
                                                                            if let Some(text) = n.get("text").and_then(|t| t.as_str()) {
                                                                                texts.push(text.to_string());
                                                                            }
                                                                        }
                                                                    }
                                                                    team1_notes.set(texts);
                                                                }
                                                            }
                                                        });
                                                    },
                                                    "View Notes"
                                                }
                                            }
                                            div { class: "mb-3",
                                                label { class: "form-label", "Select Players (max {d.tournament.max_team_size_field.unwrap_or(0)}):" }
                                                div { class: "border p-3", style: "max-height: 200px; overflow-y: auto;",
                                                    StartMatchPlayerList {
                                                        players: d.all_players.clone(),
                                                        team_ids: team1_all(),
                                                        selected_ids: team1_selected(),
                                                        other_selected_ids: team2_selected(),
                                                        on_toggle: move |(id, is_selected)| {
                                                            let mut selected = team1_selected();
                                                            if is_selected {
                                                                selected.insert(id);
                                                            } else {
                                                                selected.remove(&id);
                                                            }
                                                            team1_selected.set(selected);
                                                        }
                                                    }
                                                }
                                            }
                                            div { class: "mb-3",
                                                label { r#for: "team1_search", class: "form-label", "Add Player:" }
                                                div { class: "input-group",
                                                    input {
                                                        r#type: "text",
                                                        class: "form-control",
                                                        id: "team1_search",
                                                        placeholder: "Search players...",
                                                        value: "{team1_search()}",
                                                        oninput: move |ev| team1_search.set(ev.value().clone()),
                                                    }
                                                    button {
                                                        class: "btn btn-outline-secondary",
                                                        r#type: "button",
                                                        onclick: move |_| {
                                                            if let Some(p) = find_player(&all_players_team1, &team1_search()) {
                                                                if !team1_all().contains(&p.id) {
                                                                    let mut ids = team1_all();
                                                                    ids.push(p.id);
                                                                    team1_all.set(ids);
                                                                }
                                                                team1_search.set(String::new());
                                                            }
                                                        },
                                                        "Search"
                                                    }
                                                }
                                                div { class: "mt-2",
                                                    StartMatchSearchResults {
                                                        players: all_players_team1.clone(),
                                                        query: team1_search(),
                                                        on_add: move |id| {
                                                            let mut ids = team1_all();
                                                            if !ids.contains(&id) {
                                                                ids.push(id);
                                                                team1_all.set(ids);
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }

                                        div { class: "col-md-6",
                                            div { class: "d-flex justify-content-between align-items-center",
                                                h6 { class: "mb-0", "Team 2: {d.match_info.team2_name}" }
                                                button {
                                                    r#type: "button",
                                                    class: "btn btn-sm btn-outline-info",
                                                    onclick: move |_| {
                                                        let u = notes_url_team2.clone();
                                                        let match_id = match_uuid_notes2.clone();
                                                        let ids = team2_selected().iter().cloned().collect::<Vec<_>>().join(",");
                                                        let mut team2_notes = team2_notes;
                                                        spawn(async move {
                                                            let url = format!(
                                                                "{}/{}/get-selection-notes?match_id={}&team=team2&player_ids={}",
                                                                api::base_url(),
                                                                u,
                                                                match_id,
                                                                urlencoding::encode(&ids)
                                                            );
                                                            if let Ok(resp) = reqwest::Client::new().get(url).send().await {
                                                                if let Ok(val) = resp.json::<serde_json::Value>().await {
                                                                    let notes = val.get("notes").cloned().unwrap_or_default();
                                                                    let mut texts = Vec::new();
                                                                    if let Some(arr) = notes.as_array() {
                                                                        for n in arr {
                                                                            if let Some(text) = n.get("text").and_then(|t| t.as_str()) {
                                                                                texts.push(text.to_string());
                                                                            }
                                                                        }
                                                                    }
                                                                    team2_notes.set(texts);
                                                                }
                                                            }
                                                        });
                                                    },
                                                    "View Notes"
                                                }
                                            }
                                            div { class: "mb-3",
                                                label { class: "form-label", "Select Players (max {d.tournament.max_team_size_field.unwrap_or(0)}):" }
                                                div { class: "border p-3", style: "max-height: 200px; overflow-y: auto;",
                                                    StartMatchPlayerList {
                                                        players: d.all_players.clone(),
                                                        team_ids: team2_all(),
                                                        selected_ids: team2_selected(),
                                                        other_selected_ids: team1_selected(),
                                                        on_toggle: move |(id, is_selected)| {
                                                            let mut selected = team2_selected();
                                                            if is_selected {
                                                                selected.insert(id);
                                                            } else {
                                                                selected.remove(&id);
                                                            }
                                                            team2_selected.set(selected);
                                                        }
                                                    }
                                                }
                                            }
                                            div { class: "mb-3",
                                                label { r#for: "team2_search", class: "form-label", "Add Player:" }
                                                div { class: "input-group",
                                                    input {
                                                        r#type: "text",
                                                        class: "form-control",
                                                        id: "team2_search",
                                                        placeholder: "Search players...",
                                                        value: "{team2_search()}",
                                                        oninput: move |ev| team2_search.set(ev.value().clone()),
                                                    }
                                                    button {
                                                        class: "btn btn-outline-secondary",
                                                        r#type: "button",
                                                        onclick: move |_| {
                                                            if let Some(p) = find_player(&all_players_team2, &team2_search()) {
                                                                if !team2_all().contains(&p.id) {
                                                                    let mut ids = team2_all();
                                                                    ids.push(p.id);
                                                                    team2_all.set(ids);
                                                                }
                                                                team2_search.set(String::new());
                                                            }
                                                        },
                                                        "Search"
                                                    }
                                                }
                                                div { class: "mt-2",
                                                    StartMatchSearchResults {
                                                        players: all_players_team2.clone(),
                                                        query: team2_search(),
                                                        on_add: move |id| {
                                                            let mut ids = team2_all();
                                                            if !ids.contains(&id) {
                                                                ids.push(id);
                                                                team2_all.set(ids);
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    div { class: "mb-4",
                                        label { r#for: "match_notes", class: "form-label", "Match Notes" }
                                        textarea {
                                            class: "form-control",
                                            id: "match_notes",
                                            name: "match_notes",
                                            rows: "3",
                                            placeholder: "Any special rules or notes for this match...",
                                            value: "{match_notes()}",
                                            oninput: move |ev| match_notes.set(ev.value().clone()),
                                        }
                                    }
                                    div { class: "d-grid",
                                        button { r#type: "submit", class: "btn btn-success btn-lg", "Start Match" }
                                    }
                                }
                            }
                        }
                    }
                    div { class: "col-md-4",
                        div { class: "card",
                            div { class: "card-header", h5 { class: "mb-0", "Match Info" } }
                            div { class: "card-body",
                                p { strong { "Match: " } "{d.match_info.name}" }
                                p { strong { "Field: " } "{d.match_info.field.as_deref().unwrap_or(\"TBA\")}" }
                                p { strong { "Set Type: " } "{d.match_info.set_type.as_deref().unwrap_or(\"Standard\")}" }
                                p { strong { "Refs: " } "{d.match_info.refs.as_deref().unwrap_or(\"TBA\")}" }
                            }
                        }
                        if !team1_notes().is_empty() {
                            div { class: "card mt-3",
                                div { class: "card-header", h5 { class: "mb-0", "Team 1 Notes" } }
                                div { class: "card-body",
                                    for note in team1_notes().iter() {
                                        p { class: "small text-muted mb-1", "{note}" }
                                    }
                                }
                            }
                        }
                        if !team2_notes().is_empty() {
                            div { class: "card mt-3",
                                div { class: "card-header", h5 { class: "mb-0", "Team 2 Notes" } }
                                div { class: "card-body",
                                    for note in team2_notes().iter() {
                                        p { class: "small text-muted mb-1", "{note}" }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        Some(Err(e)) => rsx! { p { class: "text-danger", "{e}" } },
        None => rsx! { p { "Loading…" } },
    }
}

#[component]
fn StartMatchSearchResults(
    players: Vec<StartMatchPlayer>,
    query: String,
    on_add: EventHandler<String>,
) -> Element {
    let q = query.trim().to_lowercase();
    if q.is_empty() {
        return rsx! {};
    }
    rsx! {
        for p in players
            .iter()
            .filter(|p| p.name.to_lowercase().contains(&q) || p.id.to_lowercase().contains(&q))
            .take(5)
        {
            {
                let id = p.id.clone();
                rsx! {
                    div { class: "d-flex justify-content-between align-items-center border rounded p-2 mb-1",
                        div {
                            strong { "{p.name}" }
                            span { class: "text-muted ms-2", "@{p.id}" }
                        }
                        button {
                            class: "btn btn-sm btn-outline-secondary",
                            onclick: move |_| on_add.call(id.clone()),
                            "Add"
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn StartMatchPlayerList(
    players: Vec<StartMatchPlayer>,
    team_ids: Vec<String>,
    selected_ids: HashSet<String>,
    other_selected_ids: HashSet<String>,
    on_toggle: EventHandler<(String, bool)>,
) -> Element {
    rsx! {
        if team_ids.is_empty() {
            p { class: "text-muted", "No players added yet. Use the search below to add players." }
        } else {
            for player_id in team_ids.iter() {
                if let Some(p) = players.iter().find(|p| &p.id == player_id) {
                    {
                        let is_selected = selected_ids.contains(&p.id);
                        let is_on_other = other_selected_ids.contains(&p.id);
                        let disabled = !p.paid || is_on_other;
                        let injuries = if p.injuries.is_empty() {
                            None
                        } else {
                            Some(p.injuries.join(" • "))
                        };
                        let id = p.id.clone();
                        let id_for_toggle = id.clone();
                        rsx! {
                            div { class: "form-check",
                                input {
                                    class: "form-check-input",
                                    r#type: "checkbox",
                                    id: "{id}",
                                    checked: is_selected,
                                    disabled: disabled,
                                    onchange: move |_| on_toggle.call((id_for_toggle.clone(), !is_selected)),
                                }
                                label { class: "form-check-label",
                                    r#for: "{id}",
                                    {
                                        let mut label = p.jersey_name.clone().unwrap_or_else(|| p.name.clone());
                                        if let Some(num) = &p.jersey_number {
                                            label = format!("{} #{}", label, num);
                                        }
                                        label
                                    }
                                    if !p.paid {
                                        span { class: "badge bg-secondary ms-2", "Unpaid" }
                                    }
                                }
                                if let Some(inj) = injuries {
                                    div { class: "small text-danger mt-1", "{inj}" }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

fn find_player(players: &[StartMatchPlayer], query: &str) -> Option<StartMatchPlayer> {
    let q = query.trim().to_lowercase();
    if q.is_empty() {
        return None;
    }
    players
        .iter()
        .find(|p| p.name.to_lowercase().contains(&q) || p.id.to_lowercase().contains(&q))
        .cloned()
}
