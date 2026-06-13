//! Category editors for side competitions.
//!
//! `CategoriesLocalEditor` edits an in-memory list of names for the create form
//! (no API calls — the names are submitted with the comp). `CategoriesLiveEditor`
//! drives live create/rename/delete against the API for the edit form, including
//! the delete-resolution modal (deregister vs. move) when a category has players.

use crate::api;
use crate::types::SideCompCategory;
use dioxus::prelude::*;

const NAME_MAX_LEN: usize = 100;

#[component]
pub fn CategoriesLocalEditor(names: Signal<Vec<String>>) -> Element {
    rsx! {
        div { class: "mb-3",
            label { class: "form-label", "Categories" }
            div { class: "form-text mb-2",
                "Optional. Leave empty for a single group. When categories exist, players must choose one at registration."
            }
            for (i , name) in names().into_iter().enumerate() {
                div { key: "{i}", class: "input-group input-group-sm mb-1",
                    input {
                        class: "form-control",
                        r#type: "text",
                        maxlength: "{NAME_MAX_LEN}",
                        placeholder: "Category name",
                        value: "{name}",
                        oninput: move |evt| {
                            let mut n = names;
                            n.write()[i] = evt.value();
                        },
                    }
                    button {
                        class: "btn btn-outline-danger",
                        r#type: "button",
                        onclick: move |_| {
                            let mut n = names;
                            n.write().remove(i);
                        },
                        "Remove"
                    }
                }
            }
            button {
                class: "btn btn-sm btn-outline-secondary",
                r#type: "button",
                onclick: move |_| {
                    let mut n = names;
                    n.write().push(String::new());
                },
                "+ Add category"
            }
        }
    }
}

#[component]
pub fn CategoriesLiveEditor(
    comp_id: i32,
    categories: Vec<SideCompCategory>,
    on_refresh: EventHandler<()>,
) -> Element {
    let mut editing_id = use_signal(|| None as Option<i32>);
    let mut add_new = use_signal(|| false);
    let mut edit_name = use_signal(String::new);
    let mut edit_error = use_signal(|| None as Option<String>);

    let mut delete_target = use_signal(|| None as Option<SideCompCategory>);
    let mut delete_mode = use_signal(|| "deregister".to_string());
    let mut move_target = use_signal(|| None as Option<i32>);
    let mut modal_error = use_signal(|| None as Option<String>);
    let mut busy = use_signal(|| false);

    let rows: Vec<Element> = categories
        .iter()
        .cloned()
        .map(|cat| {
            let is_editing = editing_id() == Some(cat.id);
            let name_for_edit = cat.name.clone();
            let cat_for_delete = cat.clone();
            if is_editing {
                rsx! {
                    tr { key: "edit-{cat.id}",
                        td {
                            input {
                                class: "form-control form-control-sm",
                                r#type: "text",
                                maxlength: "{NAME_MAX_LEN}",
                                value: "{edit_name()}",
                                oninput: move |evt| {
                                    edit_name.set(evt.value());
                                    edit_error.set(None);
                                },
                            }
                            if let Some(err) = edit_error() {
                                span { class: "small text-danger d-block", "{err}" }
                            }
                        }
                        td { class: "text-muted small", "{cat.registrant_count}" }
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
                                    let cat_id = cat.id;
                                    let on_refresh = on_refresh;
                                    editing_id.set(None);
                                    edit_error.set(None);
                                    spawn(async move {
                                        match api::sidecomp_rename_category(cat_id, &name_trim).await {
                                            Ok(_) => on_refresh.call(()),
                                            Err(e) => edit_error.set(Some(e)),
                                        }
                                    });
                                },
                                "Save"
                            }
                            button {
                                class: "btn btn-sm btn-secondary",
                                r#type: "button",
                                onclick: move |_| {
                                    editing_id.set(None);
                                    edit_error.set(None);
                                },
                                "Cancel"
                            }
                        }
                    }
                }
            } else {
                rsx! {
                    tr { key: "{cat.id}",
                        td { "{cat.name}" }
                        td { class: "text-muted small", "{cat.registrant_count}" }
                        td {
                            button {
                                class: "btn btn-sm btn-outline-primary me-1",
                                r#type: "button",
                                onclick: move |_| {
                                    editing_id.set(Some(cat.id));
                                    add_new.set(false);
                                    edit_name.set(name_for_edit.clone());
                                    edit_error.set(None);
                                },
                                "Edit"
                            }
                            button {
                                class: "btn btn-sm btn-outline-danger",
                                r#type: "button",
                                onclick: move |_| {
                                    if cat_for_delete.registrant_count == 0 {
                                        let cat_id = cat_for_delete.id;
                                        let on_refresh = on_refresh;
                                        spawn(async move {
                                            match api::sidecomp_delete_category(cat_id, "deregister", None).await {
                                                Ok(_) => on_refresh.call(()),
                                                Err(e) => modal_error.set(Some(e)),
                                            }
                                        });
                                    } else {
                                        delete_target.set(Some(cat_for_delete.clone()));
                                        delete_mode.set("deregister".to_string());
                                        move_target.set(None);
                                        modal_error.set(None);
                                    }
                                },
                                "Delete"
                            }
                        }
                    }
                }
            }
        })
        .collect();

    let other_categories: Vec<SideCompCategory> = match delete_target() {
        Some(ref t) => categories.iter().filter(|c| c.id != t.id).cloned().collect(),
        None => Vec::new(),
    };
    let can_move = !other_categories.is_empty();

    rsx! {
        div { class: "mb-3",
            label { class: "form-label", "Categories" }
            div { class: "form-text mb-2",
                "When categories exist, players must choose one at registration."
            }
            table { class: "table table-sm align-middle",
                thead {
                    tr {
                        th { "Name" }
                        th { "Registered" }
                        th {}
                    }
                }
                tbody {
                    for el in rows.iter() {
                        {el}
                    }
                    if add_new() {
                        tr { key: "add-new-category-{comp_id}",
                            td {
                                input {
                                    class: "form-control form-control-sm",
                                    r#type: "text",
                                    maxlength: "{NAME_MAX_LEN}",
                                    placeholder: "Category name",
                                    value: "{edit_name()}",
                                    oninput: move |evt| {
                                        edit_name.set(evt.value());
                                        edit_error.set(None);
                                    },
                                }
                                if let Some(err) = edit_error() {
                                    span { class: "small text-danger d-block", "{err}" }
                                }
                            }
                            td { class: "text-muted small", "0" }
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
                                        let on_refresh = on_refresh;
                                        add_new.set(false);
                                        edit_error.set(None);
                                        spawn(async move {
                                            match api::sidecomp_create_category(comp_id, &name_trim).await {
                                                Ok(_) => on_refresh.call(()),
                                                Err(e) => edit_error.set(Some(e)),
                                            }
                                        });
                                    },
                                    "Save"
                                }
                                button {
                                    class: "btn btn-sm btn-secondary",
                                    r#type: "button",
                                    onclick: move |_| {
                                        add_new.set(false);
                                        edit_name.set(String::new());
                                        edit_error.set(None);
                                    },
                                    "Cancel"
                                }
                            }
                        }
                    }
                }
            }
            button {
                class: "btn btn-sm btn-outline-secondary",
                r#type: "button",
                onclick: move |_| {
                    if !add_new() && editing_id().is_none() {
                        add_new.set(true);
                        edit_name.set(String::new());
                        edit_error.set(None);
                    }
                },
                "+ Add category"
            }
        }

        if let Some(target) = delete_target() {
            div {
                class: "modal show d-block",
                style: "background: rgba(0,0,0,0.5);",
                tabindex: "-1",
                role: "dialog",
                aria_modal: "true",
                onclick: move |_| {
                    if !busy() {
                        delete_target.set(None);
                    }
                },
                div {
                    class: "modal-dialog modal-dialog-centered",
                    onclick: move |ev: Event<MouseData>| ev.stop_propagation(),
                    div { class: "modal-content",
                        div { class: "modal-header",
                            h5 { class: "modal-title", "Delete \"{target.name}\" — {target.registrant_count} registered" }
                            button {
                                r#type: "button",
                                class: "btn-close",
                                aria_label: "Close",
                                disabled: busy(),
                                onclick: move |_| delete_target.set(None),
                            }
                        }
                        div { class: "modal-body",
                            p { "This category has registered players. Choose what to do with them:" }
                            div { class: "form-check",
                                input {
                                    class: "form-check-input",
                                    r#type: "radio",
                                    name: "delete-mode",
                                    id: "delete-mode-deregister",
                                    checked: delete_mode() == "deregister",
                                    onchange: move |_| delete_mode.set("deregister".to_string()),
                                }
                                label { class: "form-check-label", r#for: "delete-mode-deregister",
                                    "Remove these players from the side competition"
                                }
                            }
                            if can_move {
                                div { class: "form-check",
                                    input {
                                        class: "form-check-input",
                                        r#type: "radio",
                                        name: "delete-mode",
                                        id: "delete-mode-move",
                                        checked: delete_mode() == "move",
                                        onchange: move |_| delete_mode.set("move".to_string()),
                                    }
                                    label { class: "form-check-label", r#for: "delete-mode-move",
                                        "Move these players to another category"
                                    }
                                }
                                if delete_mode() == "move" {
                                    select {
                                        class: "form-select mt-2",
                                        value: move_target().map(|v| v.to_string()).unwrap_or_default(),
                                        onchange: move |evt| {
                                            move_target.set(evt.value().parse::<i32>().ok());
                                        },
                                        option { value: "", "Select a category..." }
                                        for c in other_categories.iter() {
                                            option { value: "{c.id}", "{c.name}" }
                                        }
                                    }
                                }
                            }
                            if let Some(err) = modal_error() {
                                div { class: "alert alert-danger mt-2 mb-0", "{err}" }
                            }
                        }
                        div { class: "modal-footer",
                            button {
                                r#type: "button",
                                class: "btn btn-secondary",
                                disabled: busy(),
                                onclick: move |_| delete_target.set(None),
                                "Cancel"
                            }
                            button {
                                r#type: "button",
                                class: "btn btn-danger",
                                disabled: busy() || (delete_mode() == "move" && move_target().is_none()),
                                onclick: move |_| {
                                    let cat_id = target.id;
                                    let mode = delete_mode();
                                    let tgt = if mode == "move" { move_target() } else { None };
                                    let on_refresh = on_refresh;
                                    busy.set(true);
                                    modal_error.set(None);
                                    spawn(async move {
                                        match api::sidecomp_delete_category(cat_id, &mode, tgt).await {
                                            Ok(_) => {
                                                delete_target.set(None);
                                                busy.set(false);
                                                on_refresh.call(());
                                            }
                                            Err(e) => {
                                                modal_error.set(Some(e));
                                                busy.set(false);
                                            }
                                        }
                                    });
                                },
                                "Delete category"
                            }
                        }
                    }
                }
            }
        }
    }
}
