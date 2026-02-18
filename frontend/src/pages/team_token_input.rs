//! Team/referee token input with autocomplete and inline chips (Gmail-style).
//! Supports: team pseudonym/id, MatchName::winner, MatchName::loser, tag::TagName.

use crate::api;
use crate::types::*;
use dioxus::prelude::*;
use std::cell::RefCell;
use std::rc::Rc;
#[cfg(target_arch = "wasm32")]
use wasm_bindgen::JsCast as _;

#[derive(Clone, Debug, PartialEq)]
pub enum TokenKind {
    Team,
    Tag,
    Winner,
    Loser,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Token {
    pub kind: TokenKind,
    pub display: String,
    pub value: String,
}

fn parse_value_into_tokens(
    value: &str,
    multiple: bool,
    team_options: &[TeamOption],
    _tags: &[TagSetupData],
    _matches: &[MatchSetupData],
) -> Vec<Token> {
    let segments: Vec<&str> = if multiple {
        value.split(',').map(str::trim).filter(|s| !s.is_empty()).collect()
    } else if value.trim().is_empty() {
        return vec![];
    } else {
        vec![value.trim()]
    };
    let mut tokens = Vec::with_capacity(segments.len());
    for seg in segments {
        if seg.ends_with("::winner") {
            let name = seg.strip_suffix("::winner").unwrap_or(seg).trim();
            tokens.push(Token {
                kind: TokenKind::Winner,
                display: name.to_string(),
                value: seg.to_string(),
            });
        } else if seg.ends_with("::loser") {
            let name = seg.strip_suffix("::loser").unwrap_or(seg).trim();
            tokens.push(Token {
                kind: TokenKind::Loser,
                display: name.to_string(),
                value: seg.to_string(),
            });
        } else if seg.to_lowercase().starts_with("tag::") {
            let name = seg.get(5..).unwrap_or("").trim();
            tokens.push(Token {
                kind: TokenKind::Tag,
                display: name.to_string(),
                value: seg.to_string(),
            });
        } else {
            let team_id = team_options
                .iter()
                .find(|t| t.id == seg || t.pseudonym.as_deref() == Some(seg))
                .map(|t| t.id.clone())
                .unwrap_or_else(|| seg.to_string());
            let display = team_options
                .iter()
                .find(|t| t.id == team_id)
                .and_then(|t| t.pseudonym.clone())
                .map(|p| format!("{p} ({})", team_id))
                .unwrap_or_else(|| team_id.clone());
            tokens.push(Token {
                kind: TokenKind::Team,
                display,
                value: team_id,
            });
        }
    }
    tokens
}

fn chip_class_suffix(t: &Token) -> &'static str {
    match &t.kind {
        TokenKind::Team => "team",
        TokenKind::Tag => "tag",
        TokenKind::Winner => "winner",
        TokenKind::Loser => "loser",
    }
}

fn chip_display_and_suffix(t: &Token) -> (String, &'static str) {
    (t.display.clone(), chip_class_suffix(t))
}

fn opt_parts(o: &AutocompleteOption) -> (TokenKind, String, String) {
    (o.kind.clone(), o.display.clone(), o.value.clone())
}

fn tokens_to_value(tokens: &[Token], multiple: bool) -> String {
    if multiple {
        tokens.iter().map(|t| t.value.as_str()).collect::<Vec<_>>().join(", ")
    } else {
        tokens.first().map(|t| t.value.clone()).unwrap_or_default()
    }
}

#[derive(Clone, Debug)]
pub struct AutocompleteOption {
    pub kind: TokenKind,
    pub display: String,
    pub value: String,
}

fn collect_autocomplete(
    query: &str,
    team_options: &[TeamOption],
    tags: &[TagSetupData],
    matches: &[MatchSetupData],
) -> Vec<AutocompleteOption> {
    let q = query.trim().to_lowercase();
    let mut out = Vec::new();
    if q.is_empty() {
        for t in team_options.iter().take(15) {
            let display = t
                .pseudonym
                .clone()
                .map(|p| format!("{p} ({})", t.id))
                .unwrap_or_else(|| t.id.clone());
            out.push(AutocompleteOption {
                kind: TokenKind::Team,
                display,
                value: t.id.clone(),
            });
        }
        for tag in tags.iter().take(5) {
            out.push(AutocompleteOption {
                kind: TokenKind::Tag,
                display: tag.name.clone(),
                value: format!("tag::{}", tag.name),
            });
        }
        for m in matches.iter().take(10) {
            out.push(AutocompleteOption {
                kind: TokenKind::Winner,
                display: format!("{} winner", m.name),
                value: format!("{}::winner", m.name),
            });
            out.push(AutocompleteOption {
                kind: TokenKind::Loser,
                display: format!("{} loser", m.name),
                value: format!("{}::loser", m.name),
            });
        }
        return out;
    }
    for t in team_options.iter() {
        let id_lower = t.id.to_lowercase();
        let pseudo_lower = t.pseudonym.as_deref().unwrap_or("").to_lowercase();
        if id_lower.contains(&q) || pseudo_lower.contains(&q) {
            let display = t
                .pseudonym
                .clone()
                .map(|p| format!("{p} ({})", t.id))
                .unwrap_or_else(|| t.id.clone());
            out.push(AutocompleteOption {
                kind: TokenKind::Team,
                display,
                value: t.id.clone(),
            });
        }
    }
    for tag in tags.iter() {
        if tag.name.to_lowercase().contains(&q) {
            out.push(AutocompleteOption {
                kind: TokenKind::Tag,
                display: tag.name.clone(),
                value: format!("tag::{}", tag.name),
            });
        }
    }
    for m in matches.iter() {
        let name_lower = m.name.to_lowercase();
        if name_lower.contains(&q) {
            out.push(AutocompleteOption {
                kind: TokenKind::Winner,
                display: format!("{} winner", m.name),
                value: format!("{}::winner", m.name),
            });
            out.push(AutocompleteOption {
                kind: TokenKind::Loser,
                display: format!("{} loser", m.name),
                value: format!("{}::loser", m.name),
            });
        }
    }
    out
}

#[component]
pub fn TeamTokenInput(
    team_options: Vec<TeamOption>,
    tags: Vec<TagSetupData>,
    matches: Vec<MatchSetupData>,
    value: String,
    on_change: EventHandler<String>,
    multiple: bool,
    placeholder: String,
) -> Element {
    let mut input_text = use_signal(|| String::new());
    let mut show_autocomplete = use_signal(|| false);
    let mut ac_pos = use_signal(|| 0usize);
    let mut focused_chip = use_signal(|| None::<usize>);
    
    // Generate a unique ID for this component instance (generated once)
    static COUNTER: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let container_id = use_memo(move || {
        let id = COUNTER.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        format!("team-token-container-{}", id)
    });

    let value_rc = Rc::new(value.clone());
    let team_options_rc = Rc::new(team_options);
    let tags_rc = Rc::new(tags);
    let matches_rc = Rc::new(matches);
    let base_url = api::base_url();

    let tokens = parse_value_into_tokens(
        value_rc.as_ref(),
        multiple,
        team_options_rc.as_ref(),
        tags_rc.as_ref(),
        matches_rc.as_ref(),
    );
    let options = collect_autocomplete(
        input_text().as_str(),
        team_options_rc.as_ref(),
        tags_rc.as_ref(),
        matches_rc.as_ref(),
    );
    let options_len = options.len();
    let current_ac_pos = ac_pos();
    let tokens_empty = tokens.is_empty();
    let tokens_len = tokens.len();

    let on_change_remove = on_change.clone();

    let value_rc2 = value_rc.clone();
    let team_options_rc2 = team_options_rc.clone();
    let team_options_rc3 = team_options_rc.clone();
    let tags_rc2 = tags_rc.clone();
    let matches_rc2 = matches_rc.clone();
    let add_token_rc: Rc<RefCell<Box<dyn FnMut(Token)>>> = Rc::new(RefCell::new(Box::new(move |t: Token| {
        let mut new_tokens = parse_value_into_tokens(
            value_rc.as_ref(),
            multiple,
            team_options_rc3.as_ref(),
            tags_rc.as_ref(),
            matches_rc.as_ref(),
        );
        if multiple {
            new_tokens.push(t);
        } else {
            new_tokens = vec![t];
        }
        on_change.call(tokens_to_value(&new_tokens, multiple));
        input_text.set(String::new());
        show_autocomplete.set(false);
        ac_pos.set(0);
    })));

    let remove_token_rc: Rc<RefCell<Box<dyn FnMut(usize)>>> = Rc::new(RefCell::new(Box::new(move |idx: usize| {
        let mut new_tokens = parse_value_into_tokens(
            value_rc2.as_ref(),
            multiple,
            team_options_rc2.as_ref(),
            tags_rc2.as_ref(),
            matches_rc2.as_ref(),
        );
        if idx < new_tokens.len() {
            new_tokens.remove(idx);
            on_change_remove.call(tokens_to_value(&new_tokens, multiple));
        }
        focused_chip.set(None);
    })));

    rsx! {
        div {
            id: "{container_id()}",
            class: "team-token-input form-control",
            role: "combobox",
            "aria-expanded": "{show_autocomplete()}",
            tabindex: 0,
            onfocus: move |_| {
                show_autocomplete.set(true);
                // Focus the inner input field when the outer div receives focus
                let container_id_local = container_id();
                #[cfg(target_arch = "wasm32")]
                {
                    spawn(async move {
                        gloo_timers::future::TimeoutFuture::new(0).await;
                        if let Some(window) = web_sys::window() {
                            if let Some(doc) = window.document() {
                                if let Ok(Some(container)) = doc.query_selector(&format!("#{}", container_id_local)) {
                                    if let Ok(Some(input_el)) = container.query_selector(".team-token-input-field") {
                                        if let Ok(input) = input_el.dyn_into::<web_sys::HtmlInputElement>() {
                                            let _ = input.focus();
                                        }
                                    }
                                }
                            }
                        }
                    });
                }
            },
            onkeydown: move |ev: Event<KeyboardData>| {
                let key = ev.key().to_string();
                if show_autocomplete() && options_len > 0 {
                    if key == "ArrowDown" {
                        ev.prevent_default();
                        ac_pos.set((ac_pos() + 1) % options_len);
                        return;
                    }
                    if key == "ArrowUp" {
                        ev.prevent_default();
                        ac_pos.set(ac_pos().saturating_sub(1).max(0));
                        return;
                    }
                    if key == "Enter" {
                        ev.prevent_default();
                        if let Some(opt) = options.get(ac_pos()) {
                            add_token_rc.borrow_mut()(Token {
                                kind: opt.kind.clone(),
                                display: opt.display.clone(),
                                value: opt.value.clone(),
                            });
                        }
                        return;
                    }
                    if key == "Escape" {
                        ev.prevent_default();
                        show_autocomplete.set(false);
                        return;
                    }
                }
                if key == "Backspace" && input_text().is_empty() && !tokens_empty {
                    ev.prevent_default();
                    if let Some(focus) = focused_chip() {
                        remove_token_rc.borrow_mut()(focus);
                    } else {
                        remove_token_rc.borrow_mut()(tokens_len - 1);
                    }
                    return;
                }
                if key == "ArrowLeft" && input_text().is_empty() && !tokens_empty {
                    ev.prevent_default();
                    let next = focused_chip()
                        .map(|i| i.saturating_sub(1))
                        .or(Some(tokens_len - 1));
                    if next == Some(0) {
                        focused_chip.set(Some(0));
                    } else if next.unwrap_or(0) > 0 {
                        focused_chip.set(next);
                    }
                    return;
                }
                if key == "ArrowRight" {
                    ev.prevent_default();
                    if let Some(focus) = focused_chip() {
                        if focus + 1 >= tokens_len {
                            focused_chip.set(None);
                        } else {
                            focused_chip.set(Some(focus + 1));
                        }
                    }
                    return;
                }
            },
            onblur: move |_| {
                #[cfg(target_arch = "wasm32")]
                {
                    let mut show_ac = show_autocomplete.clone();
                    spawn(async move {
                        gloo_timers::future::TimeoutFuture::new(150).await;
                        show_ac.set(false);
                    });
                }
                #[cfg(not(target_arch = "wasm32"))]
                show_autocomplete.set(false);
            },

            div { class: "team-token-input-inner",
                for (idx, entry) in tokens.iter().enumerate() {
                    {
                        let remove_rc = remove_token_rc.clone();
                        let remove_rc2 = remove_token_rc.clone();
                        let pair = chip_display_and_suffix(entry);
                        let chip_label = pair.0;
                        let chip_suffix = pair.1;
                        let is_focused = focused_chip() == Some(idx);
                        let chip_class = format!(
                            "team-token-chip {} team-token-chip-{}",
                            if is_focused { "team-token-chip-focused " } else { "" },
                            chip_suffix
                        );
                        let team_photo = team_options_rc
                            .iter()
                            .find(|t| t.id == entry.value)
                            .and_then(|t| t.profile_photo.clone());
                        let team_content = if let Some(photo) = &team_photo {
                            rsx! {
                                img {
                                    src: "{base_url}/static/{photo}",
                                    alt: "{chip_label}",
                                    class: "team-token-avatar rounded-circle",
                                    style: "width: 1.5em; height: 1.5em; object-fit: cover;"
                                }
                                span { class: "team-token-label", "{chip_label}" }
                            }
                        } else {
                            rsx! {
                                span { class: "team-token-avatar", "{chip_label.chars().next().unwrap_or('?')}" }
                                span { class: "team-token-label", "{chip_label}" }
                            }
                        };
                        let tag_content = rsx! {
                            img { class: "team-token-icon icon-primary-svg", src: "{base_url}/static/tag.svg", alt: "Tag" }
                            span { class: "team-token-label", "{chip_label}" }
                        };
                        let winner_content = rsx! {
                            img { class: "team-token-icon icon-primary-svg", src: "{base_url}/static/reference.svg", alt: "Reference" }
                            span { class: "team-token-label", "{chip_label} winner" }
                        };
                        let loser_content = rsx! {
                            img { class: "team-token-icon icon-primary-svg", src: "{base_url}/static/reference.svg", alt: "Reference" }
                            span { class: "team-token-label", "{chip_label} loser" }
                        };
                        let chip_inner = if chip_suffix == "team" { team_content } else if chip_suffix == "tag" { tag_content } else if chip_suffix == "winner" { winner_content } else { loser_content };
                        rsx! {
                    div {
                        class: "{chip_class}",
                        key: "{idx}-{chip_label}",
                        tabindex: 0,
                        onclick: move |ev: Event<MouseData>| { ev.stop_propagation(); focused_chip.set(Some(idx)); },
                        onkeydown: move |ev: Event<KeyboardData>| {
                            if ev.key().to_string() == "Backspace" {
                                ev.prevent_default();
                                remove_rc.borrow_mut()(idx);
                            }
                        },
                        {chip_inner}
                        button {
                            class: "team-token-remove",
                            "type": "button",
                            "aria-label": "Remove",
                            onclick: move |ev: Event<MouseData>| { ev.stop_propagation(); remove_rc2.borrow_mut()(idx); },
                            "×"
                        }
                    }
                        }
                    }
                }
                input {
                    class: "team-token-input-field",
                    "type": "text",
                    placeholder: if tokens_empty { placeholder.clone() } else { "".to_string() },
                    value: "{input_text}",
                    oninput: move |e| {
                        input_text.set(e.value());
                        show_autocomplete.set(true);
                        ac_pos.set(0);
                        focused_chip.set(None);
                    },
                    onfocus: move |_| {
                        focused_chip.set(None);
                        show_autocomplete.set(true);
                    },
                }
            }

            if show_autocomplete() && !options.is_empty() {
                ul { class: "team-token-autocomplete dropdown-menu show",
                    for (idx, opt) in options.iter().enumerate() {
                        {
                            let add_rc = add_token_rc.clone();
                            let parts = opt_parts(opt);
                            let opt_kind = parts.0;
                            let opt_display = parts.1;
                            let opt_value = parts.2;
                            let is_cur = current_ac_pos == idx;
                            let opt_suffix = match &opt_kind {
                                TokenKind::Team => "team",
                                TokenKind::Tag => "tag",
                                TokenKind::Winner => "winner",
                                TokenKind::Loser => "loser",
                            };
                            let item_class = format!("dropdown-item {}", if is_cur { "active" } else { "" });
                            let opt_team_photo = team_options_rc
                                .iter()
                                .find(|t| t.id == opt_value)
                                .and_then(|t| t.profile_photo.clone());
                            let opt_team = if let Some(photo) = &opt_team_photo {
                                rsx! {
                                    img {
                                        src: "{base_url}/static/{photo}",
                                        alt: "{opt_display}",
                                        class: "team-token-avatar small me-1 rounded-circle",
                                        style: "width: 1.5em; height: 1.5em; object-fit: cover;"
                                    }
                                    span { "{opt_display}" }
                                }
                            } else {
                                rsx! {
                                    span { class: "team-token-avatar small me-1", "{opt_display.chars().next().unwrap_or('?')}" }
                                    span { "{opt_display}" }
                                }
                            };
                            let opt_tag = rsx! {
                                img { class: "icon-primary-svg me-1", src: "{base_url}/static/tag.svg", alt: "Tag" }
                                span { "{opt_display}" }
                            };
                            let opt_winner = rsx! {
                                img { class: "icon-primary-svg me-1", src: "{base_url}/static/reference.svg", alt: "Reference" }
                                span { "{opt_display}" }
                            };
                            let opt_loser = rsx! {
                                img { class: "icon-primary-svg me-1", src: "{base_url}/static/reference.svg", alt: "Reference" }
                                span { "{opt_display}" }
                            };
                            let opt_inner = if opt_suffix == "team" { opt_team } else if opt_suffix == "tag" { opt_tag } else if opt_suffix == "winner" { opt_winner } else { opt_loser };
                            rsx! {
                                li {
                                    key: "{idx}-{opt_value}",
                                    class: "{item_class}",
                                    role: "option",
                                    "aria-selected": "{is_cur}",
                                    onmousedown: move |ev: Event<MouseData>| {
                                        ev.prevent_default();
                                        ev.stop_propagation();
                                        add_rc.borrow_mut()(Token { kind: opt_kind.clone(), display: opt_display.clone(), value: opt_value.clone() });
                                    },
                                    onmouseenter: move |_| { ac_pos.set(idx); },
                                    {opt_inner}
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
