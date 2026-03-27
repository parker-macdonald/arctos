use crate::api;
use crate::types::{LeagueInfo, UserRegStatus};
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn LeaguesIndex() -> Element {
    let data = use_resource(move || async move {
        api::leagues_list().await.map_err(|e| e.to_string())
    });
    let val = data.value();

    rsx! {
        div { class: "row",
            div { class: "col-12",
                h1 { class: "mb-4", "Leagues" }
                p { class: "lead text-muted mb-4",
                    "Leagues are collections of tournaments that share a registration and have collective results."
                }
                if let Some(Ok(res)) = val.read().as_ref() {
                    if res.leagues.is_empty() {
                        div { class: "alert alert-info",
                            "No leagues yet. "
                            Link { to: Route::NewLeague {}, "Create a league" }
                            " to get started."
                        }
                    } else {
                        div { class: "row",
                            for l in res.leagues.iter() {
                                {
                                    let count = res.team_counts.get(&l.league_url).copied().unwrap_or(0);
                                    let urs = res.user_reg_status.get(&l.league_url).cloned();
                                    rsx! {
                                        LeagueCard {
                                            league: l.clone(),
                                            team_count: count,
                                            user_reg_status: urs,
                                        }
                                    }
                                }
                            }
                        }
                    }
                } else if let Some(Err(e)) = val.read().as_ref() {
                    div { class: "alert alert-danger", "{e}" }
                } else {
                    p { class: "text-muted", "Loading…" }
                }
            }
        }
    }
}

#[component]
fn LeagueCard(league: LeagueInfo, team_count: u32, user_reg_status: Option<UserRegStatus>) -> Element {
    rsx! {
        div { key: "{league.league_url}", class: "col-md-6 col-lg-4 mb-3",
            Link {
                to: Route::LeagueHome { league_url: league.league_url.clone() },
                class: "card text-decoration-none d-block position-relative",
                style: "transition: box-shadow 0.2s ease, transform 0.2s ease;",
                div { class: "card-body",
                    h5 { class: "card-title", "{league.name}" }
                    p { class: "card-text",
                        if let Some(max) = league.n_max_teams {
                            small { class: "text-muted",
                                "{team_count}/{max} teams registered"
                            }
                        } else {
                            small { class: "text-muted",
                                "{team_count} teams registered"
                            }
                        }
                        if let Some(urs) = user_reg_status {
                            br {}
                            LeagueUserRegBadges { urs: urs }
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn LeagueUserRegBadges(urs: UserRegStatus) -> Element {
    let status_class = match urs.status.as_str() {
        "CONFIRMED" => "bg-success",
        "PENDING_TEAM_APPROVAL" => "bg-warning text-dark",
        _ => "bg-secondary",
    };
    let paid_class = if urs.paid { "bg-success" } else { "bg-warning text-dark" };
    let waiver_status = urs.waiver_status.as_deref().unwrap_or("NOT_SIGNED");
    let waiver_class = match waiver_status {
        "VALID" => "bg-success",
        "OUT_OF_DATE" => "bg-warning text-dark",
        "NOT_SIGNED" => "bg-danger",
        _ => "bg-secondary",
    };
    let waiver_label = match waiver_status {
        "VALID" => "Waiver valid",
        "OUT_OF_DATE" => "Waiver out of date",
        "NOT_SIGNED" => "Waiver not signed",
        _ => "Waiver status unknown",
    };
    rsx! {
        span { class: "badge status-badge me-1 {status_class}",
            if urs.reg_type == "team" {
                "Team {urs.status}"
            } else {
                "Player {urs.status}"
            }
        }
        span { class: "badge status-badge {paid_class}",
            if urs.paid { "Paid" } else { "Unpaid" }
        }
        if urs.waiver_required {
            span { class: "badge status-badge ms-1 {waiver_class}",
                "{waiver_label}"
            }
        }
    }
}
