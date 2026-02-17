use crate::api;
use crate::types::{ToEntry, UpdatePlayerRegistrationRequest, UpdateTeamRegistrationRequest, User};
use crate::Route;
use dioxus::prelude::*;

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
pub fn TournamentHome(url: String) -> Element {
    let url_for_data = url.clone();
    let mut refresh = use_signal(|| 0u32);
    let data = use_resource(move || {
        let _ = refresh();
        let u = url_for_data.clone();
        async move { api::tournament_detail(&u).await.map_err(|e| e.to_string()) }
    });
    let me_res = use_resource(move || async move { api::me().await });
    let val = data.value();
    let backend = api::base_url();
    let mut delete_modal_open = use_signal(|| false);
    let mut delete_confirm_url = use_signal(|| String::new());
    let mut show_edit_player_modal = use_signal(|| false);
    let mut show_edit_team_modal = use_signal(|| false);
    let mut show_deregister_player_confirm = use_signal(|| false);
    let mut show_deregister_team_confirm = use_signal(|| false);
    let url_for_deregister_player = url.clone();
    let url_for_deregister_team = url.clone();
    let mut about_markdown = use_signal(|| Option::<String>::None);
    use_effect(move || {
        let v = val.read();
        if let Some(Ok(d)) = v.as_ref() {
            about_markdown.set(d.tournament.about.clone());
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

    rsx! {
        if let Some(Ok(d)) = val.read().as_ref() {
            {{
                let team_fee = d.tournament.team_reg_fee.unwrap_or(0.0);
                let player_fee = d.tournament.player_reg_fee.unwrap_or(0.0);
                let team_fee_str = format!("${:.2}", team_fee);
                let player_fee_str = format!("${:.2}", player_fee);
                let teams_count = d.teams_with_counts.len();
                let unattached_count = d.unattached_players.len();
                rsx! {
            div { class: "row",
                div { class: "col-12",
                    h1 { "{d.tournament.name}" }
                    p { class: "lead",
                        "{d.tournament.location.as_deref().unwrap_or(\"Location TBA\")} • {format_date_display(&d.tournament.start_date, d.tournament.end_date.as_ref())}"
                    }
                }
            }

            div { class: "row mb-3",
                div { class: "col-12 d-flex flex-wrap gap-2",
                    if d.tournament.schedule_published {
                        Link { to: Route::Schedule { url: url.clone() }, class: "btn btn-primary", "Schedule" }
                    } else {
                        Link { to: Route::Schedule { url: url.clone() }, class: "btn btn-outline-secondary", "Schedule (Not Published)" }
                    }
                    Link { to: Route::Results { url: url.clone() }, class: "btn btn-outline-primary", "Results" }
                    if d.tournament.bracket && (d.tournament.schedule_published || is_current_user_to(me_res.read().as_ref(), &d.to_entries)) {
                        Link { to: Route::Bracket { url: url.clone() }, class: "btn btn-outline-primary", "Bracket" }
                    }
                    if d.tournament.registration_open {
                        if let Some(Ok(current_user)) = me_res.read().as_ref() {
                            if current_user.user_type == "team" {
                                if d.is_current_team_registered {
                                    a { href: "{backend}/{url}/invitations", class: "btn btn-outline-secondary", "Manage Roster" }
                                    button {
                                        class: "btn btn-outline-secondary",
                                        onclick: move |_| show_edit_team_modal.set(true),
                                        "Edit Registration"
                                    }
                                } else {
                                    Link { to: Route::TournamentRegister { url: url.clone() }, class: "btn btn-success", "Register" }
                                }
                            } else if current_user.user_type == "player" {
                                if d.is_current_player_registered {
                                    button {
                                        class: "btn btn-outline-secondary",
                                        onclick: move |_| show_edit_player_modal.set(true),
                                        "Edit Registration"
                                    }
                                } else {
                                    Link { to: Route::TournamentRegister { url: url.clone() }, class: "btn btn-success", "Register" }
                                }
                            } else {
                                Link { to: Route::TournamentRegister { url: url.clone() }, class: "btn btn-success", "Register" }
                            }
                        } else {
                            Link { to: Route::TournamentRegister { url: url.clone() }, class: "btn btn-success", "Register" }
                        }
                    } else {
                        if let Some(Ok(current_user)) = me_res.read().as_ref() {
                            if current_user.user_type == "team" && d.is_current_team_registered {
                                a { href: "{backend}/{url}/invitations", class: "btn btn-outline-primary", "View Invitations" }
                            }
                        }
                        Link { to: Route::TournamentRegister { url: url.clone() }, class: "btn btn-outline-secondary", "Register" }
                    }
                }
            }

            div { class: "row",
                div { class: "col-md-8",
                    div { class: "card",
                        div { class: "card-header", h5 { class: "mb-0", "Tournament Information" } }
                        div { class: "card-body",
                            div { class: "row mb-3",
                                div { class: "col-md-6",
                                    p { strong { "Start Date: " } "{format_date(&d.tournament.start_date)}" }
                                    p { strong { "End Date: " } "{d.tournament.end_date.as_ref().map(|e| format_date(e)).unwrap_or_else(|| \"TBA\".into())}" }
                                    p { strong { "Number of Fields: " } "{d.tournament.num_fields.unwrap_or(1)}" }
                                }
                                div { class: "col-md-6",
                                    if let Some(max) = d.tournament.n_max_teams {
                                        p { strong { "Max Teams: " } "{max}" }
                                    }
                                    if let Some(roster) = d.tournament.max_team_size_roster {
                                        p { strong { "Max Team Size (Roster): " } "{roster}" }
                                    }
                                    if let Some(field) = d.tournament.max_team_size_field {
                                        p { strong { "Max Team Size (Field): " } "{field}" }
                                    }
                                }
                            }
                            if d.tournament.registration_open && (d.tournament.team_reg_fee.map(|f| f > 0.0).unwrap_or(false) || d.tournament.player_reg_fee.map(|f| f > 0.0).unwrap_or(false)) {
                                div { class: "alert alert-info mb-3",
                                    h6 { class: "mb-2", "Registration Fees" }
                                    if d.tournament.team_reg_fee.map(|f| f > 0.0).unwrap_or(false) {
                                        p { class: "mb-1", strong { "Team Registration: " } "{team_fee_str}" }
                                    }
                                    if d.tournament.player_reg_fee.map(|f| f > 0.0).unwrap_or(false) {
                                        p { class: "mb-0", strong { "Player Registration: " } "{player_fee_str}" }
                                    }
                                }
                            }
                            if let Some(about) = &d.tournament.about {
                                if !about.is_empty() {
                                    hr {}
                                    if let Some(Ok(html)) = about_html.value().read().as_ref() {
                                        if html.is_empty() {
                                            div { class: "markdown-content", style: "white-space: pre-wrap;", "{about}" }
                                        } else {
                                            div { dangerous_inner_html: "{html}" }
                                        }
                                    } else {
                                        div { class: "markdown-content", style: "white-space: pre-wrap;", "{about}" }
                                    }
                                }
                            } else {
                                p { class: "text-muted", "Tournament details coming soon!" }
                            }
                        }
                    }
                }
                if is_current_user_to(me_res.read().as_ref(), &d.to_entries) {
                    div { class: "col-md-4",
                        div { class: "card",
                            div { class: "card-header", h5 { class: "mb-0", "Admin" } }
                            div { class: "card-body",
                                div { class: "d-grid gap-2",
                                    Link { to: Route::TournamentSettings { url: url.clone() }, class: "btn btn-outline-secondary", "Settings" }
                                    Link { to: Route::BracketSetup { url: url.clone() }, class: "btn btn-outline-secondary", "Bracket Setup" }
                                    Link { to: Route::Manage { url: url.clone() }, class: "btn btn-outline-warning", "Registration Management" }
                                    button {
                                        class: "btn btn-outline-danger",
                                        onclick: move |_| {
                                            delete_modal_open.set(true);
                                            delete_confirm_url.set(String::new());
                                        },
                                        "Delete Tournament"
                                    }
                                }
                            }
                        }
                    }
                }
            }

            if !d.teams_with_counts.is_empty() {
                div { class: "row mt-4",
                    div { class: "col-12",
                        div { class: "card",
                            div { class: "card-header", h5 { class: "mb-0", "Registered Teams ({teams_count})" } }
                            div { class: "card-body",
                                div { class: "table-responsive",
                                    table { class: "table table-striped",
                                        thead {
                                            tr {
                                                th { "Team Name" }
                                                th { "Players" }
                                                th { "Registration Date" }
                                            }
                                        }
                                        tbody {
                                            for team in d.teams_with_counts.iter() {
                                                tr { key: "{team.team_id}",
                                                    td {
                                                        div { class: "d-flex align-items-center",
                                                            div { class: "flex-shrink-0 me-2",
                                                                if let Some(photo) = &team.profile_photo {
                                                                    img { src: "{backend}/static/{photo}", alt: "", class: "rounded-circle", style: "width: 40px; height: 40px; object-fit: cover;" }
                                                                } else {
                                                                    div { class: "d-flex align-items-center justify-content-center bg-secondary rounded-circle", style: "width: 40px; height: 40px;",
                                                                        span { class: "text-white", "👥" }
                                                                    }
                                                                }
                                                            }
                                                            div {
                                                                Link { to: Route::TeamProfilePage { id: team.team_id.clone() }, class: "text-decoration-none",
                                                                    strong { "{team.pseudonym.as_deref().unwrap_or(&team.team_name)}" }
                                                                }
                                                            }
                                                        }
                                                    }
                                                    td {
                                                        span { class: "badge bg-primary", "{team.player_count}" }
                                                        if let Some(max) = d.tournament.max_team_size_roster {
                                                            span { " / {max}" }
                                                        }
                                                    }
                                                    td { "{team.registered_at.as_deref().unwrap_or(\"-\")}" }
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

            if !d.unattached_players.is_empty() {
                div { class: "row mt-4",
                    div { class: "col-12",
                        div { class: "card",
                            div { class: "card-header", h5 { class: "mb-0", "Unattached Players ({unattached_count})" } }
                            div { class: "card-body",
                                div { class: "table-responsive",
                                    table { class: "table table-striped",
                                        thead {
                                            tr {
                                                th { "Player Name" }
                                                th { "Jersey" }
                                                th { "Registration Date" }
                                            }
                                        }
                                        tbody {
                                            for p in d.unattached_players.iter() {
                                                tr { key: "{p.player_id}",
                                                    td {
                                                        div { class: "d-flex align-items-center",
                                                            div { class: "flex-shrink-0 me-2",
                                                                if let Some(photo) = &p.profile_photo {
                                                                    img { src: "{backend}/static/{photo}", alt: "", class: "rounded-circle", style: "width: 40px; height: 40px; object-fit: cover;" }
                                                                } else {
                                                                    div { class: "d-flex align-items-center justify-content-center bg-secondary rounded-circle", style: "width: 40px; height: 40px;",
                                                                        span { class: "text-white", "👤" }
                                                                    }
                                                                }
                                                            }
                                                            div {
                                                                Link { to: Route::PlayerProfilePage { id: p.player_id.clone() }, class: "text-decoration-none",
                                                                    strong { "{p.player_name}" }
                                                                }
                                                            }
                                                        }
                                                    }
                                                    td {
                                                        if let (Some(num), Some(name)) = (&p.jersey_number, &p.jersey_name) {
                                                            "#{num} {name}"
                                                        } else if let Some(name) = &p.jersey_name {
                                                            "{name}"
                                                        } else if let Some(num) = &p.jersey_number {
                                                            "#{num}"
                                                        } else {
                                                            span { class: "text-muted", "No jersey info" }
                                                        }
                                                    }
                                                    td { "{p.registered_at.as_deref().unwrap_or(\"-\")}" }
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

            if show_edit_player_modal() {
                div {
                    class: "modal show d-block",
                    style: "background: rgba(0,0,0,0.5);",
                    tabindex: "-1",
                    role: "dialog",
                    onclick: move |_| {
                        show_edit_player_modal.set(false);
                        show_deregister_player_confirm.set(false);
                    },
                    div {
                        class: "modal-dialog modal-dialog-centered",
                        onclick: move |ev: Event<MouseData>| { ev.stop_propagation(); },
                        div { class: "modal-content",
                            div { class: "modal-header",
                                h5 { class: "modal-title", "Edit Player Registration" }
                                button {
                                    r#type: "button",
                                    class: "btn-close",
                                    aria_label: "Close",
                                    onclick: move |_| {
                                        show_edit_player_modal.set(false);
                                        show_deregister_player_confirm.set(false);
                                    },
                                }
                            }
                            div { class: "modal-body", style: "position: relative;",
                                EditPlayerRegistrationModalContent {
                                    tournament_url: url.clone(),
                                    on_close: move |_| show_edit_player_modal.set(false),
                                }
                                if show_deregister_player_confirm() {
                                    div {
                                        class: "position-absolute top-0 start-0 w-100 h-100 d-flex align-items-center justify-content-center",
                                        style: "background: rgba(0,0,0,0.3); z-index: 1050; border-radius: 0.25rem;",
                                        onclick: move |_| show_deregister_player_confirm.set(false),
                                        div {
                                            class: "card shadow",
                                            onclick: move |ev: Event<MouseData>| { ev.stop_propagation(); },
                                            div { class: "card-body",
                                                p { class: "mb-3", "Are you sure you want to deregister? You will be removed from this tournament." }
                                                div { class: "d-flex gap-2 justify-content-end",
                                                    button {
                                                        r#type: "button",
                                                        class: "btn btn-secondary",
                                                        onclick: move |_| show_deregister_player_confirm.set(false),
                                                        "Cancel"
                                                    }
                                                    button {
                                                        r#type: "button",
                                                        class: "btn btn-danger",
                                                        onclick: move |_| {
                                                            show_deregister_player_confirm.set(false);
                                                            show_edit_player_modal.set(false);
                                                            let u = url_for_deregister_player.clone();
                                                            spawn(async move {
                                                                if api::deregister_player(&u).await.is_ok() {
                                                                    refresh.set(refresh() + 1);
                                                                }
                                                            });
                                                        },
                                                        "Deregister"
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                                div { class: "modal-footer",
                                    button {
                                        r#type: "button",
                                        class: "btn btn-outline-danger",
                                        onclick: move |_| show_deregister_player_confirm.set(true),
                                        "Deregister Player"
                                    }
                                    button {
                                        r#type: "submit",
                                        form: "edit-player-registration-form",
                                        class: "btn btn-primary",
                                        "Save"
                                    }
                                }
                        }
                    }
                }
            }

            if show_edit_team_modal() {
                div {
                    class: "modal show d-block",
                    style: "background: rgba(0,0,0,0.5);",
                    tabindex: "-1",
                    role: "dialog",
                    onclick: move |_| {
                        show_edit_team_modal.set(false);
                        show_deregister_team_confirm.set(false);
                    },
                    div {
                        class: "modal-dialog modal-dialog-centered",
                        onclick: move |ev: Event<MouseData>| { ev.stop_propagation(); },
                        div { class: "modal-content",
                            div { class: "modal-header",
                                h5 { class: "modal-title", "Edit Team Registration" }
                                button {
                                    r#type: "button",
                                    class: "btn-close",
                                    aria_label: "Close",
                                    onclick: move |_| {
                                        show_edit_team_modal.set(false);
                                        show_deregister_team_confirm.set(false);
                                    },
                                }
                            }
                            div { class: "modal-body", style: "position: relative;",
                                EditTeamRegistrationModalContent {
                                    tournament_url: url.clone(),
                                    on_close: move |_| show_edit_team_modal.set(false),
                                }
                                if show_deregister_team_confirm() {
                                    div {
                                        class: "position-absolute top-0 start-0 w-100 h-100 d-flex align-items-center justify-content-center",
                                        style: "background: rgba(0,0,0,0.3); z-index: 1050; border-radius: 0.25rem;",
                                        onclick: move |_| show_deregister_team_confirm.set(false),
                                        div {
                                            class: "card shadow",
                                            onclick: move |ev: Event<MouseData>| { ev.stop_propagation(); },
                                            div { class: "card-body",
                                                p { class: "mb-3", "Are you sure you want to deregister your team? Your team will be removed from this tournament." }
                                                div { class: "d-flex gap-2 justify-content-end",
                                                    button {
                                                        r#type: "button",
                                                        class: "btn btn-secondary",
                                                        onclick: move |_| show_deregister_team_confirm.set(false),
                                                        "Cancel"
                                                    }
                                                    button {
                                                        r#type: "button",
                                                        class: "btn btn-danger",
                                                        onclick: move |_| {
                                                            show_deregister_team_confirm.set(false);
                                                            show_edit_team_modal.set(false);
                                                            let u = url_for_deregister_team.clone();
                                                            spawn(async move {
                                                                if api::deregister_team(&u).await.is_ok() {
                                                                    refresh.set(refresh() + 1);
                                                                }
                                                            });
                                                        },
                                                        "Deregister"
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                                div { class: "modal-footer",
                                    button {
                                        r#type: "button",
                                        class: "btn btn-outline-danger",
                                        onclick: move |_| show_deregister_team_confirm.set(true),
                                        "Deregister Team"
                                    }
                                    button {
                                        r#type: "submit",
                                        form: "edit-team-registration-form",
                                        class: "btn btn-primary",
                                        "Save"
                                    }
                                }
                        }
                    }
                }
            }

            if is_current_user_to(me_res.read().as_ref(), &d.to_entries) && delete_modal_open() {
                div { class: "modal d-block", tabindex: -1, style: "background: rgba(0,0,0,0.5)",
                    div { class: "modal-dialog modal-dialog-centered",
                        div { class: "modal-content",
                            div { class: "modal-header",
                                h5 { class: "modal-title", "Delete Tournament" }
                                button { class: "btn-close", onclick: move |_| delete_modal_open.set(false) }
                            }
                            div { class: "modal-body",
                                div { class: "alert alert-danger",
                                    strong { "Warning: " }
                                    "This action cannot be undone. All matches, registrations, and data will be permanently removed."
                                }
                                p { "To confirm, type the tournament URL exactly:" }
                                p { class: "text-center mb-2", strong { "{url}" } }
                                form { id: "delete-tournament-form", action: "{backend}/{url}/delete", method: "post",
                                    div { class: "mb-3",
                                        label { class: "form-label", "Tournament URL:" }
                                        input {
                                            class: "form-control",
                                            name: "confirm_url",
                                            "type": "text",
                                            placeholder: "{url}",
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
                                    "type": "submit",
                                    form: "delete-tournament-form",
                                    disabled: delete_confirm_url() != url,
                                    "Delete Tournament"
                                }
                            }
                        }
                    }
                }
            }
            }
            }}
        } else if let Some(Err(e)) = val.read().as_ref() {
            p { class: "text-danger", "{e}" }
        } else {
            p { class: "text-muted", "Loading…" }
        }
    }
}

#[component]
fn EditPlayerRegistrationModalContent(
    tournament_url: String,
    on_close: EventHandler<()>,
) -> Element {
    let mut jersey_name = use_signal(|| "".to_string());
    let mut jersey_number = use_signal(|| "".to_string());
    let mut team = use_signal(|| "".to_string());
    let mut current_team_name = use_signal(|| "".to_string());
    let mut status = use_signal(|| "".to_string());
    let mut teams = use_signal(|| vec![]);
    let mut error = use_signal(|| None::<String>);
    let mut loading = use_signal(|| true);

    let _fetch = use_resource(use_reactive(&tournament_url, move |url| {
        let url = url.clone();
        async move {
            loading.set(true);
            let reg_res = api::get_my_player_registration(&url).await;
            let detail_res = api::tournament_detail(&url).await;

            match (reg_res, detail_res) {
                (Ok(res), Ok(detail)) => {
                    jersey_name.set(res.registration.jersey_name.unwrap_or_default());
                    jersey_number.set(res.registration.jersey_number.unwrap_or_default());
                    status.set(res.registration.status.clone());
                    if let Some(ref ct) = res.current_team {
                        current_team_name.set(ct.pseudonym.clone().unwrap_or_else(|| ct.id.clone()));
                    }
                    let mut t_list = vec![];
                    for t in detail.teams_with_counts {
                        t_list.push((t.team_id.clone(), t.pseudonym.unwrap_or(t.team_name)));
                    }
                    teams.set(t_list);
                    // Set team after teams so the dropdown has options; prefer registration.team then current_team.id
                    let selected_team = res
                        .registration
                        .team
                        .clone()
                        .or_else(|| res.current_team.as_ref().map(|c| c.id.clone()))
                        .unwrap_or_default();
                    team.set(selected_team);
                }
                (Err(e), _) => error.set(Some(format!("Failed to load registration: {}", e))),
                (_, Err(e)) => error.set(Some(format!("Failed to load tournament details: {}", e))),
            }
            loading.set(false);
        }
    }));

    let tournament_url_for_submit = tournament_url.clone();
    let onsubmit = move |_evt: Event<FormData>| {
        let tournament_url = tournament_url_for_submit.clone();
        async move {
            loading.set(true);
            error.set(None);
            let t_val = team();
            let team_opt = if t_val.is_empty() { None } else { Some(t_val) };
            let req = UpdatePlayerRegistrationRequest {
                jersey_name: Some(jersey_name()),
                jersey_number: Some(jersey_number()),
                team: team_opt,
            };
            match api::update_my_player_registration(&tournament_url, &req).await {
                Ok(_) => {
                    on_close.call(());
                }
                Err(e) => {
                    error.set(Some(e));
                    loading.set(false);
                }
            }
        }
    };

    rsx! {
        if loading() {
            div { class: "d-flex justify-content-center",
                div { class: "spinner-border", role: "status",
                    span { class: "visually-hidden", "Loading..." }
                }
            }
        } else {
            if let Some(err) = error() {
                div { class: "alert alert-danger mb-3", "{err}" }
            }
            form {
                id: "edit-player-registration-form",
                onsubmit: onsubmit,
                div { class: "mb-3",
                    label { class: "form-label", "Jersey Name" }
                    input {
                        class: "form-control",
                        "type": "text",
                        value: "{jersey_name}",
                        oninput: move |e| jersey_name.set(e.value()),
                        required: true
                    }
                    div { class: "form-text", "Your name for this tournament" }
                }
                div { class: "mb-3",
                    label { class: "form-label", "Jersey Number" }
                    input {
                        class: "form-control",
                        "type": "text",
                        value: "{jersey_number}",
                        oninput: move |e| jersey_number.set(e.value())
                    }
                }
                div { class: "mb-3",
                    label { class: "form-label", "Team" }
                    select {
                        class: "form-select",
                        value: "{team}",
                        onchange: move |e| team.set(e.value()),
                        option { value: "", selected: team().is_empty(), "No Team (unattached/free merc)" }
                        for (id, name) in teams() {
                            option { value: "{id}", selected: id == team(), "{name}" }
                        }
                    }
                    div { class: "form-text",
                        if !current_team_name().is_empty() {
                            span { "Current team: {current_team_name} " }
                            if status() == "PENDING_TEAM_APPROVAL" {
                                span { class: "badge bg-warning", "Pending Approval" }
                            }
                        }
                        br {}
                        "If you change teams, your new team must approve your request."
                    }
                }
            }
        }
    }
}

#[component]
fn EditTeamRegistrationModalContent(
    tournament_url: String,
    on_close: EventHandler<()>,
) -> Element {
    let mut pseudonym = use_signal(|| "".to_string());
    let mut error = use_signal(|| None::<String>);
    let mut loading = use_signal(|| true);

    let _fetch = use_resource(use_reactive(&tournament_url, move |url| {
        let url = url.clone();
        async move {
            loading.set(true);
            match api::get_my_team_registration(&url).await {
                Ok(res) => pseudonym.set(res.registration.pseudonym.unwrap_or_default()),
                Err(e) => error.set(Some(e)),
            }
            loading.set(false);
        }
    }));

    let tournament_url_for_submit = tournament_url.clone();
    let onsubmit = move |_evt: Event<FormData>| {
        let tournament_url = tournament_url_for_submit.clone();
        async move {
            loading.set(true);
            error.set(None);
            let req = UpdateTeamRegistrationRequest {
                pseudonym: Some(pseudonym()),
            };
            match api::update_my_team_registration(&tournament_url, &req).await {
                Ok(_) => on_close.call(()),
                Err(e) => {
                    error.set(Some(e));
                    loading.set(false);
                }
            }
        }
    };

    rsx! {
        if loading() {
            div { class: "d-flex justify-content-center",
                div { class: "spinner-border", role: "status",
                    span { class: "visually-hidden", "Loading..." }
                }
            }
        } else {
            if let Some(err) = error() {
                div { class: "alert alert-danger mb-3", "{err}" }
            }
            form {
                id: "edit-team-registration-form",
                onsubmit: onsubmit,
                div { class: "mb-3",
                    label { class: "form-label", "Team Name for This Tournament" }
                    input {
                        class: "form-control",
                        "type": "text",
                        value: "{pseudonym}",
                        oninput: move |e| pseudonym.set(e.value()),
                        required: true
                    }
                    div { class: "form-text", "This is how your team will be referred to in this tournament" }
                }
            }
        }
    }
}
