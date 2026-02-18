use crate::api;
use crate::Route;
use dioxus::prelude::*;
use std::cmp::Ordering;
use std::collections::HashMap;

#[component]
pub fn Results(url: String) -> Element {
    let url_for_data = url.clone();
    let mut include_ribbon = use_signal(|| false);
    let data = use_resource(use_reactive(&(url_for_data, include_ribbon), |(u, inc_sig)| {
        let url = u.clone();
        let inc_ribbon = inc_sig();
        async move { api::results(&url, inc_ribbon).await.map_err(|e| e.to_string()) }
    }));
    let mut expanded = use_signal(|| None::<String>);
    let mut team_matches_cache =
        use_signal(|| HashMap::<String, Option<Result<crate::types::TeamMatchesResponse, String>>>::new());
    let mut sort_column = use_signal(|| "team".to_string());
    let mut sort_asc = use_signal(|| true);

    let val = data.value();
    rsx! {
        if let Some(Ok(results_data)) = val.read().as_ref() {
            div { class: "row",
                div { class: "col-12",
                    h1 { "{results_data.tournament.name} - Results" }
                    nav { aria_label: "breadcrumb",
                        ol { class: "breadcrumb",
                            li { class: "breadcrumb-item",
                                Link { to: Route::TournamentHome { url: url.clone() }, "{results_data.tournament.name}" }
                            }
                            li { class: "breadcrumb-item active", "Results" }
                        }
                    }
                }
            }
            div { class: "d-flex align-items-center gap-2 mt-2 mb-2",
                label { class: "form-check-label d-flex align-items-center gap-1 user-select-none",
                    input {
                        class: "form-check-input",
                        r#type: "checkbox",
                        id: "results-include-ribbon",
                        checked: include_ribbon(),
                        onchange: move |e| include_ribbon.set(e.value() == "true"),
                    }
                    "Include ribbon games"
                }
            }
            if results_data.teams.is_empty() {
                div { class: "alert alert-info mt-3",
                    h4 { "No results yet" }
                    p { "Tournament results will appear here as matches are completed." }
                }
            } else {
                {
                    let mut teams_sorted = results_data.teams.iter().collect::<Vec<_>>();
                    let col = sort_column().clone();
                    let asc = sort_asc();
                    teams_sorted.sort_by(|a, b| {
                        let ord = match col.as_str() {
                            "matches" => {
                                let a_tot = a.matches_won + a.matches_lost;
                                let b_tot = b.matches_won + b.matches_lost;
                                let a_ratio = if a_tot > 0 { a.matches_won as f64 / a_tot as f64 } else { 0.0 };
                                let b_ratio = if b_tot > 0 { b.matches_won as f64 / b_tot as f64 } else { 0.0 };
                                a_ratio.partial_cmp(&b_ratio).unwrap_or(Ordering::Equal)
                                    .then_with(|| a_tot.cmp(&b_tot))
                                    .then_with(|| a.matches_won.cmp(&b.matches_won))
                            }
                            "points" => {
                                let a_tot = a.points_won + a.points_lost;
                                let b_tot = b.points_won + b.points_lost;
                                let a_ratio = if a_tot > 0 { a.points_won as f64 / a_tot as f64 } else { 0.0 };
                                let b_ratio = if b_tot > 0 { b.points_won as f64 / b_tot as f64 } else { 0.0 };
                                a_ratio.partial_cmp(&b_ratio).unwrap_or(Ordering::Equal)
                                    .then_with(|| a_tot.cmp(&b_tot))
                                    .then_with(|| a.points_won.cmp(&b.points_won))
                            }
                            _ => a.pseudonym.to_lowercase().cmp(&b.pseudonym.to_lowercase()),
                        };
                        if asc { ord } else { ord.reverse() }
                    });
                    let backend = api::base_url();
                rsx! {
                div { class: "card mt-3",
                    div { class: "card-body",
                        div { class: "table-responsive",
                            table { class: "table table-striped align-middle mb-0",
                                thead {
                                    tr {
                                        th { style: "width: 1%;", "" }
                                        th {
                                            class: if sort_column() == "team" { "cursor-pointer user-select-none" } else { "cursor-pointer user-select-none" },
                                            onclick: move |_| {
                                                if sort_column() == "team" {
                                                    sort_asc.set(!sort_asc());
                                                } else {
                                                    sort_column.set("team".to_string());
                                                    sort_asc.set(true);
                                                }
                                            },
                                            "Team"
                                            if sort_column() == "team" {
                                                span { class: "ms-1", if sort_asc() { "↑" } else { "↓" } }
                                            }
                                        }
                                        th {
                                            class: "cursor-pointer user-select-none",
                                            onclick: move |_| {
                                                if sort_column() == "matches" {
                                                    sort_asc.set(!sort_asc());
                                                } else {
                                                    sort_column.set("matches".to_string());
                                                    sort_asc.set(false);
                                                }
                                            },
                                            "Matches (W–L)"
                                            if sort_column() == "matches" {
                                                span { class: "ms-1", if sort_asc() { "↑" } else { "↓" } }
                                            }
                                        }
                                        th {
                                            class: "cursor-pointer user-select-none",
                                            onclick: move |_| {
                                                if sort_column() == "points" {
                                                    sort_asc.set(!sort_asc());
                                                } else {
                                                    sort_column.set("points".to_string());
                                                    sort_asc.set(false);
                                                }
                                            },
                                            "Points (W–L)"
                                            if sort_column() == "points" {
                                                span { class: "ms-1", if sort_asc() { "↑" } else { "↓" } }
                                            }
                                        }
                                    }
                                }
                                tbody {
                                    for row_team in teams_sorted.iter() {
                                        {
                                            let tid = row_team.id.clone();
                                            let url_row = url.clone();
                                            let expanded_current = expanded();
                                            let is_expanded = expanded_current.as_ref() == Some(&tid);
                                            let cache = team_matches_cache();
                                            let has_cached = cache.contains_key(&tid);
                                            let need_fetch = is_expanded && !has_cached;
                                            if need_fetch {
                                                team_matches_cache.write().insert(tid.clone(), None);
                                                let mut cache_sig = team_matches_cache;
                                                let url_fetch = url.clone();
                                                let tid_fetch = tid.clone();
                                                spawn(async move {
                                                    let res = api::results_team_matches(&url_fetch, &tid_fetch).await;
                                                    cache_sig.write().insert(tid_fetch, Some(res));
                                                });
                                            }
                                            let tid_click = tid.clone();
                                            let tid_btn = tid.clone();
                                            rsx! {
                                        tr {
                                            key: "{tid}",
                                            class: if is_expanded { "table-active" } else { "" },
                                            onclick: move |_| {
                                                if is_expanded {
                                                    expanded.set(None);
                                                } else {
                                                    expanded.set(Some(tid_click.clone()));
                                                }
                                            },
                                            td {
                                                class: "text-center",
                                                onclick: move |ev: Event<MouseData>| { ev.stop_propagation(); },
                                                button {
                                                    r#type: "button",
                                                    class: "btn btn-lg p-0 text-secondary",
                                                    "aria-label": if is_expanded { "Collapse" } else { "Expand" },
                                                    onclick: move |ev: Event<MouseData>| {
                                                        ev.stop_propagation();
                                                        if is_expanded {
                                                            expanded.set(None);
                                                        } else {
                                                            expanded.set(Some(tid_btn.clone()));
                                                        }
                                                    },
                                                    if is_expanded { "−" } else { "+" }
                                                }
                                            }
                                            td {
                                                Link {
                                                    to: Route::TeamProfilePage { id: row_team.id.clone() },
                                                    class: "text-decoration-none d-inline-flex align-items-center",
                                                    onclick: move |ev: Event<MouseData>| { ev.stop_propagation(); },
                                                    if let Some(ph) = &row_team.profile_photo {
                                                        img {
                                                            src: "{backend}/static/{ph}",
                                                            alt: "",
                                                            class: "rounded-circle me-2",
                                                            style: "width: 28px; height: 28px; object-fit: cover;"
                                                        }
                                                    } else {
                                                        div {
                                                            class: "rounded-circle me-2 d-flex align-items-center justify-content-center bg-secondary",
                                                            style: "width: 28px; height: 28px; min-width: 28px;",
                                                            span { class: "text-white small", "👥" }
                                                        }
                                                    }
                                                    span { "{row_team.pseudonym}" }
                                                }
                                            }
                                            td { "{row_team.matches_won}–{row_team.matches_lost}" }
                                            td { "{row_team.points_won}–{row_team.points_lost}" }
                                        }
                                        if is_expanded {
                                            tr {
                                                key: "{tid}-detail",
                                                td { colspan: 4, class: "p-0 bg-light",
                                                    div { class: "p-3",
                                                        match team_matches_cache().get(&tid) {
                                                            None | Some(None) => rsx! { p { class: "text-muted mb-0", "Loading…" } },
                                                            Some(Some(Err(e))) => rsx! { p { class: "text-danger mb-0", "{e}" } },
                                                            Some(Some(Ok(ref resp))) => {
                                                            let max_sets = resp.matches.iter().map(|m| m.sets.len()).max().unwrap_or(0).max(1);
                                                            rsx! {
                                                                if resp.matches.is_empty() {
                                                                    p { class: "text-muted mb-0", "No matches in this tournament." }
                                                                } else {
                                                                    div { class: "table-responsive",
                                                                        table { class: "table table-sm table-bordered mb-0", style: "table-layout: fixed;",
                                                                            colgroup {
                                                                                col { style: "min-width: 200px; width: 35%;" }
                                                                                col { style: "width: 80px;" }
                                                                                col { style: "min-width: 120px;" }
                                                                                for _ in 0..max_sets {
                                                                                    col { style: "width: 36px;" }
                                                                                }
                                                                            }
                                                                            thead {
                                                                                tr {
                                                                                    th { class: "text-start", "Match" }
                                                                                    th { "Result" }
                                                                                    th { class: "text-start", "Team" }
                                                                                    for set_idx in 0..max_sets {
                                                                                        th { class: "text-start", style: "width: 36px;", "Set {set_idx + 1}" }
                                                                                    }
                                                                                }
                                                                            }
                                                                            tbody {
                                                                                for game_row in resp.matches.iter() {
                                                                                    {
                                                                                        let team_won = game_row.match_winner.as_deref() == game_row.your_side.as_deref();
                                                                                        let result_class = if team_won { "text-success" } else { "text-danger" };
                                                                                        let result_text = if team_won { "W" } else { "L" };
                                                                                        let our_first = game_row.your_side.as_deref() != Some("TEAM2");
                                                                                        let (row1_name, row1_sets, row2_name, row2_sets) = if our_first {
                                                                                            (
                                                                                                game_row.team1_name.as_str(), 
                                                                                                game_row.sets.iter().map(|s| s.team1_points).collect::<Vec<_>>(), 
                                                                                                game_row.team2_name.as_str(), 
                                                                                                game_row.sets.iter().map(|s| s.team2_points).collect::<Vec<_>>(), 
                                                                                            )
                                                                                        } else {
                                                                                            (
                                                                                                game_row.team2_name.as_str(), 
                                                                                                game_row.sets.iter().map(|s| s.team2_points).collect::<Vec<_>>(), 
                                                                                                game_row.team1_name.as_str(), 
                                                                                                game_row.sets.iter().map(|s| s.team1_points).collect::<Vec<_>>(), 
                                                                                            )
                                                                                        };
                                                                                        rsx! {
                                                                                    tr { key: "{game_row.uuid}-1",
                                                                                        td { rowspan: 2, class: "text-start align-top",
                                                                                            span { class: "d-inline-flex align-items-center gap-1",
                                                                                                Link {
                                                                                                    to: Route::MatchPageById { url: url_row.clone(), match_id: game_row.uuid.clone() },
                                                                                                    class: "text-decoration-none",
                                                                                                    onclick: move |ev: Event<MouseData>| { ev.stop_propagation(); },
                                                                                                    "{game_row.name}"
                                                                                                }
                                                                                                if game_row.ribbon {
                                                                                                    span {
                                                                                                        class: "schedule-timeline-ribbon-icon",
                                                                                                        title: "Ribbon game",
                                                                                                        img {
                                                                                                            src: "{backend}/static/ribbon.svg",
                                                                                                            alt: "Ribbon game"
                                                                                                        }
                                                                                                    }
                                                                                                }
                                                                                            }
                                                                                        }
                                                                                        td { rowspan: 2, class: "align-top {result_class}", strong { "{result_text}" } }
                                                                                        td { class: "text-muted text-start",
                                                                                            if let Some(ph) = &row_team.profile_photo {
                                                                                                img { src: "{backend}/static/{ph}", alt: "", class: "rounded-circle me-1", style: "width: 18px; height: 18px; object-fit: cover;" }
                                                                                            } else {
                                                                                                span { class: "d-inline-block rounded-circle me-1 bg-secondary text-white text-center", style: "width: 18px; height: 18px; line-height: 18px; font-size: 10px;", "👥" }
                                                                                            }
                                                                                            span { "{row1_name}" }
                                                                                        }
                                                                                        for i in 0..max_sets {
                                                                                            td { class: "text-start", style: "width: 36px;",
                                                                                                "{row1_sets.get(i).copied().unwrap_or(0)}"
                                                                                            }
                                                                                        }
                                                                                    }
                                                                                    tr {
                                                                                        td { class: "text-muted text-start",
                                                                                            if let Some(ph) = results_data
                                                                                                .teams
                                                                                                .iter()
                                                                                                .find(|t| t.pseudonym == row2_name)
                                                                                                .and_then(|t| t.profile_photo.as_ref())
                                                                                            {
                                                                                                img { src: "{backend}/static/{ph}", alt: "", class: "rounded-circle me-1", style: "width: 18px; height: 18px; object-fit: cover;" }
                                                                                            } else {
                                                                                                span { class: "d-inline-block rounded-circle me-1 bg-secondary text-white text-center", style: "width: 18px; height: 18px; line-height: 18px; font-size: 10px;", "👥" }
                                                                                            }
                                                                                            span { "{row2_name}" }
                                                                                        }
                                                                                        for i in 0..max_sets {
                                                                                            td { class: "text-start", style: "width: 36px;",
                                                                                                "{row2_sets.get(i).copied().unwrap_or(0)}"
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
            p { class: "text-danger", "{e}" }
        } else {
            p { "Loading…" }
        }
    }
}
