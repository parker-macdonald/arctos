use dioxus::prelude::*;
use pulldown_cmark::{Options, Parser};

const DOCS_MD: &str = include_str!("../../../docs/docs.md");

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
pub fn Docs() -> Element {
    let html = markdown_to_html(DOCS_MD);
    rsx! {
        div { class: "row",
            div { class: "col-lg-10 mx-auto",
                h1 { "User Documentation" }
                div { class: "markdown-content card card-body",
                    dangerous_inner_html: "{html}"
                }
            }
        }
    }
}
