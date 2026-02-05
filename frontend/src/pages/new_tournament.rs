use crate::api;
use dioxus::prelude::*;

#[component]
pub fn NewTournament() -> Element {
    let backend_url = api::base_url();
    let create_url = format!("{}/new-tournament", backend_url);

    rsx! {
        div { class: "row",
            div { class: "col-lg-8 mx-auto",
                h1 { "Create Tournament" }
                p { class: "lead",
                    "Use the tournament creation form on the server to create a new tournament."
                }
                a { href: "{create_url}", class: "btn btn-primary", "Open Create Tournament form" }
            }
        }
    }
}
