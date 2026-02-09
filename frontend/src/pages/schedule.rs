use crate::api;
use crate::types::*;
use crate::Route;
use dioxus::html::ModifiersInteraction;
use dioxus::prelude::*;
use serde::Serialize;
use std::cell::RefCell;
use std::rc::Rc;
use super::TeamTokenInput;
#[cfg(target_arch = "wasm32")]
use wasm_bindgen::JsCast as _;

/// CSS for schedule page: timeline layout and team-token inputs (used by modals in both table and timeline view).
const SCHEDULE_PAGE_CSS: &str = include_str!("schedule_timeline.css");

#[component]
pub fn Schedule(url: String) -> Element {
    let url_data = url.clone();
    let mut setup_data = use_resource(move || {
        let u = url_data.clone();
        async move { api::schedule_setup(&u).await }
    });

    let mut view_mode = use_signal(|| "timeline".to_string());
    let mut edit_mode = use_signal(|| false);
    let mut selected_field = use_signal(|| "all".to_string());
    let mut highlight_team = use_signal(|| "".to_string());
    
    let mut is_to = use_signal(|| false);
    
    let mut active_modal = use_signal(|| "none".to_string());
    let mut selected_match_id = use_signal(|| "".to_string());
    let mut key_nav = use_signal(|| None::<String>);
    let refresh_trigger = use_signal(|| 0u32);

    use_effect(move || {
        if let Some(Ok(data)) = setup_data.value().read().as_ref() {
            is_to.set(data.is_to);
        }
    });

    use_effect(move || {
        if refresh_trigger() > 0 {
            setup_data.restart();
        }
    });

    // Refocus the schedule container when a modal closes so keyboard shortcuts work without a click
    use_effect(move || {
        let _ = active_modal();
        #[cfg(target_arch = "wasm32")]
        if active_modal() == "none" {
            spawn(async move {
                gloo_timers::future::TimeoutFuture::new(0).await;
                if let Some(window) = web_sys::window() {
                    if let Some(doc) = window.document() {
                        if let Ok(Some(el)) = doc.query_selector(".schedule-keyboard-focus") {
                            if let Some(html_el) = el.dyn_ref::<web_sys::HtmlElement>() {
                                let _ = html_el.focus();
                            }
                        }
                    }
                }
            });
        }
    });

    let refresh = move || {
        let mut setup_data = setup_data;
        setup_data.restart();
    };

    let val = setup_data.value();
    let data_opt = val.read().as_ref().and_then(|r| r.as_ref().ok().cloned());

    match data_opt {
        Some(data) => {
            let is_to = data.is_to;
            let url_for_export = url.clone();
            let url_for_recompute = url.clone();
            let handle_keydown = move |ev: Event<KeyboardData>| {
                let key_str = ev.key().to_string();
                let modal_open = active_modal() != "none";
                if modal_open {
                    // When a modal is open, only handle Escape to close it; let all other keys go to modal inputs
                    if key_str == "Escape" {
                        ev.prevent_default();
                        active_modal.set("none".to_string());
                    }
                    return;
                }
                if key_str == "Escape" {
                    ev.prevent_default();
                    active_modal.set("none".to_string());
                } else {
                    match key_str.as_str() {
                        "n" | "N" => {
                            ev.prevent_default();
                            if view_mode() == "timeline" {
                                key_nav.set(Some("next".to_string()));
                            }
                        }
                        "p" | "P" => {
                            ev.prevent_default();
                            if view_mode() == "timeline" {
                                key_nav.set(Some("prev".to_string()));
                            }
                        }
                        "t" | "T" => {
                            ev.prevent_default();
                            if view_mode() == "timeline" {
                                key_nav.set(Some("today".to_string()));
                            }
                        }
                        "e" | "E" => {
                            ev.prevent_default();
                            if is_to {
                                edit_mode.set(!edit_mode());
                            }
                        }
                        _ => {}
                    }
                }
            };

             rsx! {
                style { {SCHEDULE_PAGE_CSS} }
                div {
                    class: "container-fluid mt-3 position-relative schedule-keyboard-focus",
                    tabindex: 0,
                    onkeydown: handle_keydown,
                    onmounted: move |ev| {
                        spawn(async move {
                            let _ = ev.data().set_focus(true).await;
                        });
                    },
                    role: "application",
                    aria_label: "Schedule",
                    div { class: "row mb-3",
                        div { class: "col",
                            h1 { "{data.tournament.name}" }
                            nav { "aria-label": "breadcrumb",
                                ol { class: "breadcrumb",
                                    li { class: "breadcrumb-item",
                                        Link { to: Route::TournamentHome { url: url.clone() }, "{data.tournament.name}" }
                                    }
                                    li { class: "breadcrumb-item active", "Schedule" }
                                }
                            }
                        }
                    }

                    div { class: "card mb-3 bg-light",
                        div { class: "card-body p-2",
                            div { class: "d-flex flex-wrap justify-content-between align-items-center gap-2",
                                div { class: "d-flex flex-wrap align-items-center gap-2",
                                    select {
                                        class: "form-select form-select-sm d-inline-block w-auto",
                                        value: "{selected_field}",
                                        onchange: move |e| selected_field.set(e.value()),
                                        option { value: "all", "All Fields" }
                                        for f in &data.fields {
                                            option { value: "{f.id}", "{f.name}" }
                                        }
                                    }
                                    input {
                                        class: "form-control form-control-sm d-inline-block",
                                        style: "width: 10rem;",
                                        placeholder: "Highlight Team...",
                                        value: "{highlight_team}",
                                        oninput: move |e| highlight_team.set(e.value())
                                    }
                                    div { class: "btn-group btn-group-sm",
                                        button {
                                            class: if view_mode() == "timeline" { "btn btn-primary" } else { "btn btn-outline-primary" },
                                            onclick: move |_| view_mode.set("timeline".to_string()),
                                            "Timeline"
                                        }
                                        button {
                                            class: if view_mode() == "table" { "btn btn-primary" } else { "btn btn-outline-primary" },
                                            onclick: move |_| view_mode.set("table".to_string()),
                                            "Table"
                                        }
                                    }
                                }
                                if data.is_to {
                                    div { class: "d-flex flex-wrap align-items-center gap-1",
                                        if edit_mode() {
                                            button { class: "btn btn-sm btn-outline-secondary", onclick: move |_| active_modal.set("tags".to_string()), "Tags" }
                                            button { class: "btn btn-sm btn-outline-secondary", onclick: move |_| active_modal.set("fields".to_string()), "Fields" }
                                            button { class: "btn btn-sm btn-outline-success", onclick: move |_| active_modal.set("match_create".to_string()), "+ Match" }
                                            button { class: "btn btn-sm btn-outline-secondary", onclick: move |_| {
                                                let u = url_for_export.clone();
                                                spawn(async move {
                                                    if let Ok(res) = api::export_schedule(&u).await {
                                                        #[cfg(target_arch = "wasm32")]
                                                        if let Some(window) = web_sys::window() {
                                                            let doc = window.document().expect("document");
                                                            let bytes = res.toml.as_bytes();
                                                            let arr = js_sys::Uint8Array::new_from_slice(bytes);
                                                            let parts = js_sys::Array::new();
                                                            parts.push(&arr);
                                                            let blob_opts = web_sys::BlobPropertyBag::new();
                                                            blob_opts.set_type("application/toml");
                                                            let blob = web_sys::Blob::new_with_u8_array_sequence_and_options(
                                                                &parts.into(),
                                                                &blob_opts,
                                                            ).expect("Blob");
                                                            let url = web_sys::Url::create_object_url_with_blob(&blob).expect("object URL");
                                                            let filename = format!(
                                                                "{}_schedule_{}.toml",
                                                                u,
                                                                chrono::Utc::now().format("%Y%m%d_%H%M%S")
                                                            );
                                                            if let Ok(a) = doc.create_element("a") {
                                                                let _ = a.set_attribute("href", &url);
                                                                let _ = a.set_attribute("download", &filename);
                                                                if let Some(anchor) = a.dyn_ref::<web_sys::HtmlAnchorElement>() {
                                                                    anchor.click();
                                                                }
                                                            }
                                                            web_sys::Url::revoke_object_url(&url).ok();
                                                        }
                                                    }
                                                });
                                            }, "Export TOML" }
                                            button { class: "btn btn-sm btn-outline-secondary", onclick: move |_| active_modal.set("toml_import".to_string()), "Import TOML" }
                                            button {
                                                class: "btn btn-sm btn-outline-primary",
                                                onclick: move |_| {
                                                    let u = url_for_recompute.clone();
                                                    let mut trigger = refresh_trigger;
                                                    spawn(async move {
                                                        if let Ok(_) = api::recompute_schedule(&u).await {
                                                            trigger.set(trigger() + 1);
                                                        }
                                                    });
                                                },
                                                "Recompute Times"
                                            }
                                        }
                                        div { class: "form-check form-switch mb-0 ms-1",
                                            input {
                                                class: "form-check-input",
                                                type: "checkbox",
                                                role: "switch",
                                                id: "editModeSwitch",
                                                checked: "{edit_mode}",
                                                onchange: move |e| edit_mode.set(e.value() == "true")
                                            }
                                            label { class: "form-check-label small", "for": "editModeSwitch", "Edit" }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    if view_mode() == "timeline" {
                        ScheduleTimeline {
                            data: data.clone(),
                            selected_field: selected_field(),
                            highlight_team: highlight_team(),
                            edit_mode: edit_mode(),
                            tournament_url: url.clone(),
                            on_edit_match: move |id: String| {
                                selected_match_id.set(id);
                                active_modal.set("match_edit".to_string());
                            },
                            key_nav: key_nav,
                            on_key_nav_consumed: move |_| key_nav.set(None),
                        }
                    } else {
                        TableView { 
                            data: data.clone(), 
                            selected_field: selected_field(), 
                            highlight_team: highlight_team(),
                            edit_mode: edit_mode(),
                            tournament_url: url.clone(),
                            on_edit_match: move |id: String| {
                                selected_match_id.set(id);
                                active_modal.set("match_edit".to_string());
                            }
                        }
                    }
                    
                    // Modals (key forces remount so Edit modal gets fresh state from match)
                    if active_modal() == "match_edit" {
                        div { key: "{selected_match_id()}",
                            EditMatchModal { 
                                tournament_url: url.clone(), 
                                match_id: selected_match_id(),
                                data: data.clone(),
                                on_close: move |_| active_modal.set("none".to_string()),
                                on_save: move |_| {
                                    active_modal.set("none".to_string());
                                    refresh();
                                }
                            }
                        }
                    }
                    if active_modal() == "match_create" {
                        CreateMatchModal {
                            tournament_url: url.clone(),
                            data: data.clone(),
                            on_close: move |_| active_modal.set("none".to_string()),
                            on_save: move |_| {
                                active_modal.set("none".to_string());
                                refresh();
                            }
                        }
                    }
                    if active_modal() == "tags" {
                        TagsModal {
                            tournament_url: url.clone(),
                            data: data.clone(),
                            on_close: move |_| active_modal.set("none".to_string()),
                            on_change: move |_| refresh()
                        }
                    }
                    if active_modal() == "fields" {
                        FieldsModal {
                            tournament_url: url.clone(),
                            data: data.clone(),
                            on_close: move |_| active_modal.set("none".to_string()),
                            on_change: move |_| refresh()
                        }
                    }
                    if active_modal() == "toml_import" {
                        TOMLImportModal {
                            tournament_url: url.clone(),
                            on_close: move |_| active_modal.set("none".to_string()),
                            on_import: move |_| {
                                active_modal.set("none".to_string());
                                refresh();
                            },
                        }
                    }
                }
            }
        }
        None => {
             // Check if it was an error or loading
             match val.read().as_ref() {
                Some(Err(e)) => rsx! { div { class: "alert alert-danger", "Error: {e}" } },
                _ => rsx! { div { class: "text-center mt-5", "Loading..." } }
             }
        }
    }
}

// ... Toolbar ...
// ... TableView ...
// ... TimelineView ...
// ... EditMatchModal ...

/// Matches on the given field, sorted by nominal_start_time descending (most recent first).
/// DSL function names and signatures for skip-condition docs popup (from app/utils/parser.py).
const DSL_FUNCTIONS: &[(&str, &str)] = &[
    ("wins", "(wins TEAM) -> INT"),
    ("losses", "(losses TEAM) -> INT"),
    ("winner", "(winner MATCH) -> TEAM"),
    ("loser", "(loser MATCH) -> TEAM"),
    ("points-won", "(points-won TEAM MATCH) -> INT"),
    ("points-lost", "(points-lost TEAM MATCH) -> INT"),
    ("is-skipped", "(is-skipped MATCH) -> BOOL"),
    ("+", "(+ INT INT) -> INT"),
    ("-", "(- INT INT) -> INT"),
    ("*", "(* INT INT) -> INT"),
    ("/", "(/ INT INT) -> INT"),
    (">", "(> INT INT) -> BOOL"),
    ("<", "(< INT INT) -> BOOL"),
    (">=", "(>= INT INT) -> BOOL"),
    ("<=", "(<= INT INT) -> BOOL"),
    ("==", "(== ANY ANY) -> BOOL"),
    ("or", "(or BOOL BOOL) -> BOOL"),
    ("and", "(and BOOL BOOL) -> BOOL"),
    ("not", "(not BOOL) -> BOOL"),
    ("if", "(if COND IF_TRUE IF_FALSE)"),
];

fn matches_on_field_sorted<'a>(
    matches: &'a [MatchSetupData],
    field_name: &str,
    exclude_uuid: Option<&str>,
) -> Vec<&'a MatchSetupData> {
    let mut v: Vec<_> = matches
        .iter()
        .filter(|m| m.field.as_deref() == Some(field_name))
        .filter(|m| exclude_uuid.map_or(true, |id| m.uuid != id))
        .collect();
    v.sort_by(|a, b| b.nominal_start_time.as_deref().cmp(&a.nominal_start_time.as_deref()));
    v
}

/// Index in `new` (byte offset) where the single added character is, when new.len() == old.len() + 1.
fn skip_condition_new_char_index(old: &str, new: &str) -> Option<usize> {
    if new.len() != old.len() + 1 {
        return None;
    }
    let mut new_chars = new.char_indices();
    let mut old_chars = old.char_indices();
    loop {
        match (new_chars.next(), old_chars.next()) {
            (Some((i, c_new)), Some((_, c_old))) => {
                if c_new != c_old {
                    return Some(i);
                }
            }
            (Some((i, _)), None) => return Some(i),
            (None, _) => return None,
        }
    }
}

/// Find matching close bracket from open_pos (byte index of open char). Returns byte index of close char.
fn skip_condition_find_matching_close(s: &str, open_byte_pos: usize, open_c: char, close_c: char) -> Option<usize> {
    let rest = s.get(open_byte_pos..)?;
    let mut depth = 1u32;
    for (i, c) in rest.char_indices() {
        if c == open_c {
            depth += 1;
        } else if c == close_c {
            depth = depth.saturating_sub(1);
            if depth == 0 {
                return Some(open_byte_pos + i);
            }
        }
    }
    None
}

/// Innermost unclosed bracket: (content_start_byte, content_end_byte). content_end_byte = position of close or s.len().
#[allow(dead_code)]
fn skip_condition_innermost_unclosed(s: &str, open_c: char, close_c: char) -> Option<(usize, usize)> {
    let open_len = open_c.len_utf8();
    let mut search_end = s.len();
    loop {
        let Some(open_pos) = s[..search_end].rfind(open_c) else {
            break;
        };
        let close_pos = skip_condition_find_matching_close(s, open_pos, open_c, close_c);
        match close_pos {
            None => return Some((open_pos + open_len, s.len())),
            Some(_end) => search_end = open_pos,
        }
    }
    None
}

/// Cursor position in character index (e.g. from selection_start).
fn skip_condition_cursor_byte(s: &str, cursor_char: usize) -> usize {
    s.char_indices()
        .nth(cursor_char)
        .map(|(i, _)| i)
        .unwrap_or(s.len())
}

/// Innermost bracket that contains the cursor. Uses largest content_start (most recent open before cursor).
#[derive(Clone, Copy)]
enum InnermostBracket {
    Paren(usize, usize), // content_start_byte, content_end_byte
    Square(usize, usize),
    Curly(usize, usize),
}

fn skip_condition_innermost_around_cursor(s: &str, cursor_char: usize) -> Option<InnermostBracket> {
    let cursor_byte = skip_condition_cursor_byte(s, cursor_char);
    let mut best: Option<(usize, InnermostBracket)> = None; // (content_start, bracket)
    if let Some(open_pos) = s[..cursor_byte].rfind('(') {
        let close_pos = skip_condition_find_matching_close(s, open_pos, '(', ')');
        let content_end = close_pos.unwrap_or(s.len());
        if close_pos.is_none() || content_end >= cursor_byte {
            let content_start = open_pos + 1;
            if content_start <= cursor_byte {
                if best.map_or(true, |(cs, _)| content_start > cs) {
                    best = Some((content_start, InnermostBracket::Paren(content_start, content_end)));
                }
            }
        }
    }
    if let Some(open_pos) = s[..cursor_byte].rfind('[') {
        let close_pos = skip_condition_find_matching_close(s, open_pos, '[', ']');
        let content_end = close_pos.unwrap_or(s.len());
        if close_pos.is_none() || content_end >= cursor_byte {
            let content_start = open_pos + 1;
            if content_start <= cursor_byte {
                if best.map_or(true, |(cs, _)| content_start > cs) {
                    best = Some((content_start, InnermostBracket::Square(content_start, content_end)));
                }
            }
        }
    }
    if let Some(open_pos) = s[..cursor_byte].rfind('{') {
        let close_pos = skip_condition_find_matching_close(s, open_pos, '{', '}');
        let content_end = close_pos.unwrap_or(s.len());
        if close_pos.is_none() || content_end >= cursor_byte {
            let content_start = open_pos + 1;
            if content_start <= cursor_byte {
                if best.map_or(true, |(cs, _)| content_start > cs) {
                    best = Some((content_start, InnermostBracket::Curly(content_start, content_end)));
                }
            }
        }
    }
    best.map(|(_, b)| b)
}

/// Segment of a skip condition expression for tokenized display (text vs team/match chips).
#[derive(Clone, Debug)]
enum SkipConditionSegment {
    Text(String),
    TeamLiteral { display: String, value: String },
    MatchLiteral { display: String },
}

fn skip_condition_parse_segments(
    s: &str,
    team_options: &[crate::types::TeamOption],
    _matches: &[crate::types::MatchSetupData],
) -> Vec<SkipConditionSegment> {
    let mut segments: Vec<SkipConditionSegment> = Vec::new();
    let mut text_start = 0usize;
    let mut pos = 0usize;
    while pos < s.len() {
        let rest = match s.get(pos..) {
            Some(r) => r,
            None => break,
        };
        if rest.starts_with('[') {
            if let Some(close) = skip_condition_find_matching_close(s, pos, '[', ']') {
                if text_start < pos {
                    segments.push(SkipConditionSegment::Text(s[text_start..pos].to_string()));
                }
                let content = s[pos + 1..close].trim().to_string();
                let display = if content.ends_with("::winner") || content.ends_with("::loser") {
                    content.clone()
                } else {
                    team_options
                        .iter()
                        .find(|t| t.id == content || t.pseudonym.as_deref() == Some(content.as_str()))
                        .and_then(|t| t.pseudonym.clone())
                        .unwrap_or_else(|| content.clone())
                };
                segments.push(SkipConditionSegment::TeamLiteral {
                    display,
                    value: content,
                });
                pos = close + 1;
                text_start = pos;
            } else {
                pos += 1;
            }
        } else if rest.starts_with('{') {
            if let Some(close) = skip_condition_find_matching_close(s, pos, '{', '}') {
                if text_start < pos {
                    segments.push(SkipConditionSegment::Text(s[text_start..pos].to_string()));
                }
                let content = s[pos + 1..close].trim().to_string();
                segments.push(SkipConditionSegment::MatchLiteral {
                    display: content.clone(),
                });
                pos = close + 1;
                text_start = pos;
            } else {
                pos += 1;
            }
        } else {
            let c = rest.chars().next().unwrap_or('\0');
            pos += c.len_utf8();
        }
    }
    if text_start < s.len() {
        segments.push(SkipConditionSegment::Text(s[text_start..].to_string()));
    }
    segments
}

/// Skip condition help modal (same content as Flask #dslHelpModal).
#[component]
fn SkipConditionHelpModal(on_close: EventHandler<()>) -> Element {
    rsx! {
        div {
            class: "modal d-block",
            style: "background: rgba(0,0,0,0.5); z-index: 1060;",
            tabindex: -1,
            div {
                class: "modal-dialog modal-lg",
                style: "z-index: 1061;",
                div { class: "modal-content",
                    div { class: "modal-header",
                        h5 { class: "modal-title", "Skip Condition Help" }
                        button { class: "btn-close", "type": "button", onclick: move |_| on_close.call(()) }
                    }
                    div { class: "modal-body",
                        p { "The skip condition uses a Lisp-like language to express boolean conditions. If it evaluates to true, the match will be skipped." }

                        h6 { class: "mt-3", "Basic Values" }
                        ul {
                            li { code { "true" } " - True" }
                            li { code { "false" } " - False" }
                            li { code { "nil" } " - Nil" }
                            li { code { "[TeamName]" } " - Team name (username, " code { "tag::TagName" } ", or " code { "MatchName::winner" } "/" code { "MatchName::loser" } ")" }
                            li { code { "{{MatchName}}" } " - Match name" }
                        }

                        h6 { class: "mt-3", "Basic Operations" }
                        ul {
                            li { code { "(== A B)" } " - Equality comparison" }
                            li { code { "(> A B)" } ", " code { "(< A B)" } ", " code { "(>= A B)" } ", " code { "(<= A B)" } " - Numeric comparisons" }
                            li { code { "(and A B)" } ", " code { "(or A B)" } ", " code { "(not A)" } " - Logical operations" }
                        }

                        h6 { class: "mt-3", "Team Operations" }
                        ul {
                            li { code { "(wins [TeamName])" } " - Number of wins for a team" }
                            li { code { "(losses [TeamName])" } " - Number of losses for a team" }
                            li { code { "(points-won [TeamName])" } " - Total points won by a team" }
                            li { code { "(points-lost [TeamName])" } " - Total points lost by a team" }
                            li { code { "(points-won [TeamName] {{MatchName}})" } " - Points won in a specific match" }
                            li { code { "(points-lost [TeamName] {{MatchName}})" } " - Points lost in a specific match" }
                            li { code { "(is-skipped {{MatchName}})" } " - True if match status is SKIPPED, false if IN_PROGRESS or COMPLETED" }
                        }

                        h6 { class: "mt-3", "Match Operations" }
                        ul {
                            li { code { "(winner {{MatchName}})" } " - Winner team of a match (returns team or NIL)" }
                            li { code { "(loser {{MatchName}})" } " - Loser team of a match (returns team or NIL)" }
                        }

                        h6 { class: "mt-3", "Other Operations" }
                        ul {
                            li { code { "(if CONDITION IF_TRUE IF_FALSE)" } " - If condition is true, return IF_TRUE, otherwise return IF_FALSE" }
                            li { code { "(lambda (*args) (output))" } " - Define a lambda function" }
                            li { code { "(cons *_)" } " - Create a list from the arguments" }
                            li { code { "(car LIST)" } " - Get the first element of a list" }
                            li { code { "(cdr LIST)" } " - Get the rest of a list" }
                            li { code { "(get INDEX LIST)" } " - Get the element at index" }
                            li { code { "(or-default VAL DEFAULT)" } " - Returns VAL if VAL is not NIL else DEFAULT" }
                            li { code { "(len LIST)" } " - Length of a list" }
                            li { code { "(map LIST FUNC)" } " - Apply a function to each element of a list" }
                            li { code { "(reduce LIST FUNC)" } " - Reduce a list to a single value" }
                            li { code { "(max LIST)" } ", " code { "(min LIST)" } " - Max/min value in a list" }
                            li { code { "(max_by LIST FUNC)" } ", " code { "(min_by LIST FUNC)" } " - Max/min by a function" }
                        }

                        h6 { class: "mt-3", "Examples" }
                        ul {
                            li { code { "(== 0 (losses [TeamName]))" } " - Skip if team has no losses" }
                            li { code { "(> (wins [TeamA]) (wins [TeamB]))" } " - Skip if TeamA has more wins than TeamB" }
                            li { code { "(== (winner {{Match1}}) [TeamName])" } " - Skip if TeamName won Match1" }
                        }

                        p { class: "text-muted small mt-3",
                            strong { "Note:" } " The expression must eventually evaluate to a boolean (true/false), but it doesn't need to simplify to a boolean immediately. "
                            "There is very minimal error checking, so be careful. "
                            strong { "You can deadlock your tournament if you do this wrong!" }
                        }
                    }
                    div { class: "modal-footer",
                        button { class: "btn btn-secondary", "type": "button", onclick: move |_| on_close.call(()), "Close" }
                    }
                }
            }
        }
    }
}

#[component]
fn CreateMatchModal(
    tournament_url: String,
    data: ScheduleSetupResponse,
    on_close: EventHandler<()>,
    on_save: EventHandler<()>,
) -> Element {
    let name = use_signal(|| "".to_string());
    let mut field = use_signal(|| "".to_string());
    let schedule_type = use_signal(|| "STATIC".to_string());
    let mut length = use_signal(|| 60u32);
    let mut start_time = use_signal(|| "".to_string());
    let mut previous_match_id = use_signal(|| "".to_string());
    let mut refs = use_signal(|| "".to_string());
    let mut team1 = use_signal(|| "".to_string());
    let mut team2 = use_signal(|| "".to_string());
    let mut set_type = use_signal(|| "SETS".to_string());
    let mut nsets = use_signal(|| 3u32);
    let mut stones_per_set = use_signal(|| 100u32);
    let ribbon = use_signal(|| false);
    let mut skip_condition = use_signal(|| "".to_string());
    let mut skip_condition_error = use_signal(|| None::<String>);
    let mut skip_condition_simplified = use_signal(|| None::<String>);
    let mut skip_condition_cursor = use_signal(|| None::<usize>);
    let mut skip_condition_cursor_pos = use_signal(|| None::<usize>);
    let mut skip_docs_visible = use_signal(|| false);
    let mut skip_bracket_ac_visible = use_signal(|| false);
    let mut skip_bracket_ac_team = use_signal(|| true);
    let mut skip_bracket_ac_index = use_signal(|| 0usize);
    let mut skip_condition_help_open = use_signal(|| false);

    let mut error = use_signal(|| None::<String>);
    let mut saving = use_signal(|| false);

    #[cfg(target_arch = "wasm32")]
    use_effect(move || {
        let pos = skip_condition_cursor();
        if let Some(p) = pos {
            skip_condition_cursor.set(None);
            let id = "skip-condition-input-create".to_string();
            spawn(async move {
                gloo_timers::future::TimeoutFuture::new(0).await;
                if let Some(window) = web_sys::window() {
                    if let Some(doc) = window.document() {
                        if let Ok(Some(el)) = doc.query_selector(&format!("#{}", id)) {
                            if let Ok(input) = el.dyn_into::<web_sys::HtmlInputElement>() {
                                let _ = input.set_selection_range(p as u32, p as u32);
                                let _ = input.focus();
                            }
                        }
                    }
                }
            });
        }
    });

    let tournament_url_val = tournament_url.clone();
    use_effect(move || {
        let expr = skip_condition();
        let _ = expr.clone();
        if expr.trim().is_empty() {
            return;
        }
        let expr_captured = expr.clone();
        let url = tournament_url_val.clone();
        spawn(async move {
            gloo_timers::future::TimeoutFuture::new(3000).await;
            let current = skip_condition();
            if current == expr_captured {
                match api::validate_dsl(&url, &expr_captured).await {
                    Ok(res) => {
                        skip_condition_error.set(if res.valid { None } else { res.error.clone() });
                        skip_condition_simplified.set(if res.valid { res.simplified } else { None });
                    }
                    Err(e) => {
                        skip_condition_error.set(Some(e));
                        skip_condition_simplified.set(None);
                    }
                }
            }
        });
    });

    let matches_on_field = matches_on_field_sorted(&data.matches, &field(), None);

    let data_field = data.clone();
    let mut on_field_change = move |new_field: String| {
        field.set(new_field.clone());
        previous_match_id.set("".to_string());
        if !new_field.is_empty() {
            let list = matches_on_field_sorted(&data_field.matches, &new_field, None);
            if schedule_type() != "STATIC" {
                if let Some(m) = list.first() {
                    previous_match_id.set(m.uuid.clone());
                }
                if let Some(m) = list.first() {
                    length.set(m.nominal_length.unwrap_or(60));
                    set_type.set(m.set_type.clone().unwrap_or_else(|| "SETS".to_string()));
                    nsets.set(m.nsets.unwrap_or(3));
                    stones_per_set.set(m.stones_per_set.unwrap_or(100));
                }
            } else if let Some(m) = list.first().and_then(|x| x.nominal_start_time.as_ref()) {
                if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(m) {
                    start_time.set(dt.format("%Y-%m-%dT%H:%M").to_string());
                }
            }
        }
    };
    let data_prev = data.clone();
    let mut on_previous_match_change = move |new_prev_id: String| {
        previous_match_id.set(new_prev_id.clone());
        if !new_prev_id.is_empty() {
            if let Some(prev) = data_prev.matches.iter().find(|m| m.uuid == new_prev_id) {
                length.set(prev.nominal_length.unwrap_or(60));
                set_type.set(prev.set_type.clone().unwrap_or_else(|| "SETS".to_string()));
                nsets.set(prev.nsets.unwrap_or(3));
                stones_per_set.set(prev.stones_per_set.unwrap_or(100));
            }
        }
    };

    let data_create_validate = data.clone();
    let validate_create_rc: Rc<RefCell<Box<dyn FnMut() -> bool>>> = Rc::new(RefCell::new(Box::new(move || {
        let st = schedule_type();
        if st == "BREAK" || st == "JOIN" || st == "FAST" || st == "SAFE" {
            let prev_id = previous_match_id().trim().to_string();
            if prev_id.is_empty() {
                error.set(Some("Previous match is required for Break, Join, Fast, and Safe matches.".to_string()));
                return false;
            }
            let current_field = field();
            if current_field.is_empty() {
                error.set(Some("Field is required when using a previous match.".to_string()));
                return false;
            }
            if let Some(prev_m) = data_create_validate.matches.iter().find(|x| x.uuid == prev_id) {
                if prev_m.field.as_deref() != Some(current_field.as_str()) {
                    error.set(Some("Previous match must be on the same field.".to_string()));
                    return false;
                }
            }
        }
        true
    })));
    let validate_create_rc2 = validate_create_rc.clone();

    let tournament_url_submit = tournament_url.clone();
    let onsubmit = move |ev: Event<FormData>| {
        ev.prevent_default();
        if !validate_create_rc.borrow_mut()() {
            return;
        }
        let tournament_url = tournament_url_submit.clone();
        let on_save = on_save.clone();
        spawn(async move {
            saving.set(true);
            error.set(None);
            if (schedule_type() == "SAFE" || schedule_type() == "FAST") && !skip_condition().trim().is_empty() {
                match api::validate_dsl(&tournament_url, &skip_condition()).await {
                    Ok(res) => {
                        if !res.valid {
                            skip_condition_error.set(res.error);
                            skip_condition_simplified.set(None);
                            saving.set(false);
                            return;
                        }
                        skip_condition_simplified.set(res.simplified);
                    }
                    Err(e) => {
                        skip_condition_error.set(Some(e));
                        skip_condition_simplified.set(None);
                        saving.set(false);
                        return;
                    }
                }
            }
            let refs_vec: Vec<String> = refs()
                .split(',')
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .collect();
            let len = if schedule_type() == "JOIN" {
                Some(0u32)
            } else {
                Some(length())
            };
            let req = CreateMatchRequest {
                name: name(),
                field: if field().is_empty() { None } else { Some(field()) },
                schedule_type: Some(schedule_type()),
                length: len,
                start_time: if start_time().is_empty() {
                    None
                } else {
                    Some(start_time())
                },
                previous_match_id: if previous_match_id().is_empty() {
                    None
                } else {
                    Some(previous_match_id())
                },
                refs: Some(refs_vec),
                team1: if team1().is_empty() { None } else { Some(team1()) },
                team2: if team2().is_empty() { None } else { Some(team2()) },
                set_type: Some(set_type()),
                nsets: Some(nsets()),
                stones_per_set: Some(stones_per_set()),
                ribbon: Some(ribbon()),
                skip_condition: Some(skip_condition()),
            };
            match api::create_match(&tournament_url, &req).await {
                Ok(_) => {
                    saving.set(false);
                    on_save.call(());
                }
                Err(e) => {
                    error.set(Some(e));
                    saving.set(false);
                }
            }
        });
    };
    let tournament_url_keydown = tournament_url.clone();
    let submit_create_rc: Rc<RefCell<Box<dyn FnMut()>>> = Rc::new(RefCell::new(Box::new(move || {
        if !validate_create_rc2.borrow_mut()() {
            return;
        }
        let tournament_url = tournament_url_keydown.clone();
        let on_save = on_save.clone();
        spawn(async move {
            saving.set(true);
            error.set(None);
            if (schedule_type() == "SAFE" || schedule_type() == "FAST") && !skip_condition().trim().is_empty() {
                if let Ok(res) = api::validate_dsl(&tournament_url, &skip_condition()).await {
                    if !res.valid {
                        skip_condition_error.set(res.error);
                        skip_condition_simplified.set(None);
                        saving.set(false);
                        return;
                    }
                    skip_condition_simplified.set(res.simplified);
                }
            }
            let refs_vec: Vec<String> = refs()
                .split(',')
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .collect();
            let len = if schedule_type() == "JOIN" {
                Some(0u32)
            } else {
                Some(length())
            };
            let req = CreateMatchRequest {
                name: name(),
                field: if field().is_empty() { None } else { Some(field()) },
                schedule_type: Some(schedule_type()),
                length: len,
                start_time: if start_time().is_empty() {
                    None
                } else {
                    Some(start_time())
                },
                previous_match_id: if previous_match_id().is_empty() {
                    None
                } else {
                    Some(previous_match_id())
                },
                refs: Some(refs_vec),
                team1: if team1().is_empty() { None } else { Some(team1()) },
                team2: if team2().is_empty() { None } else { Some(team2()) },
                set_type: Some(set_type()),
                nsets: Some(nsets()),
                stones_per_set: Some(stones_per_set()),
                ribbon: Some(ribbon()),
                skip_condition: Some(skip_condition()),
            };
            match api::create_match(&tournament_url, &req).await {
                Ok(_) => {
                    saving.set(false);
                    on_save.call(());
                }
                Err(e) => {
                    error.set(Some(e));
                    saving.set(false);
                }
            }
        });
    })));
    let submit_create_rc2 = submit_create_rc.clone();
    let form_keydown = move |ev: Event<KeyboardData>| {
        let key = ev.key().to_string();
        if key == "Enter" {
            if ev.modifiers().contains(Modifiers::SHIFT) {
                ev.prevent_default();
                ev.stop_propagation();
                submit_create_rc.borrow_mut()();
            } else {
                ev.prevent_default();
            }
        }
    };
    let modal_keydown = move |ev: Event<KeyboardData>| {
        let key = ev.key().to_string();
        if key == "Escape" {
            ev.prevent_default();
            on_close.call(());
        } else if key == "Enter" && ev.modifiers().contains(Modifiers::SHIFT) {
            ev.prevent_default();
            ev.stop_propagation();
            submit_create_rc2.borrow_mut()();
        }
    };

    let sc_val = skip_condition();
    let cursor_char = skip_condition_cursor_pos();
    let innermost = cursor_char.and_then(|c| skip_condition_innermost_around_cursor(&sc_val, c));
    let cursor_byte = cursor_char.map(|c| skip_condition_cursor_byte(&sc_val, c)).unwrap_or(0);
    let show_skip_docs = matches!(innermost, Some(InnermostBracket::Paren(_, _)));
    let docs_prefix = match &innermost {
        Some(InnermostBracket::Paren(cs, ce)) => {
            sc_val[*cs..*ce].trim().split_whitespace().next().unwrap_or("").to_lowercase()
        }
        _ => String::new(),
    };
    let docs_filtered: Vec<_> = if show_skip_docs {
        DSL_FUNCTIONS
            .iter()
            .filter(|(n, _)| n.to_lowercase().starts_with(docs_prefix.as_str()))
            .take(12)
            .collect()
    } else {
        vec![]
    };
    let (bracket_is_team, bracket_query) = match &innermost {
        Some(InnermostBracket::Square(cs, ce)) => {
            let end = (*ce).min(cursor_byte).max(*cs);
            (true, sc_val[*cs..end].trim().to_lowercase())
        }
        Some(InnermostBracket::Curly(cs, ce)) => {
            let end = (*ce).min(cursor_byte).max(*cs);
            (false, sc_val[*cs..end].trim().to_lowercase())
        }
        _ => (true, String::new()),
    };
    let show_bracket_ac = matches!(innermost, Some(InnermostBracket::Square(_, _)) | Some(InnermostBracket::Curly(_, _)));
    let bracket_ac_idx_raw = skip_bracket_ac_index();
    // (insert_value, display_value, profile_photo for teams). Teams: insert id; matches: insert name.
    // Team bracket also includes MatchName::winner and MatchName::loser.
    let bracket_options: Vec<(String, String, Option<String>)> = if show_bracket_ac && bracket_is_team {
        let team_opts: Vec<_> = data
            .team_options
            .iter()
            .filter(|t| {
                let disp = t.pseudonym.as_deref().unwrap_or(t.id.as_str());
                disp.to_lowercase().contains(bracket_query.as_str())
                    || t.id.to_lowercase().contains(bracket_query.as_str())
            })
            .map(|t| {
                (
                    t.id.clone(),
                    t.pseudonym.clone().unwrap_or_else(|| t.id.clone()),
                    t.profile_photo.clone(),
                )
            })
            .take(15)
            .collect();
        let match_qual_opts: Vec<_> = data
            .matches
            .iter()
            .flat_map(|m| {
                let w = (format!("{}::winner", m.name), format!("{}::winner", m.name), None);
                let l = (format!("{}::loser", m.name), format!("{}::loser", m.name), None);
                [w, l]
            })
            .filter(|(s, _, _)| s.to_lowercase().contains(bracket_query.as_str()))
            .take(15)
            .collect();
        team_opts
            .into_iter()
            .chain(match_qual_opts)
            .take(15)
            .collect()
    } else if show_bracket_ac {
        data.matches
            .iter()
            .filter(|m| m.name.to_lowercase().contains(bracket_query.as_str()))
            .map(|m| (m.name.clone(), m.name.clone(), None))
            .take(15)
            .collect()
    } else {
        vec![]
    };
    let bracket_ac_idx = bracket_ac_idx_raw.min(bracket_options.len().saturating_sub(1));
    let docs_items: Vec<_> = if show_skip_docs && !docs_filtered.is_empty() {
        docs_filtered
            .iter()
            .map(|(dn, ds)| {
                let fname = dn.to_string();
                rsx! {
                    li {
                        class: "py-1 px-2 rounded",
                        onclick: move |_| {
                            let v = skip_condition();
                            if let Some(i) = v.rfind('(') {
                                skip_condition.set(format!("{}{}", &v[..=i], fname));
                            }
                            skip_docs_visible.set(false);
                        },
                        span { class: "fw-medium text-primary", "{dn}" }
                        span { class: "text-muted ms-1", " {ds}" }
                    }
                }
            })
            .collect()
    } else {
        vec![]
    };
    let base_url_create = api::base_url();
    let bracket_option_items: Vec<_> = if show_bracket_ac && !bracket_options.is_empty() {
        bracket_options
            .iter()
            .enumerate()
            .map(|(idx, (insert_val, display_val, photo))| {
                let opt_insert = insert_val.clone();
                let opt_display = display_val.clone();
                let opt_photo = photo.clone();
                let is_team = bracket_is_team;
                let is_cur = bracket_ac_idx == idx;
                let li_class = if is_cur {
                    "py-1 px-2 rounded bg-primary text-white"
                } else {
                    "py-1 px-2 rounded"
                };
                let avatar_node = if is_team {
                    if let Some(photo) = &opt_photo {
                        rsx! {
                            img {
                                src: "{base_url_create}/static/{photo}",
                                alt: "{opt_display}",
                                class: "team-token-avatar small me-1 rounded-circle",
                                style: "width: 1.5em; height: 1.5em; object-fit: cover;"
                            }
                        }
                    } else {
                        rsx! {
                            span { class: "team-token-avatar small me-1", "{opt_display.chars().next().unwrap_or('?')}" }
                        }
                    }
                } else {
                    rsx! { span { class: "me-1", "🏀" } }
                };
                rsx! {
                    li {
                        class: "{li_class}",
                        onclick: move |_| {
                            let v = skip_condition();
                            let cursor_char = skip_condition_cursor_pos().unwrap_or(0);
                            let cursor_byte = skip_condition_cursor_byte(&v, cursor_char);
                            let inn = skip_condition_innermost_around_cursor(&v, cursor_char);
                            let Some(cs) = inn.and_then(|b| match b {
                                InnermostBracket::Square(cs, _) | InnermostBracket::Curly(cs, _) => Some(cs),
                                _ => None,
                            }) else {
                                skip_bracket_ac_visible.set(false);
                                return;
                            };
                            let new_v = format!("{}{}{}", &v[..cs], opt_insert, &v[cursor_byte..]);
                            skip_condition.set(new_v.clone());
                            let cs_chars = v[..cs].chars().count();
                            let new_cursor_char = cs_chars + opt_insert.chars().count();
                            skip_condition_cursor.set(Some(new_cursor_char));
                            skip_bracket_ac_visible.set(false);
                        },
                        {avatar_node}
                        span { "{display_val}" }
                    }
                }
            })
            .collect()
    } else {
        vec![]
    };

    let skip_condition_segments = skip_condition_parse_segments(
        &skip_condition(),
        &data.team_options,
        &data.matches,
    );
    let skip_condition_has_tokens = skip_condition_segments
        .iter()
        .any(|s| !matches!(s, SkipConditionSegment::Text(_)));
    let skip_condition_segment_items: Vec<_> = skip_condition_segments
        .iter()
        .map(|seg| {
            match seg {
                SkipConditionSegment::Text(t) => rsx! { span { "{t}" } },
                SkipConditionSegment::TeamLiteral { display, value } => {
                    let d = display.clone();
                    let photo = data
                        .team_options
                        .iter()
                        .find(|t| t.id == *value)
                        .and_then(|t| t.profile_photo.clone());
                    let chip_class = if value.ends_with("::winner") {
                        "team-token-chip team-token-chip-winner small me-1"
                    } else if value.ends_with("::loser") {
                        "team-token-chip team-token-chip-loser small me-1"
                    } else {
                        "team-token-chip team-token-chip-team small me-1"
                    };
                    let avatar_node = if let Some(ph) = &photo {
                        rsx! {
                            img {
                                src: "{base_url_create}/static/{ph}",
                                alt: "{d}",
                                class: "team-token-avatar rounded-circle",
                                style: "width: 1.25em; height: 1.25em; object-fit: cover;"
                            }
                        }
                    } else {
                        rsx! {
                            span { class: "team-token-avatar", "{d.chars().next().unwrap_or('?')}" }
                        }
                    };
                    rsx! {
                        span { class: "{chip_class}",
                            {avatar_node}
                            span { class: "team-token-label", "{d}" }
                        }
                    }
                }
                SkipConditionSegment::MatchLiteral { display } => {
                    let d = display.clone();
                    rsx! {
                        span { class: "team-token-chip small me-1", style: "background: #e9ecef; border-radius: 4px; padding: 2px 6px;",
                            span { class: "me-1", "🏀" }
                            span { "{d}" }
                        }
                    }
                }
            }
        })
        .collect();

    rsx! {
        div {
            div {
                class: "modal d-block",
                tabindex: -1,
                style: "background: rgba(0,0,0,0.5)",
                onkeydown: modal_keydown,
                div { class: "modal-dialog modal-lg",
                    div { class: "modal-content",
                        div { class: "modal-header",
                            h5 { class: "modal-title", "New Match" }
                        }
                    div { class: "modal-body",
                        if let Some(err) = error() {
                            div { class: "alert alert-danger", "{err}" }
                        }
                        form {
                            onsubmit: onsubmit,
                            onkeydown: form_keydown,

                            div { class: "row",
                                div { class: "col-md-6",
                                    div { class: "mb-3",
                                        label { class: "form-label", "Match Name" }
                                        input { class: "form-control", "type": "text", value: "{name}", oninput: move |e| { let mut name = name; name.set(e.value()); }, required: true }
                                    }
                                }
                                div { class: "col-md-6",
                                    div { class: "mb-3",
                                        label { class: "form-label", "Field" }
                                        select { class: "form-select", value: "{field}", onchange: move |e| on_field_change(e.value()),
                                            option { value: "", "Select Field" }
                                            for f in &data.fields {
                                                option { value: "{f.name}", "{f.name}" }
                                            }
                                        }
                                    }
                                }
                            }

                            div { class: "row",
                                div { class: "col-md-6",
                                    div { class: "mb-3",
                                        label { class: "form-label", "Type" }
                                        select { class: "form-select", value: "{schedule_type}", onchange: move |e| { let mut schedule_type = schedule_type; schedule_type.set(e.value()); },
                                            option { value: "STATIC", "Static" }
                                            option { value: "SAFE", "Safe" }
                                            option { value: "FAST", "Fast" }
                                            option { value: "BREAK", "Break" }
                                            option { value: "JOIN", "Join" }
                                        }
                                    }
                                }
                                if schedule_type() != "JOIN" {
                                    div { class: "col-md-6",
                                        div { class: "mb-3",
                                            label { class: "form-label", "Length (min)" }
                                            input { class: "form-control", "type": "number", min: "0", value: "{length}", oninput: move |e| { let mut length = length; length.set(e.value().parse().unwrap_or(60)); } }
                                        }
                                    }
                                }
                            }

                            if schedule_type() == "STATIC" {
                                div { class: "mb-3",
                                    label { class: "form-label", "Start Time" }
                                    input { class: "form-control", "type": "datetime-local", value: "{start_time}", oninput: move |e| { let mut start_time = start_time; start_time.set(e.value()); } }
                                }
                            } else if schedule_type() == "SAFE" || schedule_type() == "FAST" || schedule_type() == "BREAK" || schedule_type() == "JOIN" {
                                div { class: "mb-3",
                                    label { class: "form-label", "Previous Match" }
                                    select { class: "form-select", value: "{previous_match_id}", onchange: move |e| on_previous_match_change(e.value()),
                                        option { value: "", "None" }
                                        for m in &matches_on_field {
                                            option { value: "{m.uuid}", "{m.name}" }
                                        }
                                    }
                                }
                            }

                            if schedule_type() == "STATIC" || schedule_type() == "SAFE" || schedule_type() == "FAST" {
                                div { class: "row",
                                    div { class: "col-md-6",
                                        div { class: "mb-3",
                                            label { class: "form-label", "Team 1" }
                                            TeamTokenInput {
                                                team_options: data.team_options.clone(),
                                                tags: data.tags.clone(),
                                                matches: data.matches.clone(),
                                                value: team1(),
                                                on_change: move |s| team1.set(s),
                                                multiple: false,
                                                placeholder: "Pseudonym, MatchName::winner, tag::TagName".to_string(),
                                            }
                                            div { class: "form-text", "Team, match winner/loser (MatchName::winner), or tag (tag::TagName)" }
                                        }
                                    }
                                    div { class: "col-md-6",
                                        div { class: "mb-3",
                                            label { class: "form-label", "Team 2" }
                                            TeamTokenInput {
                                                team_options: data.team_options.clone(),
                                                tags: data.tags.clone(),
                                                matches: data.matches.clone(),
                                                value: team2(),
                                                on_change: move |s| team2.set(s),
                                                multiple: false,
                                                placeholder: "Pseudonym, MatchName::winner, tag::TagName".to_string(),
                                            }
                                            div { class: "form-text", "Team, match winner/loser (MatchName::winner), or tag (tag::TagName)" }
                                        }
                                    }
                                }
                                div { class: "mb-3",
                                    label { class: "form-label", "Referees" }
                                    TeamTokenInput {
                                        team_options: data.team_options.clone(),
                                        tags: data.tags.clone(),
                                        matches: data.matches.clone(),
                                        value: refs(),
                                        on_change: move |s| refs.set(s),
                                        multiple: true,
                                        placeholder: "Comma-separated: pseudonym, MatchName::winner, tag::TagName".to_string(),
                                    }
                                    div { class: "form-text", "Comma-separated list of teams, match winner/loser, or tags" }
                                }
                                div { class: "row",
                                    div { class: "col-md-4",
                                        div { class: "mb-3",
                                            label { class: "form-label", "Format" }
                                            select { class: "form-select", value: "{set_type}", onchange: move |e| { let mut set_type = set_type; set_type.set(e.value()); },
                                                option { value: "SETS", "Sets" }
                                                option { value: "STONES", "Stones" }
                                            }
                                        }
                                    }
                                    div { class: "col-md-4",
                                        div { class: "mb-3",
                                            label { class: "form-label", "Number of sets" }
                                            input { class: "form-control", "type": "number", min: "1", value: "{nsets}", oninput: move |e| { let mut nsets = nsets; nsets.set(e.value().parse().unwrap_or(3)); } }
                                        }
                                    }
                                    if set_type() == "STONES" {
                                        div { class: "col-md-4",
                                            div { class: "mb-3",
                                                label { class: "form-label", "Stones per set" }
                                                input { class: "form-control", "type": "number", min: "1", value: "{stones_per_set}", oninput: move |e| { let mut stones_per_set = stones_per_set; stones_per_set.set(e.value().parse().unwrap_or(100)); } }
                                            }
                                        }
                                    }
                                }
                                div { class: "mb-3",
                                    div { class: "form-check",
                                        input { class: "form-check-input", "type": "checkbox", id: "create-ribbon", checked: "{ribbon}", onchange: move |e| { let mut ribbon = ribbon; ribbon.set(e.value() == "true"); } }
                                        label { class: "form-check-label", "for": "create-ribbon", "Ribbon game" }
                                    }
                                }
                                if schedule_type() == "SAFE" || schedule_type() == "FAST" {
                                    div { class: "mb-3 position-relative",
                                        label { class: "form-label", "Skip condition" }
                                        div { class: "form-text mb-1",
                                            "Optional expression that evaluates to a boolean. If true, this match will be skipped. "
                                            a {
                                                href: "#",
                                                class: "text-decoration-none",
                                                onclick: move |ev: Event<MouseData>| {
                                                    ev.prevent_default();
                                                    skip_condition_help_open.set(true);
                                                },
                                                "(skip condition help)"
                                            }
                                        }
                                        input {
                                            id: "skip-condition-input-create",
                                            class: "form-control font-monospace",
                                            "type": "text",
                                            placeholder: "e.g. (== 0 (losses [Team]))",
                                            value: "{skip_condition}",
                                            oninput: move |e| {
                                                let new_val = e.value();
                                                let old = skip_condition();
                                                let (out, cursor_after_open) = if let Some(byte_i) = skip_condition_new_char_index(&old, &new_val) {
                                                    let open_c = new_val[byte_i..].chars().next().unwrap_or('\0');
                                                    let closing = match open_c {
                                                        '(' => ")",
                                                        '[' => {
                                                            skip_bracket_ac_visible.set(true);
                                                            skip_bracket_ac_team.set(true);
                                                            skip_bracket_ac_index.set(0);
                                                            "]"
                                                        }
                                                        '{' => {
                                                            skip_bracket_ac_visible.set(true);
                                                            skip_bracket_ac_team.set(false);
                                                            skip_bracket_ac_index.set(0);
                                                            "}"
                                                        }
                                                        _ => "",
                                                    };
                                                    if closing.is_empty() {
                                                        (new_val, None)
                                                    } else {
                                                        let char_end = byte_i + new_val[byte_i..].chars().next().map(|c| c.len_utf8()).unwrap_or(1);
                                                        let out_str = format!("{}{}{}", &new_val[..char_end], closing, &new_val[char_end..]);
                                                        (out_str, Some(char_end))
                                                    }
                                                } else {
                                                    (new_val, None)
                                                };
                                                skip_condition.set(out.clone());
                                                if let Some(pos) = cursor_after_open {
                                                    skip_condition_cursor.set(Some(pos));
                                                }
                                                skip_condition_error.set(None);
                                                if out.contains('(') {
                                                    skip_docs_visible.set(true);
                                                }
                                                let id = "skip-condition-input-create".to_string();
                                                spawn(async move {
                                                    gloo_timers::future::TimeoutFuture::new(0).await;
                                                    #[cfg(target_arch = "wasm32")]
                                                    if let Some(window) = web_sys::window() {
                                                        if let Some(doc) = window.document() {
                                                            if let Ok(Some(el)) = doc.query_selector(&format!("#{}", id)) {
                                                                if let Ok(input) = el.dyn_into::<web_sys::HtmlInputElement>() {
                                                                    if let Ok(Some(sel)) = input.selection_start() {
                                                                        skip_condition_cursor_pos.set(Some(sel as usize));
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                });
                                            },
                                            onfocus: move |_| {
                                                let id = "skip-condition-input-create".to_string();
                                                spawn(async move {
                                                    gloo_timers::future::TimeoutFuture::new(0).await;
                                                    #[cfg(target_arch = "wasm32")]
                                                    if let Some(window) = web_sys::window() {
                                                        if let Some(doc) = window.document() {
                                                            if let Ok(Some(el)) = doc.query_selector(&format!("#{}", id)) {
                                                                if let Ok(input) = el.dyn_into::<web_sys::HtmlInputElement>() {
                                                                    if let Ok(Some(sel)) = input.selection_start() {
                                                                        skip_condition_cursor_pos.set(Some(sel as usize));
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                });
                                            },
                                            onkeydown: move |ev: Event<KeyboardData>| {
                                                let key = ev.key().to_string();
                                                let n = bracket_options.len();
                                                if show_bracket_ac && n > 0 {
                                                    if key == "ArrowDown" {
                                                        ev.prevent_default();
                                                        skip_bracket_ac_index.set((bracket_ac_idx + 1) % n);
                                                        return;
                                                    }
                                                    if key == "ArrowUp" {
                                                        ev.prevent_default();
                                                        skip_bracket_ac_index.set((bracket_ac_idx + n - 1) % n);
                                                        return;
                                                    }
                                                    if key == "Enter" {
                                                        ev.prevent_default();
                                                        if let Some((opt_insert, _, _)) = bracket_options.get(bracket_ac_idx) {
                                                            let v = skip_condition();
                                                            let cursor_char = skip_condition_cursor_pos().unwrap_or(0);
                                                            let cursor_byte = skip_condition_cursor_byte(&v, cursor_char);
                                                            let inn = skip_condition_innermost_around_cursor(&v, cursor_char);
                                                            if let Some(cs) = inn.and_then(|b| match b {
                                                                InnermostBracket::Square(cs, _) | InnermostBracket::Curly(cs, _) => Some(cs),
                                                                _ => None,
                                                            }) {
                                                                let new_v = format!("{}{}{}", &v[..cs], opt_insert, &v[cursor_byte..]);
                                                                skip_condition.set(new_v);
                                                                let cs_chars = v[..cs].chars().count();
                                                                let new_cursor_char = cs_chars + opt_insert.chars().count();
                                                                skip_condition_cursor.set(Some(new_cursor_char));
                                                                skip_bracket_ac_visible.set(false);
                                                            }
                                                        }
                                                        return;
                                                    }
                                                }
                                                if key == "Enter" && !ev.modifiers().contains(Modifiers::SHIFT) {
                                                    ev.prevent_default();
                                                }
                                            },
                                            onkeyup: move |_| {
                                                let id = "skip-condition-input-create".to_string();
                                                spawn(async move {
                                                    gloo_timers::future::TimeoutFuture::new(0).await;
                                                    #[cfg(target_arch = "wasm32")]
                                                    if let Some(window) = web_sys::window() {
                                                        if let Some(doc) = window.document() {
                                                            if let Ok(Some(el)) = doc.query_selector(&format!("#{}", id)) {
                                                                if let Ok(input) = el.dyn_into::<web_sys::HtmlInputElement>() {
                                                                    if let Ok(Some(sel)) = input.selection_start() {
                                                                        let sel_i = sel as usize;
                                                                        skip_condition_cursor_pos.set(Some(sel_i));
                                                                        let val = input.value();
                                                                        let inside = skip_condition_innermost_around_cursor(&val, sel_i)
                                                                            .map(|b| matches!(b, InnermostBracket::Square(_, _) | InnermostBracket::Curly(_, _)))
                                                                            .unwrap_or(false);
                                                                        if !inside {
                                                                            skip_bracket_ac_visible.set(false);
                                                                        }
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                });
                                            },
                                            onblur: move |_| {
                                                skip_docs_visible.set(false);
                                                skip_bracket_ac_visible.set(false);
                                                let expr = skip_condition();
                                                if expr.trim().is_empty() {
                                                    skip_condition_error.set(None);
                                                    return;
                                                }
                                                let url = tournament_url.clone();
                                                spawn(async move {
                                                    match api::validate_dsl(&url, &expr).await {
                                                        Ok(res) => {
                                                            skip_condition_error.set(if res.valid {
                                                                None
                                                            } else {
                                                                res.error.clone()
                                                            });
                                                            skip_condition_simplified.set(if res.valid {
                                                                res.simplified
                                                            } else {
                                                                None
                                                            });
                                                        }
                                                        Err(e) => {
                                                            skip_condition_error.set(Some(e));
                                                            skip_condition_simplified.set(None);
                                                        }
                                                    }
                                                });
                                            },
                                        }
                                        if show_skip_docs && !docs_filtered.is_empty() {
                                            div { class: "position-absolute start-0 mt-1 p-2 bg-light border rounded shadow-sm z-3",
                                                style: "min-width: 280px; max-height: 240px; overflow-y: auto;",
                                                ul { class: "list-unstyled mb-0 small",
                                                    for item in docs_items.iter() {
                                                        {item.clone()}
                                                    }
                                                }
                                            }
                                        }
                                        if show_bracket_ac && !bracket_option_items.is_empty() {
                                            div { class: "position-absolute start-0 mt-1 p-2 bg-light border rounded shadow-sm z-3",
                                                style: "min-width: 200px; max-height: 200px; overflow-y: auto;",
                                                ul { class: "list-unstyled mb-0 small",
                                                    for bracket_item in bracket_option_items.iter() {
                                                        {bracket_item.clone()}
                                                    }
                                                }
                                            }
                                        }
                                        if skip_condition_has_tokens {
                                            div { class: "form-text mt-1 d-flex flex-wrap align-items-center gap-0",
                                                for item in skip_condition_segment_items.iter() {
                                                    {item.clone()}
                                                }
                                            }
                                        }
                                        if let Some(err) = skip_condition_error() {
                                            div { class: "form-text text-danger", "✗ {err}" }
                                        } else if let Some(simp) = skip_condition_simplified() {
                                            div { class: "form-text text-success", "✓ Valid (simplified: {simp})" }
                                        } else if !skip_condition().trim().is_empty() {
                                            div { class: "form-text text-success", "✓ Valid" }
                                        }
                                    }
                                }
                            }

                            div { class: "modal-footer",
                                button { class: "btn btn-secondary", "type": "button", onclick: move |_| on_close.call(()), "Cancel (Esc)" }
                                button { class: "btn btn-success", "type": "submit", disabled: "{saving}",
                                    if saving() { span { class: "spinner-border spinner-border-sm me-2" } }
                                    "Save (⇧↵)"
                                }
                            }
                        }
                    }
                }
                }
            }
            if skip_condition_help_open() {
                SkipConditionHelpModal { on_close: move |_| skip_condition_help_open.set(false) }
            }
        }
    }
}

#[component]
fn FieldsModal(
    tournament_url: String,
    data: ScheduleSetupResponse,
    on_close: EventHandler<()>,
    on_change: EventHandler<()>,
) -> Element {
    let mut new_name = use_signal(|| "".to_string());
    let mut new_cam = use_signal(|| "".to_string());
    let mut error = use_signal(|| None::<String>);
    let url_sig = use_signal(|| tournament_url.clone());
    let mut recording_modal_field = use_signal(|| None::<u32>);
    let mut recording_modal_url = use_signal(|| None::<String>);
    let mut recording_modal_loading = use_signal(|| false);
    let mut recording_modal_error = use_signal(|| None::<String>);
    let mut editing_field_id = use_signal(|| None::<u32>);
    let mut editing_name = use_signal(|| "".to_string());
    let mut editing_camera = use_signal(|| "".to_string());

    rsx! {
        div { class: "modal d-block", tabindex: "-1", style: "background: rgba(0,0,0,0.5)",
            div { class: "modal-dialog modal-lg",
                div { class: "modal-content",
                    div { class: "modal-header d-flex justify-content-between align-items-center",
                        h5 { class: "modal-title mb-0", "Manage Fields" }
                        button { type: "button", class: "btn-close", "aria-label": "Close", onclick: move |_| on_close.call(()) }
                    }
                    div { class: "modal-body",
                        if let Some(err) = error() { div { class: "alert alert-danger", "{err}" } }

                        div { class: "input-group mb-3",
                            input { class: "form-control", placeholder: "Field Name", value: "{new_name}", oninput: move |e| new_name.set(e.value()) }
                            input { class: "form-control", placeholder: "YouTube Livestream URL (opt)", value: "{new_cam}", oninput: move |e| new_cam.set(e.value()) }
                            button { class: "btn btn-outline-success",
                                onclick: move |_| {
                                    let u = url_sig().clone();
                                    let on_change = on_change.clone();
                                    spawn(async move {
                                        let cams = if new_cam().is_empty() { vec![] } else { vec![new_cam()] };
                                        let req = CreateFieldRequest { name: new_name(), camera_urls: cams };
                                        match api::create_field(&u, &req).await {
                                            Ok(_) => { new_name.set("".to_string()); new_cam.set("".to_string()); on_change.call(()); }
                                            Err(e) => error.set(Some(e)),
                                        }
                                    });
                                },
                                "Add"
                            }
                        }

                        h6 { "Existing Fields" }
                        ul { class: "list-group",
                            {data.fields.iter().map(|f| {
                                let fid = f.id;
                                let fname = f.name.clone();
                                let fname_for_rec = fname.clone();
                                let first_cam = f.camera_urls.first().cloned().unwrap_or_default();
                                let is_editing = editing_field_id() == Some(fid);
                                rsx! {
                                    li { key: "{fid}", class: "list-group-item d-flex flex-column gap-2",
                                        if is_editing {
                                            div { class: "d-flex flex-column gap-2",
                                                input { class: "form-control form-control-sm", placeholder: "Field Name", value: "{editing_name}", oninput: move |e| editing_name.set(e.value()) }
                                                input { class: "form-control form-control-sm", placeholder: "YouTube Livestream URL (opt)", value: "{editing_camera}", oninput: move |e| editing_camera.set(e.value()) }
                                                div { class: "d-flex gap-1",
                                                    button { class: "btn btn-sm btn-primary",
                                                        onclick: move |_| {
                                                            let u = url_sig().clone();
                                                            let name = editing_name().clone();
                                                            let cam = editing_camera().clone();
                                                            let on_change = on_change.clone();
                                                            spawn(async move {
                                                                let cams = if cam.trim().is_empty() { vec![] } else { vec![cam] };
                                                                let req = UpdateFieldRequest { name, camera_urls: cams };
                                                                if let Ok(_) = api::update_field(&u, fid, &req).await {
                                                                    editing_field_id.set(None);
                                                                    on_change.call(());
                                                                } else {
                                                                    error.set(Some("Failed to update field".to_string()));
                                                                }
                                                            });
                                                        },
                                                        "Save"
                                                    }
                                                    button { class: "btn btn-sm btn-secondary",
                                                        onclick: move |_| editing_field_id.set(None),
                                                        "Cancel"
                                                    }
                                                }
                                            }
                                            } else {
                                            div { class: "d-flex justify-content-between align-items-center flex-wrap gap-2",
                                                div { class: "d-flex align-items-center gap-2 flex-wrap",
                                                    strong { "{fname}" }
                                                    if !first_cam.is_empty() {
                                                        a { href: "{first_cam}", target: "_blank", rel: "noopener noreferrer", class: "small text-primary", "{first_cam}" }
                                                    }
                                                }
                                                div { class: "btn-group btn-group-sm",
                                                    button { class: "btn btn-outline-info",
                                                        onclick: move |_| {
                                                            recording_modal_field.set(Some(fid));
                                                            recording_modal_url.set(None);
                                                            recording_modal_error.set(None);
                                                            recording_modal_loading.set(true);
                                                            let u = url_sig().clone();
                                                            let name = fname_for_rec.clone();
                                                            spawn(async move {
                                                                match api::camera_url(&u, &name).await {
                                                                    Ok(url) => {
                                                                        recording_modal_url.set(Some(url));
                                                                        recording_modal_loading.set(false);
                                                                    }
                                                                    Err(e) => {
                                                                        recording_modal_error.set(Some(e));
                                                                        recording_modal_loading.set(false);
                                                                    }
                                                                }
                                                            });
                                                        },
                                                        "Get recording link"
                                                    }
                                                    button { class: "btn btn-outline-primary",
                                                        onclick: move |_| {
                                                            editing_field_id.set(Some(fid));
                                                            editing_name.set(fname.clone());
                                                            editing_camera.set(first_cam.clone());
                                                        },
                                                        "Edit"
                                                    }
                                                    button { class: "btn btn-outline-danger",
                                                        onclick: move |_| {
                                                            let u = url_sig().clone();
                                                            let on_change = on_change.clone();
                                                            spawn(async move {
                                                                if let Ok(_) = api::delete_field(&u, fid).await {
                                                                    on_change.call(());
                                                                } else {
                                                                    error.set(Some("Cannot delete field with matches".to_string()));
                                                                }
                                                            });
                                                        },
                                                        "Delete"
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            })}
                        }
                    }
                }
            }
        }

        {{
            let rec_fid_opt = recording_modal_field();
            match rec_fid_opt {
                Some(rec_fid) => {
                    let rec_field_label = data.fields.iter().find(|x| x.id == rec_fid).map(|x| x.name.as_str()).unwrap_or("");
                    let rec_url = recording_modal_url();
                    let rec_loading = recording_modal_loading();
                    let rec_err = recording_modal_error();
                    let qr_src = rec_url.as_ref().map(|u| format!("https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={}", urlencoding::encode(u)));
                    rsx! {
                        div { class: "modal d-block", tabindex: "-1", style: "background: rgba(0,0,0,0.5); z-index: 1060;",
                            div { class: "modal-dialog modal-dialog-centered",
                                div { class: "modal-content",
                                    div { class: "modal-header d-flex justify-content-between align-items-center",
                                        h5 { class: "modal-title mb-0", "Recording link — {rec_field_label}" }
                                        button { type: "button", class: "btn-close", onclick: move |_| {
                                            recording_modal_field.set(None);
                                            recording_modal_url.set(None);
                                            recording_modal_error.set(None);
                                            recording_modal_loading.set(false);
                                        } }
                                    }
                                    div { class: "modal-body text-center",
                                        if rec_loading {
                                            p { class: "text-muted", "Loading..." }
                                        } else if let Some(ref e) = rec_err {
                                            p { class: "text-danger", "{e}" }
                                        } else if let (Some(ref url), Some(ref qr)) = (rec_url, qr_src) {
                                            img { src: "{qr}", alt: "QR code", style: "max-width: 200px; height: auto;" }
                                            a { href: "{url}", target: "_blank", rel: "noopener noreferrer", class: "d-block mt-2 small text-break", "{url}" }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                None => rsx! { div {} },
            }
        }}
    }
}

#[component]
fn TOMLImportModal(
    tournament_url: String,
    on_close: EventHandler<()>,
    on_import: EventHandler<()>,
) -> Element {
    let mut error = use_signal(|| None::<String>);
    let mut importing = use_signal(|| false);
    let on_file_change = move |ev: Event<FormData>| {
        let files = ev.files();
        if let Some(file) = files.first().cloned() {
            let u = tournament_url.clone();
            let on_import = on_import.clone();
            importing.set(true);
            error.set(None);
            spawn(async move {
                match file.read_string().await {
                    Ok(toml_content) => {
                        let req = ImportScheduleRequest { toml: toml_content };
                        match api::import_schedule(&u, &req).await {
                            Ok(_) => {
                                importing.set(false);
                                on_import.call(());
                            }
                            Err(e) => {
                                error.set(Some(e));
                                importing.set(false);
                            }
                        }
                    }
                    Err(e) => {
                        error.set(Some(e.to_string()));
                        importing.set(false);
                    }
                }
            });
        }
    };
    rsx! {
        div { class: "modal d-block", tabindex: "-1", style: "background: rgba(0,0,0,0.5)",
            div { class: "modal-dialog modal-lg",
                div { class: "modal-content",
                    div { class: "modal-header",
                        h5 { class: "modal-title", "Import Schedule (TOML)" }
                    }
                    div { class: "modal-body",
                        if let Some(err) = error() {
                            div { class: "alert alert-danger", "{err}" }
                        }
                        p { class: "text-muted", "Select a TOML file exported from a tournament schedule." }
                        input {
                            r#type: "file",
                            class: "form-control",
                            accept: ".toml",
                            onchange: on_file_change,
                        }
                        if importing() {
                            div { class: "mt-2 text-muted", "Importing..." }
                        }
                    }
                    div { class: "modal-footer",
                        button { class: "btn btn-secondary", onclick: move |_| on_close.call(()), "Cancel" }
                    }
                }
            }
        }
    }
}

#[component]
fn TagsModal(
    tournament_url: String,
    data: ScheduleSetupResponse,
    on_close: EventHandler<()>,
    on_change: EventHandler<()>,
) -> Element {
    let mut new_tag = use_signal(|| "".to_string());
    let mut error = use_signal(|| None::<String>);
    let url_sig = use_signal(|| tournament_url.clone());

    rsx! {
        div { class: "modal d-block", tabindex: "-1", style: "background: rgba(0,0,0,0.5)",
            div { class: "modal-dialog modal-lg",
                div { class: "modal-content",
                    div { class: "modal-header d-flex justify-content-between align-items-center",
                        h5 { class: "modal-title mb-0", "Manage Tags" }
                        button { type: "button", class: "btn-close", "aria-label": "Close", onclick: move |_| on_close.call(()) }
                    }
                    div { class: "modal-body",
                        if let Some(err) = error() { div { class: "alert alert-danger", "{err}" } }

                        h6 { "Create Tag" }
                        div { class: "input-group mb-3",
                            input { class: "form-control", placeholder: "Tag Name (e.g. Pool A Winner)", value: "{new_tag}", oninput: move |e| { new_tag.set(e.value()); error.set(None); } }
                            button { class: "btn btn-outline-success",
                                onclick: move |_| {
                                    let u = url_sig();
                                    let on_change = on_change.clone();
                                    let name = new_tag().trim().to_string();
                                    if name.is_empty() {
                                        error.set(Some("Tag name is required.".to_string()));
                                        return;
                                    }
                                    if name.contains("::") {
                                        error.set(Some("Tag name cannot contain \"::\".".to_string()));
                                        return;
                                    }
                                    error.set(None);
                                    spawn(async move {
                                        let req = CreateTagRequest { name };
                                        match api::create_tag(&u, &req).await {
                                            Ok(_) => { new_tag.set("".to_string()); on_change.call(()); }
                                            Err(e) => error.set(Some(e)),
                                        }
                                    });
                                },
                                "Create"
                            }
                        }

                        h6 { "Existing Tags" }
                        ul { class: "list-group",
                            {data.tags.iter().map(|tag| {
                                let tag_id = tag.id;
                                let current_team = tag.team.as_deref().unwrap_or("").to_string();
                                let tag_name = tag.name.clone();
                                rsx! {
                                    li { key: "{tag_id}", class: "list-group-item d-flex justify-content-between align-items-center gap-2 flex-wrap",
                                        span { class: "flex-grow-1", "{tag_name}" }
                                        select {
                                            class: "form-select form-select-sm",
                                            style: "max-width: 12rem;",
                                            value: "{current_team}",
                                            onchange: move |e| {
                                                let u = url_sig();
                                                let team_id = e.value();
                                                let on_change = on_change.clone();
                                                spawn(async move {
                                                    let req = UpdateTagsRequest { tag_id, team_id };
                                                    if let Err(e) = api::update_tags(&u, &req).await {
                                                        error.set(Some(e));
                                                    } else {
                                                        error.set(None);
                                                        on_change.call(());
                                                    }
                                                });
                                            },
                                            option { value: "", "No team" }
                                            for opt in &data.team_options {
                                                option { value: "{opt.id}", "{opt.pseudonym.as_deref().unwrap_or(&opt.id)}" }
                                            }
                                        }
                                        button { class: "btn btn-sm btn-outline-danger",
                                            onclick: move |_| {
                                                let u = url_sig();
                                                let on_change = on_change.clone();
                                                spawn(async move {
                                                    match api::delete_tag(&u, tag_id).await {
                                                        Ok(_) => { error.set(None); on_change.call(()); }
                                                        Err(e) => error.set(Some(e)),
                                                    }
                                                });
                                            },
                                            "×"
                                        }
                                    }
                                }
                            })}
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn TableView(
    data: ScheduleSetupResponse, 
    selected_field: String, 
    highlight_team: String, 
    edit_mode: bool,
    tournament_url: String,
    on_edit_match: EventHandler<String>
) -> Element {
    // ... existing filter logic ...
    let matches: Vec<&MatchSetupData> = data.matches.iter().filter(|m| {
        if m.status == "SKIPPED" { return false; }
        if selected_field != "all" {
             if let Some(f_name) = &m.field {
                 let field_id = data.fields.iter().find(|f| &f.name == f_name).map(|f| f.id.to_string());
                 if field_id.as_deref() != Some(selected_field.as_str()) { return false; }
             } else {
                 return false;
             }
        }
        if !highlight_team.is_empty() {
             let ht = highlight_team.to_lowercase();
             let t1 = m.team1.as_ref()
                 .and_then(|id| data.team_options.iter().find(|o| &o.id == id))
                 .and_then(|o| o.pseudonym.as_deref())
                 .map(String::from)
                 .unwrap_or_else(|| m.team1_initial.as_deref().unwrap_or("").to_string())
                 .to_lowercase();
             let t2 = m.team2.as_ref()
                 .and_then(|id| data.team_options.iter().find(|o| &o.id == id))
                 .and_then(|o| o.pseudonym.as_deref())
                 .map(String::from)
                 .unwrap_or_else(|| m.team2_initial.as_deref().unwrap_or("").to_string())
                 .to_lowercase();
             let refs_display = m.refs.as_deref().or(m.refs_initial.as_deref()).unwrap_or("")
                 .split(',').map(|s| s.trim()).filter(|s| !s.is_empty())
                 .map(|token| {
                     data.team_options.iter().find(|o| o.id == token)
                         .and_then(|o| o.pseudonym.as_deref())
                         .map(String::from)
                         .unwrap_or_else(|| token.to_string())
                 })
                 .collect::<Vec<_>>().join(", ").to_lowercase();
             if !t1.contains(&ht) && !t2.contains(&ht) && !refs_display.contains(&ht) { return false; }
        }
        true
    }).collect();

    let base_url = api::base_url();
    rsx! {
        div { class: "table-responsive schedule-table-view",
            table { class: "table table-striped table-hover table-sm align-middle",
                thead {
                    tr {
                        th { "Match" }
                        th { "Field" }
                        th { "Start" }
                        th { "Type" }
                        th { "Status" }
                        th { "Team 1" }
                        th { "Team 2" }
                        th { "Refs" }
                        if edit_mode { th { "Edit" } }
                    }
                }
                tbody {
                    {matches.iter().map(|m| {
                        let match_id = m.uuid.clone();
                        // Team 1 column: only m.team1 / m.team1_initial (first token if comma-separated)
                        let opt1 = m.team1.as_ref().and_then(|id| data.team_options.iter().find(|o| &o.id == id));
                        let t1_raw = opt1.and_then(|o| o.pseudonym.as_deref()).map(String::from)
                            .unwrap_or_else(|| m.team1_initial.as_deref().unwrap_or("").to_string());
                        let t1 = if t1_raw.contains(',') { t1_raw.split(',').next().map(|s| s.trim().to_string()).unwrap_or_default() } else { t1_raw };
                        let photo1 = opt1.and_then(|o| o.profile_photo.clone());
                        // Team 2 column: only m.team2 / m.team2_initial (first token if comma-separated)
                        let opt2 = m.team2.as_ref().and_then(|id| data.team_options.iter().find(|o| &o.id == id));
                        let t2_raw = opt2.and_then(|o| o.pseudonym.as_deref()).map(String::from)
                            .unwrap_or_else(|| m.team2_initial.as_deref().unwrap_or("").to_string());
                        let t2 = if t2_raw.contains(',') { t2_raw.split(',').next().map(|s| s.trim().to_string()).unwrap_or_default() } else { t2_raw };
                        let photo2 = opt2.and_then(|o| o.profile_photo.clone());
                        // Refs column: only m.refs / m.refs_initial (comma-separated list)
                        let refs_list: Vec<(String, Option<String>)> = m.refs.as_deref().or(m.refs_initial.as_deref()).unwrap_or("")
                            .split(',')
                            .map(|s| s.trim())
                            .filter(|s| !s.is_empty())
                            .map(|token| {
                                let opt = data.team_options.iter().find(|o| o.id == token);
                                let display = opt.and_then(|o| o.pseudonym.as_deref()).map(String::from).unwrap_or_else(|| token.to_string());
                                let photo = opt.and_then(|o| o.profile_photo.clone());
                                (display, photo)
                            })
                            .collect();
                        let (t1_kind, t1_label) = team_ref_display(&t1);
                        let (t2_kind, t2_label) = team_ref_display(&t2);
                        let refs_display_list: Vec<(String, Option<String>, u8, String)> = refs_list
                            .iter()
                            .map(|(d, p)| {
                                let (k, l) = team_ref_display(d);
                                (d.clone(), p.clone(), k, l)
                            })
                            .collect();
                        let schedule_type_display = m.schedule_type.as_deref().unwrap_or("-");
                        let (status_color, status_label) = if m.status.is_empty() { ("#e9ecef".to_string(), "-".to_string()) } else { status_color_and_label(&m.status) };
                        rsx! {
                            tr { key: "{m.uuid}",
                                td {
                                    if edit_mode {
                                        "{m.name}"
                                    } else {
                                        Link { to: Route::MatchPageById { url: tournament_url.clone(), match_id: m.uuid.clone() }, class: "text-decoration-none", "{m.name}" }
                                    }
                                }
                                td { "{m.field.as_deref().unwrap_or(\"\")}" }
                                td {
                                    if let Some(t) = &m.nominal_start_time {
                                        "{format_time(t)}"
                                    } else { "-" }
                                }
                                td { "{schedule_type_display}" }
                                td { class: "align-middle",
                                    span {
                                        class: "schedule-timeline-status-tag",
                                        style: "background-color: {status_color};",
                                        "{status_label}"
                                    }
                                }
                                td { class: "align-middle",
                                    div { class: "d-flex align-items-center gap-1",
                                        if t1_kind == 0 {
                                            if let Some(ph) = &photo1 {
                                                img { class: "rounded-circle", style: "width: 1.5em; height: 1.5em; object-fit: cover;", src: "{base_url}/static/{ph}", alt: "" }
                                            } else if !t1.is_empty() {
                                                span { class: "rounded-circle d-inline-flex align-items-center justify-content-center", style: "width: 1.5em; height: 1.5em; font-size: 0.75em; background: #6c757d; color: white;", "{t1.chars().next().unwrap_or('?')}" }
                                            }
                                        }
                                        if t1_kind == 1 { img { class: "team-token-icon icon-primary-svg", src: "{base_url}/static/tag.svg", alt: "Tag" } }
                                        if t1_kind == 2 { img { class: "team-token-icon icon-primary-svg", src: "{base_url}/static/reference.svg", alt: "Reference" } }
                                        span { "{t1_label}" }
                                    }
                                }
                                td { class: "align-middle",
                                    div { class: "d-flex align-items-center gap-1",
                                        if t2_kind == 0 {
                                            if let Some(ph) = &photo2 {
                                                img { class: "rounded-circle", style: "width: 1.5em; height: 1.5em; object-fit: cover;", src: "{base_url}/static/{ph}", alt: "" }
                                            } else if !t2.is_empty() {
                                                span { class: "rounded-circle d-inline-flex align-items-center justify-content-center", style: "width: 1.5em; height: 1.5em; font-size: 0.75em; background: #6c757d; color: white;", "{t2.chars().next().unwrap_or('?')}" }
                                            }
                                        }
                                        if t2_kind == 1 { img { class: "team-token-icon icon-primary-svg", src: "{base_url}/static/tag.svg", alt: "Tag" } }
                                        if t2_kind == 2 { img { class: "team-token-icon icon-primary-svg", src: "{base_url}/static/reference.svg", alt: "Reference" } }
                                        span { "{t2_label}" }
                                    }
                                }
                                td { class: "align-middle",
                                    div { class: "d-flex align-items-center flex-wrap gap-1",
                                        for (ref_display, ref_photo, r_kind, r_label) in &refs_display_list {
                                            span { class: "d-inline-flex align-items-center gap-1",
                                                if *r_kind == 0 {
                                                    if let Some(ph) = ref_photo {
                                                        img { class: "rounded-circle", style: "width: 1.25em; height: 1.25em; object-fit: cover;", src: "{base_url}/static/{ph}", alt: "" }
                                                    } else {
                                                        span { class: "rounded-circle d-inline-flex align-items-center justify-content-center", style: "width: 1.25em; height: 1.25em; font-size: 0.65em; background: #6c757d; color: white;", "{ref_display.chars().next().unwrap_or('?')}" }
                                                    }
                                                }
                                                if *r_kind == 1 { img { class: "team-token-icon icon-primary-svg", src: "{base_url}/static/tag.svg", alt: "Tag" } }
                                                if *r_kind == 2 { img { class: "team-token-icon icon-primary-svg", src: "{base_url}/static/reference.svg", alt: "Reference" } }
                                                span { "{r_label}" }
                                            }
                                        }
                                    }
                                }
                                if edit_mode {
                                    td {
                                        button {
                                            class: "btn btn-sm btn-link",
                                            onclick: move |_| on_edit_match.call(match_id.clone()),
                                            "✎"
                                        }
                                    }
                                }
                            }
                        }
                    })}
                }
            }
        }
    }
}

// ... Scheduler structs ...

#[allow(dead_code)]
#[derive(Serialize)]
struct SchedulerEvent {
    id: String,
    text: String,
    start_date: String,
    end_date: String,
    section_id: String, // Field ID
    color: String,
    team1: String,
    team2: String,
}

#[allow(dead_code)]
#[derive(Serialize)]
struct SchedulerSection {
    key: String,
    label: String,
}

// Internal types for timeline events
#[allow(dead_code)]
#[derive(Clone, Debug)]
struct TimelineEvent {
    id: String,
    name: String,
    team1: String,
    team2: String,
    team1_photo: Option<String>,
    team2_photo: Option<String>,
    refs_display: String, // ref teams as pseudonyms (comma-separated)
    refs_list: Vec<(String, Option<String>)>, // (display_name, profile_photo) for refs
    start_time: chrono::NaiveDateTime,
    end_time: chrono::NaiveDateTime,
    length_min: i64,
    field_id: u32,
    field_name: String,
    color: String, // status color only (for tag); never overwritten for highlight
    status: String,
    schedule_type: Option<String>,
    lane_index: usize,
    num_lanes: usize,
    highlight_playing: bool, // team is team1 or team2
    highlight_ref: bool,     // team is one of refs (matched by pseudonym)
    ribbon: bool,
}

#[derive(Clone, Debug)]
struct JoinGroup {
    name: String,
    time: chrono::NaiveDateTime,
    // For each JOIN match: (field_id, match_uuid)
    field_matches: Vec<(u32, String)>,
}


#[component]
fn ScheduleTimeline(
    data: ScheduleSetupResponse,
    selected_field: String,
    highlight_team: String,
    edit_mode: bool,
    tournament_url: String,
    on_edit_match: EventHandler<String>,
    key_nav: Signal<Option<String>>,
    on_key_nav_consumed: EventHandler<()>,
) -> Element {
    use chrono::Timelike;
    use chrono::NaiveDateTime;
    let navigator = use_navigator();

    // Get browser timezone offset in minutes (local = utc + offset). Only used on wasm.
    fn get_tz_offset_minutes() -> i64 {
        #[cfg(target_arch = "wasm32")]
        {
            let date = js_sys::Date::new_0();
            let offset = date.get_timezone_offset();
            -offset as i64 // get_timezone_offset returns UTC - local, so local = utc - offset
        }
        #[cfg(not(target_arch = "wasm32"))]
        {
            0_i64
        }
    }

    fn parse_schedule_time_to_local(s: &str, tz_offset_minutes: i64) -> Option<NaiveDateTime> {
        let utc_dt = {
            if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(s) {
                dt.naive_utc()
            } else if let Ok(dt) = NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M:%S%.f") {
                dt
            } else if let Ok(dt) = NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M") {
                dt
            } else if let Ok(dt) = NaiveDateTime::parse_from_str(s, "%Y-%m-%d %H:%M") {
                dt
            } else if let Ok(dt) = NaiveDateTime::parse_from_str(s, "%Y-%m-%d %H:%M:%S") {
                dt
            } else {
                return None;
            }
        };
        let local = utc_dt + chrono::Duration::minutes(tz_offset_minutes);
        Some(local)
    }

    let tz_offset_minutes = get_tz_offset_minutes();

    // All match dates in local time (unique, sorted) for prev/next navigation
    let dates_with_matches: Vec<chrono::NaiveDate> = {
        let mut dates: Vec<chrono::NaiveDate> = data.matches.iter()
            .filter(|m| m.status != "SKIPPED")
            .filter_map(|m| m.nominal_start_time.as_ref())
            .filter_map(|s| parse_schedule_time_to_local(s, tz_offset_minutes))
            .map(|dt| dt.date())
            .collect();
        dates.sort();
        dates.dedup();
        dates
    };

    // Today in local time
    let today_local = (chrono::Utc::now() + chrono::Duration::minutes(tz_offset_minutes)).date_naive();

    // Default visible date: today if it has matches, else first day with matches
    let mut visible_date_signal = use_signal(|| {
        if dates_with_matches.contains(&today_local) {
            today_local
        } else {
            dates_with_matches.first().copied().unwrap_or(today_local)
        }
    });

    // React to keyboard nav (n/p/t) from Schedule
    let dates_for_nav = dates_with_matches.clone();
    use_effect(move || {
        let cmd = key_nav();
        if let Some(c) = cmd.as_deref() {
            let dates = dates_for_nav.clone();
            let current = visible_date_signal();
            match c {
                "next" => {
                    if let Some(idx) = dates.iter().position(|&d| d == current) {
                        if let Some(&next_date) = dates.get(idx + 1) {
                            visible_date_signal.set(next_date);
                        }
                    }
                }
                "prev" => {
                    if let Some(idx) = dates.iter().position(|&d| d == current).and_then(|i| i.checked_sub(1)) {
                        if let Some(&prev_date) = dates.get(idx) {
                            visible_date_signal.set(prev_date);
                        }
                    }
                }
                "today" => {
                    if dates.contains(&today_local) {
                        visible_date_signal.set(today_local);
                    } else if let Some(&first) = dates.first() {
                        visible_date_signal.set(first);
                    }
                }
                _ => {}
            }
            on_key_nav_consumed.call(());
        }
    });

    // Filter visible fields
    let visible_fields: Vec<&FieldSetupData> = if selected_field == "all" {
        data.fields.iter().collect()
    } else {
        data.fields.iter()
            .filter(|f| f.id.to_string() == selected_field)
            .collect()
    };

    // Time scale: full day (00:00 to 24:00), 30-minute slots.
    //
    // Important: the schedule times come back as RFC3339 with offsets. We currently
    // convert to UTC for layout. If we used a narrow window like 06:00–22:00,
    // tournaments in some timezones could have all matches fall outside the window
    // after UTC conversion, making the timeline appear empty with no errors.
    const SLOT_MINUTES: i64 = 30;
    const FIRST_HOUR: u32 = 0;
    const LAST_HOUR: u32 = 24;
    let slots_per_day = ((LAST_HOUR - FIRST_HOUR) * 60 / SLOT_MINUTES as u32) as usize;
    
    // Get current visible date value (reactive - will update when signal changes)
    let current_visible_date = visible_date_signal();

    // Build timeline events (non-join matches)
    // Note: We filter by date later when rendering, not here, so all events are available
    let mut timeline_events: Vec<TimelineEvent> = data.matches.iter()
        .filter(|m| m.status != "SKIPPED")
        .filter(|m| m.schedule_type.as_deref() != Some("JOIN"))
        .filter_map(|m| {
            if m.nominal_start_time.is_none() || m.field.is_none() {
                return None;
            }
            
            let start_str = m.nominal_start_time.as_ref()?;
            let start_dt = parse_schedule_time_to_local(start_str, tz_offset_minutes)?;
            let length_min = m.nominal_length.unwrap_or(30) as i64;
            let end_dt = start_dt + chrono::Duration::minutes(length_min);
            
            let field_name = m.field.as_ref()?;
            let field = data.fields.iter().find(|f| &f.name == field_name)?;
            
            // Check if field is visible
            if selected_field != "all" && field.id.to_string() != selected_field {
                return None;
            }
            
            // Don't filter by date here - we'll filter when rendering based on current_visible_date
            // This allows date navigation to work properly
            
            // Display pseudonyms (from registration): prefer team_options pseudonym when team ID is set
            let t1 = m.team1.as_ref()
                .and_then(|id| data.team_options.iter().find(|o| &o.id == id))
                .and_then(|o| o.pseudonym.as_deref())
                .map(String::from)
                .unwrap_or_else(|| m.team1_initial.as_deref().unwrap_or("").to_string());
            let t2 = m.team2.as_ref()
                .and_then(|id| data.team_options.iter().find(|o| &o.id == id))
                .and_then(|o| o.pseudonym.as_deref())
                .map(String::from)
                .unwrap_or_else(|| m.team2_initial.as_deref().unwrap_or("").to_string());
            
            // Team profile photos
            let team1_photo = m.team1.as_ref()
                .and_then(|id| data.team_options.iter().find(|o| &o.id == id))
                .and_then(|o| o.profile_photo.clone());
            let team2_photo = m.team2.as_ref()
                .and_then(|id| data.team_options.iter().find(|o| &o.id == id))
                .and_then(|o| o.profile_photo.clone());
            // Refs as list of (display_name, profile_photo)
            let refs_list: Vec<(String, Option<String>)> = m.refs.as_deref().or(m.refs_initial.as_deref()).unwrap_or("")
                .split(',')
                .map(|s| s.trim())
                .filter(|s| !s.is_empty())
                .map(|token| {
                    let opt = data.team_options.iter().find(|o| o.id == token);
                    let display = opt.and_then(|o| o.pseudonym.as_deref()).map(String::from).unwrap_or_else(|| token.to_string());
                    let photo = opt.and_then(|o| o.profile_photo.clone());
                    (display, photo)
                })
                .collect();
            let refs_display = refs_list.iter().map(|(d, _)| d.as_str()).collect::<Vec<_>>().join(", ");
            
            // Status tag palette only (never overwritten for highlight; highlight is on the block)
            let (color, _) = status_color_and_label(&m.status);
            
            // Highlight: match against pseudonyms only (t1/t2/refs_display are already pseudonyms)
            let (highlight_playing, highlight_ref) = if highlight_team.is_empty() {
                (false, false)
            } else {
                let ht = highlight_team.to_lowercase();
                let playing = t1.to_lowercase().contains(&ht) || t2.to_lowercase().contains(&ht);
                let reffing = !playing && refs_display.to_lowercase().contains(&ht);
                (playing, reffing)
            };
            
            Some(TimelineEvent {
                id: m.uuid.clone(),
                name: m.name.clone(),
                team1: t1,
                team2: t2,
                team1_photo,
                team2_photo,
                refs_display,
                refs_list,
                start_time: start_dt,
                end_time: end_dt,
                length_min,
                field_id: field.id,
                field_name: field.name.clone(),
                color: color.to_string(),
                status: m.status.clone(),
                schedule_type: m.schedule_type.clone(),
                lane_index: 0, // Will be computed below
                num_lanes: 1,  // Will be computed below
                highlight_playing,
                highlight_ref,
                ribbon: m.ribbon,
            })
        })
        .collect();

    // Helper: get start_slot and end_slot for an event on current_visible_date
    let event_slots = |e: &TimelineEvent| -> (usize, usize) {
        let start_slot = {
            if e.start_time.date() != current_visible_date {
                0
            } else {
                let hour = e.start_time.hour();
                let minute = e.start_time.minute();
                if hour < FIRST_HOUR || hour >= LAST_HOUR {
                    0
                } else {
                    let total_minutes = (hour - FIRST_HOUR) * 60 + minute;
                    (total_minutes as i64 / SLOT_MINUTES) as usize
                }
            }
        };
        let end_slot = {
            if e.end_time.date() != current_visible_date {
                slots_per_day
            } else {
                let hour = e.end_time.hour();
                let minute = e.end_time.minute();
                if hour < FIRST_HOUR || hour >= LAST_HOUR {
                    slots_per_day
                } else {
                    let total_minutes = (hour - FIRST_HOUR) * 60 + minute;
                    ((total_minutes as i64 / SLOT_MINUTES) as usize).max(start_slot + 1)
                }
            }
        };
        (start_slot, end_slot)
    };

    // Compute lanes for overlapping events per field (ignore JOIN and SKIPPED for overlap)
    for field in &visible_fields {
        // Only non-JOIN, non-SKIPPED events participate in lane assignment
        let field_event_indices: Vec<usize> = timeline_events.iter()
            .enumerate()
            .filter(|(_, e)| {
                e.field_id == field.id
                    && e.start_time.date() == current_visible_date
                    && e.schedule_type.as_deref() != Some("JOIN")
                    && e.status != "SKIPPED"
            })
            .map(|(i, _)| i)
            .collect();

        if field_event_indices.is_empty() {
            continue;
        }

        // Sort by start time
        let mut sorted_indices = field_event_indices.clone();
        sorted_indices.sort_by_key(|&idx| timeline_events[idx].start_time);

        // Track which lanes are occupied at each slot
        let mut slot_lanes: Vec<std::collections::HashSet<usize>> =
            vec![std::collections::HashSet::new(); slots_per_day];

        // Assign lanes to events
        for &idx in &sorted_indices {
            let event = &timeline_events[idx];
            let (start_slot, end_slot) = event_slots(event);

            // Find first available lane that doesn't conflict
            let mut assigned_lane = 0;
            'lane_search: loop {
                let mut has_conflict = false;
                for slot in start_slot..end_slot.min(slots_per_day) {
                    if slot_lanes[slot].contains(&assigned_lane) {
                        has_conflict = true;
                        break;
                    }
                }
                if !has_conflict {
                    break 'lane_search;
                }
                assigned_lane += 1;
            }

            for slot in start_slot..end_slot.min(slots_per_day) {
                slot_lanes[slot].insert(assigned_lane);
            }

            timeline_events[idx].lane_index = assigned_lane;
        }

        // num_lanes per event = lanes used in this event's time range only (not field-wide)
        for &idx in &field_event_indices {
            let (start_slot, end_slot) = event_slots(&timeline_events[idx]);
            let max_lane_in_range = (start_slot..end_slot.min(slots_per_day))
                .flat_map(|slot| slot_lanes[slot].iter().copied())
                .max()
                .unwrap_or(0);
            timeline_events[idx].num_lanes = (max_lane_in_range + 1).max(1);
        }
    }

    // Build join groups
    let join_groups: Vec<JoinGroup> = {
        use std::collections::HashMap;
        let mut groups: HashMap<String, Vec<&MatchSetupData>> = HashMap::new();
        
        for m in &data.matches {
            if m.status == "SKIPPED" {
                continue;
            }
            if m.schedule_type.as_deref() == Some("JOIN") {
                groups.entry(m.name.clone()).or_insert_with(Vec::new).push(m);
            }
        }
        
        groups.into_iter().filter_map(|(name, matches)| {
            if matches.is_empty() {
                return None;
            }
            
            // Get time from first match (in local time)
            let time_str = matches[0].nominal_start_time.as_ref()?;
            let time_dt = parse_schedule_time_to_local(time_str, tz_offset_minutes)?;
            
            // Build per-field join matches (field_id -> match_uuid)
            let field_matches: Vec<(u32, String)> = matches
                .iter()
                .filter_map(|m| {
                    let field_name = m.field.as_ref()?;
                    let field_id = data.fields.iter().find(|f| &f.name == field_name).map(|f| f.id)?;
                    Some((field_id, m.uuid.clone()))
                })
                .filter(|(field_id, _)| selected_field == "all" || field_id.to_string() == selected_field)
                .collect();

            if field_matches.is_empty() {
                return None;
            }
            
            Some(JoinGroup {
                name: name.clone(),
                time: time_dt,
                field_matches,
            })
        }).collect()
    };

    // Pre-compute slot time strings
    let slot_times: Vec<String> = (0..slots_per_day)
        .map(|slot| {
            let minutes = (slot as u32) * SLOT_MINUTES as u32;
            let hour = FIRST_HOUR + minutes / 60;
            let minute = minutes % 60;
            format!("{:02}:{:02}", hour, minute)
        })
        .collect();
    
    // Pre-compute join line data with slots
    #[allow(dead_code)]
    struct JoinLineData {
        slot: usize,
        join: JoinGroup,
        time_str: String,
        start_col_idx: usize,
        end_col_idx: usize,
        // (visible field column index, match uuid)
        field_items: Vec<(usize, String)>,
    }
    
    let join_lines_data: Vec<JoinLineData> = join_groups.iter()
        .filter_map(|join| {
            let date = join.time.date();
            if date != current_visible_date {
                return None;
            }
            let hour = join.time.hour();
            let minute = join.time.minute();
            if hour < FIRST_HOUR || hour >= LAST_HOUR {
                return None;
            }
            let total_minutes = (hour - FIRST_HOUR) * 60 + minute;
            let slot = (total_minutes as i64 / SLOT_MINUTES) as usize;
            let time_str = join.time.format("%H:%M").to_string();
            
            let field_items: Vec<(usize, String)> = visible_fields
                .iter()
                .enumerate()
                .filter_map(|(col_idx, f)| {
                    join.field_matches
                        .iter()
                        .find(|(fid, _)| *fid == f.id)
                        .map(|(_, mid)| (col_idx, mid.clone()))
                })
                .collect();
            
            if field_items.is_empty() {
                return None;
            }
            
            let start_col_idx = field_items.iter().map(|(c, _)| *c).min().unwrap_or(0);
            let end_col_idx = field_items.iter().map(|(c, _)| *c).max().unwrap_or(0);
            
            Some(JoinLineData {
                slot,
                join: join.clone(),
                time_str,
                start_col_idx,
                end_col_idx,
                field_items,
            })
        })
        .collect();

    // Target row for auto-scroll: first match of the day, or current time if viewing today
    let first_match_slot = {
        let event_slots = timeline_events.iter()
            .filter(|e| e.start_time.date() == current_visible_date)
            .map(|e| {
                let h = e.start_time.hour();
                let m = e.start_time.minute();
                ((h - FIRST_HOUR) * 60 + m) as i64 / SLOT_MINUTES
            })
            .map(|s| s as usize);
        let join_slots = join_lines_data.iter().map(|j| j.slot);
        event_slots.chain(join_slots).min().unwrap_or(0)
    };
    let target_slot = if current_visible_date == today_local {
        let now_local = chrono::Utc::now() + chrono::Duration::minutes(tz_offset_minutes);
        let hour = now_local.hour();
        let minute = now_local.minute();
        let slot = ((hour - FIRST_HOUR) * 60 + minute) as i64 / SLOT_MINUTES;
        (slot as usize).min(slots_per_day.saturating_sub(1))
    } else {
        first_match_slot
    };

    // Auto-scroll only the timeline body to target row (do not scroll the page)
    use_effect(move || {
        let _ = visible_date_signal(); // re-run effect when date changes
        let slot = target_slot;
        #[cfg(target_arch = "wasm32")]
        {
            let id = format!("schedule-timeline-slot-{}", slot);
            wasm_bindgen_futures::spawn_local(async move {
                gloo_timers::future::TimeoutFuture::new(100).await;
                if let Some(window) = web_sys::window() {
                    if let Some(doc) = window.document() {
                        if let (Some(scroll_el), Some(target_el)) = (
                            doc.get_element_by_id("schedule-timeline-scroll"),
                            doc.get_element_by_id(&id),
                        ) {
                            let scroll_rect = scroll_el.get_bounding_client_rect();
                            let target_rect = target_el.get_bounding_client_rect();
                            let delta = target_rect.top() - scroll_rect.top();
                            let new_scroll_top = scroll_el.scroll_top() + delta as i32;
                            scroll_el.set_scroll_top(new_scroll_top.max(0));
                        }
                    }
                }
            });
        }
        #[cfg(not(target_arch = "wasm32"))]
        {
            let _ = slot;
        }
    });

    const TIME_COL_WIDTH_PX: u32 = 80;
    let base_url = api::base_url();
    
    rsx! {
        div { class: "schedule-timeline-wrapper", id: "schedule-timeline-wrapper",
            div { class: "schedule-timeline-nav",
                {
                    let dates = dates_with_matches.clone();
                    let current = visible_date_signal();
                    let current_idx = dates.iter().position(|&d| d == current);
                    let has_prev = current_idx.and_then(|i| i.checked_sub(1)).and_then(|i| dates.get(i)).is_some();
                    let has_next = current_idx.map(|i| i + 1 < dates.len()).unwrap_or(false);
                    let dates_prev = dates_with_matches.clone();
                    let dates_today = dates_with_matches.clone();
                    let dates_next = dates_with_matches.clone();
                    rsx! {
                        button {
                            class: "btn btn-sm btn-outline-secondary",
                            disabled: !has_prev,
                            onclick: move |_| {
                                let d = dates_prev.clone();
                                let current = visible_date_signal();
                                if let Some(idx) = d.iter().position(|&d2| d2 == current).and_then(|i| i.checked_sub(1)) {
                                    if let Some(&prev_date) = d.get(idx) {
                                        visible_date_signal.set(prev_date);
                                    }
                                }
                            },
                            "← Prev"
                        }
                        button {
                            class: "btn btn-sm btn-outline-secondary",
                            onclick: move |_| {
                                if dates_today.contains(&today_local) {
                                    visible_date_signal.set(today_local);
                                } else if let Some(&first) = dates_today.first() {
                                    visible_date_signal.set(first);
                                }
                            },
                            "Today"
                        }
                        button {
                            class: "btn btn-sm btn-outline-secondary",
                            disabled: !has_next,
                            onclick: move |_| {
                                let d = dates_next.clone();
                                let current = visible_date_signal();
                                if let Some(idx) = d.iter().position(|&d2| d2 == current) {
                                    if let Some(&next_date) = d.get(idx + 1) {
                                        visible_date_signal.set(next_date);
                                    }
                                }
                            },
                            "Next →"
                        }
                        span { class: "schedule-timeline-date",
                            " {visible_date_signal().format(\"%A, %B %d\")}"
                        }
                    }
                }
            }
            div { class: "schedule-timeline-scroll", id: "schedule-timeline-scroll",
                div {
                    class: "schedule-timeline",
                    // Important: this is the positioning container for join overlays.
                    style: "position: relative; --num-fields: {visible_fields.len()}; --time-col-width: {TIME_COL_WIDTH_PX}px;",
                    div { class: "schedule-timeline-header",
                    div { class: "schedule-timeline-time-col", "Time" }
                    for field in &visible_fields {
                        div { class: "schedule-timeline-field-col", "{field.name}" }
                    }
                }
                div { class: "schedule-timeline-body",
                    for (slot, time_str) in (0..slots_per_day).zip(slot_times.iter()) {
                        {
                            let row_id = format!("schedule-timeline-slot-{}", slot);
                            rsx! {
                                div { class: "schedule-timeline-row", key: "{slot}",
                            div { class: "schedule-timeline-time-col", id: "{row_id}", "{time_str}" }
                            for (col_idx, field) in visible_fields.iter().enumerate() {
                                div {
                                    class: "schedule-timeline-cell",
                                    key: "{field.id}-{slot}",
                                    {
                                        // Render events that start in this slot
                                        let events_in_slot: Vec<&TimelineEvent> = timeline_events.iter()
                                            .filter(|e| {
                                                if e.field_id != field.id {
                                                    return false;
                                                }
                                                let date = e.start_time.date();
                                                if date != current_visible_date {
                                                    return false;
                                                }
                                                let hour = e.start_time.hour();
                                                let minute = e.start_time.minute();
                                                if hour < FIRST_HOUR || hour >= LAST_HOUR {
                                                    return false;
                                                }
                                                let total_minutes = (hour - FIRST_HOUR) * 60 + minute;
                                                let event_slot = (total_minutes as i64 / SLOT_MINUTES) as usize;
                                                event_slot == slot
                                            })
                                            .collect();
                                        
                                        // Pre-compute event rendering data if there are events
                                        let event_render_data_opt = if !events_in_slot.is_empty() {
                                            let max_lanes = events_in_slot.first().map(|e| e.num_lanes).unwrap_or(1);
                                            Some(events_in_slot.iter().map(|event| {
                                                // Size blocks from nominal length so a 30-min match is exactly 1 slot.
                                                let duration_slots: usize =
                                                    ((event.length_min + SLOT_MINUTES - 1) / SLOT_MINUTES).max(1) as usize;
                                                let width_pct = 100.0 / max_lanes as f64;
                                                let left_pct = (event.lane_index as f64) * width_pct;
                                                (event.id.clone(), width_pct, left_pct, duration_slots)
                                            }).collect::<Vec<_>>())
                                        } else {
                                            None
                                        };
                                        
                                        // Join at this (slot, col_idx): horizontal line in cell; label in edit mode
                                        let join_in_cell = join_lines_data.iter().find_map(|jl| {
                                            if jl.slot != slot { return None; }
                                            jl.field_items.iter()
                                                .find(|(c, _)| *c == col_idx)
                                                .map(|(_, mid)| (jl.join.name.clone(), mid.clone()))
                                        });
                                        
                                        rsx! {
                                            if let Some(event_render_data) = event_render_data_opt {
                                                div {
                                                    class: "schedule-timeline-event-container",
                                                    for (idx, event) in events_in_slot.iter().enumerate() {
                                                        {
                                                            let (event_id, width_pct, left_pct, duration_slots) = &event_render_data[idx];
                                                            let event_id_clone = event_id.clone();
                                                            let (_, status_label) = status_color_and_label(&event.status);

                                                            let is_break = event.schedule_type.as_deref() == Some("BREAK");
                                                            let event_style = format!("background-color: #ffffff; width: {}%; left: {}%; height: calc({} * var(--slot-height)); position: absolute; top: 0;", width_pct, left_pct, duration_slots);
                                                            let event_title = if is_break { event.name.clone() } else { format!("{} - {} vs {}", event.name, event.team1, event.team2) };
                                                            let url_clone = tournament_url.clone();
                                                            let nav = navigator.clone();
                                                            let event_class = format!(
                                                                "schedule-timeline-event{}{}",
                                                                if event.highlight_playing { " schedule-timeline-event--highlight-playing" } else { "" },
                                                                if event.highlight_ref { " schedule-timeline-event--highlight-ref" } else { "" }
                                                            );
                                                            let (t1_kind, t1_label) = team_ref_display(&event.team1);
                                                            let (t2_kind, t2_label) = team_ref_display(&event.team2);
                                                            let event_refs: Vec<(String, Option<String>, u8, String)> = event.refs_list
                                                                .iter()
                                                                .map(|(d, p)| {
                                                                    let (k, l) = team_ref_display(d);
                                                                    (d.clone(), p.clone(), k, l)
                                                                })
                                                                .collect();
                                                            rsx! {
                                                                div {
                                                                    class: "{event_class}",
                                                                    style: "{event_style}",
                                                                    title: "{event_title}",
                                                                    cursor: if is_break && !edit_mode { "default" } else { "pointer" },
                                                                    onclick: move |_| {
                                                                        if is_break && !edit_mode {
                                                                            // Break matches don't link anywhere
                                                                        } else if edit_mode {
                                                                            on_edit_match.call(event_id_clone.clone());
                                                                        } else {
                                                                            nav.push(Route::MatchPageById { url: url_clone.clone(), match_id: event_id_clone.clone() });
                                                                        }
                                                                    },
                                                                    span {
                                                                        class: "schedule-timeline-status-tag schedule-timeline-status-tag--corner",
                                                                        style: "background-color: {event.color};",
                                                                        "{status_label}"
                                                                    }
                                                                    div { class: "schedule-timeline-event-header",
                                                                        div { class: "schedule-timeline-event-name", "{event.name}" }
                                                                    }
                                                                    if !is_break {
                                                                        div { class: "schedule-timeline-event-teams d-flex align-items-center flex-wrap gap-1",
                                                                            span { class: "d-inline-flex align-items-center gap-1",
                                                                                if t1_kind == 0 {
                                                                                    if let Some(ph) = &event.team1_photo {
                                                                                        img { class: "rounded-circle", style: "width: 1.25em; height: 1.25em; object-fit: cover;", src: "{base_url}/static/{ph}", alt: "" }
                                                                                    } else {
                                                                                        span { class: "team-token-avatar rounded-circle d-inline-flex align-items-center justify-content-center", style: "width: 1.25em; height: 1.25em; font-size: 0.7em; background: #6c757d; color: white;", "{event.team1.chars().next().unwrap_or('?')}" }
                                                                                    }
                                                                                }
                                                                                if t1_kind == 1 { img { class: "team-token-icon icon-primary-svg", src: "{base_url}/static/tag.svg", alt: "Tag" } }
                                                                                if t1_kind == 2 { img { class: "team-token-icon icon-primary-svg", src: "{base_url}/static/reference.svg", alt: "Reference" } }
                                                                                span { "{t1_label}" }
                                                                            }
                                                                            span { " vs " }
                                                                            span { class: "d-inline-flex align-items-center gap-1",
                                                                                if t2_kind == 0 {
                                                                                    if let Some(ph) = &event.team2_photo {
                                                                                        img { class: "rounded-circle", style: "width: 1.25em; height: 1.25em; object-fit: cover;", src: "{base_url}/static/{ph}", alt: "" }
                                                                                    } else {
                                                                                        span { class: "team-token-avatar rounded-circle d-inline-flex align-items-center justify-content-center", style: "width: 1.25em; height: 1.25em; font-size: 0.7em; background: #6c757d; color: white;", "{event.team2.chars().next().unwrap_or('?')}" }
                                                                                    }
                                                                                }
                                                                                if t2_kind == 1 { img { class: "team-token-icon icon-primary-svg", src: "{base_url}/static/tag.svg", alt: "Tag" } }
                                                                                if t2_kind == 2 { img { class: "team-token-icon icon-primary-svg", src: "{base_url}/static/reference.svg", alt: "Reference" } }
                                                                                span { "{t2_label}" }
                                                                            }
                                                                        }
                                                                        if !event.refs_list.is_empty() {
                                                                            div { class: "schedule-timeline-event-refs d-flex align-items-center flex-wrap gap-1 mt-1",
                                                                                span { class: "me-1", "Refs:" }
                                                                                for (ref_display, ref_photo, r_kind, r_label) in &event_refs {
                                                                                    span { class: "d-inline-flex align-items-center gap-1",
                                                                                        if *r_kind == 0 {
                                                                                            if let Some(ph) = ref_photo {
                                                                                                img { class: "rounded-circle", style: "width: 1.1em; height: 1.1em; object-fit: cover;", src: "{base_url}/static/{ph}", alt: "" }
                                                                                            } else {
                                                                                                span { class: "team-token-avatar rounded-circle d-inline-flex align-items-center justify-content-center", style: "width: 1.1em; height: 1.1em; font-size: 0.65em; background: #6c757d; color: white;", "{ref_display.chars().next().unwrap_or('?')}" }
                                                                                            }
                                                                                        }
                                                                                        if *r_kind == 1 { img { class: "team-token-icon icon-primary-svg", src: "{base_url}/static/tag.svg", alt: "Tag" } }
                                                                                        if *r_kind == 2 { img { class: "team-token-icon icon-primary-svg", src: "{base_url}/static/reference.svg", alt: "Reference" } }
                                                                                        span { "{r_label}" }
                                                                                    }
                                                                                }
                                                                            }
                                                                        }
                                                                    }
                                                                    if event.ribbon {
                                                                        span {
                                                                            class: "schedule-timeline-ribbon-icon",
                                                                            title: "This is a ribbon game",
                                                                            img { src: "{base_url}/static/ribbon.svg", alt: "Ribbon game" }
                                                                        }
                                                                    }
                                                                }
                                                            }
                                                        }
                                                }
                                            }
                                            }
                                            else {
                                                div {}
                                            }
                                            if let Some((join_name, match_id)) = join_in_cell {
                                                div {
                                                    class: "schedule-timeline-join-in-cell",
                                                    div { class: "schedule-timeline-join-line-in-cell" }
                                                    if edit_mode {
                                                        div {
                                                            class: "schedule-timeline-join-label",
                                                            onclick: move |_| on_edit_match.call(match_id.clone()),
                                                            "{join_name}"
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
                }
            }
        }
    }
}

#[component]
fn EditMatchModal(
    tournament_url: String, 
    match_id: String, 
    data: ScheduleSetupResponse,
    on_close: EventHandler<()>, 
    on_save: EventHandler<()>
) -> Element {
    let match_data = data.matches.iter().find(|m| m.uuid == match_id).cloned();
    
    if match_data.is_none() {
        return rsx! { div { "Match not found" } };
    }
    
    let m = match_data.unwrap();
    
    let name = use_signal(|| m.name.clone());
    let mut field = use_signal(|| m.field.clone().unwrap_or_default());
    let schedule_type = use_signal(|| m.schedule_type.clone().unwrap_or("STATIC".to_string()));
    let mut length = use_signal(|| m.nominal_length.unwrap_or(60));
    
    let start_time_init = if let Some(t) = &m.nominal_start_time {
        // Format for datetime-local: YYYY-MM-DDTHH:MM
        if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(t) {
            dt.format("%Y-%m-%dT%H:%M").to_string()
        } else {
            t.chars().take(16).collect::<String>()
        }
    } else {
        "".to_string()
    };
    
    let start_time = use_signal(|| start_time_init);
    let mut previous_match_id = use_signal(|| m.previous_match.clone().unwrap_or_default());
    let mut refs = use_signal(|| m.refs_initial.clone().or(m.refs.clone()).unwrap_or_default());
    let mut team1 = use_signal(|| m.team1_initial.clone().or(m.team1.clone()).unwrap_or_default());
    let mut team2 = use_signal(|| m.team2_initial.clone().or(m.team2.clone()).unwrap_or_default());
    let mut set_type = use_signal(|| m.set_type.clone().unwrap_or("SETS".to_string()));
    let mut nsets = use_signal(|| m.nsets.unwrap_or(3));
    let mut stones_per_set = use_signal(|| m.stones_per_set.unwrap_or(100));
    let ribbon = use_signal(|| m.ribbon);
    let mut skip_condition = use_signal(|| m.skip_condition.clone().unwrap_or_default());
    let mut skip_condition_error = use_signal(|| None::<String>);
    let mut skip_condition_simplified = use_signal(|| None::<String>);
    let mut skip_condition_cursor = use_signal(|| None::<usize>);
    let mut skip_condition_cursor_pos = use_signal(|| None::<usize>);
    let mut skip_docs_visible = use_signal(|| false);
    let mut skip_bracket_ac_visible = use_signal(|| false);
    let mut skip_bracket_ac_team = use_signal(|| true);
    let mut skip_bracket_ac_index = use_signal(|| 0usize);
    let mut skip_condition_help_open = use_signal(|| false);

    #[cfg(target_arch = "wasm32")]
    use_effect(move || {
        let pos = skip_condition_cursor();
        if let Some(p) = pos {
            skip_condition_cursor.set(None);
            let id = "skip-condition-input-edit".to_string();
            spawn(async move {
                gloo_timers::future::TimeoutFuture::new(0).await;
                if let Some(window) = web_sys::window() {
                    if let Some(doc) = window.document() {
                        if let Ok(Some(el)) = doc.query_selector(&format!("#{}", id)) {
                            if let Ok(input) = el.dyn_into::<web_sys::HtmlInputElement>() {
                                let _ = input.set_selection_range(p as u32, p as u32);
                                let _ = input.focus();
                            }
                        }
                    }
                }
            });
        }
    });

    let mut error = use_signal(|| None::<String>);
    let mut saving = use_signal(|| false);
    let url_sig = use_signal(|| tournament_url.clone());

    // Sync field and previous_match_id from match data when modal opens (fixes initial display)
    let match_id_effect = match_id.clone();
    let data_effect = data.clone();
    use_effect(move || {
        if let Some(m) = data_effect.matches.iter().find(|x| x.uuid == match_id_effect) {
            field.set(m.field.clone().unwrap_or_default());
            previous_match_id.set(m.previous_match.clone().unwrap_or_default());
        }
    });

    let matches_on_field_edit = matches_on_field_sorted(&data.matches, &field(), Some(&match_id));

    // When field changes, clear previous match so user must pick one on the new field
    let data_field_edit = data.clone();
    let match_id_for_field = match_id.clone();
    let mut on_field_change_edit = move |new_field: String| {
        field.set(new_field.clone());
        previous_match_id.set("".to_string());
        if !new_field.is_empty() {
            let list = matches_on_field_sorted(&data_field_edit.matches, &new_field, Some(&match_id_for_field));
            if let Some(prev) = list.first() {
                length.set(prev.nominal_length.unwrap_or(60));
                set_type.set(prev.set_type.clone().unwrap_or_else(|| "SETS".to_string()));
                nsets.set(prev.nsets.unwrap_or(3));
                stones_per_set.set(prev.stones_per_set.unwrap_or(100));
            }
        }
    };

    let u_save = tournament_url.clone();
    let m_id_save = match_id.clone();
    let data_save = data.clone();
    let do_save_rc: Rc<RefCell<Box<dyn FnMut()>>> = Rc::new(RefCell::new(Box::new(move || {
        // Validation: BREAK, JOIN, FAST, SAFE require previous match and same field
        let st = schedule_type();
        if st == "BREAK" || st == "JOIN" || st == "FAST" || st == "SAFE" {
            let prev_id = previous_match_id().trim().to_string();
            if prev_id.is_empty() {
                error.set(Some("Previous match is required for Break, Join, Fast, and Safe matches.".to_string()));
                return;
            }
            let current_field = field();
            if let Some(prev_m) = data_save.matches.iter().find(|x| x.uuid == prev_id) {
                if prev_m.field.as_deref() != Some(current_field.as_str()) {
                    error.set(Some("Previous match must be on the same field.".to_string()));
                    return;
                }
            }
        }
        let tournament_url = u_save.clone();
        let match_id = m_id_save.clone();
        let on_save = on_save.clone();
        saving.set(true);
        error.set(None);
        spawn(async move {
            if (schedule_type() == "SAFE" || schedule_type() == "FAST") && !skip_condition().trim().is_empty() {
                match api::validate_dsl(&tournament_url, &skip_condition()).await {
                    Ok(res) => {
                        if !res.valid {
                            skip_condition_error.set(res.error);
                            skip_condition_simplified.set(None);
                            saving.set(false);
                            return;
                        }
                        skip_condition_simplified.set(res.simplified);
                    }
                    Err(e) => {
                        skip_condition_error.set(Some(e));
                        skip_condition_simplified.set(None);
                        saving.set(false);
                        return;
                    }
                }
            }
            let refs_vec: Vec<String> = refs().split(',').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect();
            let len = if schedule_type() == "JOIN" {
                Some(0u32)
            } else {
                Some(length())
            };
            let req = UpdateMatchRequest {
                name: Some(name()),
                field: Some(field()),
                schedule_type: Some(schedule_type()),
                length: len,
                start_time: if start_time().is_empty() { None } else { Some(start_time()) },
                previous_match_id: Some(previous_match_id()),
                refs: Some(refs_vec),
                team1: Some(team1()),
                team2: Some(team2()),
                set_type: Some(set_type()),
                nsets: Some(nsets()),
                stones_per_set: Some(stones_per_set()),
                ribbon: Some(ribbon()),
                skip_condition: Some(skip_condition()),
            };
            match api::update_match(&tournament_url, &match_id, &req).await {
                Ok(_) => { saving.set(false); on_save.call(()); }
                Err(e) => { error.set(Some(e)); saving.set(false); }
            }
        });
    })));
    let do_save_rc2 = do_save_rc.clone();
    let do_save_rc3 = do_save_rc.clone();
    let onsubmit = move |ev: Event<FormData>| {
        ev.prevent_default();
        do_save_rc.borrow_mut()();
    };
    let form_keydown = move |ev: Event<KeyboardData>| {
        let key = ev.key().to_string();
        if key == "Enter" {
            if ev.modifiers().contains(Modifiers::SHIFT) {
                ev.prevent_default();
                ev.stop_propagation();
                do_save_rc2.borrow_mut()();
            } else {
                ev.prevent_default();
            }
        }
    };
    let modal_keydown = move |ev: Event<KeyboardData>| {
        let key = ev.key().to_string();
        if key == "Escape" {
            ev.prevent_default();
            on_close.call(());
        } else if key == "Enter" && ev.modifiers().contains(Modifiers::SHIFT) {
            ev.prevent_default();
            ev.stop_propagation();
            do_save_rc3.borrow_mut()();
        }
    };

    let sc_val_edit = skip_condition();
    let cursor_char_edit = skip_condition_cursor_pos();
    let innermost_edit = cursor_char_edit.and_then(|c| skip_condition_innermost_around_cursor(&sc_val_edit, c));
    let cursor_byte_edit = cursor_char_edit.map(|c| skip_condition_cursor_byte(&sc_val_edit, c)).unwrap_or(0);
    let show_skip_docs_edit = matches!(innermost_edit, Some(InnermostBracket::Paren(_, _)));
    let docs_prefix_edit = match &innermost_edit {
        Some(InnermostBracket::Paren(cs, ce)) => {
            sc_val_edit[*cs..*ce].trim().split_whitespace().next().unwrap_or("").to_lowercase()
        }
        _ => String::new(),
    };
    let docs_filtered_edit: Vec<_> = if show_skip_docs_edit {
        DSL_FUNCTIONS
            .iter()
            .filter(|(n, _)| n.to_lowercase().starts_with(docs_prefix_edit.as_str()))
            .take(12)
            .collect()
    } else {
        vec![]
    };
    let (bracket_is_team_edit, bracket_query_edit) = match &innermost_edit {
        Some(InnermostBracket::Square(cs, ce)) => {
            let end = (*ce).min(cursor_byte_edit).max(*cs);
            (true, sc_val_edit[*cs..end].trim().to_lowercase())
        }
        Some(InnermostBracket::Curly(cs, ce)) => {
            let end = (*ce).min(cursor_byte_edit).max(*cs);
            (false, sc_val_edit[*cs..end].trim().to_lowercase())
        }
        _ => (true, String::new()),
    };
    let show_bracket_ac_edit = matches!(innermost_edit, Some(InnermostBracket::Square(_, _)) | Some(InnermostBracket::Curly(_, _)));
    let bracket_ac_idx_edit_raw = skip_bracket_ac_index();
    let bracket_options_edit: Vec<(String, String, Option<String>)> = if show_bracket_ac_edit && bracket_is_team_edit {
        let team_opts_edit: Vec<_> = data
            .team_options
            .iter()
            .filter(|t| {
                let disp = t.pseudonym.as_deref().unwrap_or(t.id.as_str());
                disp.to_lowercase().contains(bracket_query_edit.as_str())
                    || t.id.to_lowercase().contains(bracket_query_edit.as_str())
            })
            .map(|t| {
                (
                    t.id.clone(),
                    t.pseudonym.clone().unwrap_or_else(|| t.id.clone()),
                    t.profile_photo.clone(),
                )
            })
            .take(15)
            .collect();
        let match_qual_opts_edit: Vec<_> = data
            .matches
            .iter()
            .flat_map(|m| {
                let w = (format!("{}::winner", m.name), format!("{}::winner", m.name), None);
                let l = (format!("{}::loser", m.name), format!("{}::loser", m.name), None);
                [w, l]
            })
            .filter(|(s, _, _)| s.to_lowercase().contains(bracket_query_edit.as_str()))
            .take(15)
            .collect();
        team_opts_edit
            .into_iter()
            .chain(match_qual_opts_edit)
            .take(15)
            .collect()
    } else if show_bracket_ac_edit {
        data.matches
            .iter()
            .filter(|m| m.name.to_lowercase().contains(bracket_query_edit.as_str()))
            .map(|m| (m.name.clone(), m.name.clone(), None))
            .take(15)
            .collect()
    } else {
        vec![]
    };
    let bracket_ac_idx_edit = bracket_ac_idx_edit_raw.min(bracket_options_edit.len().saturating_sub(1));
    let docs_items_edit: Vec<_> = if show_skip_docs_edit && !docs_filtered_edit.is_empty() {
        docs_filtered_edit
            .iter()
            .map(|(dn, ds)| {
                let fname = dn.to_string();
                rsx! {
                    li {
                        class: "py-1 px-2 rounded",
                        onclick: move |_| {
                            let v = skip_condition();
                            if let Some(i) = v.rfind('(') {
                                skip_condition.set(format!("{}{}", &v[..=i], fname));
                            }
                            skip_docs_visible.set(false);
                        },
                        span { class: "fw-medium text-primary", "{dn}" }
                        span { class: "text-muted ms-1", " {ds}" }
                    }
                }
            })
            .collect()
    } else {
        vec![]
    };
    let base_url_edit = api::base_url();
    let bracket_option_items_edit: Vec<_> = if show_bracket_ac_edit && !bracket_options_edit.is_empty() {
        bracket_options_edit
            .iter()
            .enumerate()
            .map(|(idx, (insert_val, display_val, photo))| {
                let opt_insert = insert_val.clone();
                let opt_display = display_val.clone();
                let opt_photo = photo.clone();
                let is_team = bracket_is_team_edit;
                let is_cur = bracket_ac_idx_edit == idx;
                let li_class = if is_cur {
                    "py-1 px-2 rounded bg-primary text-white"
                } else {
                    "py-1 px-2 rounded"
                };
                let avatar_node_edit = if is_team {
                    if let Some(photo) = &opt_photo {
                        rsx! {
                            img {
                                src: "{base_url_edit}/static/{photo}",
                                alt: "{opt_display}",
                                class: "team-token-avatar small me-1 rounded-circle",
                                style: "width: 1.5em; height: 1.5em; object-fit: cover;"
                            }
                        }
                    } else {
                        rsx! {
                            span { class: "team-token-avatar small me-1", "{opt_display.chars().next().unwrap_or('?')}" }
                        }
                    }
                } else {
                    rsx! { span { class: "me-1", "🏀" } }
                };
                rsx! {
                    li {
                        class: "{li_class}",
                        onclick: move |_| {
                            let v = skip_condition();
                            let cursor_char = skip_condition_cursor_pos().unwrap_or(0);
                            let cursor_byte = skip_condition_cursor_byte(&v, cursor_char);
                            let inn = skip_condition_innermost_around_cursor(&v, cursor_char);
                            let Some(cs) = inn.and_then(|b| match b {
                                InnermostBracket::Square(cs, _) | InnermostBracket::Curly(cs, _) => Some(cs),
                                _ => None,
                            }) else {
                                skip_bracket_ac_visible.set(false);
                                return;
                            };
                            let new_v = format!("{}{}{}", &v[..cs], opt_insert, &v[cursor_byte..]);
                            skip_condition.set(new_v.clone());
                            let cs_chars = v[..cs].chars().count();
                            let new_cursor_char = cs_chars + opt_insert.chars().count();
                            skip_condition_cursor.set(Some(new_cursor_char));
                            skip_bracket_ac_visible.set(false);
                        },
                        {avatar_node_edit}
                        span { "{display_val}" }
                    }
                }
            })
            .collect()
    } else {
        vec![]
    };

    let skip_condition_segments_edit = skip_condition_parse_segments(
        &skip_condition(),
        &data.team_options,
        &data.matches,
    );
    let skip_condition_has_tokens_edit = skip_condition_segments_edit
        .iter()
        .any(|s| !matches!(s, SkipConditionSegment::Text(_)));
    let skip_condition_segment_items_edit: Vec<_> = skip_condition_segments_edit
        .iter()
        .map(|seg| {
            match seg {
                SkipConditionSegment::Text(t) => rsx! { span { "{t}" } },
                SkipConditionSegment::TeamLiteral { display, value } => {
                    let d = display.clone();
                    let photo_edit = data
                        .team_options
                        .iter()
                        .find(|t| t.id == *value)
                        .and_then(|t| t.profile_photo.clone());
                    let chip_class = if value.ends_with("::winner") {
                        "team-token-chip team-token-chip-winner small me-1"
                    } else if value.ends_with("::loser") {
                        "team-token-chip team-token-chip-loser small me-1"
                    } else {
                        "team-token-chip team-token-chip-team small me-1"
                    };
                    let avatar_node_edit = if let Some(ph) = &photo_edit {
                        rsx! {
                            img {
                                src: "{base_url_edit}/static/{ph}",
                                alt: "{d}",
                                class: "team-token-avatar rounded-circle",
                                style: "width: 1.25em; height: 1.25em; object-fit: cover;"
                            }
                        }
                    } else {
                        rsx! {
                            span { class: "team-token-avatar", "{d.chars().next().unwrap_or('?')}" }
                        }
                    };
                    rsx! {
                        span { class: "{chip_class}",
                            {avatar_node_edit}
                            span { class: "team-token-label", "{d}" }
                        }
                    }
                }
                SkipConditionSegment::MatchLiteral { display } => {
                    let d = display.clone();
                    rsx! {
                        span { class: "team-token-chip small me-1", style: "background: #e9ecef; border-radius: 4px; padding: 2px 6px;",
                            span { class: "me-1", "🏀" }
                            span { "{d}" }
                        }
                    }
                }
            }
        })
        .collect();

    let tournament_url_val_edit = tournament_url.clone();
    use_effect(move || {
        let expr = skip_condition();
        let _ = expr.clone();
        if expr.trim().is_empty() {
            return;
        }
        let expr_captured = expr.clone();
        let url = tournament_url_val_edit.clone();
        spawn(async move {
            gloo_timers::future::TimeoutFuture::new(3000).await;
            let current = skip_condition();
            if current == expr_captured {
                match api::validate_dsl(&url, &expr_captured).await {
                    Ok(res) => {
                        skip_condition_error.set(if res.valid { None } else { res.error.clone() });
                        skip_condition_simplified.set(if res.valid { res.simplified } else { None });
                    }
                    Err(e) => {
                        skip_condition_error.set(Some(e));
                        skip_condition_simplified.set(None);
                    }
                }
            }
        });
    });

    rsx! {
        div {
            div {
                class: "modal d-block",
                tabindex: -1,
                style: "background: rgba(0,0,0,0.5)",
                onkeydown: modal_keydown,
                div { class: "modal-dialog modal-lg",
                    div { class: "modal-content",
                        div { class: "modal-header",
                            h5 { class: "modal-title", "Edit Match: {name}" }
                        }
                        div { class: "modal-body",
                        if let Some(err) = error() {
                            div { class: "alert alert-danger", "{err}" }
                        }
                        form {
                            onsubmit: onsubmit,
                            onkeydown: form_keydown,
                            
                            div { class: "row",
                                div { class: "col-md-6",
                                    div { class: "mb-3",
                                        label { class: "form-label", "Match Name" }
                                        input { class: "form-control", "type": "text", value: "{name}", oninput: move |e| { let mut name = name; name.set(e.value()); }, required: true }
                                    }
                                }
                                div { class: "col-md-6",
                                    div { class: "mb-3",
                                        label { class: "form-label", "Field" }
                                        select { class: "form-select", value: "{field}", onchange: move |e| on_field_change_edit(e.value()),
                                            option { value: "", "Select Field" }
                                            for f in &data.fields {
                                                option { value: "{f.name}", "{f.name}" }
                                            }
                                        }
                                    }
                                }
                            }
                            
                            div { class: "row",
                                div { class: "col-md-6",
                                    div { class: "mb-3",
                                        label { class: "form-label", "Match Type" }
                                        select { class: "form-select", value: "{schedule_type}", onchange: move |e| { let mut schedule_type = schedule_type; schedule_type.set(e.value()); },
                                            option { value: "STATIC", "Static" }
                                            option { value: "SAFE", "Safe" }
                                            option { value: "FAST", "Fast" }
                                            option { value: "BREAK", "Break" }
                                            option { value: "JOIN", "Join" }
                                        }
                                    }
                                }
                                if schedule_type() != "JOIN" {
                                    div { class: "col-md-6",
                                        div { class: "mb-3",
                                            label { class: "form-label", "Length (min)" }
                                            input { class: "form-control", "type": "number", min: "0", value: "{length}", oninput: move |e| { let mut length = length; length.set(e.value().parse().unwrap_or(60)); } }
                                        }
                                    }
                                }
                            }
                            
                            if schedule_type() == "STATIC" {
                                div { class: "mb-3",
                                    label { class: "form-label", "Start Time" }
                                    input { class: "form-control", "type": "datetime-local", value: "{start_time}", oninput: move |e| { let mut start_time = start_time; start_time.set(e.value()); } }
                                }
                            } else if schedule_type() == "SAFE" || schedule_type() == "FAST" || schedule_type() == "BREAK" || schedule_type() == "JOIN" {
                                div { class: "mb-3",
                                    label { class: "form-label", "Previous Match" }
                                    select { class: "form-select", value: "{previous_match_id}", onchange: move |e| { let mut previous_match_id = previous_match_id; previous_match_id.set(e.value()); },
                                        option { value: "", "None" }
                                        for m in &matches_on_field_edit {
                                            option { value: "{m.uuid}", "{m.name}" }
                                        }
                                    }
                                }
                            }
                            
                            if schedule_type() == "STATIC" || schedule_type() == "SAFE" || schedule_type() == "FAST" {
                                div { class: "row",
                                    div { class: "col-md-6",
                                        div { class: "mb-3",
                                            label { class: "form-label", "Team 1" }
                                            TeamTokenInput {
                                                team_options: data.team_options.clone(),
                                                tags: data.tags.clone(),
                                                matches: data.matches.clone(),
                                                value: team1(),
                                                on_change: move |s| team1.set(s),
                                                multiple: false,
                                                placeholder: "Pseudonym, MatchName::winner, tag::TagName".to_string(),
                                            }
                                            div { class: "form-text", "Team, match winner/loser, or tag" }
                                        }
                                    }
                                    div { class: "col-md-6",
                                        div { class: "mb-3",
                                            label { class: "form-label", "Team 2" }
                                            TeamTokenInput {
                                                team_options: data.team_options.clone(),
                                                tags: data.tags.clone(),
                                                matches: data.matches.clone(),
                                                value: team2(),
                                                on_change: move |s| team2.set(s),
                                                multiple: false,
                                                placeholder: "Pseudonym, MatchName::winner, tag::TagName".to_string(),
                                            }
                                            div { class: "form-text", "Team pseudonym, match winner/loser, or tag" }
                                        }
                                    }
                                }
                                div { class: "mb-3",
                                    label { class: "form-label", "Referees" }
                                    TeamTokenInput {
                                        team_options: data.team_options.clone(),
                                        tags: data.tags.clone(),
                                        matches: data.matches.clone(),
                                        value: refs(),
                                        on_change: move |s| refs.set(s),
                                        multiple: true,
                                        placeholder: "Comma-separated: pseudonym, MatchName::winner, tag::TagName".to_string(),
                                    }
                                    div { class: "form-text", "Comma-separated list of team pseudonyms, match references, or tags" }
                                }
                                div { class: "row",
                                    div { class: "col-md-4",
                                        div { class: "mb-3",
                                            label { class: "form-label", "Format" }
                                            select { class: "form-select", value: "{set_type}", onchange: move |e| { let mut set_type = set_type; set_type.set(e.value()); },
                                                option { value: "SETS", "Sets" }
                                                option { value: "STONES", "Stones" }
                                            }
                                        }
                                    }
                                    div { class: "col-md-4",
                                        div { class: "mb-3",
                                            label { class: "form-label", "Number of sets" }
                                            input { class: "form-control", "type": "number", min: "1", value: "{nsets}", oninput: move |e| { let mut nsets = nsets; nsets.set(e.value().parse().unwrap_or(3)); } }
                                        }
                                    }
                                    if set_type() == "STONES" {
                                        div { class: "col-md-4",
                                            div { class: "mb-3",
                                                label { class: "form-label", "Stones per set" }
                                                input { class: "form-control", "type": "number", min: "1", value: "{stones_per_set}", oninput: move |e| { let mut stones_per_set = stones_per_set; stones_per_set.set(e.value().parse().unwrap_or(100)); } }
                                            }
                                        }
                                    }
                                }
                                div { class: "mb-3",
                                    div { class: "form-check",
                                        input { class: "form-check-input", "type": "checkbox", id: "edit-ribbon", checked: "{ribbon}", onchange: move |e| { let mut ribbon = ribbon; ribbon.set(e.value() == "true"); } }
                                        label { class: "form-check-label", "for": "edit-ribbon", "Ribbon game" }
                                    }
                                }
                                if schedule_type() == "SAFE" || schedule_type() == "FAST" {
                                    div { class: "mb-3 position-relative",
                                        label { class: "form-label", "Skip condition" }
                                        div { class: "form-text mb-1",
                                            "Optional expression that evaluates to a boolean. If true, this match will be skipped. "
                                            a {
                                                href: "#",
                                                class: "text-decoration-none",
                                                onclick: move |ev: Event<MouseData>| {
                                                    ev.prevent_default();
                                                    skip_condition_help_open.set(true);
                                                },
                                                "(skip condition help)"
                                            }
                                        }
                                        input {
                                            id: "skip-condition-input-edit",
                                            class: "form-control font-monospace",
                                            "type": "text",
                                            placeholder: "e.g. (== 0 (losses [Team]))",
                                            value: "{skip_condition}",
                                            oninput: move |e| {
                                                let new_val = e.value();
                                                let old = skip_condition();
                                                let (out, cursor_after_open) = if let Some(byte_i) = skip_condition_new_char_index(&old, &new_val) {
                                                    let open_c = new_val[byte_i..].chars().next().unwrap_or('\0');
                                                    let closing = match open_c {
                                                        '(' => ")",
                                                        '[' => {
                                                            skip_bracket_ac_visible.set(true);
                                                            skip_bracket_ac_team.set(true);
                                                            skip_bracket_ac_index.set(0);
                                                            "]"
                                                        }
                                                        '{' => {
                                                            skip_bracket_ac_visible.set(true);
                                                            skip_bracket_ac_team.set(false);
                                                            skip_bracket_ac_index.set(0);
                                                            "}"
                                                        }
                                                        _ => "",
                                                    };
                                                    if closing.is_empty() {
                                                        (new_val, None)
                                                    } else {
                                                        let char_end = byte_i + new_val[byte_i..].chars().next().map(|c| c.len_utf8()).unwrap_or(1);
                                                        let out_str = format!("{}{}{}", &new_val[..char_end], closing, &new_val[char_end..]);
                                                        (out_str, Some(char_end))
                                                    }
                                                } else {
                                                    (new_val, None)
                                                };
                                                skip_condition.set(out.clone());
                                                if let Some(pos) = cursor_after_open {
                                                    skip_condition_cursor.set(Some(pos));
                                                }
                                                skip_condition_error.set(None);
                                                if out.contains('(') {
                                                    skip_docs_visible.set(true);
                                                }
                                                let id = "skip-condition-input-edit".to_string();
                                                spawn(async move {
                                                    gloo_timers::future::TimeoutFuture::new(0).await;
                                                    #[cfg(target_arch = "wasm32")]
                                                    if let Some(window) = web_sys::window() {
                                                        if let Some(doc) = window.document() {
                                                            if let Ok(Some(el)) = doc.query_selector(&format!("#{}", id)) {
                                                                if let Ok(input) = el.dyn_into::<web_sys::HtmlInputElement>() {
                                                                    if let Ok(Some(sel)) = input.selection_start() {
                                                                        skip_condition_cursor_pos.set(Some(sel as usize));
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                });
                                            },
                                            onfocus: move |_| {
                                                let id = "skip-condition-input-edit".to_string();
                                                spawn(async move {
                                                    gloo_timers::future::TimeoutFuture::new(0).await;
                                                    #[cfg(target_arch = "wasm32")]
                                                    if let Some(window) = web_sys::window() {
                                                        if let Some(doc) = window.document() {
                                                            if let Ok(Some(el)) = doc.query_selector(&format!("#{}", id)) {
                                                                if let Ok(input) = el.dyn_into::<web_sys::HtmlInputElement>() {
                                                                    if let Ok(Some(sel)) = input.selection_start() {
                                                                        skip_condition_cursor_pos.set(Some(sel as usize));
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                });
                                            },
                                            onkeydown: move |ev: Event<KeyboardData>| {
                                                let key = ev.key().to_string();
                                                let n_edit = bracket_options_edit.len();
                                                if show_bracket_ac_edit && n_edit > 0 {
                                                    if key == "ArrowDown" {
                                                        ev.prevent_default();
                                                        skip_bracket_ac_index.set((bracket_ac_idx_edit + 1) % n_edit);
                                                        return;
                                                    }
                                                    if key == "ArrowUp" {
                                                        ev.prevent_default();
                                                        skip_bracket_ac_index.set((bracket_ac_idx_edit + n_edit - 1) % n_edit);
                                                        return;
                                                    }
                                                    if key == "Enter" {
                                                        ev.prevent_default();
                                                        if let Some((opt_insert, _, _)) = bracket_options_edit.get(bracket_ac_idx_edit) {
                                                            let v = skip_condition();
                                                            let cursor_char = skip_condition_cursor_pos().unwrap_or(0);
                                                            let cursor_byte = skip_condition_cursor_byte(&v, cursor_char);
                                                            let inn = skip_condition_innermost_around_cursor(&v, cursor_char);
                                                            if let Some(cs) = inn.and_then(|b| match b {
                                                                InnermostBracket::Square(cs, _) | InnermostBracket::Curly(cs, _) => Some(cs),
                                                                _ => None,
                                                            }) {
                                                                let new_v = format!("{}{}{}", &v[..cs], opt_insert, &v[cursor_byte..]);
                                                                skip_condition.set(new_v);
                                                                let cs_chars = v[..cs].chars().count();
                                                                let new_cursor_char = cs_chars + opt_insert.chars().count();
                                                                skip_condition_cursor.set(Some(new_cursor_char));
                                                                skip_bracket_ac_visible.set(false);
                                                            }
                                                        }
                                                        return;
                                                    }
                                                }
                                                if key == "Enter" && !ev.modifiers().contains(Modifiers::SHIFT) {
                                                    ev.prevent_default();
                                                }
                                            },
                                            onkeyup: move |_| {
                                                let id = "skip-condition-input-edit".to_string();
                                                spawn(async move {
                                                    gloo_timers::future::TimeoutFuture::new(0).await;
                                                    #[cfg(target_arch = "wasm32")]
                                                    if let Some(window) = web_sys::window() {
                                                        if let Some(doc) = window.document() {
                                                            if let Ok(Some(el)) = doc.query_selector(&format!("#{}", id)) {
                                                                if let Ok(input) = el.dyn_into::<web_sys::HtmlInputElement>() {
                                                                    if let Ok(Some(sel)) = input.selection_start() {
                                                                        let sel_i = sel as usize;
                                                                        skip_condition_cursor_pos.set(Some(sel_i));
                                                                        let val = input.value();
                                                                        let inside = skip_condition_innermost_around_cursor(&val, sel_i)
                                                                            .map(|b| matches!(b, InnermostBracket::Square(_, _) | InnermostBracket::Curly(_, _)))
                                                                            .unwrap_or(false);
                                                                        if !inside {
                                                                            skip_bracket_ac_visible.set(false);
                                                                        }
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                });
                                            },
                                            onblur: move |_| {
                                                skip_docs_visible.set(false);
                                                skip_bracket_ac_visible.set(false);
                                                let expr = skip_condition();
                                                if expr.trim().is_empty() {
                                                    skip_condition_error.set(None);
                                                    return;
                                                }
                                                let url = tournament_url.clone();
                                                spawn(async move {
                                                    match api::validate_dsl(&url, &expr).await {
                                                        Ok(res) => {
                                                            skip_condition_error.set(if res.valid {
                                                                None
                                                            } else {
                                                                res.error
                                                            });
                                                            skip_condition_simplified.set(if res.valid {
                                                                res.simplified
                                                            } else {
                                                                None
                                                            });
                                                        }
                                                        Err(e) => {
                                                            skip_condition_error.set(Some(e));
                                                            skip_condition_simplified.set(None);
                                                        }
                                                    }
                                                });
                                            },
                                        }
                                        if show_skip_docs_edit && !docs_filtered_edit.is_empty() {
                                            div { class: "position-absolute start-0 mt-1 p-2 bg-light border rounded shadow-sm z-3",
                                                style: "min-width: 280px; max-height: 240px; overflow-y: auto;",
                                                ul { class: "list-unstyled mb-0 small",
                                                    for item in docs_items_edit.iter() {
                                                        {item.clone()}
                                                    }
                                                }
                                            }
                                        }
                                        if show_bracket_ac_edit && !bracket_options_edit.is_empty() {
                                            div { class: "position-absolute start-0 mt-1 p-2 bg-light border rounded shadow-sm z-3",
                                                style: "min-width: 200px; max-height: 240px; overflow-y: auto;",
                                                ul { class: "list-unstyled mb-0 small",
                                                    for item in bracket_option_items_edit.iter() {
                                                        {item.clone()}
                                                    }
                                                }
                                            }
                                        }
                                        if skip_condition_has_tokens_edit {
                                            div { class: "form-text mt-1 d-flex flex-wrap align-items-center gap-0",
                                                for item in skip_condition_segment_items_edit.iter() {
                                                    {item.clone()}
                                                }
                                            }
                                        }
                                        if let Some(err) = skip_condition_error() {
                                            div { class: "form-text text-danger", "✗ {err}" }
                                        } else if let Some(simp) = skip_condition_simplified() {
                                            div { class: "form-text text-success", "✓ Valid (simplified: {simp})" }
                                        } else if !skip_condition().trim().is_empty() {
                                            div { class: "form-text text-success", "✓ Valid" }
                                        }
                                    }
                                }
                            }
                            
                            div { class: "modal-footer",
                                button { class: "btn btn-secondary", "type": "button", onclick: move |_| on_close.call(()), "Cancel (Esc)" }
                                button { class: "btn btn-danger", "type": "button", 
                                    onclick: move |_| {
                                        // Delete match
                                        let u = url_sig();
                                        let mid = match_id.clone();
                                        let cb = on_save.clone();
                                        async move {
                                            if let Ok(_) = api::delete_match(&u, &mid).await {
                                                cb.call(());
                                            }
                                        }
                                    },
                                    "Delete" 
                                }
                                button { class: "btn btn-primary", "type": "submit", disabled: "{saving}",
                                    if saving() { span { class: "spinner-border spinner-border-sm me-2" } }
                                    "Save (⇧↵)" 
                                }
                            }
                        }
                    }
                }
            }
            }
            if skip_condition_help_open() {
                SkipConditionHelpModal { on_close: move |_| skip_condition_help_open.set(false) }
            }
        }
    }
}

/// Status color and label for timeline blocks and table status column (same logic in both places).
fn status_color_and_label(status: &str) -> (String, String) {
    let color = match status {
        "COMPLETED" => "#7acb8b",
        "IN_PROGRESS" => "#ffd666",
        "TIME_FINALIZED" => "#a5adb5",
        "READY_TO_START" => "#82b1ff",
        _ => "#6cc5d4",
    };
    let label: String = match status {
        "COMPLETED" => "Completed".to_string(),
        "IN_PROGRESS" => "In Progress".to_string(),
        "TIME_FINALIZED" => "Time Finalized".to_string(),
        "NOT_STARTED" => "Not Started".to_string(),
        "READY_TO_START" => "Ready to Start".to_string(),
        other => {
            let mut s = other.replace('_', " ").to_lowercase();
            if let Some(first) = s.get_mut(0..1) {
                first.make_ascii_uppercase();
            }
            s
        }
    };
    (color.to_string(), label)
}

/// Returns (kind, label): 0 = team (avatar + label), 1 = tag (tag icon + label), 2 = link (reference icon + "MatchName winner/loser").
fn team_ref_display(raw: &str) -> (u8, String) {
    if raw.ends_with("::winner") {
        let name = raw.strip_suffix("::winner").unwrap_or(raw).trim();
        (2, format!("{} winner", name))
    } else if raw.ends_with("::loser") {
        let name = raw.strip_suffix("::loser").unwrap_or(raw).trim();
        (2, format!("{} loser", name))
    } else if raw.len() >= 5 && raw.get(..5).map(|s| s.eq_ignore_ascii_case("tag::")).unwrap_or(false) {
        (1, raw.get(5..).unwrap_or("").trim().to_string())
    } else {
        (0, raw.to_string())
    }
}

fn format_time(iso: &str) -> String {
    if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(iso) {
        dt.format("%H:%M").to_string()
    } else {
        iso.to_string()
    }
}
