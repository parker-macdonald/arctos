use crate::api;
use crate::pages::TeamSelectionField;
use crate::types::{BracketConfig, BracketTeamConfig};
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn BracketSetup(url: String) -> Element {
    let url_for_data = url.clone();
    let data = use_resource(move || {
        let u = url_for_data.clone();
        async move { api::bracket_setup_data(&u).await.map_err(|e| e.to_string()) }
    });

    let url_for_setup = url.clone();
    let setup_data = use_resource(move || {
        let u = url_for_setup.clone();
        async move { api::schedule_setup(&u).await.map_err(|e| e.to_string()) }
    });

    let mut brackets_state = use_signal(|| Vec::<BracketConfig>::new());
    let save_status = use_signal(|| Option::<String>::None);
    let saving = use_signal(|| false);

    let val = data.value();
    let setup_val = setup_data.value();
    let backend = api::base_url();

    // Initialize local state from fetched data once
    if let Some(Ok(d)) = val.read().as_ref() {
        if brackets_state.read().is_empty() && !d.brackets.is_empty() {
            brackets_state.set(d.brackets.clone());
        }
    }

    let url_for_upload = url.clone();

    // Reuse the schedule page CSS so TeamTokenInput looks identical (chips, icons, hidden text box styling)
    const SCHEDULE_PAGE_CSS: &str = include_str!("schedule_timeline.css");

    rsx! {
        style { {SCHEDULE_PAGE_CSS} }
        // Lightly scope token styling tweaks to bracket setup context
        style { r#"
.bracket-setup-team-token .team-token-input {{
    width: 100%;
}}
.bracket-setup-team-token .team-token-input-field {{
    border: none !important;
    box-shadow: none !important;
    background: transparent !important;
    padding: 0.2rem 0;
}}
.bracket-setup-team-token .team-token-remove {{
    background: none !important;
    border: none !important;
}}
.bracket-setup-team-token .team-token-icon,
.bracket-setup-team-token .icon-primary-svg {{
    width: 1em;
    height: 1em;
    object-fit: contain;
    vertical-align: -0.15em;
    filter: invert(27%) sepia(98%) saturate(2476%) hue-rotate(226deg) brightness(99%) contrast(101%);
}}
"# }
        if let Some(Ok(d)) = val.read().as_ref() {
            div { class: "row",
                div { class: "col-12",
                    h1 { "{d.tournament.name} - Bracket Setup" }
                    nav { "aria-label": "breadcrumb",
                        ol { class: "breadcrumb",
                            li { class: "breadcrumb-item",
                                Link { to: Route::TournamentHome { url: url.clone() }, "{d.tournament.name}" }
                            }
                            li { class: "breadcrumb-item active", "Bracket Setup" }
                        }
                    }
                    p {
                        "Brackets are images with team labels placed on top. Upload your bracket images and configure team labels and positions here."
                    }
                    p {
                        "Teams may be entered as explicit usernames, tags (e.g. tag::MyTag), or match results like "
                        code { "MatchName::winner" } " or " code { "MatchName::loser" } "."
                    }
                }
            }

            if let Some(msg) = save_status.read().as_ref() {
                div { class: "alert alert-info", "{msg}" }
            }

            div { class: "row",
                div { class: "col-12",
                    {brackets_state.read().iter().enumerate().map(|(idx, bracket)| {
                        let idx_u32 = idx as u32;
                        let bracket_name = bracket.name.clone();
                        let bracket_image = bracket.image.clone();
                        let teams = bracket.teams.clone();
                        let url_upload = url_for_upload.clone();
                        rsx! {
                            div { class: "card mb-4", key: "bracket-{idx}",
                                div { class: "card-header d-flex justify-content-between align-items-center",
                                    h5 { class: "mb-0", "Bracket {idx_u32 + 1}" }
                                    button {
                                        class: "btn btn-sm btn-outline-danger",
                                        onclick: move |_| {
                                            brackets_state.write().remove(idx);
                                        },
                                        "Remove"
                                    }
                                }
                                div { class: "card-body",
                                    div { class: "row",
                                        div { class: "col-md-6",
                                            div { class: "mb-3",
                                                label { class: "form-label", "Bracket Name" }
                                                input {
                                                    class: "form-control",
                                                    r#type: "text",
                                                    value: "{bracket_name}",
                                                    oninput: move |e| {
                                                        let mut vec = brackets_state.write();
                                                        if let Some(b) = vec.get_mut(idx) {
                                                            b.name = e.value();
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                        div { class: "col-md-6",
                                            div { class: "mb-3",
                                                label { class: "form-label", "Bracket Image" }
                                                if !bracket_image.is_empty() {
                                                    div { class: "mb-2",
                                                        img {
                                                            src: "{backend}/static/{bracket_image}",
                                                            alt: "{bracket_name}",
                                                            class: "img-thumbnail",
                                                            style: "max-width: 200px; max-height: 200px;"
                                                        }
                                                    }
                                                }
                                                input {
                                                    class: "form-control mb-2",
                                                    r#type: "file",
                                                    accept: "image/*",
                                                    onchange: {
                                                        let url_upload_inner = url_upload.clone();
                                                        let brackets_state_inner = brackets_state.clone();
                                                        let save_status_inner = save_status.clone();
                                                        move |evt| {
                                                            #[cfg(target_arch = "wasm32")]
                                                            {
                                                                use dioxus::html::HasFileData;
                                                                let files = evt.files();
                                                                if let Some(file) = files.into_iter().next() {
                                                                    let url_upload_closure = url_upload_inner.clone();
                                                                    let mut brackets_state_closure = brackets_state_inner.clone();
                                                                    let mut save_status_closure = save_status_inner.clone();
                                                                    dioxus::prelude::spawn(async move {
                                                                        let filename = file.name();
                                                                        match file.read_bytes().await {
                                                                            Ok(bytes) => {
                                                                                let res = api::upload_bracket_image_bytes(
                                                                                    &url_upload_closure,
                                                                                    idx_u32,
                                                                                    &filename,
                                                                                    bytes,
                                                                                ).await;
                                                                                match res {
                                                                                    Ok(path) => {
                                                                                        let mut vec = brackets_state_closure.write();
                                                                                        if let Some(b) = vec.get_mut(idx) {
                                                                                            b.image = path.clone();
                                                                                        }
                                                                                        save_status_closure.set(Some(format!("Uploaded image {}", filename)));
                                                                                    }
                                                                                    Err(e) => {
                                                                                        save_status_closure.set(Some(format!("Error uploading image: {}", e)));
                                                                                    }
                                                                                }
                                                                            }
                                                                            Err(_) => {
                                                                                save_status_closure.set(Some("Failed to read image file".to_string()));
                                                                            }
                                                                        }
                                                                    });
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }

                                    hr {}
                                    h6 { "Team Entries" }
                                    {
                                        teams.iter().enumerate().map(|(tidx, team)| {
                                            let tref = team.team.clone();
                                            let tx = team.x;
                                            let ty = team.y;
                                            let thalign = team.halign.clone().unwrap_or_else(|| "center".to_string());
                                            let tvalign = team.valign.clone().unwrap_or_else(|| "center".to_string());
                                            let tsize = team.size.unwrap_or(20);
                                            rsx! {
                                                div { class: "card mb-2", key: "team-{idx}-{tidx}",
                                                    div { class: "card-body",
                                                        div { class: "row",
                                                            div { class: "col-md-3",
                                                                {
                                                                    if let Some(Ok(setup)) = setup_val.read().as_ref() {
                                                                        rsx! {
                                                                            TeamSelectionField {
                                                                                label: "Team Reference".to_string(),
                                                                                team_options: setup.team_options.clone(),
                                                                                tags: setup.tags.clone(),
                                                                                matches: setup.matches.clone(),
                                                                                value: tref.clone(),
                                                                                on_change: move |s| {
                                                                                    let mut vec = brackets_state.write();
                                                                                    if let Some(b) = vec.get_mut(idx) {
                                                                                        if let Some(t) = b.teams.get_mut(tidx) {
                                                                                            t.team = s;
                                                                                        }
                                                                                    }
                                                                                },
                                                                                multiple: false,
                                                                                placeholder: "Pseudonym, MatchName::winner, tag::TagName".to_string(),
                                                                                help_text: Some("Team, match winner/loser (MatchName::winner), or tag (tag::TagName)".to_string()),
                                                                                wrapper_class: Some("mb-2 bracket-setup-team-token".to_string()),
                                                                            }
                                                                        }
                                                                    } else {
                                                                        rsx! {
                                                                            div { class: "mb-2",
                                                                                label { class: "form-label", "Team Reference" }
                                                                                input {
                                                                                    class: "form-control",
                                                                                    r#type: "text",
                                                                                    value: "{tref}",
                                                                                    placeholder: "Team ID, tag::Name, Match::winner",
                                                                                    oninput: move |e| {
                                                                                        let mut vec = brackets_state.write();
                                                                                        if let Some(b) = vec.get_mut(idx) {
                                                                                            if let Some(t) = b.teams.get_mut(tidx) {
                                                                                                t.team = e.value();
                                                                                            }
                                                                                        }
                                                                                    }
                                                                                }
                                                                            }
                                                                        }
                                                                    }
                                                                }
                                                            }
                                                            div { class: "col-md-1",
                                                                div { class: "mb-1",
                                                                    label { class: "form-label", "X (px)" }
                                                                    input {
                                                                        class: "form-control",
                                                                        r#type: "number",
                                                                        value: "{tx}",
                                                                        oninput: move |e| {
                                                                            if let Ok(v) = e.value().parse::<i32>() {
                                                                                let mut vec = brackets_state.write();
                                                                                if let Some(b) = vec.get_mut(idx) {
                                                                                    if let Some(t) = b.teams.get_mut(tidx) {
                                                                                        t.x = v;
                                                                                    }
                                                                                }
                                                                            }
                                                                        }
                                                                    }
                                                                }
                                                            }
                                                            div { class: "col-md-1",
                                                                div { class: "mb-1",
                                                                    label { class: "form-label", "Y (px)" }
                                                                    input {
                                                                        class: "form-control",
                                                                        r#type: "number",
                                                                        value: "{ty}",
                                                                        oninput: move |e| {
                                                                            if let Ok(v) = e.value().parse::<i32>() {
                                                                                let mut vec = brackets_state.write();
                                                                                if let Some(b) = vec.get_mut(idx) {
                                                                                    if let Some(t) = b.teams.get_mut(tidx) {
                                                                                        t.y = v;
                                                                                    }
                                                                                }
                                                                            }
                                                                        }
                                                                    }
                                                                }
                                                            }
                                                            div { class: "col-md-1",
                                                                div { class: "mb-1",
                                                                    label { class: "form-label", "H-Align" }
                                                                    select {
                                                                        class: "form-select",
                                                                        value: "{thalign}",
                                                                        oninput: move |e| {
                                                                            let v = e.value();
                                                                            let mut vec = brackets_state.write();
                                                                            if let Some(b) = vec.get_mut(idx) {
                                                                                if let Some(t) = b.teams.get_mut(tidx) {
                                                                                    t.halign = Some(v);
                                                                                }
                                                                            }
                                                                        },
                                                                        option { value: "left", selected: thalign == "left", "Left" }
                                                                        option { value: "center", selected: thalign == "center", "Center" }
                                                                        option { value: "right", selected: thalign == "right", "Right" }
                                                                    }
                                                                }
                                                            }
                                                            div { class: "col-md-1",
                                                                div { class: "mb-1",
                                                                    label { class: "form-label", "V-Align" }
                                                                    select {
                                                                        class: "form-select",
                                                                        value: "{tvalign}",
                                                                        oninput: move |e| {
                                                                            let v = e.value();
                                                                            let mut vec = brackets_state.write();
                                                                            if let Some(b) = vec.get_mut(idx) {
                                                                                if let Some(t) = b.teams.get_mut(tidx) {
                                                                                    t.valign = Some(v);
                                                                                }
                                                                            }
                                                                        },
                                                                        option { value: "top", selected: tvalign == "top", "Top" }
                                                                        option { value: "center", selected: tvalign == "center", "Center" }
                                                                        option { value: "bottom", selected: tvalign == "bottom", "Bottom" }
                                                                    }
                                                                }
                                                            }
                                                            div { class: "col-md-1",
                                                                div { class: "mb-1",
                                                                    label { class: "form-label", "Size (px)" }
                                                                    input {
                                                                        class: "form-control",
                                                                        r#type: "number",
                                                                        value: "{tsize}",
                                                                        min: "1",
                                                                        oninput: move |e| {
                                                                            if let Ok(v) = e.value().parse::<u32>() {
                                                                                let mut vec = brackets_state.write();
                                                                                if let Some(b) = vec.get_mut(idx) {
                                                                                    if let Some(t) = b.teams.get_mut(tidx) {
                                                                                        t.size = Some(v);
                                                                                    }
                                                                                }
                                                                            }
                                                                        }
                                                                    }
                                                                }
                                                            }
                                                            div { class: "col-md-2",
                                                                div { class: "mb-1",
                                                                    label { class: "form-label", " " }
                                                                    button {
                                                                        class: "btn btn-sm btn-outline-danger form-control",
                                                                        onclick: move |_| {
                                                                            let mut vec = brackets_state.write();
                                                                            if let Some(b) = vec.get_mut(idx) {
                                                                                if tidx < b.teams.len() {
                                                                                    b.teams.remove(tidx);
                                                                                }
                                                                            }
                                                                        },
                                                                        "Remove Team"
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        })
                                    }
                                    button {
                                        class: "btn btn-sm btn-outline-primary mt-2",
                                        onclick: move |_| {
                                            let mut vec = brackets_state.write();
                                            if let Some(b) = vec.get_mut(idx) {
                                                b.teams.push(BracketTeamConfig {
                                                    team: String::new(),
                                                    x: 0,
                                                    y: 0,
                                                    halign: Some("center".to_string()),
                                                    valign: Some("center".to_string()),
                                                    size: Some(20),
                                                });
                                            }
                                        },
                                        "Add Team Entry"
                                    }
                                }
                            }
                        }
                    })}

                    button {
                        class: "btn btn-primary mb-3",
                        onclick: move |_| {
                            let mut vec = brackets_state.write();
                            let next_index = vec.len() + 1;
                            vec.push(BracketConfig {
                                name: format!("Bracket {}", next_index),
                                image: String::new(),
                                teams: Vec::new(),
                            });
                        },
                        "Add Bracket"
                    }

                    div { class: "d-grid gap-2 mt-3",
                        button {
                            class: "btn btn-success",
                            disabled: saving(),
                            onclick: move |_| {
                                let url_clone = url.clone();
                                let brackets = brackets_state.read().clone();
                                let mut saving = saving.clone();
                                let mut save_status = save_status.clone();
                                saving.set(true);
                                save_status.set(None);
                                spawn(async move {
                                    match api::save_bracket_setup(&url_clone, &brackets).await {
                                        Ok(()) => {
                                            save_status.set(Some("Bracket configuration saved successfully.".to_string()));
                                        }
                                        Err(e) => {
                                            save_status.set(Some(format!("Error saving bracket configuration: {}", e)));
                                        }
                                    }
                                    saving.set(false);
                                });
                            },
                            "Save Bracket Configuration"
                        }
                        Link { to: Route::TournamentHome { url: url.clone() }, class: "btn btn-outline-secondary", "Cancel" }
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

