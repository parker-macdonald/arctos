use crate::api;
use crate::types::{ToEntry, User};
use crate::Route;
use dioxus::prelude::*;
use pulldown_cmark::{Options, Parser};

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

fn markdown_to_html(md: &str) -> String {
    let mut options = Options::empty();
    options.insert(Options::ENABLE_STRIKETHROUGH);
    options.insert(Options::ENABLE_TABLES);
    let parser = Parser::new_ext(md, options);
    let mut html = String::new();
    pulldown_cmark::html::push_html(&mut html, parser);
    html
}

#[component]
pub fn TournamentHome(url: String) -> Element {
    let url_for_data = url.clone();
    let data = use_resource(move || {
        let u = url_for_data.clone();
        async move { api::tournament_detail(&u).await.map_err(|e| e.to_string()) }
    });
    let me_res = use_resource(move || async move { api::me().await });
    let val = data.value();
    let backend = api::base_url();

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
                                    a { href: "{backend}/{url}/invitations", class: "btn btn-outline-primary", "Manage Roster" }
                                    Link { to: Route::EditTeamRegistration { tournament_url: url.clone() }, class: "btn btn-outline-secondary", "Edit Registration" }
                                    a { href: "{backend}/{url}/deregister-team", class: "btn btn-outline-danger", "Deregister Team" }
                                } else {
                                    Link { to: Route::TournamentRegister { url: url.clone() }, class: "btn btn-success", "Register" }
                                }
                            } else if current_user.user_type == "player" {
                                if d.is_current_player_registered {
                                    Link { to: Route::EditPlayerRegistration { tournament_url: url.clone() }, class: "btn btn-outline-secondary", "Edit Registration" }
                                    a { href: "{backend}/{url}/deregister-player", class: "btn btn-outline-danger", "Deregister Player" }
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
                                    div { class: "markdown-content", dangerous_inner_html: "{markdown_to_html(about)}" }
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
                                    Link { to: Route::TournamentSetup { url: url.clone() }, class: "btn btn-outline-secondary", "Setup" }
                                    a { href: "{backend}/{url}/bracket-setup", class: "btn btn-outline-secondary", "Bracket Setup" }
                                    Link { to: Route::Manage { url: url.clone() }, class: "btn btn-outline-warning", "Registration Management" }
                                    form {
                                        action: "{backend}/{url}/delete",
                                        method: "post",
                                        class: "border rounded p-2",
                                        div { class: "mb-2",
                                            label { class: "form-label small mb-1", "Type the tournament URL to confirm" }
                                            input {
                                                class: "form-control form-control-sm",
                                                name: "confirm_url",
                                                "type": "text",
                                                placeholder: "{url}",
                                                required: true
                                            }
                                        }
                                        button { class: "btn btn-outline-danger btn-sm w-100", "type": "submit", "Delete Tournament" }
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
                                                                Link { to: Route::TeamProfile { id: team.team_id.clone() }, class: "text-decoration-none",
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
                                                                Link { to: Route::PlayerProfile { id: p.player_id.clone() }, class: "text-decoration-none",
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
            }
            }}
        } else if let Some(Err(e)) = val.read().as_ref() {
            p { class: "text-danger", "{e}" }
        } else {
            p { class: "text-muted", "Loading…" }
        }
    }
}
