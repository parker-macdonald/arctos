use crate::api;
use crate::types::SideCompCategory;
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn SideCompDetail(url: String, comp_id: i32) -> Element {
    let detail = use_resource(move || async move { api::sidecomp_detail(comp_id).await });
    let mut action_error = use_signal(|| None::<String>);

    let url_for_back = url.clone();
    let url_for_edit = url.clone();
    let url_for_register = url.clone();

    rsx! {
        div { class: "row",
            div { class: "col-12",
                Link {
                    to: Route::TournamentHomeWithTab { url: url_for_back, tab: "sidecomps".to_string() },
                    class: "btn btn-link",
                    "<- Back to side competitions"
                }
                match detail.read().as_ref() {
                    Some(Ok(d)) => {
                        let registrants = d.registrants.clone();
                        let viewer_is_to = d.viewer_is_to;
                        let viewer_can_register = d.viewer_can_register;
                        let viewer_is_registered_in_comp = d.viewer_is_registered_in_comp;
                        let registration_open = d.registration_open;
                        let description = d.description.clone();
                        let categories = d.categories.clone();
                        let has_categories = d.has_categories;
                        rsx! {
                            h1 { "{d.name}" }
                            p {
                                span { class: "badge bg-secondary me-2", "{d.type_}" }
                                if registration_open {
                                    span { class: "badge bg-success", "Open" }
                                } else {
                                    span { class: "badge bg-secondary", "Closed" }
                                }
                            }
                            if let Some(desc) = description.as_ref() {
                                if !desc.is_empty() {
                                    p { style: "white-space: pre-wrap;", "{desc}" }
                                }
                            }
                            if viewer_is_to {
                                div { class: "mb-3",
                                    Link {
                                        to: Route::SideCompEdit { url: url_for_edit.clone(), comp_id },
                                        class: "btn btn-outline-secondary me-2",
                                        "Edit"
                                    }
                                    Link {
                                        to: Route::SideCompRegisterAsTo { url: url_for_register.clone(), comp_id },
                                        class: "btn btn-outline-primary",
                                        "Quick Register players"
                                    }
                                }
                            }
                            SelfRegisterControls {
                                comp_id,
                                action_error,
                                show_register: viewer_can_register,
                                show_deregister: viewer_is_registered_in_comp,
                                categories: categories.clone(),
                                has_categories,
                            }
                            h2 { "Registrants ({registrants.len()})" }
                            if registrants.is_empty() {
                                p { class: "text-muted", "No registrants yet." }
                            } else {
                                table { class: "table",
                                    thead { tr {
                                        th { "#" }
                                        th { "Player" }
                                        if has_categories { th { "Category" } }
                                        th { "Registered" }
                                        th { "Source" }
                                    } }
                                    tbody {
                                        for r in registrants.iter() {
                                            tr {
                                                td { "{r.entry_number}" }
                                                td { "{r.player_name}" }
                                                if has_categories {
                                                    td { "{r.category_name.clone().unwrap_or_default()}" }
                                                }
                                                td { "{r.registered_at.clone().unwrap_or_default()}" }
                                                td { if r.registered_by_to { "TO" } else { "Self" } }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    Some(Err(e)) => rsx! { div { class: "alert alert-danger", "Error: {e}" } },
                    None => rsx! { div { class: "spinner-border" } },
                }
                if let Some(err) = action_error() {
                    div { class: "alert alert-danger mt-3", "{err}" }
                }
            }
        }
    }
}

#[component]
fn SelfRegisterControls(
    comp_id: i32,
    action_error: Signal<Option<String>>,
    show_register: bool,
    show_deregister: bool,
    categories: Vec<SideCompCategory>,
    has_categories: bool,
) -> Element {
    let mut busy = use_signal(|| false);
    let mut selected_category = use_signal(|| None as Option<i32>);
    if !show_register && !show_deregister {
        return rsx! {};
    }
    let register_disabled = busy() || (has_categories && selected_category().is_none());
    rsx! {
        div { class: "mb-3 d-flex gap-2 align-items-center",
            if show_register {
                if has_categories {
                    select {
                        class: "form-select w-auto",
                        value: selected_category().map(|v| v.to_string()).unwrap_or_default(),
                        onchange: move |evt| selected_category.set(evt.value().parse::<i32>().ok()),
                        option { value: "", "Choose a category..." }
                        for c in categories.iter() {
                            option { value: "{c.id}", "{c.name}" }
                        }
                    }
                }
                button {
                    class: "btn btn-success",
                    disabled: register_disabled,
                    onclick: move |_| {
                        busy.set(true);
                        let mut err = action_error;
                        let cat = selected_category();
                        spawn(async move {
                            match api::sidecomp_register(comp_id, cat).await {
                                Ok(_) => {
                                    if let Some(win) = web_sys::window() {
                                        let _ = win.location().reload();
                                    }
                                }
                                Err(e) => err.set(Some(e)),
                            }
                            busy.set(false);
                        });
                    },
                    "Register me"
                }
            }
            if show_deregister {
                button {
                    class: "btn btn-outline-danger",
                    disabled: busy(),
                    onclick: move |_| {
                        busy.set(true);
                        let mut err = action_error;
                        spawn(async move {
                            match api::sidecomp_deregister(comp_id).await {
                                Ok(_) => {
                                    if let Some(win) = web_sys::window() {
                                        let _ = win.location().reload();
                                    }
                                }
                                Err(e) => err.set(Some(e)),
                            }
                            busy.set(false);
                        });
                    },
                    "Deregister me"
                }
            }
        }
    }
}
