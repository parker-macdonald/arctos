use crate::api;
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn TeamsList() -> Element {
    let mut search = use_signal(|| String::new());
    let data = use_resource(move || {
        let s = search().clone();
        async move { api::teams_list(&s).await.map_err(|e| e.to_string()) }
    });
    let val = data.value();
    rsx! {
        h1 { "Teams" }
        input {
            r#type: "text",
            placeholder: "Search",
            value: "{search()}",
            oninput: move |ev| search.set(ev.value().clone()),
        }
        if let Some(Ok(d)) = val.read().as_ref() {
            ul { class: "teams-list",
                for t in d.teams.iter() {
                    li { key: "{t.id}",
                        Link { to: Route::TeamProfile { id: t.id.clone() }, "{t.name}" }
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
