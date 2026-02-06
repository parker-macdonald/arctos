use crate::api;
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn Invitations(url: String) -> Element {
    let url_for_data = url.clone();
    let data = use_resource(move || {
        let u = url_for_data.clone();
        async move { api::tournament_invitations(&u).await.map_err(|e| e.to_string()) }
    });
    let val = data.value();
    let backend = api::base_url();
    rsx! {
        if let Some(Ok(d)) = val.read().as_ref() {
            div { class: "row",
                div { class: "col-12",
                    h1 { "{d.tournament.name} - {d.team_registration.pseudonym} Roster" }
                    nav { aria_label: "breadcrumb",
                        ol { class: "breadcrumb",
                            li { class: "breadcrumb-item", Link { to: Route::TournamentHome { url: url.clone() }, "{d.tournament.name}" } }
                            li { class: "breadcrumb-item active", "Roster" }
                        }
                    }
                }
            }

            div { class: "row",
                div { class: "col-12",
                    div { class: "card",
                        div { class: "card-header",
                            h5 { class: "mb-0", "Pending Player Requests" }
                        }
                        div { class: "card-body",
                            if d.invitations.is_empty() {
                                p { class: "text-muted", "No pending requests." }
                            } else {
                                div { class: "alert alert-info",
                                    strong { "Current Team Size: " }
                                    "{d.current_team_size}"
                                    if let Some(max) = d.tournament.max_team_size_roster {
                                        " / {max} (max)"
                                    }
                                }
                                div { class: "table-responsive",
                                    table { class: "table table-striped",
                                        thead {
                                            tr {
                                                th { "Player" }
                                                th { "Jersey Name" }
                                                th { "Jersey Number" }
                                                th { "Actions" }
                                            }
                                        }
                                        tbody {
                                            for invitation in d.invitations.iter() {
                                                {
                                                    let accept_url = format!(
                                                        "{}/{}/invitation/{}/accept",
                                                        backend, url, invitation.registration.id
                                                    );
                                                    let decline_url = format!(
                                                        "{}/{}/invitation/{}/decline",
                                                        backend, url, invitation.registration.id
                                                    );
                                                    rsx! {
                                                        tr { key: "{invitation.registration.id}",
                                                            td {
                                                                div { class: "d-flex align-items-center",
                                                                    div { class: "flex-shrink-0 me-2",
                                                                        if let Some(photo) = &invitation.player.profile_photo {
                                                                            img { src: "{backend}/static/{photo}", alt: "{invitation.player.name}", class: "rounded-circle", style: "width: 40px; height: 40px; object-fit: cover;" }
                                                                        } else {
                                                                            div { class: "d-flex align-items-center justify-content-center bg-secondary rounded-circle", style: "width: 40px; height: 40px;",
                                                                                i { class: "fas fa-user text-white" }
                                                                            }
                                                                        }
                                                                    }
                                                                    div { class: "flex-grow-1",
                                                                        Link { to: Route::PlayerProfile { id: invitation.player.id.clone() }, "{invitation.player.name}" }
                                                                    }
                                                                }
                                                            }
                                                            td { "{invitation.registration.jersey_name.as_deref().unwrap_or(\"N/A\")}" }
                                                            td { "{invitation.registration.jersey_number.as_deref().unwrap_or(\"N/A\")}" }
                                                            td {
                                                                div { class: "btn-group", role: "group",
                                                                    form { method: "POST", action: "{accept_url}", style: "display: inline;",
                                                                        button {
                                                                            r#type: "submit",
                                                                            class: "btn btn-success btn-sm",
                                                                            disabled: d.tournament.max_team_size_roster.map(|max| d.current_team_size >= max).unwrap_or(false),
                                                                            "Accept"
                                                                        }
                                                                    }
                                                                    form { method: "POST", action: "{decline_url}", style: "display: inline;",
                                                                        button { r#type: "submit", class: "btn btn-danger btn-sm", "Decline" }
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
                    }

                    if !d.team_roster.is_empty() {
                        div { class: "card mt-3",
                            div { class: "card-header",
                                h5 { class: "mb-0", "Team Roster" }
                            }
                            div { class: "card-body",
                                div { class: "table-responsive",
                                    table { class: "table table-striped",
                                        thead {
                                            tr {
                                                th { "Player" }
                                                th { "Jersey Name" }
                                                th { "Jersey Number" }
                                                th { "Status" }
                                                th { "Payment" }
                                            }
                                        }
                                        tbody {
                                            for roster_item in d.team_roster.iter() {
                                                tr { key: "{roster_item.registration.id}",
                                                    td {
                                                        div { class: "d-flex align-items-center",
                                                            div { class: "flex-shrink-0 me-2",
                                                                if let Some(photo) = &roster_item.player.profile_photo {
                                                                    img { src: "{backend}/static/{photo}", alt: "{roster_item.player.name}", class: "rounded-circle", style: "width: 40px; height: 40px; object-fit: cover;" }
                                                                } else {
                                                                    div { class: "d-flex align-items-center justify-content-center bg-secondary rounded-circle", style: "width: 40px; height: 40px;",
                                                                        i { class: "fas fa-user text-white" }
                                                                    }
                                                                }
                                                            }
                                                            div { class: "flex-grow-1",
                                                                Link { to: Route::PlayerProfile { id: roster_item.player.id.clone() }, "{roster_item.player.name}" }
                                                            }
                                                        }
                                                    }
                                                    td { "{roster_item.registration.jersey_name.as_deref().unwrap_or(\"N/A\")}" }
                                                    td { "{roster_item.registration.jersey_number.as_deref().unwrap_or(\"N/A\")}" }
                                                    td {
                                                        match roster_item.registration.status.as_str() {
                                                            "CONFIRMED" => rsx! { span { class: "badge bg-success", "Confirmed" } },
                                                            "PENDING_TEAM_APPROVAL" => rsx! { span { class: "badge bg-warning", "Pending Approval" } },
                                                            "REJECTED" => rsx! { span { class: "badge bg-danger", "Rejected" } },
                                                            "CANCELLED" => rsx! { span { class: "badge bg-secondary", "Cancelled" } },
                                                            _ => rsx! { span { class: "badge bg-secondary", "{roster_item.registration.status}" } },
                                                        }
                                                    }
                                                    td {
                                                        if roster_item.registration.paid {
                                                            span { class: "badge bg-success", "Paid" }
                                                            if roster_item.registration.amount_paid > 0.0 {
                                                                {
                                                                    let paid_amount = format!("${:.2}", roster_item.registration.amount_paid);
                                                                    rsx! { small { class: "text-muted ms-1", "{paid_amount}" } }
                                                                }
                                                            }
                                                        } else {
                                                            span { class: "badge bg-warning", "Unpaid" }
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
        } else if let Some(Err(e)) = val.read().as_ref() {
            p { class: "text-danger", "{e}" }
        } else {
            p { "Loading…" }
        }
    }
}
