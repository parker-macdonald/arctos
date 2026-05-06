use dioxus::prelude::*;

#[component]
pub fn SideCompCheckin(url: String, comp_id: i32) -> Element {
    rsx! { div { class: "container my-4", "TBD: SideCompCheckin for {url} / {comp_id}" } }
}
