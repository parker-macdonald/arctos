//! Penalty types table for league settings.

use crate::api;
use dioxus::prelude::*;

const PREDEFINED_COLORS: &[&str] = &[
    "FF0000", "FF8C00", "FFD700", "32CD32", "008000", "00CED1", "1E90FF", "0000FF",
    "8A2BE2", "FF00FF", "C71585", "A52A2A", "808080", "000000",
];
const NAME_MAX_LEN: usize = 50;

#[component]
pub fn LeaguePenaltyTypesTable(
    penalty_types: Vec<crate::types::PenaltyType>,
    league_url: String,
    on_refresh: EventHandler<()>,
) -> Element {
    let mut editing_pt_id = use_signal(|| None as Option<i32>);
    let mut add_new_penalty = use_signal(|| false);
    let mut edit_name = use_signal(|| String::new());
    let mut edit_color = use_signal(|| "808080".to_string());
    let mut edit_desc = use_signal(|| String::new());
    let mut edit_error = use_signal(|| None as Option<String>);
    let mut show_color_picker_for = use_signal(|| None as Option<i32>);
    let mut custom_color_hex = use_signal(|| String::new());

    let penalty_rows: Vec<_> = penalty_types
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
            )
        })
        .collect();

    let row_elements: Vec<Element> = penalty_rows
        .into_iter()
        .map(|(pt_id, name, color, desc, preview, is_editing)| {
            let url_save = league_url.clone();
            let url_del = league_url.clone();
            let on_refresh = on_refresh.clone();
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
                                let desc_opt = if desc_val.is_empty() { None } else { Some(desc_val) };
                                editing_pt_id.set(None);
                                edit_error.set(None);
                                let u = url_save.clone();
                                spawn(async move {
                                    let _ = api::update_league_penalty_type(&u, pt_id, Some(&name_trim), Some(&color_val), desc_opt.as_deref()).await;
                                    on_refresh.call(());
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
                                spawn(async move {
                                    let _ = api::delete_league_penalty_type(&u, row_id).await;
                                    on_refresh.call(());
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
            tr { key: "add-new-row-{league_url}",
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
                            let u = league_url.clone();
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
                            spawn(async move {
                                let _ = api::create_league_penalty_type(&u, &name_trim, color_opt.as_deref(), desc_opt.as_deref()).await;
                                on_refresh.call(());
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
