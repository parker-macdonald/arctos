use crate::api;
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn PlayerProfile(id: String) -> Element {
    let id = id.clone();
    let data = use_resource(move || {
        let i = id.clone();
        async move { api::player_profile(&i).await.map_err(|e| e.to_string()) }
    });
    let val = data.value();
    rsx! {
        if let Some(Ok(d)) = val.read().as_ref() {
            h1 { "{d.player.name}" }
            Link { to: Route::PlayersList {}, "← Players" }
            if let Some(photo) = &d.player.profile_photo {
                p { "Photo: {photo}" }
            }
            if let Some(loc) = &d.player.location {
                p { "Location: {loc}" }
            }
            if let Some(bio) = &d.player.bio {
                p { "{bio}" }
            }
            h3 { "Registrations" }
            ul {
                for r in d.registrations.iter() {
                    li { key: "{r.event}-{r.team.as_deref().unwrap_or(\"\")}",
                        "{r.event} — {r.team.as_deref().unwrap_or(\"unattached\")} ({r.status})"
                    }
                }
            }
        } else if let Some(Err(e)) = val.read().as_ref() {
            p { class: "error", "{e}" }
        } else {
            p { "Loading…" }
        }
    }
}
