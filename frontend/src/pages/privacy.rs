use dioxus::prelude::*;
use pulldown_cmark::{Options, Parser};

const PRIVACY_MD: &str = include_str!("../../../docs/privacy-policy.md");

fn markdown_to_html(md: &str) -> String {
    let mut options = Options::empty();
    options.insert(Options::ENABLE_STRIKETHROUGH);
    options.insert(Options::ENABLE_TABLES);
    let parser = Parser::new_ext(md, options);
    let mut html = String::new();
    pulldown_cmark::html::push_html(&mut html, parser);
    html
}

#[component]
pub fn Privacy() -> Element {
    let html = markdown_to_html(PRIVACY_MD);
    rsx! {
        div { class: "row",
            div { class: "col-lg-8 mx-auto",
                h1 { "Privacy Policy" }
                div { class: "markdown-content card card-body",
                    dangerous_inner_html: "{html}"
                }
            }
        }
    }
}
