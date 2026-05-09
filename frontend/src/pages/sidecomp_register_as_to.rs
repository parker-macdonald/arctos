use crate::api;
use crate::types::EligiblePlayer;
use crate::Route;
use dioxus::prelude::*;

#[derive(Clone, Debug, PartialEq)]
struct LogEntry {
    player_id: String,
    player_name: String,
}

#[component]
pub fn SideCompRegisterAsTo(url: String, comp_id: i32) -> Element {
    let mut eligible = use_signal(Vec::<EligiblePlayer>::new);
    let mut filter = use_signal(String::new);
    let mut session_log = use_signal(Vec::<LogEntry>::new);
    let mut error = use_signal(|| None::<String>);

    use_effect(move || {
        spawn(async move {
            match api::sidecomp_eligible_players(comp_id).await {
                Ok(rows) => eligible.set(rows),
                Err(e) => error.set(Some(e)),
            }
        });
    });

    let url_for_back = url.clone();

    rsx! {
        div { class: "row",
            div { class: "col-12",
                Link {
                    to: Route::SideCompDetail { url: url_for_back, comp_id },
                    class: "btn btn-link",
                    "<- Back to side competition"
                }
                h1 { "Quick Register players" }
                input {
                    class: "form-control mb-3",
                    r#type: "text",
                    placeholder: "Filter by name...",
                    value: "{filter}",
                    oninput: move |evt| filter.set(evt.value()),
                }
                if let Some(err) = error() {
                    div { class: "alert alert-danger", "{err}" }
                }
                {
                    let q = filter().to_lowercase();
                    let rows: Vec<EligiblePlayer> = eligible()
                        .into_iter()
                        .filter(|p| q.is_empty() || p.player_name.to_lowercase().contains(&q))
                        .collect();
                    rsx! {
                        if rows.is_empty() {
                            p { class: "text-muted", "No eligible players found." }
                        } else {
                            ul { class: "list-group mb-4",
                                for p in rows.iter().cloned() {
                                    EligibleRow {
                                        key: "{p.player_id}",
                                        p: p.clone(),
                                        comp_id,
                                        on_registered: move |entry: LogEntry| {
                                            let pid = entry.player_id.clone();
                                            session_log.write().insert(0, entry);
                                            eligible.write().retain(|x| x.player_id != pid);
                                        },
                                        on_error: move |e| error.set(Some(e)),
                                    }
                                }
                            }
                        }
                    }
                }
                h2 { "Session log ({session_log().len()})" }
                if session_log().is_empty() {
                    p { class: "text-muted", "No one registered yet." }
                } else {
                    ul { class: "list-group",
                        for entry in session_log().iter() {
                            li { class: "list-group-item", "{entry.player_name} (registered)" }
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn EligibleRow(
    p: EligiblePlayer,
    comp_id: i32,
    on_registered: EventHandler<LogEntry>,
    on_error: EventHandler<String>,
) -> Element {
    let mut busy = use_signal(|| false);
    let p_render = p.clone();
    let p_click = p.clone();

    rsx! {
        li { class: "list-group-item d-flex justify-content-between align-items-center",
            div {
                strong { "{p_render.player_name}" }
                if let Some(team) = p_render.team_pseudonym.as_ref() {
                    span { class: "text-muted ms-2", "({team})" }
                }
            }
            button {
                class: "btn btn-sm btn-primary",
                disabled: busy(),
                onclick: move |_| {
                    let pid = p_click.player_id.clone();
                    let pname = p_click.player_name.clone();
                    busy.set(true);
                    spawn(async move {
                        match api::sidecomp_to_register_player_as_to(comp_id, &pid).await {
                            Ok(_) => on_registered.call(LogEntry { player_id: pid, player_name: pname }),
                            Err(e) => on_error.call(e),
                        }
                        busy.set(false);
                    });
                },
                if busy() { "Registering..." } else { "Quick Register" }
            }
        }
    }
}
