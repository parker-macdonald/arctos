use crate::api;
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn TeamProfile(id: String) -> Element {
    let id = id.clone();
    let data = use_resource(move || {
        let i = id.clone();
        async move { api::team_profile(&i).await.map_err(|e| e.to_string()) }
    });
    let val = data.value();
    rsx! {
        if let Some(Ok(d)) = val.read().as_ref() {
            h1 { "{d.team.name}" }
            Link { to: Route::TeamsList {}, "← Teams" }
            if let Some(photo) = &d.team.profile_photo {
                p { "Photo: {photo}" }
            }
            h3 { "Registrations" }
            ul {
                for r in d.registrations.iter() {
                    {
                        let line = format!(
                            "{}{}",
                            r.event,
                            r.pseudonym.as_ref().map(|p| format!(" — {}", p)).unwrap_or_default()
                        );
                        rsx! { li { key: "{r.event}", "{line}" } }
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
