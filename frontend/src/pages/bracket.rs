use crate::api;
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn Bracket(url: String) -> Element {
    let url_for_data = url.clone();
    let data = use_resource(move || {
        let u = url_for_data.clone();
        async move { api::tournament_bracket(&u).await.map_err(|e| e.to_string()) }
    });
    let val = data.value();
    let backend = api::base_url();
    rsx! {
        if let Some(Ok(d)) = val.read().as_ref() {
            div { class: "row",
                div { class: "col-12",
                    h1 { "{d.tournament.name} - Bracket" }
                    Link { to: Route::TournamentHome { url: url.clone() }, class: "btn btn-outline-secondary mb-3", "Back to Tournament" }
                }
            }

            for bracket in d.brackets.iter() {
                div { class: "row mb-5", key: "{bracket.name}",
                    div { class: "col-12",
                        div { class: "card",
                            div { class: "card-header",
                                h3 { class: "mb-0", "{bracket.name}" }
                            }
                            div { class: "card-body",
                                div { class: "position-relative", style: "display: inline-block;",
                                    img { src: "{backend}/static/{bracket.image}", alt: "{bracket.name}", class: "img-fluid", style: "max-width: none; height: none;" }
                                    for team_entry in bracket.teams.iter() {
                                        if let Some(team_info) = &team_entry.team_info {
                                            {
                                                let mut style_parts = vec![format!("position: absolute")];
                                                let mut transform_parts: Vec<String> = vec![];
                                                if team_entry.halign == "left" {
                                                    style_parts.push(format!("left: {}px", team_entry.x));
                                                } else if team_entry.halign == "right" {
                                                    style_parts.push(format!("left: {}px", team_entry.x));
                                                    transform_parts.push("translateX(-100%)".to_string());
                                                } else {
                                                    style_parts.push(format!("left: {}px", team_entry.x));
                                                    transform_parts.push("translateX(-50%)".to_string());
                                                }
                                                if team_entry.valign == "top" {
                                                    style_parts.push(format!("top: {}px", team_entry.y));
                                                } else if team_entry.valign == "bottom" {
                                                    style_parts.push(format!("top: {}px", team_entry.y));
                                                    transform_parts.push("translateY(-100%)".to_string());
                                                } else {
                                                    style_parts.push(format!("top: {}px", team_entry.y));
                                                    transform_parts.push("translateY(-50%)".to_string());
                                                }
                                                if !transform_parts.is_empty() {
                                                    style_parts.push(format!("transform: {}", transform_parts.join(" ")));
                                                }
                                                style_parts.push(format!("font-size: {}px", team_entry.size));
                                                style_parts.push("line-height: 1.2".to_string());
                                                let style_str = style_parts.join("; ");
                                                let match_ref = team_entry.match_name.clone().unwrap_or_default();
                                                rsx! {
                                                    div { class: "bracket-team-overlay", style: "{style_str}",
                                                        if team_entry.is_tag {
                                                            span { "{team_info.display_text}" }
                                                        } else if let Some(team_id) = &team_info.id {
                                                            Link { to: Route::TeamProfilePage { id: team_id.clone() }, class: "text-decoration-none text-dark d-inline-flex align-items-center",
                                                                if let Some(photo) = &team_info.profile_photo {
                                                                    img { src: "{backend}/static/{photo}", alt: "{team_info.pseudonym.as_deref().unwrap_or(&team_info.display_text)}", class: "rounded-circle me-1", style: "width: {team_entry.size}px; height: {team_entry.size}px; object-fit: cover;" }
                                                                }
                                                                span { "{team_info.pseudonym.as_deref().unwrap_or(&team_info.display_text)}" }
                                                            }
                                                        } else if team_entry.is_reference {
                                                            a { href: "/{url}/match?name={match_ref}", class: "text-decoration-none text-dark",
                                                                {team_info.display_text.replace("::", " ")}
                                                            }
                                                        } else {
                                                            span { "{team_info.display_text}" }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            style { r#"
            .bracket-team-overlay {{
                white-space: nowrap;
                z-index: 10;
            }}
            .bracket-team-overlay a {{
                display: inline-flex;
                align-items: center;
            }}
            .bracket-team-overlay img {{
                flex-shrink: 0;
            }}
            "# }
        } else if let Some(Err(e)) = val.read().as_ref() {
            p { class: "text-danger", "{e}" }
        } else {
            p { "Loading…" }
        }
    }
}
