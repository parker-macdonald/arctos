use crate::api;
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn PlayersList() -> Element {
    let mut search = use_signal(|| String::new());
    let mut page = use_signal(|| 1u32);
    let data = use_resource(move || {
        let s = search().clone();
        let p = page();
        async move { api::players_list(&s, p).await.map_err(|e| e.to_string()) }
    });
    let val = data.value();
    rsx! {
        h1 { "Players" }
        input {
            r#type: "text",
            placeholder: "Search",
            value: "{search()}",
            oninput: move |ev| {
                search.set(ev.value().clone());
                page.set(1);
            },
        }
        if let Some(Ok(d)) = val.read().as_ref() {
            ul { class: "players-list",
                for p in d.players.iter() {
                    li { key: "{p.id}",
                        Link { to: Route::PlayerProfile { id: p.id.clone() }, "{p.name}" }
                    }
                }
            }
            p { "Page {d.page} of {d.total_pages} ({d.total} total)" }
            if d.page > 1 {
                button {
                    onclick: move |_| page.set(page().saturating_sub(1)),
                    "Previous"
                }
            }
            if d.page < d.total_pages {
                button {
                    onclick: move |_| page.set(page() + 1),
                    "Next"
                }
            }
        } else if let Some(Err(e)) = val.read().as_ref() {
            p { class: "error", "{e}" }
        } else {
            p { "Loading…" }
        }
    }
}
