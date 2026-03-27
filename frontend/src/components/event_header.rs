//! Shared event header (title, subtitle, optional league badge).

use crate::Route;
use dioxus::prelude::*;

#[derive(Clone, PartialEq, Props)]
pub struct EventHeaderProps {
    pub title: String,
    pub subtitle: String,
    /// When set, show a "Part of {name}" badge linking to the league.
    pub badge_league_url: Option<String>,
    pub badge_season: Option<String>,
    pub badge_name: Option<String>,
}

#[component]
pub fn EventHeader(props: EventHeaderProps) -> Element {
    let EventHeaderProps {
        title,
        subtitle,
        badge_league_url,
        badge_season: _,
        badge_name,
    } = props;
    rsx! {
        div { class: "row",
            div { class: "col-12",
                h1 { "{title}" }
                if let (Some(lu), Some(name)) = (badge_league_url, badge_name) {
                    p { class: "mb-1",
                        Link {
                            to: Route::LeagueHome { league_url: lu },
                            class: "badge bg-secondary text-decoration-none",
                            "Part of {name}"
                        }
                    }
                }
                p { class: "lead", "{subtitle}" }
            }
        }
    }
}
