use crate::api;
use dioxus::prelude::*;

#[component]
pub fn NewTournament() -> Element {
    let backend_url = api::base_url();
    let create_url = format!("{}/create-tournament", backend_url);

    rsx! {
        div { class: "row justify-content-center",
            div { class: "col-md-8",
                div { class: "card",
                    div { class: "card-header",
                        h3 { class: "mb-0", "Create New Tournament" }
                    }
                    div { class: "card-body",
                        form { method: "POST", action: "{create_url}",
                            div { class: "mb-3",
                                label { r#for: "name", class: "form-label", "Tournament Name" }
                                input { r#type: "text", class: "form-control", id: "name", name: "name", required: true }
                            }
                            div { class: "mb-3",
                                label { r#for: "url", class: "form-label", "URL Slug" }
                                input { r#type: "text", class: "form-control", id: "url", name: "url", required: true }
                                div { class: "form-text", "This will be used in the URL (e.g., /my-tournament)" }
                            }
                            div { class: "mb-3",
                                label { r#for: "permission_key", class: "form-label", "Permission Key" }
                                input { r#type: "text", class: "form-control", id: "permission_key", name: "permission_key", required: true }
                                div { class: "form-text",
                                    strong { "Required:" }
                                    " A permission key is required to create a tournament. This helps limit tournament creation. Please contact reid [at] xz [dot] ax to request a permission key for your tournament URL slug."
                                }
                            }
                            div { class: "d-grid",
                                button { r#type: "submit", class: "btn btn-primary", "Create Tournament" }
                            }
                        }
                    }
                }
            }
        }
    }
}
