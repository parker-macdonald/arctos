use crate::api;
use crate::Route;
use dioxus::prelude::*;

fn get_query_param(name: &str) -> Option<String> {
    #[cfg(target_arch = "wasm32")]
    {
        let window = web_sys::window()?;
        let search = window.location().search().ok()?;
        let params = web_sys::UrlSearchParams::new_with_str(&search).ok()?;
        params.get(name)
    }
    #[cfg(not(target_arch = "wasm32"))]
    {
        let _ = name;
        None
    }
}

#[component]
pub fn MatchPage(url: String) -> Element {
    let url_for_resource = url.clone();
    let match_id = get_query_param("id");
    let match_name = get_query_param("name");
    let id_for_resource = match_id.clone();
    let name_for_resource = match_name.clone();
    let data = use_resource(move || {
        let u = url_for_resource.clone();
        let id = id_for_resource.clone();
        let name = name_for_resource.clone();
        async move {
            if id.is_some() || name.is_some() {
                api::match_detail(&u, id.as_deref(), name.as_deref())
                    .await
                    .map_err(|e| e.to_string())
            } else {
                Err("id or name query param required".to_string())
            }
        }
    });
    let val = data.value();
    rsx! {
        if let Some(Ok(d)) = val.read().as_ref() {
            h1 { "Match: {d.match_data.name}" }
            Link { to: Route::Schedule { url: url.clone() }, "← Schedule" }
            p { "Field: {d.match_data.field.as_deref().unwrap_or(\"-\")}" }
            p { "{d.match_data.team1_name} vs {d.match_data.team2_name}" }
            p { "Status: {d.match_data.status}" }
            if let Some(w) = &d.match_data.match_winner {
                p { "Winner: {w}" }
            }
            h3 { "Points" }
            ul {
                for pt in d.points.iter() {
                    li { key: "{pt.uuid}",
                        "Set {pt.set_number.unwrap_or(0)} — {pt.winner.as_deref().unwrap_or(\"-\")}"
                    }
                }
            }
        } else if let Some(Err(e)) = val.read().as_ref() {
            p { class: "error", "{e}" }
        } else if get_query_param("id").is_none() && get_query_param("name").is_none() {
            p { "Add ?id=... or ?name=... to the URL" }
        } else {
            p { "Loading…" }
        }
    }
}
