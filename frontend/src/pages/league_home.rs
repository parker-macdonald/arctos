use crate::api;
use crate::components::{
    EditRegistrationContext, EditRegistrationModal, EventAbout, EventHeader, EventTeamsList,
    LeagueRegistrationButtons,
};
use crate::types::{ToEntry, User};
use crate::Route;
use dioxus::prelude::*;

fn get_query_param(name: &str) -> Option<String> {
    let window = web_sys::window()?;
    let search = window.location().search().ok()?;
    let params = web_sys::UrlSearchParams::new_with_str(&search).ok()?;
    params.get(name)
}

fn is_current_user_to(me: Option<&Result<User, String>>, to_entries: &[ToEntry]) -> bool {
    me.and_then(|r| r.as_ref().ok())
        .map_or(false, |u| {
            to_entries
                .iter()
                .any(|e| e.user_id == u.id && e.user_type == u.user_type)
        })
}

fn format_date(iso: &str) -> String {
    iso.split('T').next().unwrap_or(iso).to_string()
}

fn format_date_display(start: &str, end: Option<&String>) -> String {
    let start_fmt = format_date(start);
    match end {
        None => start_fmt,
        Some(e) if e.as_str() == start => start_fmt,
        Some(e) => format!("{} - {}", start_fmt, format_date(e)),
    }
}

#[component]
pub fn LeagueHome(league_url: String) -> Element {
    let url_for_data = league_url.clone();
    let mut refresh = use_signal(|| 0u32);
    let mut show_edit_modal = use_signal(|| false);
    let mut delete_modal_open = use_signal(|| false);
    let mut delete_confirm_url = use_signal(|| String::new());
    let mut delete_error = use_signal(|| None::<String>);
    let mut show_registration_success = use_signal(|| false);
    let navigator = use_navigator();
    let url_for_delete_confirm = league_url.clone();
    let data = use_resource(move || {
        let _ = refresh();
        let lu = url_for_data.clone();
        async move { api::league_detail(&lu).await.map_err(|e| e.to_string()) }
    });
    let me_res = use_resource(move || async move { api::me().await });
    let league_url_for_warning = league_url.clone();
    let waiver_warning = use_resource(move || {
        let lu = league_url_for_warning.clone();
        async move {
            match api::get_my_player_registration_league(&lu).await {
                Ok(res) => res.waiver_required && !res.waiver_signature_valid,
                Err(_) => false,
            }
        }
    });
    let val = data.value();
    let mut about_markdown = use_signal(|| Option::<String>::None);
    use_effect(move || {
        let v = val.read();
        if let Some(Ok(d)) = v.as_ref() {
            about_markdown.set(d.league.about.clone());
        } else {
            about_markdown.set(None);
        }
    });
    let about_html = use_resource(use_reactive(&about_markdown, move |md| {
        let md = md().clone();
        async move {
            match md.as_deref() {
                Some(m) if !m.is_empty() => api::render_markdown(m).await,
                _ => Ok(String::new()),
            }
        }
    }));

    use_effect(move || {
        if get_query_param("registered").as_deref() == Some("1") {
            show_registration_success.set(true);
            if let Some(window) = web_sys::window() {
                if let Ok(loc) = window.location().pathname() {
                    let _ = window.history().and_then(|h| h.replace_state_with_url(&wasm_bindgen::JsValue::NULL, "", Some(&loc)));
                }
            }
        }
    });

    rsx! {
        if let Some(Ok(d)) = val.read().as_ref() {
            {{
                let team_fee = d.league.team_reg_fee.unwrap_or(0.0);
                let player_fee = d.league.player_reg_fee.unwrap_or(0.0);
                let team_fee_str = format!("${:.2}", team_fee);
                let player_fee_str = format!("${:.2}", player_fee);
                rsx! {
            EventHeader {
                title: d.league.name.clone(),
                subtitle: String::new(),
                badge_league_url: None,
                badge_season: None,
                badge_name: None,
            }

            div { class: "row mb-3",
                div { class: "col-12 d-flex flex-wrap gap-2",
                    if show_registration_success() {
                        div { class: "alert alert-success mb-0 w-100",
                            "Registration submitted!"
                        }
                    }
                    Link { to: Route::LeagueResults { league_url: league_url.clone() }, class: "btn btn-outline-primary", "Results" }
                    if (d.league.team_registration_open || d.league.player_registration_open) || d.is_current_team_registered || d.is_current_player_registered {
                        LeagueRegistrationButtons {
                            league_url: league_url.clone(),
                            registration_open: d.league.registration_open,
                            team_registration_open: Some(d.league.team_registration_open),
                            player_registration_open: Some(d.league.player_registration_open),
                            current_user: me_res.read().as_ref().cloned(),
                            is_team_registered: d.is_current_team_registered,
                            is_player_registered: d.is_current_player_registered,
                            use_edit_modal: true,
                            on_edit_registration: move |_| show_edit_modal.set(true),
                            register_label: String::from("Register"),
                            show_edit_warning: waiver_warning
                                .value()
                                .read()
                                .as_ref()
                                .copied()
                                .unwrap_or(false),
                        }
                    }
                }
            }



            div { class: "row",
                div { class: "col-md-8",
                    EventAbout {
                        card_title: "League Information".to_string(),
                        show_fees: d.league.team_registration_open || d.league.player_registration_open,
                        team_fee,
                        player_fee,
                        team_fee_str: team_fee_str.clone(),
                        player_fee_str: player_fee_str.clone(),
                        max_teams: d.league.n_max_teams,
                        max_roster: d.league.max_team_size_roster,
                        max_field: d.league.max_team_size_field,
                        about_html: about_html.value().read().as_ref().and_then(|r| r.as_ref().ok()).cloned(),
                        about_raw: d.league.about.clone(),
                        empty_message: "League details coming soon!".to_string(),
                    }
                }
                if !d.events.is_empty() {
                    div { class: "col-md-4",
                        div { class: "card",
                            div { class: "card-header", h5 { class: "mb-0", "Events" } }
                            div { class: "card-body",
                                div { class: "list-group list-group-flush",
                                    for event in d.events.iter() {
                                        li { key: "{event.url}", class: "list-group-item d-flex justify-content-between align-items-center",
                                            Link { to: Route::TournamentHome { url: event.url.clone() }, class: "text-decoration-none",
                                                strong { "{event.name}" }
                                            }
                                            span { class: "text-muted",
                                                "{event.location.as_deref().unwrap_or(\"TBA\")} • {format_date_display(&event.start_date, event.end_date.as_ref())}"
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        if is_current_user_to(me_res.read().as_ref(), &d.to_entries) {
                            div { class: "card mt-3",
                                div { class: "card-header", h5 { class: "mb-0", "Admin" } }
                                div { class: "card-body",
                                    div { class: "d-grid gap-2",
                                        Link { to: Route::LeagueSettings { league_url: league_url.clone() }, class: "btn btn-outline-secondary", "Settings" }
                                        Link { to: Route::LeagueNewTournament { league_url: league_url.clone() }, class: "btn btn-outline-secondary", "Add Event" }
                                        Link { to: Route::LeagueManage { league_url: league_url.clone() }, class: "btn btn-outline-warning", "Registration Management" }
                                        button {
                                            class: "btn btn-outline-danger",
                                            onclick: move |_| {
                                                delete_modal_open.set(true);
                                                delete_confirm_url.set(String::new());
                                                delete_error.set(None);
                                            },
                                            "Delete League"
                                        }
                                    }
                                }
                            }
                        }
                    }
                } else if is_current_user_to(me_res.read().as_ref(), &d.to_entries) {
                    div { class: "col-md-4",
                        div { class: "card",
                            div { class: "card-header", h5 { class: "mb-0", "Admin" } }
                            div { class: "card-body",
                                div { class: "d-grid gap-2",
                                    Link { to: Route::LeagueSettings { league_url: league_url.clone() }, class: "btn btn-outline-secondary", "Settings" }
                                    Link { to: Route::LeagueNewTournament { league_url: league_url.clone() }, class: "btn btn-outline-secondary", "Add Event" }
                                    Link { to: Route::LeagueManage { league_url: league_url.clone() }, class: "btn btn-outline-warning", "Registration Management" }
                                    button {
                                        class: "btn btn-outline-danger",
                                        onclick: move |_| {
                                            delete_modal_open.set(true);
                                            delete_confirm_url.set(String::new());
                                            delete_error.set(None);
                                        },
                                        "Delete League"
                                    }
                                }
                            }
                        }
                    }
                }

            EventTeamsList {
                teams: d.teams_with_counts.clone(),
                card_title: "Registered Teams".to_string(),
                show_registered_at: true,
                max_team_size_roster: d.league.max_team_size_roster,
            }
            if show_edit_modal() {
                if let Some(Ok(me)) = me_res.read().as_ref() {
                    EditRegistrationModal {
                        context: EditRegistrationContext::League { league_url: league_url.clone() },
                        user_type: me.user_type.clone(),
                        on_close: move |_| show_edit_modal.set(false),
                        on_success: move |_| {
                            show_edit_modal.set(false);
                            refresh.set(refresh() + 1);
                        },
                    }
                }
            }
            if delete_modal_open() {
                div { class: "modal d-block", tabindex: "-1", style: "background: rgba(0,0,0,0.5);",
                    div { class: "modal-dialog modal-dialog-centered",
                        div { class: "modal-content",
                            div { class: "modal-header",
                                h5 { class: "modal-title", "Delete League" }
                                button { class: "btn-close", onclick: move |_| delete_modal_open.set(false) }
                            }
                            div { class: "modal-body",
                                if let Some(ref err) = delete_error() {
                                    div { class: "alert alert-danger mb-3", "{err}" }
                                }
                                div { class: "alert alert-danger",
                                    strong { "Warning: " }
                                    "This action cannot be undone. The league and all its events, registrations, and data will be permanently removed."
                                }
                                p { "To confirm, type the league URL exactly:" }
                                p { class: "text-center mb-2", strong { "{league_url}" } }
                                form {
                                    id: "delete-league-form",
                                    onsubmit: move |ev| {
                                        ev.prevent_default();
                                        if delete_confirm_url() != url_for_delete_confirm {
                                            return;
                                        }
                                        delete_error.set(None);
                                        let nav = navigator.clone();
                                        let url_submit = url_for_delete_confirm.clone();
                                        let confirm = delete_confirm_url();
                                        spawn(async move {
                                            match api::delete_league(&url_submit, &confirm).await {
                                                Ok(res) if res.success => {
                                                    nav.push(Route::Index {});
                                                }
                                                Ok(res) => {
                                                    delete_error.set(Some(res.error.unwrap_or_else(|| "Delete failed.".to_string())));
                                                }
                                                Err(e) => {
                                                    delete_error.set(Some(e));
                                                }
                                            }
                                        });
                                    },
                                    div { class: "mb-3",
                                        label { class: "form-label", "League URL:" }
                                        input {
                                            class: "form-control",
                                            name: "confirm_url",
                                            r#type: "text",
                                            placeholder: "{league_url}",
                                            value: "{delete_confirm_url()}",
                                            oninput: move |e| delete_confirm_url.set(e.value()),
                                        }
                                    }
                                }
                            }
                            div { class: "modal-footer",
                                button { class: "btn btn-secondary", onclick: move |_| delete_modal_open.set(false), "Cancel" }
                                button {
                                    class: "btn btn-danger",
                                    r#type: "submit",
                                    form: "delete-league-form",
                                    disabled: delete_confirm_url() != league_url,
                                    "Delete League"
                                }
                            }
                        }
                    }
                }
            }
            }
            }
        }}
        } else if let Some(Err(e)) = val.read().as_ref() {
            div { class: "alert alert-danger", "{e}" }
        } else {
            p { class: "text-muted", "Loading…" }
        }
    }
}
