use dioxus::prelude::*;

#[component]
pub fn SideCompDetail(url: String, comp_id: i32) -> Element {
    rsx! { div { class: "container my-4", "TBD: SideCompDetail for {url} / {comp_id}" } }
}
