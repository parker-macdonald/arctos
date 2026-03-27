use crate::Route;
use dioxus::prelude::*;

#[component]
pub fn CreateEvent() -> Element {
    rsx! {
        div { class: "row justify-content-center",
            div { class: "col-lg-10",
                div { class: "row g-4",
                    div { class: "col-md-6",
                        div { class: "card h-100",
                            div { class: "card-body d-flex flex-column",
                                h5 { class: "card-title", "Tournament" }
                                p { class: "card-text flex-grow-1 text-muted",
                                    "A single event with a schedule, bracket, and results. Use this for a one-day or one-weekend tournament that is not part of a league."
                                }
                                Link {
                                    to: Route::NewTournament {},
                                    class: "btn btn-primary align-self-start",
                                    "Create tournament"
                                }
                            }
                        }
                    }
                    div { class: "col-md-6",
                        div { class: "card h-100",
                            div { class: "card-body d-flex flex-column",
                                h5 { class: "card-title", "League" }
                                p { class: "card-text flex-grow-1 text-muted",
                                    "A league (season) that can contain multiple tournaments. Use this when you run a series of events (e.g. CJL 2025) and want a shared registration, standings, and organizers."
                                }
                                Link {
                                    to: Route::NewLeague {},
                                    class: "btn btn-primary align-self-start",
                                    "Create league"
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
