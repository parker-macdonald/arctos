//! Shared registered teams table card.

use crate::api;
use crate::types::TeamWithCount;
use crate::Route;
use dioxus::prelude::*;

#[derive(Clone, PartialEq, Props)]
pub struct EventTeamsListProps {
    pub teams: Vec<TeamWithCount>,
    pub card_title: String,
    /// Show a "Registration Date" column (tournament/league home use this).
    #[props(default = true)]
    pub show_registered_at: bool,
    /// If set, show "count / max" in Players column (matches tournament_home).
    #[props(default)]
    pub max_team_size_roster: Option<u32>,
}

#[component]
pub fn EventTeamsList(props: EventTeamsListProps) -> Element {
    let EventTeamsListProps {
        teams,
        card_title,
        show_registered_at,
        max_team_size_roster,
    } = props;
    let backend = api::base_url();
    if teams.is_empty() {
        return rsx! { };
    }
    let count = teams.len();
    let title = format!("{card_title} ({count})");
    rsx! {
        div { class: "row mt-4",
            div { class: "col-12",
                div { class: "card",
                    div { class: "card-header", h5 { class: "mb-0", "{title}" } }
                    div { class: "card-body",
                        div { class: "table-responsive",
                            table { class: "table table-striped",
                                thead {
                                    tr {
                                        th { "Team Name" }
                                        th { "Players" }
                                        if show_registered_at {
                                            th { "Registration Date" }
                                        }
                                    }
                                }
                                tbody {
                                    for team in teams.iter() {
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
                                                if let Some(max) = max_team_size_roster {
                                                    span { " / {max}" }
                                                }
                                            }
                                            if show_registered_at {
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
    }
}
