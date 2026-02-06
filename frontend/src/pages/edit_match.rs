use crate::api;
use crate::types::{UpdateMatchRequest};
use dioxus::prelude::*;
use dioxus::prelude::use_navigator;
use crate::Route;

#[component]
pub fn EditMatch(tournament_url: String, match_id: String) -> Element {
    let nav = use_navigator();
    
    // Form state
    let mut name = use_signal(|| "".to_string());
    let mut field = use_signal(|| "".to_string());
    let mut schedule_type = use_signal(|| "STATIC".to_string());
    let mut length = use_signal(|| 60u32);
    let mut start_time = use_signal(|| "".to_string());
    let mut previous_match_id = use_signal(|| "".to_string());
    let mut refs = use_signal(|| "".to_string());
    let mut team1 = use_signal(|| "".to_string());
    let mut team2 = use_signal(|| "".to_string());
    let mut set_type = use_signal(|| "SETS".to_string());
    let mut nsets = use_signal(|| 3u32);
    let mut stones_per_set = use_signal(|| 100u32);
    let mut ribbon = use_signal(|| false);
    let mut skip_condition = use_signal(|| "".to_string());

    let mut error = use_signal(|| None::<String>);
    let mut loading = use_signal(|| true);
    
    // Data for dropdowns
    let mut fields = use_signal(|| vec![]);
    let mut matches = use_signal(|| vec![]);

    let _fetch = use_resource(use_reactive((&tournament_url, &match_id), move |(url, id)| async move {
        loading.set(true);
        
        let sched_res = api::schedule(&url).await;
        let match_res = api::match_detail(&url, Some(&id), None).await;
        
        match (sched_res, match_res) {
            (Ok(sched), Ok(detail)) => {
                fields.set(sched.fields);
                matches.set(sched.matches);
                
                let m = detail.match_data;
                name.set(m.name);
                field.set(m.field.unwrap_or_default());
                if let Some(st) = m.schedule_type {
                    schedule_type.set(st);
                }
                if let Some(l) = m.nominal_length {
                    length.set(l);
                }
                if let Some(t) = m.nominal_start_time {
                     start_time.set(t.chars().take(16).collect::<String>());
                }
                if let Some(pm) = m.previous_match {
                    previous_match_id.set(pm);
                }
                if let Some(r) = m.refs_initial {
                    refs.set(r);
                }
                if let Some(t1) = m.team1_initial {
                    team1.set(t1);
                } else if let Some(t1) = m.team1 {
                     team1.set(t1);
                }
                if let Some(t2) = m.team2_initial {
                    team2.set(t2);
                } else if let Some(t2) = m.team2 {
                    team2.set(t2);
                }
                if let Some(st) = m.set_type {
                    set_type.set(st);
                }
                if let Some(ns) = m.nsets {
                    nsets.set(ns);
                }
                if let Some(sps) = m.stones_per_set {
                    stones_per_set.set(sps);
                }
                ribbon.set(m.ribbon);
                if let Some(sc) = m.skip_condition {
                    skip_condition.set(sc);
                }
            }
            (Err(e), _) => error.set(Some(format!("Failed to load schedule: {}", e))),
            (_, Err(e)) => error.set(Some(format!("Failed to load match: {}", e))),
        }
        loading.set(false);
    }));

    let tournament_url_for_submit = tournament_url.clone();
    let match_id_for_submit = match_id.clone();
    let onsubmit = move |evt: Event<FormData>| {
        let tournament_url = tournament_url_for_submit.clone();
        let match_id = match_id_for_submit.clone();
        async move {
            loading.set(true);
            error.set(None);
            
            let refs_vec: Vec<String> = refs().split(',').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect();
            
            let req = UpdateMatchRequest {
                name: Some(name()),
                field: Some(field()),
                schedule_type: Some(schedule_type()),
                length: Some(length()),
                start_time: if start_time().is_empty() { None } else { Some(start_time()) },
                previous_match_id: Some(previous_match_id()),
                refs: Some(refs_vec),
                team1: Some(team1()),
                team2: Some(team2()),
                set_type: Some(set_type()),
                nsets: Some(nsets()),
                stones_per_set: Some(stones_per_set()),
                ribbon: Some(ribbon()),
                skip_condition: Some(skip_condition()),
            };

            match api::update_match(&tournament_url, &match_id, &req).await {
                Ok(_) => {
                    nav.push(Route::TournamentSetup { url: tournament_url.clone() });
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
                    h1 { "Edit Match: {name}" }
                    nav { "aria-label": "breadcrumb",
                        ol { class: "breadcrumb",
                            li { class: "breadcrumb-item",
                                Link { to: Route::TournamentHome { url: tournament_url.clone() }, "{tournament_url}" }
                            }
                            li { class: "breadcrumb-item",
                                Link { to: Route::TournamentSetup { url: tournament_url.clone() }, "Setup" }
                            }
                            li { class: "breadcrumb-item active", "Edit Match" }
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
                            h5 { class: "mb-0", "Match Details" }
                        }
                        div { class: "card-body",
                            if let Some(err) = error() {
                                div { class: "alert alert-danger", "{err}" }
                            }
                            form {
                                onsubmit: onsubmit,
                                div { class: "row",
                                        div { class: "col-md-6",
                                            div { class: "mb-3",
                                                label { class: "form-label", "Match Name" }
                                                input {
                                                    class: "form-control",
                                                    "type": "text",
                                                    value: "{name}",
                                                    oninput: move |e| name.set(e.value()),
                                                    required: true
                                                }
                                            }
                                        }
                                        div { class: "col-md-6",
                                            div { class: "mb-3",
                                                label { class: "form-label", "Field" }
                                                select {
                                                    class: "form-select",
                                                    value: "{field}",
                                                    onchange: move |e| field.set(e.value()),
                                                    option { value: "", "Select Field" }
                                                    for f in fields() {
                                                        option { value: "{f.name}", "{f.name}" }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    
                                    div { class: "row",
                                        div { class: "col-md-6",
                                            div { class: "mb-3",
                                                label { class: "form-label", "Match Type" }
                                                select {
                                                    class: "form-select",
                                                    value: "{schedule_type}",
                                                    onchange: move |e| schedule_type.set(e.value()),
                                                    option { value: "STATIC", "Static (starts at scheduled time)" }
                                                    option { value: "SAFE", "Safe (time finalized when last dependency starts)" }
                                                    option { value: "FAST", "Fast (time finalized when dependencies complete)" }
                                                    option { value: "BREAK", "Break" }
                                                    option { value: "JOIN", "Join" }
                                                }
                                            }
                                        }
                                        div { class: "col-md-6",
                                            div { class: "mb-3",
                                                label { class: "form-label", "Length (minutes)" }
                                                input {
                                                    class: "form-control",
                                                    "type": "number",
                                                    value: "{length}",
                                                    oninput: move |e| length.set(e.value().parse().unwrap_or(60)),
                                                    min: "1"
                                                }
                                            }
                                        }
                                    }
                                    
                                    div { class: "row",
                                        div { class: "col-md-6",
                                            if schedule_type() == "STATIC" {
                                                div { class: "mb-3",
                                                    label { class: "form-label", "Start Time" }
                                                    input {
                                                        class: "form-control",
                                                        "type": "datetime-local",
                                                        value: "{start_time}",
                                                        oninput: move |e| start_time.set(e.value())
                                                    }
                                                }
                                                div { class: "mb-3",
                                                    label { class: "form-label", "Previous Match" }
                                                    select {
                                                        class: "form-select",
                                                        value: "{previous_match_id}",
                                                        onchange: move |e| previous_match_id.set(e.value()),
                                                        option { value: "", "None (first match on field)" }
                                                        for m in matches() {
                                                            if m.uuid != match_id {
                                                                option { value: "{m.uuid}", "{m.name} ({m.field.clone().unwrap_or_default()})" }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                        div { class: "col-md-6",
                                            div { class: "mb-3",
                                                label { class: "form-label", "Referees" }
                                                input {
                                                    class: "form-control",
                                                    "type": "text",
                                                    value: "{refs}",
                                                    oninput: move |e| refs.set(e.value()),
                                                    placeholder: "Search teams, tags, or match results"
                                                }
                                            }
                                        }
                                    }
                                    
                                    if schedule_type() != "BREAK" && schedule_type() != "JOIN" {
                                        div { class: "row",
                                            div { class: "col-md-6",
                                                div { class: "mb-3",
                                                    label { class: "form-label", "Team 1" }
                                                    input {
                                                        class: "form-control",
                                                        "type": "text",
                                                        value: "{team1}",
                                                        oninput: move |e| team1.set(e.value()),
                                                        placeholder: "Search teams, tags, or match results"
                                                    }
                                                }
                                            }
                                            div { class: "col-md-6",
                                                div { class: "mb-3",
                                                    label { class: "form-label", "Team 2" }
                                                    input {
                                                        class: "form-control",
                                                        "type": "text",
                                                        value: "{team2}",
                                                        oninput: move |e| team2.set(e.value()),
                                                        placeholder: "Search teams, tags, or match results"
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    
                                    div { class: "row",
                                        div { class: "col-md-6",
                                            div { class: "mb-3",
                                                label { class: "form-label", "Match Format" }
                                                select {
                                                    class: "form-select",
                                                    value: "{set_type}",
                                                    onchange: move |e| set_type.set(e.value()),
                                                    option { value: "SETS", "Sets" }
                                                    option { value: "STONES", "Stones" }
                                                }
                                            }
                                        }
                                        div { class: "col-md-6",
                                            div { class: "mb-3",
                                                label { class: "form-label", "Number of Sets" }
                                                input {
                                                    class: "form-control",
                                                    "type": "number",
                                                    value: "{nsets}",
                                                    oninput: move |e| nsets.set(e.value().parse().unwrap_or(3)),
                                                    min: "1"
                                                }
                                            }
                                        }
                                    }
                                    
                                    if set_type() == "STONES" {
                                        div { class: "row",
                                            div { class: "col-md-6",
                                                div { class: "mb-3",
                                                    label { class: "form-label", "Stones per Set" }
                                                    input {
                                                        class: "form-control",
                                                        "type": "number",
                                                        value: "{stones_per_set}",
                                                        oninput: move |e| stones_per_set.set(e.value().parse().unwrap_or(100)),
                                                        min: "1"
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    
                                    div { class: "row",
                                        div { class: "col-md-12",
                                            div { class: "mb-3",
                                                div { class: "form-check",
                                                    input {
                                                        class: "form-check-input",
                                                        "type": "checkbox",
                                                        checked: ribbon(),
                                                        onchange: move |e| ribbon.set(e.checked())
                                                    }
                                                    label { class: "form-check-label",
                                                        "Ribbon Game (not counted in tournament results)"
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    
                                    if schedule_type() == "SAFE" || schedule_type() == "FAST" {
                                        div { class: "row",
                                            div { class: "col-md-12",
                                                div { class: "mb-3",
                                                    label { class: "form-label", "Skip Condition" }
                                                    input {
                                                        class: "form-control",
                                                        "type": "text",
                                                        value: "{skip_condition}",
                                                        oninput: move |e| skip_condition.set(e.value()),
                                                        placeholder: "e.g., (== 0 (losses [Ursae Majoris]))"
                                                    }
                                                    div { class: "form-text",
                                                        "Optional expression that evaluates to a boolean. If true, this match will be skipped."
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    
                                    div { class: "d-grid gap-2",
                                        button { class: "btn btn-primary", "type": "submit", "Update Match" }
                                        Link {
                                            class: "btn btn-outline-secondary",
                                            to: Route::TournamentSetup { url: tournament_url.clone() },
                                            "Cancel"
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
