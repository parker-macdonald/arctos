//! Shared registration buttons for league context (league home or league-event tournament).
//! Shows "Manage Roster" and "Edit Registration" when registered, or "Register" when not.

use crate::types::User;
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn LeagueRegistrationButtons(
    league_url: String,
    /// Aggregate flag kept for compatibility; per-role flags below take precedence.
    registration_open: bool,
    current_user: Option<Result<User, String>>,
    is_team_registered: bool,
    is_player_registered: bool,
    /// When true, Edit Registration uses a button that calls on_edit_registration; otherwise links to the registration page.
    use_edit_modal: bool,
    /// Callback to open the Edit Registration modal. Used when use_edit_modal is true.
    on_edit_registration: EventHandler<()>,
    /// Label for the register button when not registered. Default "Register".
    #[props(default = String::from("Register"))]
    register_label: String,
    /// Per-role toggles; when provided, override the aggregate flag.
    #[props(default = None)]
    team_registration_open: Option<bool>,
    #[props(default = None)]
    player_registration_open: Option<bool>,
) -> Element {
    let show_register_only = current_user.is_none();
    let (is_registered, user_type) = current_user
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .map(|u| {
            let reg = (u.user_type == "team" && is_team_registered)
                || (u.user_type == "player" && is_player_registered);
            (reg, u.user_type.as_str())
        })
        .unwrap_or((false, ""));

    let team_open = team_registration_open.unwrap_or(registration_open);
    let player_open = player_registration_open.unwrap_or(registration_open);

    rsx! {
        if show_register_only {
            button {
                r#type: "button",
                class: "btn btn-secondary disabled",
                disabled: true,
                "Sign in to register"
            }
        } else {
            if user_type == "team" {
                if is_team_registered {
                    Link {
                        to: Route::LeagueInvitations { league_url: league_url.clone() },
                        class: "btn btn-outline-secondary",
                        "Manage Roster"
                    }
                    if use_edit_modal {
                        button {
                            r#type: "button",
                            class: "btn btn-outline-secondary",
                            onclick: move |_| on_edit_registration.call(()),
                            "Edit Registration"
                        }
                    } else {
                        Link {
                            to: Route::LeagueRegister { league_url: league_url.clone() },
                            class: "btn btn-outline-secondary",
                            "Edit Registration"
                        }
                    }
                } else if team_open {
                    Link {
                        to: Route::LeagueRegister { league_url: league_url.clone() },
                        class: "btn btn-success",
                        "{register_label}"
                    }
                } else {
                    button {
                        r#type: "button",
                        class: "btn btn-secondary disabled",
                        disabled: true,
                        "Team registration closed"
                    }
                }
            } else if user_type == "player" {
                if is_player_registered {
                    if use_edit_modal {
                        button {
                            r#type: "button",
                            class: "btn btn-outline-secondary",
                            onclick: move |_| on_edit_registration.call(()),
                            "Edit Registration"
                        }
                    } else {
                        Link {
                            to: Route::LeagueRegister { league_url: league_url.clone() },
                            class: "btn btn-outline-secondary",
                            "Edit Registration"
                        }
                    }
                } else if player_open {
                    Link {
                        to: Route::LeagueRegister { league_url: league_url.clone() },
                        class: "btn btn-success",
                        "{register_label}"
                    }
                } else {
                    button {
                        r#type: "button",
                        class: "btn btn-secondary disabled",
                        disabled: true,
                        "Player registration closed"
                    }
                }
            } else {
                if team_open || player_open {
                    Link {
                        to: Route::LeagueRegister { league_url: league_url.clone() },
                        class: "btn btn-success",
                        "{register_label}"
                    }
                } else {
                    button {
                        r#type: "button",
                        class: "btn btn-secondary disabled",
                        disabled: true,
                        "Registration closed"
                    }
                }
            }
        }
    }
}
