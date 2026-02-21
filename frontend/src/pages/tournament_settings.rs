use crate::api;
use crate::Route;
use dioxus::prelude::*;
use wasm_bindgen::JsCast;

const PREDEFINED_COLORS: &[&str] = &[
    "FF0000", "FF8C00", "FFD700", "32CD32", "008000", "00CED1", "1E90FF", "0000FF",
    "8A2BE2", "FF00FF", "C71585", "A52A2A", "808080", "000000",
];

fn get_form_value(id: &str) -> String {
    let window = web_sys::window().unwrap();
    let doc = window.document().unwrap();
    doc.get_element_by_id(id)
        .and_then(|e| e.dyn_into::<web_sys::HtmlInputElement>().ok())
        .map(|e| e.value())
        .unwrap_or_default()
}

fn get_form_textarea(id: &str) -> String {
    let window = web_sys::window().unwrap();
    let doc = window.document().unwrap();
    doc.get_element_by_id(id)
        .and_then(|e| e.dyn_into::<web_sys::HtmlTextAreaElement>().ok())
        .map(|e| e.value())
        .unwrap_or_default()
}

fn get_form_check(id: &str) -> bool {
    let window = web_sys::window().unwrap();
    let doc = window.document().unwrap();
    doc.get_element_by_id(id)
        .and_then(|e| e.dyn_into::<web_sys::HtmlInputElement>().ok())
        .map(|e| e.checked())
        .unwrap_or(false)
}

const NAME_MAX_LEN: usize = 50;

#[component]
fn PenaltyTypesTableBody(
    penalty_types: Vec<crate::types::PenaltyType>,
    url: String,
    data: Resource<Result<crate::types::TournamentDetailResponse, String>>,
    editing_pt_id: Signal<Option<i32>>,
    add_new_penalty: Signal<bool>,
    edit_name: Signal<String>,
    edit_color: Signal<String>,
    edit_desc: Signal<String>,
    edit_error: Signal<Option<String>>,
    show_color_picker_for: Signal<Option<i32>>,
    custom_color_hex: Signal<String>,
) -> Element {
    let penalty_rows: Vec<(i32, String, String, String, String, bool, String)> = penalty_types
        .iter()
        .map(|pt| {
            let desc = pt.desc.as_deref().unwrap_or("").to_string();
            let preview = if desc.len() > 80 {
                format!("{}\u{2026}", desc.chars().take(80).collect::<String>())
            } else {
                desc.clone()
            };
            (
                pt.id,
                pt.name.clone(),
                pt.color.clone(),
                desc,
                preview,
                editing_pt_id() == Some(pt.id),
                url.clone(),
            )
        })
        .collect();
    let add_new_key = "add-new-row";
    let row_elements: Vec<Element> = penalty_rows
        .into_iter()
        .map(|row| {
            let (pt_id, name, color, desc, preview, is_editing, url) = row;
            let url_save = url.clone();
            let url_del = url.clone();
            let edit_tr = rsx! {
                    tr { key: "edit-{pt_id}",
                    td {
                        input {
                            r#type: "text",
                            class: "form-control form-control-sm",
                            maxlength: "{NAME_MAX_LEN}",
                            placeholder: "Name (max 50)",
                            value: "{edit_name()}",
                            oninput: move |ev| {
                                edit_name.set(ev.value().clone());
                                edit_error.set(None);
                            }
                        }
                        span { class: "small text-muted", "{edit_name().len()}/{NAME_MAX_LEN}" }
                    }
                    td {
                        div {
                            class: "d-flex align-items-center gap-1",
                            div {
                                class: "rounded border",
                                style: format!("width: 24px; height: 24px; background-color: #{}; cursor: pointer;", edit_color()),
                                                                onclick: move |_| {
                                                                    if show_color_picker_for() == Some(pt_id) {
                                                                        show_color_picker_for.set(None);
                                                                    } else {
                                                                        show_color_picker_for.set(Some(pt_id));
                                                                        custom_color_hex.set(edit_color());
                                                                    }
                                                                }
                                                            }
                                                            if show_color_picker_for() == Some(pt_id) {
                                div { class: "position-absolute bg-white border rounded p-2 shadow", style: "z-index: 1000;",
                                    div { class: "d-flex flex-wrap gap-1 mb-2", style: "width: 150px;",
                                        for c in PREDEFINED_COLORS.iter() {
                                            div {
                                                class: "rounded-circle border",
                                                style: format!("width: 20px; height: 20px; background-color: #{}; cursor: pointer;", *c),
                                                onclick: move |_| {
                                                    edit_color.set(c.to_string());
                                                    custom_color_hex.set(c.to_string());
                                                }
                                            }
                                        }
                                    }
                                    div { class: "input-group input-group-sm",
                                        span { class: "input-group-text", "#" }
                                        input {
                                            r#type: "text",
                                            class: "form-control",
                                            value: "{custom_color_hex()}",
                                            oninput: move |ev| custom_color_hex.set(ev.value().clone())
                                        }
                                        button {
                                            class: "btn btn-outline-primary btn-sm",
                                            r#type: "button",
                                            onclick: move |_| {
                                                let c = custom_color_hex().trim().trim_start_matches('#').to_string();
                                                if c.len() == 6 {
                                                    edit_color.set(c);
                                                    show_color_picker_for.set(None);
                                                }
                                            },
                                            "Apply"
                                        }
                                    }
                                }
                            }
                        }
                    }
                    td {
                        textarea {
                            class: "form-control form-control-sm",
                            rows: "3",
                            placeholder: "Description (optional)",
                            value: "{edit_desc()}",
                            oninput: move |ev| edit_desc.set(ev.value().clone())
                        }
                    }
                    td {
                        button {
                            class: "btn btn-sm btn-primary me-1",
                            r#type: "button",
                                                            onclick: move |_| {
                                                                let u = url_save.clone();
                                                                let name_trim = edit_name().trim().to_string();
                                let name_len = name_trim.len();
                                if name_trim.is_empty() {
                                    edit_error.set(Some("Name is required.".to_string()));
                                    return;
                                }
                                if name_len > NAME_MAX_LEN {
                                    edit_error.set(Some(format!("Name must be at most {} characters.", NAME_MAX_LEN)));
                                    return;
                                }
                                let color_val = edit_color().trim_start_matches('#').to_string();
                                let desc_val = edit_desc().trim().to_string();
                                let desc_opt = if desc_val.is_empty() { None } else { Some(desc_val) };
                                editing_pt_id.set(None);
                                edit_error.set(None);
                                let mut data = data.clone();
                                                                spawn(async move {
                                                                    let _ = api::update_penalty_type(&u, pt_id, Some(&name_trim), Some(&color_val), desc_opt.as_deref()).await;
                                                                    data.restart();
                                                                });
                                                            },
                                                            "Save"
                                                        }
                                                        button {
                                                            class: "btn btn-sm btn-secondary",
                                                            r#type: "button",
                                                            onclick: move |_| {
                                                                editing_pt_id.set(None);
                                                                edit_error.set(None);
                                                            },
                                                            "Cancel"
                                                        }
                                                    }
                                                }
                };
            let view_tr = rsx! {
                                                tr { key: "{pt_id}",
                                                    td { "{name}" }
                                                    td {
                                                        div {
                                                            class: "rounded border d-inline-block",
                                                            style: format!("width: 20px; height: 20px; background-color: #{};", color)
                                                        }
                                                    }
                                                    td { class: "small text-muted", "{preview}" }
                                                    td {
                                                        button {
                                                            class: "btn btn-sm btn-outline-primary me-1",
                                                            r#type: "button",
                                                            onclick: move |_| {
                                                                editing_pt_id.set(Some(pt_id));
                                                                edit_name.set(name.clone());
                                                                edit_color.set(color.clone());
                                                                edit_desc.set(desc.clone());
                                                                edit_error.set(None);
                                                            },
                                                            "Edit"
                                                        }
                                                        button {
                                                            class: "btn btn-sm btn-outline-danger",
                                                            r#type: "button",
                                                            onclick: move |_| {
                                                                let u = url_del.clone();
                                                                let row_id = pt_id;
                                                                let mut data = data.clone();
                                                                spawn(async move {
                                                                    let _ = api::delete_penalty_type(&u, row_id).await;
                                                                    data.restart();
                                                                });
                                                            },
                                                            "Delete"
                                                        }
                                                    }
                                                }
                };
            if is_editing { edit_tr } else { view_tr }
        })
        .collect();
    rsx! {
        for el in row_elements.iter() {
            {el}
        }
        if add_new_penalty() {
            tr { key: "{add_new_key}",
                td {
                    input {
                        r#type: "text",
                        class: "form-control form-control-sm",
                        maxlength: "{NAME_MAX_LEN}",
                        placeholder: "Name (max 50)",
                        value: "{edit_name()}",
                        oninput: move |ev| {
                            edit_name.set(ev.value().clone());
                            edit_error.set(None);
                        }
                    }
                    span { class: "small text-muted", "{edit_name().len()}/{NAME_MAX_LEN}" }
                    if let Some(ref err) = edit_error() {
                        span { class: "small text-danger d-block", "{err}" }
                    }
                }
                td {
                    div {
                        class: "d-flex align-items-center gap-1",
                        div {
                            class: "rounded border",
                            style: format!("width: 24px; height: 24px; background-color: #{}; cursor: pointer;", edit_color()),
                            onclick: move |_| {
                                if show_color_picker_for() == Some(-1) {
                                    show_color_picker_for.set(None);
                                } else {
                                    show_color_picker_for.set(Some(-1));
                                    custom_color_hex.set(edit_color());
                                }
                            }
                        }
                        if show_color_picker_for() == Some(-1) {
                            div { class: "position-absolute bg-white border rounded p-2 shadow", style: "z-index: 1000;",
                                div { class: "d-flex flex-wrap gap-1 mb-2", style: "width: 150px;",
                                    for c in PREDEFINED_COLORS.iter() {
                                        div {
                                            class: "rounded-circle border",
                                            style: format!("width: 20px; height: 20px; background-color: #{}; cursor: pointer;", *c),
                                            onclick: move |_| {
                                                edit_color.set(c.to_string());
                                                custom_color_hex.set(c.to_string());
                                            }
                                        }
                                    }
                                }
                                div { class: "input-group input-group-sm",
                                    span { class: "input-group-text", "#" }
                                    input {
                                        r#type: "text",
                                        class: "form-control",
                                        value: "{custom_color_hex()}",
                                        oninput: move |ev| custom_color_hex.set(ev.value().clone())
                                    }
                                    button {
                                        class: "btn btn-outline-primary btn-sm",
                                        r#type: "button",
                                        onclick: move |_| {
                                            let c = custom_color_hex().trim().trim_start_matches('#').to_string();
                                            if c.len() == 6 {
                                                edit_color.set(c);
                                                show_color_picker_for.set(None);
                                            }
                                        },
                                        "Apply"
                                    }
                                }
                            }
                        }
                    }
                }
                td {
                    textarea {
                        class: "form-control form-control-sm",
                        rows: "3",
                        placeholder: "Description (optional)",
                        value: "{edit_desc()}",
                        oninput: move |ev| edit_desc.set(ev.value().clone())
                    }
                }
                td {
                    button {
                        class: "btn btn-sm btn-primary me-1",
                        r#type: "button",
                        onclick: move |_| {
                            let u = url.clone();
                            let name_trim = edit_name().trim().to_string();
                            if name_trim.is_empty() {
                                edit_error.set(Some("Name is required.".to_string()));
                                return;
                            }
                            if name_trim.len() > NAME_MAX_LEN {
                                edit_error.set(Some(format!("Name must be at most {} characters.", NAME_MAX_LEN)));
                                return;
                            }
                            let color_val = edit_color().trim_start_matches('#').to_string();
                            let desc_val = edit_desc().trim().to_string();
                            let color_opt = if color_val.len() == 6 { Some(color_val) } else { None };
                            let desc_opt = if desc_val.is_empty() { None } else { Some(desc_val) };
                            add_new_penalty.set(false);
                            edit_error.set(None);
                            let mut data = data.clone();
                            spawn(async move {
                                let _ = api::create_penalty_type(&u, &name_trim, color_opt.as_deref(), desc_opt.as_deref()).await;
                                data.restart();
                            });
                        },
                        "Save"
                    }
                    button {
                        class: "btn btn-sm btn-secondary",
                        r#type: "button",
                        onclick: move |_| {
                            add_new_penalty.set(false);
                            edit_name.set(String::new());
                            edit_color.set("808080".to_string());
                            edit_desc.set(String::new());
                            edit_error.set(None);
                            show_color_picker_for.set(None);
                        },
                        "Cancel"
                    }
                }
            }
        }
        tr {
            td { colspan: "4", class: "border-0 pt-1",
                button {
                    class: "btn btn-sm btn-outline-secondary",
                    r#type: "button",
                    onclick: move |_| {
                        if !add_new_penalty() && editing_pt_id().is_none() {
                            add_new_penalty.set(true);
                            edit_name.set(String::new());
                            edit_color.set("808080".to_string());
                            edit_desc.set(String::new());
                            edit_error.set(None);
                        }
                    },
                    "+ Add penalty type"
                }
            }
        }
    }
}

#[component]
pub fn TournamentSettings(url: String) -> Element {
    let navigator = use_navigator();
    let url_for_data = url.clone();
    let data = use_resource(move || {
        let u = url_for_data.clone();
        async move { api::tournament_detail(&u).await.map_err(|e| e.to_string()) }
    });
    let mut editing_pt_id = use_signal(|| None as Option<i32>);
    let mut add_new_penalty = use_signal(|| false);
    let mut edit_name = use_signal(|| String::new());
    let mut edit_color = use_signal(|| "808080".to_string());
    let mut edit_desc = use_signal(|| String::new());
    let mut edit_error = use_signal(|| None as Option<String>);
    let mut show_color_picker_for = use_signal(|| None as Option<i32>);
    let mut custom_color_hex = use_signal(|| String::new());
    let val = data.value();
    let _backend = api::base_url();
    let url_form = url.clone();
    rsx! {
        if let Some(Ok(d)) = val.read().as_ref() {
            div { class: "penalty-settings-wrap",
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
                            form {
                                id: "tournament-settings-form",
                                onsubmit: move |ev| {
                                    ev.prevent_default();
                                    let params: Vec<(String, String)> = vec![
                                        ("name".into(), get_form_value("name")),
                                        ("location".into(), get_form_value("location")),
                                        ("start_date".into(), get_form_value("start_date")),
                                        ("end_date".into(), get_form_value("end_date")),
                                        ("num_fields".into(), get_form_value("num_fields")),
                                        ("n_max_teams".into(), get_form_value("n_max_teams")),
                                        ("max_team_size_roster".into(), get_form_value("max_team_size_roster")),
                                        ("max_team_size_field".into(), get_form_value("max_team_size_field")),
                                        ("team_reg_fee".into(), get_form_value("team_reg_fee")),
                                        ("player_reg_fee".into(), get_form_value("player_reg_fee")),
                                        ("about".into(), get_form_textarea("about")),
                                        ("terms_link".into(), get_form_value("terms_link")),
                                        ("head_refs_allowed_list".into(), get_form_value("head_refs_allowed_list")),
                                    ];
                                    let mut params = params;
                                    if get_form_check("head_refs_allow_anyone") {
                                        params.push(("head_refs_allow_anyone".into(), "on".to_string()));
                                    }
                                    if get_form_check("head_refs_allow_reffing_teams") {
                                        params.push(("head_refs_allow_reffing_teams".into(), "on".to_string()));
                                    }
                                    if get_form_check("published") {
                                        params.push(("published".into(), "on".to_string()));
                                    }
                                    if get_form_check("schedule_published") {
                                        params.push(("schedule_published".into(), "on".to_string()));
                                    }
                                    if get_form_check("registration_open") {
                                        params.push(("registration_open".into(), "on".to_string()));
                                    }
                                    let nav = navigator.clone();
                                    let url_submit = url_form.clone();
                                    spawn(async move {
                                        match api::update_tournament_settings(&url_submit, &params).await {
                                            Ok(res) => {
                                                if res.success {
                                                    nav.push(Route::TournamentHome { url: url_submit });
                                                }
                                            }
                                            Err(_) => {}
                                        }
                                    });
                                },
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
                                            input { r#type: "date", class: "form-control", id: "end_date", name: "end_date", value: "{d.tournament.end_date.as_deref().map(|s| s.split('T').next().unwrap_or(s)).unwrap_or(\"\")}" }
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

                    div { class: "card mt-4",
                        div { class: "card-header", h5 { class: "mb-0", "Penalty Types" } }
                        div { class: "card-body",
                            div { class: "table-responsive",
                                table { class: "table table-sm",
                                    thead {
                                        tr {
                                            th { "Name" }
                                            th { "Color" }
                                            th { "Description" }
                                            th { style: "width: 1%; white-space: nowrap;", "Actions" }
                                        }
                                    }
                                    tbody {
                                        PenaltyTypesTableBody {
                                            penalty_types: d.penalty_types.clone(),
                                            url: url.clone(),
                                            data: data.clone(),
                                            editing_pt_id: editing_pt_id,
                                            add_new_penalty: add_new_penalty,
                                            edit_name: edit_name,
                                            edit_color: edit_color,
                                            edit_desc: edit_desc,
                                            edit_error: edit_error,
                                            show_color_picker_for: show_color_picker_for,
                                            custom_color_hex: custom_color_hex,
                                        }
                                    }
                                }
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
