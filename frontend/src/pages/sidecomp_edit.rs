use dioxus::prelude::*;

#[component]
pub fn SideCompEdit(url: String, comp_id: i32) -> Element {
    rsx! { div { class: "container my-4", "TBD: SideCompEdit for {url} / {comp_id}" } }
}
