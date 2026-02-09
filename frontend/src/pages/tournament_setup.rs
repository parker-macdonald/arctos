use crate::pages::schedule::Schedule;
use dioxus::prelude::*;

#[component]
pub fn TournamentSetup(url: String) -> Element {
    rsx! {
        Schedule { url: url }
    }
}
