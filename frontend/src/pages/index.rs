use crate::api;
use crate::types::UserRegStatus;
use crate::Route;
use dioxus::prelude::*;

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
pub fn Index() -> Element {
    let tournaments = use_resource(move || async move {
        api::tournaments().await.map_err(|e| e.to_string())
    });
    let val = tournaments.value();

    rsx! {
        div { class: "row",
            div { class: "col-12",
                if let Some(Ok(data)) = val.read().as_ref() {
                    if !data.upcoming.is_empty() || !data.past.is_empty() {
                        h2 { class: "mb-3", "Upcoming Events" }
                        div { class: "row mb-4",
                            for t in data.upcoming.iter() {
                                div { key: "{t.url}", class: "col-md-6 col-lg-4 mb-3",
                                    Link {
                                        to: Route::TournamentHome { url: t.url.clone() },
                                        class: "card tournament-card text-decoration-none",
                                        style: "display: block; transition: box-shadow 0.2s ease, transform 0.2s ease;",
                                        div { class: "card-body",
                                            h5 { class: "card-title", "{t.name}" }
                                            p { class: "card-text",
                                                span { class: "text-muted",
                                                    "📅 {format_date_display(&t.start_date, t.end_date.as_ref())}"
                                                }
                                                br {}
                                                span { class: "text-muted",
                                                    "📍 {t.location.as_deref().unwrap_or(\"TBA\")}"
                                                }
                                                br {}
                                                if let Some(max) = t.n_max_teams {
                                                    small { class: "text-muted",
                                                        "{data.team_counts.get(&t.url).copied().unwrap_or(0)}/{max} teams registered"
                                                    }
                                                } else {
                                                    small { class: "text-muted",
                                                        "{data.team_counts.get(&t.url).copied().unwrap_or(0)} teams registered"
                                                    }
                                                }
                                                if let Some(urs) = data.user_reg_status.get(&t.url) {
                                                    br {}
                                                    UserRegBadges { urs: urs.clone() }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        h2 { class: "mb-3", "Past Events" }
                        div { class: "row",
                            for t in data.past.iter() {
                                div { key: "{t.url}", class: "col-md-6 col-lg-4 mb-3",
                                    Link {
                                        to: Route::TournamentHome { url: t.url.clone() },
                                        class: "card tournament-card text-decoration-none",
                                        style: "display: block;",
                                        div { class: "card-body",
                                            h5 { class: "card-title", "{t.name}" }
                                            p { class: "card-text text-muted",
                                                "{format_date_display(&t.start_date, t.end_date.as_ref())}"
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    } else {
                        h2 { "Upcoming Events" }
                        div { class: "alert alert-info",
                            h4 { "No tournaments available" }
                            p { "Check back later for upcoming events!" }
                        }
                    }
                } else if let Some(Err(e)) = val.read().as_ref() {
                    p { class: "text-danger", "{e}" }
                } else {
                    p { class: "text-muted", "Loading…" }
                }
            }
        }
    }
}

#[component]
fn UserRegBadges(urs: UserRegStatus) -> Element {
    let status_class = match urs.status.as_str() {
        "CONFIRMED" => "bg-success",
        "PENDING_TEAM_APPROVAL" => "bg-warning text-dark",
        _ => "bg-secondary",
    };
    let paid_class = if urs.paid { "bg-success" } else { "bg-warning text-dark" };
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
    }
}
