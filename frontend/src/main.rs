#![allow(non_snake_case)]

mod api;
mod components;
mod pages;

#[cfg(target_arch = "wasm32")]
mod record_idb;
mod stones_filter;
mod types;

use dioxus::prelude::*;
use pages::*;

#[derive(Routable, Clone, PartialEq)]
#[rustfmt::skip]
enum Route {
    #[layout(Layout)]
    #[route("/")]
    Index {},

    #[route("/login")]
    Login {},

    #[route("/register")]
    Register {},

    #[route("/register/player")]
    RegisterPlayer {},

    #[route("/register/team")]
    RegisterTeam {},

    #[route("/auth/google/choose-account-type")]
    GoogleChooseAccountType {},

    #[route("/auth/google/complete-profile")]
    GoogleCompleteProfile {},

    #[route("/:url")]
    TournamentHome { url: String },

    #[route("/:url/schedule")]
    Schedule { url: String },

    #[route("/:url/results")]
    Results { url: String },

    #[route("/:url/bracket")]
    Bracket { url: String },

    #[route("/:url/bracket-setup")]
    BracketSetup { url: String },

    #[route("/:url/settings")]
    TournamentSettings { url: String },

    #[route("/:url/register")]
    TournamentRegister { url: String },

    #[route("/:url/manage")]
    Manage { url: String },

    #[route("/:url/invitations")]
    Invitations { url: String },

    #[route("/:url/start-match/:match_id")]
    StartMatch { url: String, match_id: String },

    #[route("/:url/run-match/:match_id")]
    RunMatch { url: String, match_id: String },

    #[route("/:url/finalize-match/:match_id")]
    FinalizeMatch { url: String, match_id: String },

    #[route("/:url/scoreboard?:field")]
    Scoreboard { url: String, field: String },

    #[route("/:url/record?:field&:camera_key&:camera_name")]
    Record { url: String, field: String, camera_key: String, camera_name: String },

    #[route("/:url/match")]
    MatchPage { url: String },

    #[route("/:url/match/:match_id")]
    MatchPageById { url: String, match_id: String },

    #[route("/players/:player_id/injuries/new")]
    AddInjury { player_id: String },

    #[route("/players/:player_id/injuries/:injury_id/edit")]
    EditInjury { player_id: String, injury_id: u32 },

    #[route("/players/:player_id/edit")]
    EditPlayerProfile { player_id: String },

    #[route("/teams/:team_id/edit")]
    EditTeamProfile { team_id: String },

    #[route("/players")]
    PlayersList {},

    #[route("/players/:id")]
    PlayerProfilePage { id: String },

    #[route("/teams")]
    TeamsList {},

    #[route("/teams/:id")]
    TeamProfilePage { id: String },

    #[route("/stones")]
    Stones {},

    #[route("/about")]
    About {},

    #[route("/new-tournament")]
    NewTournament {},

    #[route("/docs")]
    Docs {},

    #[route("/privacy-policy")]
    Privacy {},

    #[route("/terms")]
    Terms {},

    #[route("/thanks")]
    Thanks {},

    #[route("/license")]
    License {},

    #[route("/arctos-schedule-script")]
    ArctosScheduleScript {},

    #[route("/data-accessibility-guide")]
    DataAccessibilityGuide {},
}

fn main() {
    dioxus::launch(|| {
        rsx! {
            Router::<Route> {}
        }
    });
}
