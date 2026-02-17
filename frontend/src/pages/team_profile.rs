use crate::api;
use crate::Route;
use dioxus::prelude::*;

/// Page component for the router. Reads id from use_route() so navigation
/// between profiles updates the view (router reuses the same component and
/// does not pass new props).
#[component]
pub fn TeamProfilePage(id: String) -> Element {
    let route = use_route::<Route>();
    let id = match &route {
        Route::TeamProfilePage { id } => id.clone(),
        _ => return rsx! { div { class: "alert alert-danger", "Invalid route" } },
    };
    let mut id_signal = use_signal(|| id.clone());
    id_signal.set(id);
    rsx! {
        TeamProfile { id: id_signal }
    }
}

#[component]
pub fn TeamProfile(id: Signal<String>) -> Element {
    let data = use_resource(use_reactive(&id, move |sid| {
        let i = sid().clone();
        async move { api::team_profile(&i).await.map_err(|e| e.to_string()) }
    }));
    let me = use_resource(move || async move { api::me().await });
    let val = data.value();
    let backend = api::base_url();
    let mut about_markdown = use_signal(|| Option::<String>::None);
    use_effect(move || {
        let v = val.read();
        if let Some(Ok(d)) = v.as_ref() {
            about_markdown.set(d.team.about.clone());
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
            div { class: "row",
                div { class: "col-12",
                    h1 { "{d.team.name}" }
                    nav { aria_label: "breadcrumb",
                        ol { class: "breadcrumb",
                            li { class: "breadcrumb-item", Link { to: Route::TeamsList {}, "Teams" } }
                            li { class: "breadcrumb-item active", "{d.team.name}" }
                        }
                    }
                }
            }

            div { class: "row",
                div { class: "col-md-8",
                    div { class: "card",
                        div { class: "card-header",
                            h5 { class: "mb-0", "Team Information" }
                        }
                        div { class: "card-body",
                            if let Some(photo) = &d.team.profile_photo {
                                div { class: "text-center mb-3",
                                    img { src: "{backend}/static/{photo}", alt: "Team Photo", class: "rounded", style: "width: 150px; height: 150px; object-fit: cover;" }
                                }
                            }
                            p { strong { "Team Name: " } "{d.team.name}" }
                            if let Some(loc) = &d.team.location {
                                p { strong { "Location: " } "{loc}" }
                            }
                            if let Some(site) = &d.team.website {
                                p { strong { "Website: " } a { href: "{site}", target: "_blank", "{site}" } }
                            }
                            if let Some(email) = &d.team.email {
                                p { strong { "Email: " } "{email}" }
                            }
                            if let Some(about) = &d.team.about {
                                if !about.is_empty() {
                                    p { strong { "About: " } }
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
                            }
                        }
                    }

                    div { class: "card mt-3",
                        div { class: "card-header",
                            h5 { class: "mb-0", "Tournament Registrations" }
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
                                                th { "Team Name" }
                                                th { "Date" }
                                                th { "Status" }
                                                th { "Payment" }
                                                th { "Actions" }
                                            }
                                        }
                                        tbody {
                                            for r in d.registrations.iter() {
                                                tr { key: "{r.event}",
                                                    td { Link { to: Route::TournamentHome { url: r.event.clone() }, "{r.event}" } }
                                                    td {
                                                        strong { "{r.pseudonym.as_deref().unwrap_or(\"-\")}" }
                                                    }
                                                    td {
                                                        if let Some(date) = &r.start_date {
                                                            "{date.split('T').next().unwrap_or(date)}"
                                                        } else {
                                                            "TBA"
                                                        }
                                                    }
                                                    td {
                                                        span {
                                                            class: format!(
                                                                "badge {}",
                                                                if r.status == "CONFIRMED" {
                                                                    "bg-success"
                                                                } else {
                                                                    "bg-warning"
                                                                }
                                                            ),
                                                            "{r.status}"
                                                        }
                                                    }
                                                    td {
                                                        if r.paid {
                                                            span { class: "badge bg-success", "Paid" }
                                                            if r.amount_paid > 0.0 {
                                                                {
                                                                    let paid_amount = format!("${:.2}", r.amount_paid);
                                                                    rsx! { small { class: "text-muted ms-1", "{paid_amount}" } }
                                                                }
                                                            }
                                                        } else {
                                                            span { class: "badge bg-warning", "Unpaid" }
                                                        }
                                                    }
                                                    td {
                                                        if let Some(Ok(u)) = me.read().as_ref() {
                                                            if u.user_type == "team" && u.id == d.team.id {
                                                                Link {
                                                                to: Route::Invitations { url: r.event.clone() },
                                                                    class: "btn btn-sm btn-outline-primary",
                                                                    "Manage Roster"
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

                    if !d.team_notes.is_empty() {
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
                                            for note in d.team_notes.iter() {
                                                tr { key: "{note.created_at.as_deref().unwrap_or(\"-\")}-{note.point_index}",
                                                    td { "{note.created_at.as_deref().unwrap_or(\"-\")}" }
                                                    td { "{note.text}" }
                                                    td { "{note.point_index}" }
                                                    td {
                                                        a { href: "/app/{note.match_info.event}/match/{note.match_info.uuid}", "{note.match_info.name}" }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    if let Some(Ok(u)) = me.read().as_ref() {
                        if u.user_type == "team" && u.id == d.team.id && !d.tournament_players.is_empty() {
                            div { class: "card mt-3",
                                div { class: "card-header",
                                    h5 { class: "mb-0", "Team Members by Tournament" }
                                }
                                div { class: "card-body",
                                    for (tournament_url, players) in d.tournament_players.iter() {
                                        div { class: "mb-3",
                                            h6 { a { href: "/app/{tournament_url}", "{tournament_url}" } }
                                            if players.is_empty() {
                                                p { class: "text-muted", "No players registered yet." }
                                            } else {
                                                div { class: "row",
                                                    for p in players.iter() {
                                                        div { class: "col-md-6 mb-2",
                                                            div { class: "card card-body py-2",
                                                                div { class: "d-flex align-items-center",
                                                                    div { class: "flex-shrink-0 me-2",
                                                                        if let Some(player) = &p.player {
                                                                            if let Some(photo) = &player.profile_photo {
                                                                                img { src: "{backend}/static/{photo}", alt: "{player.name}", class: "rounded-circle", style: "width: 40px; height: 40px; object-fit: cover;" }
                                                                            } else {
                                                                                div { class: "d-flex align-items-center justify-content-center bg-secondary rounded-circle", style: "width: 40px; height: 40px;",
                                                                                    i { class: "fas fa-user text-white" }
                                                                                }
                                                                            }
                                                                        } else {
                                                                            div { class: "d-flex align-items-center justify-content-center bg-secondary rounded-circle", style: "width: 40px; height: 40px;",
                                                                                i { class: "fas fa-user text-white" }
                                                                            }
                                                                        }
                                                                    }
                                                                    div { class: "flex-grow-1",
                                                                        div { class: "d-flex justify-content-between align-items-center",
                                                                            div {
                                                                                strong { "{p.registration.jersey_name.as_deref().unwrap_or(\"-\")}" }
                                                                                if let Some(num) = &p.registration.jersey_number {
                                                                                    span { class: "text-muted ms-1", "#{num}" }
                                                                                }
                                                                            }
                                                                            small { class: "text-muted", "{p.registration.player}" }
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
                }
            }
        } else if let Some(Err(e)) = val.read().as_ref() {
            p { class: "error", "{e}" }
        } else {
            p { "Loading…" }
        }
    }
}
