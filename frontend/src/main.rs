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

    #[route("/:url")]
    TournamentHome { url: String },

    #[route("/:url/schedule")]
    Schedule { url: String },

    #[route("/:url/results")]
    Results { url: String },

    #[route("/:url/bracket")]
    Bracket { url: String },

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

    #[route("/:url/start-match")]
    StartMatch { url: String },

    #[route("/:url/run-match")]
    RunMatch { url: String },

    #[route("/:url/finalize-match")]
    FinalizeMatch { url: String },

    #[route("/:url/scoreboard")]
    Scoreboard { url: String },

    #[route("/:url/record")]
    Record { url: String },

    #[route("/:url/match")]
    MatchPage { url: String },

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
