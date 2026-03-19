use crate::api;
use crate::components::{
    EditRegistrationContext, EditRegistrationModal, EventHeader, LeagueRegistrationButtons,
};
use crate::types::{ToEntry, UpdatePlayerRegistrationRequest, UpdateTeamRegistrationRequest, User};
use crate::Route;
use dioxus::prelude::*;

#[derive(Clone)]
struct PendingUpload {
    filename: String,
    file: dioxus::html::FileData,
    field_id: u32,
    start_world_suggested: Option<String>,
    start_world_value: String,
    start_world_loading: bool,
    start_world_error: Option<String>,
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
pub fn TournamentHome(url: String) -> Element {
    let url_for_data = url.clone();
    let navigator = use_navigator();
    let mut refresh = use_signal(|| 0u32);
    let data = use_resource(move || {
        let _ = refresh();
        let u = url_for_data.clone();
        async move { api::tournament_detail(&u).await.map_err(|e| e.to_string()) }
    });
    let me_res = use_resource(move || async move { api::me().await });
    let url_for_warning = url.clone();
    let waiver_warning = use_resource(move || {
        let u = url_for_warning.clone();
        async move {
            match api::get_my_player_registration(&u).await {
                Ok(res) => res.waiver_required && !res.waiver_signature_valid,
                Err(_) => false,
            }
        }
    });
    let val = data.value();
    let backend = api::base_url();
    let mut delete_modal_open = use_signal(|| false);
    let mut delete_confirm_url = use_signal(|| String::new());
    let mut delete_error = use_signal(|| None::<String>);
    let mut show_edit_player_modal = use_signal(|| false);
    let mut show_edit_team_modal = use_signal(|| false);
    let mut show_league_edit_modal = use_signal(|| false);
    let url_for_delete_confirm = url.clone();
    let url_for_user_upload = url.clone();
    let url_for_user_upload_delete = url.clone();
    let mut about_markdown = use_signal(|| Option::<String>::None);
    let mut delete_redirect_league = use_signal(|| None as Option<String>);
    use_effect(move || {
        let v = val.read();
        if let Some(Ok(d)) = v.as_ref() {
            about_markdown.set(d.tournament.about.clone());
            delete_redirect_league.set(d.tournament.league.as_ref().map(|l| l.league_url.clone()));
        } else {
            about_markdown.set(None);
            delete_redirect_league.set(None);
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

    // Upload footage UI state (hidden when not logged in).
    let mut pending_uploads = use_signal(|| Vec::<PendingUpload>::new());
    let mut upload_error = use_signal(|| None::<String>);
    let mut uploading = use_signal(|| false);
    let mut upload_modal_open = use_signal(|| false);
    let mut user_uploads_refresh = use_signal(|| 0u32);
    let mut user_upload_delete_error = use_signal(|| None::<String>);

    let url_for_fields = url.clone();
    let fields_res = use_resource(move || {
        let value = url_for_fields.clone();
        async move {
            api::tournament_fields(&value)
                .await
                .map_err(|e| e.to_string())
        }
    });

    let url_for_uploads_list = url.clone();
    let user_uploads_res = use_resource(move || {
        let _ = user_uploads_refresh();
        let u = url_for_uploads_list.clone();
        async move {
            api::user_uploaded_cameras_list(&u)
                .await
                .map_err(|e| e.to_string())
        }
    });

    rsx! {
        if let Some(Ok(d)) = val.read().as_ref() {
            {{
                let teams_count = d.teams_with_counts.len();
                let unattached_count = d.unattached_players.len();
                rsx! {
            EventHeader {
                title: d.tournament.name.clone(),
                subtitle: format!("{} • {}", d.tournament.location.as_deref().unwrap_or("Location TBA"), format_date_display(&d.tournament.start_date, d.tournament.end_date.as_ref())),
                badge_league_url: d.tournament.league.as_ref().map(|l| l.league_url.clone()),
                badge_season: None,
                badge_name: d.tournament.league.as_ref().map(|l| l.name.clone()),
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
                    if me_res.read().as_ref().and_then(|r| r.as_ref().ok()).is_some() {
                        button {
                            class: "btn btn-outline-secondary",
                            onclick: move |_| {
                                upload_modal_open.set(true);
                                upload_error.set(None);
                            },
                            "Upload Footage"
                        }
                    }
                    if let Some(ref l) = d.tournament.league {
                        LeagueRegistrationButtons {
                            league_url: l.league_url.clone(),
                            registration_open: l.registration_open,
                            team_registration_open: Some(l.team_registration_open),
                            player_registration_open: Some(l.player_registration_open),
                            current_user: me_res.read().as_ref().cloned(),
                            is_team_registered: d.is_current_team_registered,
                            is_player_registered: d.is_current_player_registered,
                            use_edit_modal: true,
                            on_edit_registration: move |_| show_league_edit_modal.set(true),
                            register_label: String::from("Register (league)"),
                            show_edit_warning: waiver_warning
                                .value()
                                .read()
                                .as_ref()
                                .copied()
                                .unwrap_or(false),
                        }
                    } else {
                        if let Some(current_user) = me_res.read().as_ref().and_then(|r| r.as_ref().ok()) {
                            if current_user.user_type == "team" {
                                if d.is_current_team_registered {
                                    a { href: "{backend}/{url}/invitations", class: "btn btn-outline-secondary", "Manage Roster" }
                                    button {
                                        class: "btn btn-outline-secondary",
                                        onclick: move |_| show_edit_team_modal.set(true),
                                        "Edit Registration"
                                    }
                                } else if d.tournament.team_registration_open {
                                    Link { to: Route::TournamentRegister { url: url.clone() }, class: "btn btn-success", "Register" }
                                } else {
                                    button {
                                        r#type: "button",
                                        class: "btn btn-secondary disabled",
                                        disabled: true,
                                        "Team registration closed"
                                    }
                                }
                            } else if current_user.user_type == "player" {
                                if d.is_current_player_registered {
                                    button {
                                        class: "btn btn-outline-secondary",
                                        onclick: move |_| show_edit_player_modal.set(true),
                                        if waiver_warning
                                            .value()
                                            .read()
                                            .as_ref()
                                            .copied()
                                            .unwrap_or(false)
                                        {
                                            "Edit Registration ⚠️"
                                        } else {
                                            "Edit Registration"
                                        }
                                    }
                                } else if d.tournament.player_registration_open {
                                    Link { to: Route::TournamentRegister { url: url.clone() }, class: "btn btn-success", "Register" }
                                } else {
                                    button {
                                        r#type: "button",
                                        class: "btn btn-secondary disabled",
                                        disabled: true,
                                        "Player registration closed"
                                    }
                                }
                            } else {
                                if d.tournament.team_registration_open || d.tournament.player_registration_open {
                                    Link { to: Route::TournamentRegister { url: url.clone() }, class: "btn btn-success", "Register" }
                                } else {
                                    button {
                                        r#type: "button",
                                        class: "btn btn-secondary disabled",
                                        disabled: true,
                                        "Registration closed"
                                    }
                                }
                            }
                        } else {
                            button {
                                r#type: "button",
                                class: "btn btn-secondary disabled",
                                disabled: true,
                                "Sign in to register"
                            }
                        }
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
                            if d.tournament.league.is_none() && {
                                let ro = d.tournament.team_registration_open || d.tournament.player_registration_open;
                                let tf = d.tournament.team_reg_fee.unwrap_or(0.0);
                                let pf = d.tournament.player_reg_fee.unwrap_or(0.0);
                                ro && (tf > 0.0 || pf > 0.0)
                            } {
                                div { class: "alert alert-info mb-3",
                                    h6 { class: "mb-2", "Registration Fees" }
                                    {
                                        let tf = d.tournament.team_reg_fee.unwrap_or(0.0);
                                        let pf = d.tournament.player_reg_fee.unwrap_or(0.0);
                                        let tf_str = format!("${:.2}", tf);
                                        let pf_str = format!("${:.2}", pf);
                                        rsx! {
                                            if tf > 0.0 {
                                                p { class: "mb-1", strong { "Team Registration: " } "{tf_str}" }
                                            }
                                            if pf > 0.0 {
                                                p { class: "mb-0", strong { "Player Registration: " } "{pf_str}" }
                                            }
                                        }
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
                    // Upload Footage is now a modal triggered from the button row.
                }
                                if is_current_user_to(me_res.read().as_ref(), &d.to_entries) {
                                    div { class: "col-md-4",
                                        div { class: "card",
                                            div { class: "card-header", h5 { class: "mb-0", "Admin" } }
                                            div { class: "card-body",
                                                div { class: "d-grid gap-2",
                                                    Link { to: Route::TournamentSettings { url: url.clone() }, class: "btn btn-outline-secondary", "Settings" }
                                                    Link { to: Route::BracketSetup { url: url.clone() }, class: "btn btn-outline-secondary", "Bracket Setup" }
                                                    if let Some(ref l) = d.tournament.league {
                                                        Link { to: Route::LeagueManage { league_url: l.league_url.clone() }, class: "btn btn-outline-warning", "Registration Management" }
                                                    } else {
                                                        Link { to: Route::Manage { url: url.clone() }, class: "btn btn-outline-warning", "Registration Management" }
                                                    }
                                    button {
                                        class: "btn btn-outline-danger",
                                        onclick: move |_| {
                                            delete_modal_open.set(true);
                                            delete_confirm_url.set(String::new());
                                            delete_error.set(None);
                                        },
                                        "Delete Tournament"
                                    }
                                }
                            }
                        }
                        div { class: "card mt-4",
                            div { class: "card-header",
                                h5 { class: "mb-0", "User Uploaded Videos" }
                            }
                            div { class: "card-body",
                                if let Some(Ok(cams)) = user_uploads_res.read().as_ref() {
                                    if cams.cameras.is_empty() {
                                        p { class: "text-muted", "No user uploads yet." }
                                    } else {
                                        div { class: "table-responsive",
                                            table { class: "table table-sm align-middle",
                                                thead {
                                                    tr {
                                                        th { "Match" }
                                                        th { "Field" }
                                                        th { "Camera" }
                                                        th { "Status" }
                                                        th { "" }
                                                    }
                                                }
                                                tbody {
                                                    for cam in cams.cameras.iter().cloned() {
                                                        tr { key: "{cam.uuid}",
                                                            td { "{cam.match_name}" }
                                                            td { "{cam.field_name}" }
                                                            td { "{cam.camera_name}" }
                                                            td { "{cam.status}" }
                                                            td {
                                                                {{
                                                                    let url = url_for_user_upload_delete.clone();
                                                                    let uuid = cam.uuid.clone();
                                                                    let delete_err = user_upload_delete_error.clone();
                                                                    let refresh_sig = user_uploads_refresh.clone();
                                                                    rsx! {
                                                                        button {
                                                                            class: "btn btn-sm btn-outline-danger",
                                                                            disabled: uploading(),
                                                                            onclick: move |_| {
                                                                                let mut delete_err_local = delete_err.clone();
                                                                                let mut refresh_sig_local = refresh_sig.clone();
                                                                                delete_err_local.set(None);
                                                                                let url = url.clone();
                                                                                let uuid = uuid.clone();
                                                                                spawn(async move {
                                                                                    match api::delete_user_uploaded_camera(&url, &uuid).await {
                                                                                        Ok(()) => {
                                                                                            refresh_sig_local
                                                                                                .set(refresh_sig_local() + 1);
                                                                                        }
                                                                                        Err(e) => {
                                                                                            delete_err_local.set(Some(e));
                                                                                        }
                                                                                    }
                                                                                });
                                                                            },
                                                                            "Delete"
                                                                        }
                                                                    }
                                                                }}
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                } else {
                                    p { class: "text-muted", "Loading..." }
                                }
                                if let Some(err) = user_upload_delete_error() {
                                    p { class: "text-danger mt-3", "{err}" }
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
                if let Some(Ok(me)) = me_res.read().as_ref() {
                    EditRegistrationModal {
                        context: EditRegistrationContext::Tournament {
                            tournament_url: url.clone(),
                        },
                        user_type: me.user_type.clone(),
                        on_close: move |_| show_edit_player_modal.set(false),
                        on_success: move |_| {
                            show_edit_player_modal.set(false);
                            refresh.set(refresh() + 1);
                        },
                    }
                }
            }

            if show_edit_team_modal() {
                if let Some(Ok(me)) = me_res.read().as_ref() {
                    EditRegistrationModal {
                        context: EditRegistrationContext::Tournament {
                            tournament_url: url.clone(),
                        },
                        user_type: me.user_type.clone(),
                        on_close: move |_| show_edit_team_modal.set(false),
                        on_success: move |_| {
                            show_edit_team_modal.set(false);
                            refresh.set(refresh() + 1);
                        },
                    }
                }
            }

            if show_league_edit_modal() {
                if let Some(ref l) = d.tournament.league {
                    if let Some(Ok(me)) = me_res.read().as_ref() {
                        EditRegistrationModal {
                            context: EditRegistrationContext::League { league_url: l.league_url.clone() },
                            user_type: me.user_type.clone(),
                            on_close: move |_| show_league_edit_modal.set(false),
                            on_success: move |_| {
                                show_league_edit_modal.set(false);
                                refresh.set(refresh() + 1);
                            },
                        }
                    }
                }
            }

            if upload_modal_open() {
                div {
                    class: "modal show d-block",
                    style: "background: rgba(0,0,0,0.5);",
                    tabindex: "-1",
                    role: "dialog",
                    onclick: move |_| upload_modal_open.set(false),
                    div {
                        class: "modal-dialog modal-dialog-centered modal-lg",
                        onclick: move |ev: Event<MouseData>| { ev.stop_propagation(); },
                        div { class: "modal-content",
                            div { class: "modal-header",
                                h5 { class: "modal-title", "Upload Footage" }
                                button {
                                    r#type: "button",
                                    class: "btn-close",
                                    aria_label: "Close",
                                    onclick: move |_| upload_modal_open.set(false),
                                }
                            }
                            div { class: "modal-body",
                                if let Some(err) = upload_error() {
                                    div { class: "alert alert-danger mb-3", "{err}" }
                                }
                                if let Some(Ok(fields)) = fields_res.read().as_ref() {
                                    if fields.is_empty() {
                                        p { class: "text-muted", "No fields configured for this tournament." }
                                    } else {
                                        {{
                                            let default_field_id = fields[0].id;
                                            let upload_url_onchange = url_for_user_upload.clone();
                                            let upload_url_reset = url_for_user_upload.clone();
                                            rsx! {
                                                p { class: "text-muted mb-2",
                                                    "Select one or more videos. We'll auto-detect the start timestamp from metadata; you can edit it if it's wrong."
                                                }
                                                input {
                                                    class: "form-control",
                                                    r#type: "file",
                                                    accept: "video/*",
                                                    multiple: true,
                                                    disabled: uploading(),
                                                    onchange: move |evt| {
                                                        #[cfg(target_arch = "wasm32")]
                                                        {
                                                            use dioxus::html::HasFileData;
                                                            let files = evt.files();
                                                            if files.is_empty() {
                                                                return;
                                                            }

                                                            let mut items: Vec<PendingUpload> = Vec::new();
                                                            for f in files {
                                                                items.push(PendingUpload {
                                                                    filename: f.name(),
                                                                    file: f,
                                                                    field_id: default_field_id,
                                                                    start_world_suggested: None,
                                                                    start_world_value: String::new(),
                                                                    start_world_loading: true,
                                                                    start_world_error: None,
                                                                });
                                                            }
                                                            pending_uploads.set(items);
                                                            upload_error.set(None);

                                                            // Probe metadata timestamps in the background.
                                                            let tournament_url = upload_url_onchange.clone();
                                                            let mut pending_sig = pending_uploads.clone();
                                                            spawn(async move {
                                                                let snapshot = pending_sig();
                                                                for (idx, u) in snapshot.iter().enumerate() {
                                                                    let bytes = match u.file.read_bytes().await {
                                                                        Ok(b) => b,
                                                                        Err(_) => {
                                                                            let mut list = pending_sig();
                                                                            if let Some(t) = list.get_mut(idx) {
                                                                                t.start_world_loading = false;
                                                                                t.start_world_error =
                                                                                    Some("Failed to read file".to_string());
                                                                            }
                                                                            pending_sig.set(list);
                                                                            continue;
                                                                        }
                                                                    };
                                                                    let ct = u.file.content_type();
                                                                    match api::user_upload_probe_start_timestamp(
                                                                        &tournament_url,
                                                                        bytes,
                                                                        ct,
                                                                    )
                                                                    .await
                                                                    {
                                                                        Ok(ts) => {
                                                                            let mut list = pending_sig();
                                                                            if let Some(t) = list.get_mut(idx) {
                                                                                t.start_world_loading = false;
                                                                                t.start_world_suggested = Some(ts.clone());
                                                                                t.start_world_value = ts;
                                                                                t.start_world_error = None;
                                                                            }
                                                                            pending_sig.set(list);
                                                                        }
                                                                        Err(e) => {
                                                                            let mut list = pending_sig();
                                                                            if let Some(t) = list.get_mut(idx) {
                                                                                t.start_world_loading = false;
                                                                                t.start_world_error = Some(e);
                                                                            }
                                                                            pending_sig.set(list);
                                                                        }
                                                                    }
                                                                }
                                                            });
                                                        }
                                                    }
                                                }

                                                if !pending_uploads().is_empty() {
                                                    div { class: "mt-3 table-responsive",
                                                        table { class: "table table-sm align-middle",
                                                            thead {
                                                                tr {
                                                                    th { "File" }
                                                                    th { "Field" }
                                                                    th { "Start timestamp (UTC)" }
                                                                    th { "" }
                                                                }
                                                            }
                                                            tbody {
                                                                for (idx, item) in pending_uploads().iter().enumerate() {
                                                                    tr { key: "{item.filename}-{idx}",
                                                                        td { "{item.filename}" }
                                                                        td {
                                                                            select {
                                                                                class: "form-select form-select-sm",
                                                                                value: "{item.field_id}",
                                                                                disabled: uploading(),
                                                                                onchange: move |ev| {
                                                                                    let v = ev.value().parse::<u32>().unwrap_or(default_field_id);
                                                                                    let mut list = pending_uploads();
                                                                                    if let Some(t) = list.get_mut(idx) {
                                                                                        t.field_id = v;
                                                                                    }
                                                                                    pending_uploads.set(list);
                                                                                }
                                                                                ,
                                                                                for f in fields.iter() {
                                                                                    option { value: "{f.id}", "{f.name}" }
                                                                                }
                                                                            }
                                                                        }
                                                                        td {
                                                                            div { class: "d-flex gap-2 align-items-center",
                                                                                input {
                                                                                    class: "form-control form-control-sm",
                                                                                    r#type: "text",
                                                                                    placeholder: "2026-03-18T01:23:45Z",
                                                                                    value: "{item.start_world_value}",
                                                                                    disabled: uploading() || item.start_world_loading,
                                                                                    oninput: move |e| {
                                                                                        let mut list = pending_uploads();
                                                                                        if let Some(t) = list.get_mut(idx) {
                                                                                            t.start_world_value = e.value();
                                                                                        }
                                                                                        pending_uploads.set(list);
                                                                                    }
                                                                                }
                                                                                {{
                                                                                    let reset_url = upload_url_reset.clone();
                                                                                    rsx! {
                                                                                        button {
                                                                                            class: "btn btn-sm btn-outline-secondary",
                                                                                            disabled: uploading() || item.start_world_loading,
                                                                                            onclick: move |_| {
                                                                                                #[cfg(target_arch = "wasm32")]
                                                                                                {
                                                                                                    let tournament_url = reset_url.clone();
                                                                                                    let u = pending_uploads()[idx].clone();
                                                                                                    let mut pending_sig = pending_uploads.clone();
                                                                                                    spawn(async move {
                                                                                                        let bytes = match u.file.read_bytes().await {
                                                                                                            Ok(b) => b,
                                                                                                            Err(_) => {
                                                                                                                let mut list = pending_sig();
                                                                                                                if let Some(t) = list.get_mut(idx) {
                                                                                                                    t.start_world_error = Some("Failed to read file".to_string());
                                                                                                                }
                                                                                                                pending_sig.set(list);
                                                                                                                return;
                                                                                                            }
                                                                                                        };
                                                                                                        let ct = u.file.content_type();
                                                                                                        match api::user_upload_probe_start_timestamp(
                                                                                                            &tournament_url,
                                                                                                            bytes,
                                                                                                            ct,
                                                                                                        )
                                                                                                        .await
                                                                                                        {
                                                                                                            Ok(ts) => {
                                                                                                                let mut list = pending_sig();
                                                                                                                if let Some(t) = list.get_mut(idx) {
                                                                                                                    t.start_world_suggested = Some(ts.clone());
                                                                                                                    t.start_world_value = ts;
                                                                                                                    t.start_world_error = None;
                                                                                                                }
                                                                                                                pending_sig.set(list);
                                                                                                            }
                                                                                                            Err(e) => {
                                                                                                                let mut list = pending_sig();
                                                                                                                if let Some(t) = list.get_mut(idx) {
                                                                                                                    t.start_world_error = Some(e);
                                                                                                                }
                                                                                                                pending_sig.set(list);
                                                                                                            }
                                                                                                        }
                                                                                                    });
                                                                                                }
                                                                                            },
                                                                                            "Reset"
                                                                                        }
                                                                                    }
                                                                                }}
                                                                            }
                                                                            if item.start_world_loading {
                                                                                div { class: "text-muted small mt-1", "Reading metadata…" }
                                                                            } else if let Some(err) = &item.start_world_error {
                                                                                div { class: "text-danger small mt-1", "{err}" }
                                                                            } else if let Some(s) = &item.start_world_suggested {
                                                                                div { class: "text-muted small mt-1", "Metadata: {s}" }
                                                                            }
                                                                        }
                                                                        td {
                                                                            button {
                                                                                class: "btn btn-sm btn-outline-danger",
                                                                                disabled: uploading(),
                                                                                onclick: move |_| {
                                                                                    let mut list = pending_uploads();
                                                                                    if idx < list.len() {
                                                                                        list.remove(idx);
                                                                                    }
                                                                                    pending_uploads.set(list);
                                                                                },
                                                                                "Remove"
                                                                            }
                                                                        }
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }}
                                    }
                                } else {
                                    p { class: "text-muted", "Loading fields..." }
                                }
                            }
                            div { class: "modal-footer",
                                button {
                                    class: "btn btn-secondary",
                                    onclick: move |_| upload_modal_open.set(false),
                                    "Close"
                                }
                                {{
                                    let upload_url_submit = url_for_user_upload.clone();
                                    rsx! {
                                        button {
                                            class: "btn btn-primary",
                                            disabled: uploading() || pending_uploads().is_empty(),
                                            onclick: move |_| {
                                                #[cfg(target_arch = "wasm32")]
                                                {
                                                    let url = upload_url_submit.clone();
                                                    let uploads = pending_uploads();
                                                    if uploads.is_empty() {
                                                        return;
                                                    }
                                                    uploading.set(true);
                                                    upload_error.set(None);
                                                    spawn(async move {
                                                        let mut first_err: Option<String> = None;
                                                        for u in uploads {
                                                            let content_type = u.file.content_type();
                                                            let bytes = match u.file.read_bytes().await {
                                                                Ok(b) => b,
                                                                Err(_) => {
                                                                    if first_err.is_none() {
                                                                        first_err = Some("Failed to read uploaded file".to_string());
                                                                    }
                                                                    continue;
                                                                }
                                                            };
                                                            let start_world = if u.start_world_value.trim().is_empty() {
                                                                None
                                                            } else {
                                                                Some(u.start_world_value.clone())
                                                            };
                                                            if let Err(e) = api::user_upload_video_footage(
                                                                &url,
                                                                u.field_id,
                                                                bytes,
                                                                content_type,
                                                                start_world,
                                                            )
                                                            .await
                                                            {
                                                                if first_err.is_none() {
                                                                    first_err = Some(e);
                                                                }
                                                            }
                                                        }
                                                        uploading.set(false);
                                                        if let Some(e) = first_err {
                                                            upload_error.set(Some(e));
                                                        } else {
                                                            pending_uploads.set(Vec::new());
                                                            user_uploads_refresh.set(user_uploads_refresh() + 1);
                                                            upload_modal_open.set(false);
                                                        }
                                                    });
                                                }
                                            },
                                            if uploading() { "Uploading..." } else { "Upload" }
                                        }
                                    }
                                }}
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
                                if let Some(ref err) = delete_error() {
                                    div { class: "alert alert-danger mb-3", "{err}" }
                                }
                                div { class: "alert alert-danger",
                                    strong { "Warning: " }
                                    "This action cannot be undone. All matches, registrations, and data will be permanently removed."
                                }
                                p { "To confirm, type the tournament URL exactly:" }
                                p { class: "text-center mb-2", strong { "{url}" } }
                                form {
                                    id: "delete-tournament-form",
                                    onsubmit: move |ev| {
                                        ev.prevent_default();
                                        if delete_confirm_url() != url_for_delete_confirm {
                                            return;
                                        }
                                        delete_error.set(None);
                                        let nav = navigator.clone();
                                        let url_submit = url_for_delete_confirm.clone();
                                        let confirm = delete_confirm_url();
                                        let redirect_league = delete_redirect_league();
                                        spawn(async move {
                                            match api::delete_tournament(&url_submit, &confirm).await {
                                                Ok(res) if res.success => {
                                                    if let Some(lu) = redirect_league {
                                                        let _ = nav.push(Route::LeagueHome { league_url: lu });
                                                    } else {
                                                        let _ = nav.push(Route::Index {});
                                                    }
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
    let backend = api::base_url();
    let mut jersey_name = use_signal(|| "".to_string());
    let mut jersey_number = use_signal(|| "".to_string());
    let mut team = use_signal(|| "".to_string());
    let mut current_team_name = use_signal(|| "".to_string());
    let mut status = use_signal(|| "".to_string());
    let mut teams = use_signal(|| vec![]);
    let mut waiver_required = use_signal(|| false);
    let mut waiver_signature_valid = use_signal(|| false);
    let mut waiver_filepath = use_signal(|| None::<String>);
    let mut waiver_sha256 = use_signal(|| None::<String>);
    let mut waiver_legal_name_signature = use_signal(|| "".to_string());
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

                    waiver_required.set(res.waiver_required);
                    waiver_signature_valid.set(res.waiver_signature_valid);
                    waiver_filepath.set(res.waiver_filepath);
                    waiver_sha256.set(res.waiver_sha256);
                    waiver_legal_name_signature
                        .set(res.waiver_legal_name_signature.unwrap_or_default());

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
                waiver_legal_name_signature: if waiver_required() && !waiver_signature_valid() {
                    Some(waiver_legal_name_signature())
                } else {
                    None
                },
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
                
                if waiver_required() {
                    div { class: "mb-3",
                        label { class: "form-label", "Waiver Signature" }
                        if let Some(link) = waiver_filepath() {
                            div { class: "form-text mb-2",
                                "Waiver file: "
                                a { href: "{backend}{link}", target: "_blank", class: "text-decoration-none", "{backend}{link}" }
                                if let Some(sha) = waiver_sha256() {
                                    div { class: "text-muted mt-1", "Hash (SHA-256):" }
                                    pre { class: "p-2 border rounded bg-light mt-1 mb-0", style: "white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word;", code { "{sha}" } }
                                }
                            }
                        }
                        p { class: "form-text mb-2", "By entering your full legal name below, you agree to the terms of the waiver linked above, and affirm that the waiver you viewed matches the SHA-256 hash displayed." }
                        input {
                            class: if waiver_signature_valid() {
                                "form-control bg-light text-muted"
                            } else {
                                "form-control"
                            },
                            r#type: "text",
                            value: "{waiver_legal_name_signature}",
                            disabled: waiver_signature_valid(),
                            required: !waiver_signature_valid(),
                            oninput: move |e| waiver_legal_name_signature.set(e.value()),
                        }
                        div { class: "form-text mb-2",
                            "Waiver signature:"
                            if waiver_signature_valid() {
                                span { class: "text-success ms-2", "Valid" }
                            } else {
                                span { class: "text-warning ms-2", "Needs signing / re-signing" }
                            }
                        }
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
