use crate::api;
use crate::types::{TeamRegItem, TournamentPlayerItem};
use crate::Route;
use dioxus::prelude::*;
use std::collections::HashMap;

/// Cache value: None = loading, Some(Ok(players)) = loaded, Some(Err(_)) = error.
type PlayersCache = HashMap<String, Option<Result<Vec<TournamentPlayerItem>, String>>>;

#[component]
fn RegistrationRow(
    registration: TeamRegItem,
    is_expanded: bool,
    on_toggle: EventHandler<()>,
    is_own_team: bool,
    backend: String,
    players_cache: Signal<PlayersCache>,
) -> Element {
    let event_key = registration.event.clone();
    rsx! {
        tr {
            class: if is_expanded { "table-active" } else { "" },
            onclick: move |_| on_toggle.call(()),
            style: "cursor: pointer;",
            td {
                i {
                    class: if is_expanded { "fas fa-chevron-down" } else { "fas fa-chevron-right" },
                    style: "font-size: 0.7rem;"
                }
            }
            td { Link { to: Route::TournamentHome { url: event_key.clone() }, "{event_key}" } }
            td { strong { "{registration.pseudonym.as_deref().unwrap_or(\"-\")}" } }
            td {
                if let Some(date) = &registration.start_date {
                    "{date.split('T').next().unwrap_or(date)}"
                } else {
                    "TBA"
                }
            }
            td {
                span {
                    class: format!(
                        "badge {}",
                        if registration.status == "CONFIRMED" { "bg-success" } else { "bg-warning" }
                    ),
                    "{registration.status}"
                }
            }
            td {
                if registration.paid {
                    span { class: "badge bg-success", "Paid" }
                    if registration.amount_paid > 0.0 {
                        { let amt = format!("${:.2}", registration.amount_paid); rsx! { small { class: "text-muted ms-1", "{amt}" } } }
                    }
                } else {
                    span { class: "badge bg-warning", "Unpaid" }
                }
            }
            td {
                onclick: move |e: Event<MouseData>| e.stop_propagation(),
                if is_own_team {
                    Link {
                        to: Route::Invitations { url: event_key.clone() },
                        class: "btn btn-sm btn-outline-primary",
                        "Manage Roster"
                    }
                }
            }
        }
        if is_expanded {
            tr {
                key: "{event_key}-players",
                td { colspan: 7, class: "bg-light py-3",
                    {
                        let ev = registration.event.clone();
                        let cached = players_cache().get(&ev).cloned();
                        let (loading, err_msg, players) = match &cached {
                            None => (true, false, None),
                            Some(None) => (true, false, None),
                            Some(Some(Ok(list))) => (false, false, Some(list.clone())),
                            Some(Some(Err(_))) => (false, true, None),
                        };
                        rsx! {
                            div { class: "ps-4", onclick: move |e: Event<MouseData>| e.stop_propagation(),
                                if let Some(players_list) = players {
                                    if players_list.is_empty() {
                                        p { class: "text-muted mb-0", "No players registered yet." }
                                    } else {
                                        div { class: "row",
                                            for p in players_list.iter() {
                                                div { class: "col-md-6 mb-2",
                                                    Link {
                                                        to: Route::PlayerProfilePage { id: p.registration.player.clone() },
                                                        class: "text-decoration-none text-body",
                                                        div { class: "card card-body py-2",
                                                            div { class: "d-flex align-items-center",
                                                                div { class: "flex-shrink-0 me-2",
                                                                    if let Some(player) = &p.player {
                                                                        if let Some(photo) = &player.profile_photo {
                                                                            img { src: "{backend}/static/{photo}", alt: "{player.name}", class: "rounded-circle", style: "width: 40px; height: 40px; object-fit: cover;" }
                                                                        } else {
                                                                            div { class: "d-flex align-items-center justify-content-center bg-secondary rounded-circle", style: "width: 40px; height: 40px;", i { class: "fas fa-user text-white" } }
                                                                        }
                                                                    } else {
                                                                        div { class: "d-flex align-items-center justify-content-center bg-secondary rounded-circle", style: "width: 40px; height: 40px;", i { class: "fas fa-user text-white" } }
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
                                } else if loading {
                                    p { class: "text-muted mb-0", "Loading…" }
                                } else if err_msg {
                                    p { class: "text-danger mb-0", "Failed to load players." }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

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

    let mut expanded_event = use_signal(|| Option::<String>::None);
    let mut players_cache = use_signal(|| PlayersCache::new());
    let team_id_for_fetch = id().clone();
    use_effect(move || {
        let expanded = expanded_event();
        if let Some(ev) = &expanded {
            if !players_cache().contains_key(ev) {
                let mut c = players_cache().clone();
                c.insert(ev.clone(), None);
                players_cache.set(c);
                let tid = team_id_for_fetch.clone();
                let ev_fetch = ev.clone();
                let mut cache_sig = players_cache;
                spawn(async move {
                    let res = api::team_registration_players(&tid, &ev_fetch).await;
                    cache_sig.set({
                        let mut c = cache_sig();
                        c.insert(ev_fetch, Some(res));
                        c
                    });
                });
            }
        }
    });

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
                        div { class: "card-header d-flex justify-content-between align-items-center",
                            h5 { class: "mb-0", "Team Information" }
                            if me.read().as_ref().and_then(|r| r.as_ref().ok())
                                .map(|u| u.user_type == "team" && u.id == d.team.id)
                                .unwrap_or(false)
                            {
                                Link {
                                    to: Route::EditTeamProfile { team_id: d.team.id.clone() },
                                    class: "btn btn-outline-secondary btn-sm",
                                    "✎"
                                }
                            }
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
                                                th { style: "width: 2rem;", "" }
                                                th { "Tournament" }
                                                th { "Team Name" }
                                                th { "Date" }
                                                th { "Status" }
                                                th { "Payment" }
                                                th { "Actions" }
                                            }
                                        }
                                        tbody {
                                            { {
                                                let mut row_views = Vec::new();
                                                for reg_item in d.registrations.iter() {
                                                    let reg_clone = reg_item.clone();
                                                    let ev = reg_clone.event.clone();
                                                    let is_expanded = expanded_event() == Some(ev.clone());
                                                    let ev_for_toggle = ev.clone();
                                                    let is_own = me.read().as_ref().and_then(|r| r.as_ref().ok()).map(|u| u.user_type == "team" && u.id == d.team.id).unwrap_or(false);
                                                    row_views.push(rsx! {
                                                        RegistrationRow {
                                                            key: "{ev}",
                                                            registration: reg_clone,
                                                            is_expanded,
                                                            on_toggle: move |_| {
                                                                expanded_event.set(if is_expanded { None } else { Some(ev_for_toggle.clone()) });
                                                            },
                                                            is_own_team: is_own,
                                                            backend: backend.clone(),
                                                            players_cache,
                                                        }
                                                    });
                                                }
                                                rsx! { for row in row_views { {row} } }
                                            } }
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
                                                        a { href: "/{note.match_info.event}/match/{note.match_info.uuid}", "{note.match_info.name}" }
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
