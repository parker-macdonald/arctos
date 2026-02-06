use crate::api;
use crate::types::PlayerInjury;
use crate::Route;
use dioxus::prelude::*;
use pulldown_cmark::{html, Options, Parser};
use serde_json::json;

fn render_markdown(markdown: &str) -> String {
    let mut options = Options::empty();
    options.insert(Options::ENABLE_STRIKETHROUGH);
    let parser = Parser::new_ext(markdown, options);
    let mut html_output = String::new();
    html::push_html(&mut html_output, parser);
    html_output
}

#[derive(Clone, Debug, PartialEq)]
struct EditableInjury {
    id: Option<u32>,
    message: String,
    date: String,
    active: bool,
    show: bool,
    original_message: String,
    original_date: String,
    original_active: bool,
    original_show: bool,
    editing: bool,
    is_new: bool,
}

fn stamp_to_date(stamp: &Option<String>) -> String {
    stamp
        .as_deref()
        .map(|s| s.chars().take(10).collect())
        .unwrap_or_default()
}

fn editable_injury_from_api(inj: &PlayerInjury) -> EditableInjury {
    let date = stamp_to_date(&inj.stamp);
    EditableInjury {
        id: Some(inj.id),
        message: inj.message.clone(),
        date: date.clone(),
        active: inj.active,
        show: inj.show,
        original_message: inj.message.clone(),
        original_date: date,
        original_active: inj.active,
        original_show: inj.show,
        editing: false,
        is_new: false,
    }
}

#[component]
pub fn PlayerProfile(id: String) -> Element {
    let player_id = id.clone();
    let data = use_resource(move || {
        let i = player_id.clone();
        async move { api::player_profile(&i).await.map_err(|e| e.to_string()) }
    });
    let me = use_resource(move || async move { api::me().await });
    let val = data.value();
    let backend = api::base_url();
    let mut injuries_state = use_signal(|| Vec::<EditableInjury>::new());
    let mut injuries_initialized = use_signal(|| false);
    let mut injury_error = use_signal(|| None::<String>);
    let mut injury_saving = use_signal(|| false);

    use_effect(move || {
        if !injuries_initialized() {
            if let Some(Ok(d)) = val.read().as_ref() {
                let list = d
                    .injuries
                    .iter()
                    .map(editable_injury_from_api)
                    .collect::<Vec<_>>();
                injuries_state.set(list);
                injuries_initialized.set(true);
            }
        }
    });
    if let Some(Ok(d)) = val.read().as_ref() {
        let can_edit_injuries = if let Some(Ok(u)) = me.read().as_ref() {
            u.user_type == "player" && u.id == d.player.id
        } else {
            false
        };
        let can_edit_profile = can_edit_injuries;
        let player_id = d.player.id.clone();
        return rsx! {
            div { class: "row",
                div { class: "col-12",
                    h1 { "{d.player.name}" }
                    nav { aria_label: "breadcrumb",
                        ol { class: "breadcrumb",
                            li { class: "breadcrumb-item", Link { to: Route::PlayersList {}, "Players" } }
                            li { class: "breadcrumb-item active", "{d.player.name}" }
                        }
                    }
                }
            }

            div { class: "row",
                div { class: "col-md-8",
                    div { class: "card",
                        div { class: "card-header d-flex justify-content-between align-items-center",
                            h5 { class: "mb-0", "Player Information" }
                            if can_edit_profile {
                                Link {
                                    to: Route::EditPlayerProfile { player_id: d.player.id.clone() },
                                    class: "btn btn-outline-secondary btn-sm",
                                    "✎"
                                }
                            }
                        }
                        div { class: "card-body",
                            if let Some(photo) = &d.player.profile_photo {
                                div { class: "text-center mb-3",
                                    img { src: "{backend}/static/{photo}", alt: "Profile Photo", class: "rounded-circle", style: "width: 100px; height: 100px; object-fit: cover;" }
                                }
                            }
                            p { strong { "Username: " } "@{d.player.id}" }
                            p { strong { "Display Name: " } "{d.player.name}" }
                            if let Some(loc) = &d.player.location {
                                p { strong { "Location: " } "{loc}" }
                            }
                            if let Some(phone) = &d.player.phone {
                                p { strong { "Phone: " } "{phone}" }
                            }
                            if let Some(bio) = &d.player.bio {
                                div { class: "mt-3",
                                    h6 { strong { "Bio:" } }
                                    div { dangerous_inner_html: "{render_markdown(bio)}" }
                                }
                            }
                        }
                    }

                    div { class: "card mt-3",
                        div { class: "card-header",
                            h5 { class: "mb-0", "Tournament History" }
                        }
                        div { class: "card-body",
                            if d.registrations.is_empty() {
                                p { class: "text-muted", "No tournament registrations yet." }
                            } else {
                                div { class: "table-responsive",
                                    table { class: "table table-striped",
                                        thead {
                                            tr {
                                                th { "Tournament" }
                                                th { "Team" }
                                                th { "Jersey" }
                                                th { "Status" }
                                            }
                                        }
                                        tbody {
                                            for r in d.registrations.iter() {
                                                tr { key: "{r.event}-{r.team.as_deref().unwrap_or(\"\")}",
                                                    td { a { href: "/app/{r.event}", "{r.event}" } }
                                                    td {
                                                        if let Some(team) = &r.team {
                                                            Link { to: Route::TeamProfile { id: team.clone() }, "{team}" }
                                                        } else {
                                                            "Unattached"
                                                        }
                                                    }
                                                    td {
                                                        if let Some(jersey_name) = &r.jersey_name {
                                                            "{jersey_name}"
                                                            if let Some(jersey_number) = &r.jersey_number {
                                                                " #{jersey_number}"
                                                            }
                                                        } else {
                                                            "-"
                                                        }
                                                    }
                                                    td {
                                                        span { class: if r.status == "CONFIRMED" { "badge bg-success" } else { "badge bg-warning" },
                                                            "{r.status}"
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

                    if can_edit_injuries || !d.injuries.is_empty() {
                        div { class: "card mt-3",
                            div { class: "card-header",
                                h5 { class: "mb-0", "Injury History" }
                            }
                            div { class: "card-body",
                                if let Some(err) = injury_error() {
                                    div { class: "alert alert-danger", "{err}" }
                                }
                                div { class: "table-responsive",
                                    table { class: "table table-striped",
                                        thead {
                                            tr {
                                                th { "Date" }
                                                th { "Description" }
                                                th { "Status" }
                                                th { "Public" }
                                                if can_edit_injuries {
                                                    th { "Actions" }
                                                }
                                            }
                                        }
                                        tbody {
                                            if can_edit_injuries {
                                                for (idx, inj) in injuries_state().iter().enumerate() {
                                                    {
                                                        let row_key = if let Some(id) = inj.id {
                                                            format!("injury-{}", id)
                                                        } else {
                                                            format!("injury-new-{}", idx)
                                                        };
                                                        let player_id_for_save = player_id.clone();
                                                        let player_id_for_delete = player_id.clone();
                                                        rsx! { tr { key: "{row_key}",
                                                        td {
                                                            if inj.editing {
                                                                input {
                                                                    class: "form-control form-control-sm",
                                                                    "type": "date",
                                                                    value: "{inj.date}",
                                                                    oninput: move |e| {
                                                                        let mut rows = injuries_state.write();
                                                                        if let Some(row) = rows.get_mut(idx) {
                                                                            row.date = e.value();
                                                                        }
                                                                    }
                                                                }
                                                            } else if inj.date.is_empty() {
                                                                "-"
                                                            } else {
                                                                "{inj.date}"
                                                            }
                                                        }
                                                        td {
                                                            if inj.editing {
                                                                input {
                                                                    class: "form-control form-control-sm",
                                                                    "type": "text",
                                                                    value: "{inj.message}",
                                                                    oninput: move |e| {
                                                                        let mut rows = injuries_state.write();
                                                                        if let Some(row) = rows.get_mut(idx) {
                                                                            row.message = e.value();
                                                                        }
                                                                    }
                                                                }
                                                            } else {
                                                                "{inj.message}"
                                                            }
                                                        }
                                                        td {
                                                            if inj.editing {
                                                                div { class: "form-check",
                                                                    input {
                                                                        class: "form-check-input",
                                                                        "type": "checkbox",
                                                                        checked: inj.active,
                                                                        onchange: move |e| {
                                                                            let mut rows = injuries_state.write();
                                                                            if let Some(row) = rows.get_mut(idx) {
                                                                                row.active = e.checked();
                                                                            }
                                                                        }
                                                                    }
                                                                    label { class: "form-check-label", "Active" }
                                                                }
                                                            } else if inj.active {
                                                                span { class: "badge bg-warning", "Active" }
                                                            } else {
                                                                span { class: "badge bg-success", "Healed" }
                                                            }
                                                        }
                                                        td {
                                                            if inj.editing {
                                                                div { class: "form-check",
                                                                    input {
                                                                        class: "form-check-input",
                                                                        "type": "checkbox",
                                                                        checked: inj.show,
                                                                        onchange: move |e| {
                                                                            let mut rows = injuries_state.write();
                                                                            if let Some(row) = rows.get_mut(idx) {
                                                                                row.show = e.checked();
                                                                            }
                                                                        }
                                                                    }
                                                                    label { class: "form-check-label", "Public" }
                                                                }
                                                            } else if inj.show {
                                                                span { class: "badge bg-info", "Public" }
                                                            } else {
                                                                span { class: "badge bg-secondary", "Private" }
                                                            }
                                                        }
                                                        if can_edit_injuries {
                                                            td {
                                                                div { class: "btn-group btn-group-sm",
                                                                    if inj.editing {
                                                                        button {
                                                                            class: "btn btn-outline-success btn-sm",
                                                                            "type": "button",
                                                                            disabled: injury_saving(),
                                                                            onclick: move |_| {
                                                                                let player_id = player_id_for_save.clone();
                                                                                async move {
                                                                                    injury_saving.set(true);
                                                                                    injury_error.set(None);
                                                                                    let snap = injuries_state.read().get(idx).cloned();
                                                                                    if let Some(row) = snap {
                                                                                        let req = json!({
                                                                                            "message": row.message,
                                                                                            "custom_date": if row.date.is_empty() { None } else { Some(row.date) },
                                                                                            "active": row.active,
                                                                                            "show": row.show
                                                                                        });
                                                                                        let saved = if let Some(id) = row.id {
                                                                                            api::update_injury(&player_id, id, &req).await
                                                                                        } else {
                                                                                            api::create_injury(&player_id, &req).await
                                                                                        };
                                                                                        match saved {
                                                                                            Ok(inj) => {
                                                                                                let date = stamp_to_date(&inj.stamp);
                                                                                                let mut rows = injuries_state.write();
                                                                                                if let Some(mut_row) = rows.get_mut(idx) {
                                                                                                    mut_row.id = Some(inj.id);
                                                                                                    mut_row.message = inj.message.clone();
                                                                                                    mut_row.date = date.clone();
                                                                                                    mut_row.active = inj.active;
                                                                                                    mut_row.show = inj.show;
                                                                                                    mut_row.original_message = inj.message;
                                                                                                    mut_row.original_date = date;
                                                                                                    mut_row.original_active = inj.active;
                                                                                                    mut_row.original_show = inj.show;
                                                                                                    mut_row.editing = false;
                                                                                                    mut_row.is_new = false;
                                                                                                }
                                                                                            }
                                                                                            Err(e) => injury_error.set(Some(e)),
                                                                                        }
                                                                                    }
                                                                                    injury_saving.set(false);
                                                                                }
                                                                            },
                                                                            "Save"
                                                                        }
                                                                        button {
                                                                            class: "btn btn-outline-secondary btn-sm",
                                                                            "type": "button",
                                                                            onclick: move |_| {
                                                                                let mut rows = injuries_state.write();
                                                                                if let Some(row) = rows.get_mut(idx) {
                                                                                    if row.is_new {
                                                                                        rows.remove(idx);
                                                                                    } else {
                                                                                        row.message = row.original_message.clone();
                                                                                        row.date = row.original_date.clone();
                                                                                        row.active = row.original_active;
                                                                                        row.show = row.original_show;
                                                                                        row.editing = false;
                                                                                    }
                                                                                }
                                                                            },
                                                                            "Cancel"
                                                                        }
                                                                    } else {
                                                                        button {
                                                                            class: "btn btn-outline-primary btn-sm",
                                                                            "type": "button",
                                                                            onclick: move |_| {
                                                                                let mut rows = injuries_state.write();
                                                                                if let Some(row) = rows.get_mut(idx) {
                                                                                    row.editing = true;
                                                                                }
                                                                            },
                                                                            "Edit"
                                                                        }
                                                                    }
                                                                    if inj.id.is_some() {
                                                                        button {
                                                                            class: "btn btn-outline-danger btn-sm",
                                                                            "type": "button",
                                                                            onclick: move |_| {
                                                                                let player_id = player_id_for_delete.clone();
                                                                                async move {
                                                                                    if !web_sys::window()
                                                                                        .unwrap()
                                                                                        .confirm_with_message("Delete this injury?")
                                                                                        .unwrap_or(false)
                                                                                    {
                                                                                        return;
                                                                                    }
                                                                                    injury_saving.set(true);
                                                                                    injury_error.set(None);
                                                                                    let injury_id = injuries_state.read().get(idx).and_then(|row| row.id);
                                                                                    if let Some(id) = injury_id {
                                                                                        match api::delete_injury(&player_id, id).await {
                                                                                            Ok(_) => {
                                                                                                injuries_state.write().remove(idx);
                                                                                            }
                                                                                            Err(e) => injury_error.set(Some(e)),
                                                                                        }
                                                                                    }
                                                                                    injury_saving.set(false);
                                                                                }
                                                                            },
                                                                            "Delete"
                                                                        }
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                        } }
                                                }
                                            } else {
                                                for inj in d.injuries.iter() {
                                                    tr { key: "{inj.id}",
                                                        td { "{inj.stamp.as_deref().unwrap_or(\"-\")}" }
                                                        td { "{inj.message}" }
                                                        td {
                                                            if inj.active {
                                                                span { class: "badge bg-warning", "Active" }
                                                            } else {
                                                                span { class: "badge bg-success", "Healed" }
                                                            }
                                                        }
                                                        td {
                                                            if inj.show {
                                                                span { class: "badge bg-info", "Public" }
                                                            } else {
                                                                span { class: "badge bg-secondary", "Private" }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                                if can_edit_injuries {
                                    div { class: "d-grid mt-2",
                                        button {
                                            class: "btn btn-outline-primary btn-sm",
                                            "type": "button",
                                            onclick: move |_| {
                                                let mut rows = injuries_state.write();
                                                rows.push(EditableInjury {
                                                    id: None,
                                                    message: "".to_string(),
                                                    date: "".to_string(),
                                                    active: true,
                                                    show: true,
                                                    original_message: "".to_string(),
                                                    original_date: "".to_string(),
                                                    original_active: true,
                                                    original_show: true,
                                                    editing: true,
                                                    is_new: true,
                                                });
                                            },
                                            "New Injury"
                                        }
                                    }
                                }
                            }
                        }
                    }

                    if let Some(Ok(u)) = me.read().as_ref() {
                        if u.user_type == "player" && u.id == d.player.id {
                            if !d.player_notes.is_empty() {
                                div { class: "card mt-3",
                                    div { class: "card-header",
                                        h5 { class: "mb-0", "Notes Received" }
                                    }
                                    div { class: "card-body",
                                        div { class: "table-responsive",
                                            table { class: "table table-striped table-sm",
                                                thead {
                                                    tr {
                                                        th { "Date" }
                                                        th { "Note" }
                                                        th { "Point #" }
                                                        th { "Match" }
                                                    }
                                                }
                                                tbody {
                                                    for note in d.player_notes.iter() {
                                                        tr { key: "{note.created_at.as_deref().unwrap_or(\"-\")}-{note.point_index}",
                                                            td { "{note.created_at.as_deref().unwrap_or(\"-\")}" }
                                                            td { "{note.text}" }
                                                            td { "{note.point_index}" }
                                                            td {
                                                                if let Some(match_info) = &note.match_info {
                                                                    a { href: "/app/{match_info.event}/match/{match_info.uuid}", "{match_info.name}" }
                                                                } else {
                                                                    "-"
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
                }

            }
        };
    }
    if let Some(Err(e)) = val.read().as_ref() {
        return rsx! { p { class: "error", "{e}" } };
    }
    rsx! { p { "Loading…" } }
}
