//! Shared event about card (fees, markdown about).

use dioxus::prelude::*;

#[derive(Clone, PartialEq, Props)]
pub struct EventAboutProps {
    pub card_title: String,
    pub show_fees: bool,
    pub team_fee: f64,
    pub player_fee: f64,
    pub team_fee_str: String,
    pub player_fee_str: String,
    pub about_html: Option<String>,
    pub about_raw: Option<String>,
    pub empty_message: String,
    pub max_teams: Option<u32>,
    pub max_roster: Option<u32>,
    pub max_field: Option<u32>,
}

#[component]
pub fn EventAbout(props: EventAboutProps) -> Element {
    let EventAboutProps {
        card_title,
        show_fees,
        team_fee,
        player_fee,
        team_fee_str,
        player_fee_str,
        about_html,
        about_raw,
        empty_message,
        max_teams,
        max_roster,
        max_field,
    } = props;
    rsx! {
        div { class: "card",
            div { class: "card-header", h5 { class: "mb-0", "{card_title}" } }
            div { class: "card-body",
                if max_teams.is_some() || max_roster.is_some() || max_field.is_some() {
                    div { class: "mb-3",
                        if let Some(max) = max_teams {
                            p { strong { "Max Teams: " } "{max}" }
                        }
                        if let Some(roster) = max_roster {
                            p { strong { "Max Team Size (Roster): " } "{roster}" }
                        }
                        if let Some(field) = max_field {
                            p { strong { "Max Team Size (Field): " } "{field}" }
                        }
                    }
                }
                if show_fees && (team_fee > 0.0 || player_fee > 0.0) {
                    div { class: "alert alert-info mb-3",
                        h6 { class: "mb-2", "Registration Fees" }
                        if team_fee > 0.0 {
                            p { class: "mb-1", strong { "Team Registration: " } "{team_fee_str}" }
                        }
                        if player_fee > 0.0 {
                            p { class: "mb-0", strong { "Player Registration: " } "{player_fee_str}" }
                        }
                    }
                }
                if let Some(about) = about_raw.as_ref() {
                    if !about.is_empty() {
                        if let Some(ref html) = about_html {
                            if html.is_empty() {
                                div { class: "markdown-content", style: "white-space: pre-wrap;", "{about}" }
                            } else {
                                div { dangerous_inner_html: "{html}" }
                            }
                        } else {
                            div { class: "markdown-content", style: "white-space: pre-wrap;", "{about}" }
                        }
                    } else {
                        p { class: "text-muted", "{empty_message}" }
                    }
                } else {
                    p { class: "text-muted", "{empty_message}" }
                }
            }
        }
    }
}
