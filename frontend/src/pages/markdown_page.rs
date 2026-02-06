use crate::api;
use dioxus::prelude::*;
use pulldown_cmark::{Options, Parser};

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
pub fn MarkdownPage(slug: String) -> Element {
    let slug_for_data = slug.clone();
    let data = use_resource(move || {
        let s = slug_for_data.clone();
        async move { api::markdown_page(&s).await.map_err(|e| e.to_string()) }
    });
    let val = data.value();

    rsx! {
        if let Some(Ok(d)) = val.read().as_ref() {
            {
                let html = markdown_to_html(&d.markdown);
                rsx! {
                    div { class: "row",
                        div { class: "col-lg-10 mx-auto",
                            h1 { "{d.title}" }
                            div { class: "markdown-content card card-body",
                                dangerous_inner_html: "{html}"
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
