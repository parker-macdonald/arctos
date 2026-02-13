#![allow(non_snake_case)]

mod api;
mod pages;

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

    #[route("/auth/google/choose-account-type")]
    GoogleChooseAccountType {},

    #[route("/auth/google/complete-profile")]
    GoogleCompleteProfile {},

    #[route("/markdown/:slug")]
    MarkdownPage { slug: String },

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

    #[route("/:url/setup")]
    TournamentSetup { url: String },

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

    #[route("/:url/scoreboard")]
    Scoreboard { url: String },

    #[route("/:url/record?:field&:camera_key")]
    Record { url: String, field: String, camera_key: String },

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

    #[route("/:tournament_url/fields/:field_id/edit")]
    EditField { tournament_url: String, field_id: u32 },

    #[route("/:tournament_url/tags/:tag_id/edit")]
    EditTag { tournament_url: String, tag_id: u32 },

    #[route("/:tournament_url/matches/:match_id/edit")]
    EditMatch { tournament_url: String, match_id: String },

    #[route("/:tournament_url/register/player/edit")]
    EditPlayerRegistration { tournament_url: String },

    #[route("/:tournament_url/register/team/edit")]
    EditTeamRegistration { tournament_url: String },

    #[route("/players")]
    PlayersList {},

    #[route("/players/:id")]
    PlayerProfile { id: String },

    #[route("/teams")]
    TeamsList {},

    #[route("/teams/:id")]
    TeamProfile { id: String },

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
}

fn main() {
    dioxus::launch(|| {
        rsx! {
            Router::<Route> {}
        }
    });
}
