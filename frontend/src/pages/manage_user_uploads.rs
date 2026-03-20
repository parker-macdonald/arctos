use crate::api;
use crate::types::UserUploadedCameraRow;
use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn ManageUserUploads(url: String) -> Element {
    let mut query = use_signal(|| String::new());
    let mut refresh = use_signal(|| 0u32);
    let mut delete_error = use_signal(|| None::<String>);

    let url_for_data = url.clone();
    let data = use_resource(move || {
        let u = url_for_data.clone();
        let _ = refresh();
        async move {
            let tournament = api::tournament_detail(&u).await.map_err(|e| e.to_string())?;
            let cams = api::user_uploaded_cameras_list(&u)
                .await
                .map_err(|e| e.to_string())?;
            Ok::<(String, Vec<UserUploadedCameraRow>), String>((tournament.tournament.name, cams.cameras))
        }
    });
    let val = data.value();

    rsx! {
        if let Some(Ok((tournament_name, cameras))) = val.read().as_ref() {
            div { class: "row",
                div { class: "col-12",
                    h1 { "{tournament_name} - Manage User Uploaded Videos" }
                    nav { aria_label: "breadcrumb",
                        ol { class: "breadcrumb",
                            li { class: "breadcrumb-item", Link { to: Route::TournamentHome { url: url.clone() }, "{tournament_name}" } }
                            li { class: "breadcrumb-item active", "Manage User Uploaded Videos" }
                        }
                    }
                }
            }

            div { class: "row mb-3",
                div { class: "col-md-8",
                    input {
                        class: "form-control",
                        r#type: "text",
                        placeholder: "Search match, field, camera, status, user, timestamp",
                        value: "{query}",
                        oninput: move |e| query.set(e.value()),
                    }
                }
            }

            if let Some(err) = delete_error() {
                div { class: "alert alert-danger", "{err}" }
            }

            div { class: "row",
                div { class: "col-12",
                    div { class: "card",
                        div { class: "card-body",
                            div { class: "table-responsive",
                                table { class: "table table-striped align-middle",
                                    thead {
                                        tr {
                                            th { "Match" }
                                            th { "Field" }
                                            th { "Camera" }
                                            th { "Status" }
                                            th { "User" }
                                            th { "World Start Timestamp" }
                                            th { "" }
                                        }
                                    }
                                    tbody {
                                        for cam in cameras.iter().filter(|cam| {
                                            let q = query().to_lowercase();
                                            if q.is_empty() {
                                                return true;
                                            }
                                            let hay = format!(
                                                "{} {} {} {} {} {}",
                                                cam.match_name,
                                                cam.field_name,
                                                cam.camera_name,
                                                cam.status,
                                                cam.user.clone().unwrap_or_default(),
                                                cam.world_start_timestamp.clone().unwrap_or_default(),
                                            )
                                            .to_lowercase();
                                            hay.contains(&q)
                                        }) {
                                            tr { key: "{cam.uuid}",
                                                td { "{cam.match_name}" }
                                                td { "{cam.field_name}" }
                                                td { "{cam.camera_name}" }
                                                td { "{cam.status}" }
                                                td { "{cam.user.clone().unwrap_or_else(|| \"-\".to_string())}" }
                                                td { "{cam.world_start_timestamp.clone().unwrap_or_else(|| \"-\".to_string())}" }
                                                td {
                                                    button {
                                                        class: "btn btn-sm btn-outline-danger",
                                                        onclick: {
                                                            let u = url.clone();
                                                            let uuid = cam.uuid.clone();
                                                            let mut delete_error_sig = delete_error;
                                                            let mut refresh_sig = refresh;
                                                            move |_| {
                                                                delete_error_sig.set(None);
                                                                let u = u.clone();
                                                                let uuid = uuid.clone();
                                                                let mut delete_error_sig = delete_error_sig;
                                                                let mut refresh_sig = refresh_sig;
                                                                spawn(async move {
                                                                    match api::delete_user_uploaded_camera(&u, &uuid).await {
                                                                        Ok(()) => refresh_sig.set(refresh_sig() + 1),
                                                                        Err(e) => delete_error_sig.set(Some(e)),
                                                                    }
                                                                });
                                                            }
                                                        },
                                                        "Delete"
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
            p { class: "text-muted", "Loading..." }
        }
    }
}
