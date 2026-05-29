//! ASS (Arctos Schedule Script) expression editor.
//!
//! Single-input component for entering skip conditions:
//! - Auto-closes `(`, `[`, `{`.
//! - Pops up a function dropdown when the cursor is inside `( ... )`.
//! - Pops up a team/tag/match-ref dropdown inside `[ ... ]`.
//! - Pops up a match dropdown inside `{ ... }`.
//! - Renders parsed `[...]` and `{...}` literals as chips in a live preview.
//! - Calls `validate_dsl` on blur and shows error/simplified output.

use crate::api;
use crate::types::*;
use dioxus::html::ModifiersInteraction;
use dioxus::prelude::*;
use std::cell::RefCell;
use std::rc::Rc;
#[cfg(target_arch = "wasm32")]
use wasm_bindgen::JsCast as _;

/// (name, signature, short description)
const DSL_FUNCTIONS: &[(&str, &str, &str)] = &[
    ("wins", "(wins TEAM) -> INT", "Wins for a team this event"),
    ("losses", "(losses TEAM) -> INT", "Losses for a team this event"),
    ("winner", "(winner MATCH) -> TEAM", "Winner of a match"),
    ("loser", "(loser MATCH) -> TEAM", "Loser of a match"),
    ("points-won", "(points-won TEAM MATCH?) -> INT", "Points won (optionally in MATCH)"),
    ("points-lost", "(points-lost TEAM MATCH?) -> INT", "Points lost (optionally in MATCH)"),
    ("is-skipped", "(is-skipped MATCH) -> BOOL", "True if match was skipped"),
    ("if", "(if COND IF_TRUE IF_FALSE)", "Conditional"),
    ("and", "(and BOOL BOOL) -> BOOL", "Logical and"),
    ("or", "(or BOOL BOOL) -> BOOL", "Logical or"),
    ("not", "(not BOOL) -> BOOL", "Logical not"),
    ("==", "(== ANY ANY) -> BOOL", "Equality"),
    (">", "(> INT INT) -> BOOL", "Greater than"),
    ("<", "(< INT INT) -> BOOL", "Less than"),
    (">=", "(>= INT INT) -> BOOL", "Greater or equal"),
    ("<=", "(<= INT INT) -> BOOL", "Less or equal"),
    ("+", "(+ INT INT) -> INT", "Addition"),
    ("-", "(- INT INT) -> INT", "Subtraction"),
    ("*", "(* INT INT) -> INT", "Multiplication"),
    ("/", "(/ INT INT) -> INT", "Integer division"),
    ("cons", "(cons *_) -> LIST", "Build a list from arguments"),
    ("car", "(car LIST)", "First element"),
    ("cdr", "(cdr LIST)", "All but the first element"),
    ("get", "(get INDEX LIST)", "Element at INDEX, or NIL"),
    ("len", "(len LIST) -> INT", "Length of a list"),
    ("or-default", "(or-default VAL DEFAULT)", "VAL if not NIL else DEFAULT"),
    ("map", "(map LIST FUNC) -> LIST", "Apply FUNC to each element"),
    ("reduce", "(reduce LIST FUNC)", "Combine elements with FUNC"),
    ("max", "(max LIST)", "Maximum of a list"),
    ("min", "(min LIST)", "Minimum of a list"),
    ("max-by", "(max-by LIST FUNC)", "Element with max FUNC value"),
    ("min-by", "(min-by LIST FUNC)", "Element with min FUNC value"),
    ("lambda", "(lambda (args) body)", "Define a function"),
];

/// Find matching close bracket from open_pos (byte index of open char). Returns byte index of close char.
fn find_matching_close(s: &str, open_byte_pos: usize, open_c: char, close_c: char) -> Option<usize> {
    let after_open = open_byte_pos + open_c.len_utf8();
    let rest = s.get(after_open..)?;
    let mut depth = 1u32;
    for (i, c) in rest.char_indices() {
        if c == open_c {
            depth += 1;
        } else if c == close_c {
            depth -= 1;
            if depth == 0 {
                return Some(after_open + i);
            }
        }
    }
    None
}

/// Convert a cursor position in characters to byte offset.
fn cursor_byte(s: &str, cursor_char: usize) -> usize {
    s.char_indices().nth(cursor_char).map(|(i, _)| i).unwrap_or(s.len())
}

/// Index in `new` (byte offset) of the inserted character when `new.len() == old.len() + 1`.
fn new_char_index(old: &str, new: &str) -> Option<usize> {
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

/// Innermost bracket whose content contains the cursor, recorded as (content_start_byte, content_end_byte).
/// content_end_byte is the byte position of the closing char, or s.len() if unclosed.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum InnermostBracket {
    Paren(usize, usize),
    Square(usize, usize),
    Curly(usize, usize),
}

/// Pick the bracket whose open is closest to the cursor (largest content_start ≤ cursor) among
/// brackets that either contain the cursor (close ≥ cursor) or are unclosed.
pub fn innermost_around_cursor(s: &str, cursor_char: usize) -> Option<InnermostBracket> {
    let cb = cursor_byte(s, cursor_char);
    let mut best: Option<(usize, InnermostBracket)> = None;

    let consider = |open_c: char, close_c: char, best: &mut Option<(usize, InnermostBracket)>, s: &str, cb: usize| {
        let Some(open_pos) = s[..cb].rfind(open_c) else {
            return;
        };
        let close = find_matching_close(s, open_pos, open_c, close_c);
        let end = close.unwrap_or(s.len());
        if close.is_some() && end < cb {
            return;
        }
        let content_start = open_pos + open_c.len_utf8();
        if content_start > cb {
            return;
        }
        let bracket = match open_c {
            '(' => InnermostBracket::Paren(content_start, end),
            '[' => InnermostBracket::Square(content_start, end),
            '{' => InnermostBracket::Curly(content_start, end),
            _ => return,
        };
        if best.map_or(true, |(cs, _)| content_start > cs) {
            *best = Some((content_start, bracket));
        }
    };
    consider('(', ')', &mut best, s, cb);
    consider('[', ']', &mut best, s, cb);
    consider('{', '}', &mut best, s, cb);
    best.map(|(_, b)| b)
}

/// Tokenize the expression for the preview row. Each token is a chunk of text the user wrote,
/// classified as a literal kind so we can render chips for [..] and {..}.
///
/// As a special case, the patterns `(winner {NAME})` and `(loser {NAME})` collapse into a
/// single `WinnerCall`/`LoserCall` token — they're conceptually a single team-reference,
/// just spelled differently from `[NAME::winner]` / `[NAME::loser]`.
#[derive(Clone, Debug)]
enum PreviewToken {
    Text(String),
    Team(String),
    Match(String),
    WinnerCall(String),
    LoserCall(String),
    OpenBracket(char),
    CloseBracket(char),
}

/// If `s[i..]` starts with `( <ws>* (winner|loser) <ws>+ {NAME} <ws>* )`, return
/// `(winner_or_loser, name, end_byte)` so we can collapse it into a single chip.
fn match_winner_loser_call(s: &str, i: usize) -> Option<(bool, String, usize)> {
    let bytes = s.as_bytes();
    if bytes.get(i).copied() != Some(b'(') {
        return None;
    }
    let mut j = i + 1;
    while j < bytes.len() && bytes[j].is_ascii_whitespace() {
        j += 1;
    }
    let is_winner = if s[j..].starts_with("winner") {
        j += "winner".len();
        true
    } else if s[j..].starts_with("loser") {
        j += "loser".len();
        false
    } else {
        return None;
    };
    if !bytes.get(j).map_or(false, |c| c.is_ascii_whitespace()) {
        return None;
    }
    while j < bytes.len() && bytes[j].is_ascii_whitespace() {
        j += 1;
    }
    if bytes.get(j).copied() != Some(b'{') {
        return None;
    }
    let after_open = j + 1;
    let close_rel = s[after_open..].find('}')?;
    let name = s[after_open..after_open + close_rel].trim().to_string();
    let mut k = after_open + close_rel + 1;
    while k < bytes.len() && bytes[k].is_ascii_whitespace() {
        k += 1;
    }
    if bytes.get(k).copied() != Some(b')') {
        return None;
    }
    Some((is_winner, name, k + 1))
}

fn tokenize_preview(s: &str) -> Vec<PreviewToken> {
    let mut out: Vec<PreviewToken> = Vec::new();
    let bytes = s.as_bytes();
    let mut i = 0;
    let mut text_buf = String::new();
    let flush_text = |buf: &mut String, out: &mut Vec<PreviewToken>| {
        if !buf.is_empty() {
            out.push(PreviewToken::Text(std::mem::take(buf)));
        }
    };
    while i < bytes.len() {
        let c = bytes[i] as char;
        if c == '(' {
            if let Some((is_winner, name, end)) = match_winner_loser_call(s, i) {
                flush_text(&mut text_buf, &mut out);
                if is_winner {
                    out.push(PreviewToken::WinnerCall(name));
                } else {
                    out.push(PreviewToken::LoserCall(name));
                }
                i = end;
                continue;
            }
        }
        if c == '[' || c == '{' {
            let close_c = if c == '[' { ']' } else { '}' };
            // Find first close in same kind without trying to support nesting (literals don't nest).
            let after = i + 1;
            if let Some(rel) = s[after..].find(close_c) {
                let inner = &s[after..after + rel];
                flush_text(&mut text_buf, &mut out);
                if c == '[' {
                    out.push(PreviewToken::Team(inner.to_string()));
                } else {
                    out.push(PreviewToken::Match(inner.to_string()));
                }
                i = after + rel + 1;
                continue;
            } else {
                // Unclosed: render as open bracket then continue rendering remaining text
                flush_text(&mut text_buf, &mut out);
                out.push(PreviewToken::OpenBracket(c));
                i += 1;
                continue;
            }
        }
        if c == ']' || c == '}' {
            flush_text(&mut text_buf, &mut out);
            out.push(PreviewToken::CloseBracket(c));
            i += 1;
            continue;
        }
        text_buf.push(c);
        i += 1;
    }
    if !text_buf.is_empty() {
        out.push(PreviewToken::Text(text_buf));
    }
    out
}

#[derive(Clone, Debug)]
struct TeamRefResolved {
    profile_photo: Option<String>,
    display: String,
}

/// Resolve a `[...]` literal to display info: pseudonym, tag→team, MatchName::winner/loser.
/// Returns the kind label and resolved team if available.
fn resolve_team_literal(
    inner: &str,
    team_options: &[TeamOption],
    tags: &[TagSetupData],
    matches: &[MatchSetupData],
) -> (TeamRefKind, Option<TeamRefResolved>) {
    let trimmed = inner.trim();
    if let Some(rest) = trimmed.strip_suffix("::winner") {
        let name = rest.trim();
        let resolved = matches
            .iter()
            .find(|m| m.name.eq_ignore_ascii_case(name) && m.status.eq_ignore_ascii_case("COMPLETED"))
            .and_then(|m| match m.match_winner.as_deref() {
                Some(s) if s.eq_ignore_ascii_case("TEAM1") => m.team1.clone(),
                Some(s) if s.eq_ignore_ascii_case("TEAM2") => m.team2.clone(),
                _ => None,
            })
            .and_then(|tid| team_options.iter().find(|t| t.id == tid))
            .map(|t| TeamRefResolved {
                profile_photo: t.profile_photo.clone(),
                display: t.pseudonym.clone().map(|p| format!("{p} ({})", t.id)).unwrap_or_else(|| t.id.clone()),
            });
        return (TeamRefKind::Winner(name.to_string()), resolved);
    }
    if let Some(rest) = trimmed.strip_suffix("::loser") {
        let name = rest.trim();
        let resolved = matches
            .iter()
            .find(|m| m.name.eq_ignore_ascii_case(name) && m.status.eq_ignore_ascii_case("COMPLETED"))
            .and_then(|m| match m.match_winner.as_deref() {
                Some(s) if s.eq_ignore_ascii_case("TEAM1") => m.team2.clone(),
                Some(s) if s.eq_ignore_ascii_case("TEAM2") => m.team1.clone(),
                _ => None,
            })
            .and_then(|tid| team_options.iter().find(|t| t.id == tid))
            .map(|t| TeamRefResolved {
                profile_photo: t.profile_photo.clone(),
                display: t.pseudonym.clone().map(|p| format!("{p} ({})", t.id)).unwrap_or_else(|| t.id.clone()),
            });
        return (TeamRefKind::Loser(name.to_string()), resolved);
    }
    if trimmed.len() >= 5 && trimmed[..5].eq_ignore_ascii_case("tag::") {
        let name = trimmed[5..].trim();
        let resolved = tags
            .iter()
            .find(|t| t.name.eq_ignore_ascii_case(name))
            .and_then(|t| t.team.clone())
            .and_then(|tid| team_options.iter().find(|t| t.id == tid).cloned())
            .map(|t| TeamRefResolved {
                profile_photo: t.profile_photo.clone(),
                display: t.pseudonym.clone().map(|p| format!("{p} ({})", t.id)).unwrap_or_else(|| t.id.clone()),
            });
        return (TeamRefKind::Tag(name.to_string()), resolved);
    }
    let team = team_options.iter().find(|t| t.id.eq_ignore_ascii_case(trimmed));
    let resolved = team.map(|t| TeamRefResolved {
        profile_photo: t.profile_photo.clone(),
        display: t.pseudonym.clone().map(|p| format!("{p} ({})", t.id)).unwrap_or_else(|| t.id.clone()),
    });
    (TeamRefKind::Team(trimmed.to_string()), resolved)
}

#[derive(Clone, Debug)]
enum TeamRefKind {
    Team(String),
    Tag(String),
    Winner(String),
    Loser(String),
}

/// Compact display name for a team — prefer `shortname` when present, then `pseudonym`, then id.
fn team_short_label(t: &TeamOption) -> String {
    t.shortname
        .clone()
        .or_else(|| t.pseudonym.clone())
        .unwrap_or_else(|| t.id.clone())
}

/// One ASS atom (the kind of thing that can stand in for a team in a match): a team id,
/// `tag::TagName`, or `MatchName::winner` / `MatchName::loser`. Used to render compact
/// inline references in the match autocomplete.
#[derive(Clone, Debug)]
enum AssAtom {
    Team(String),       // team id
    Tag(String),        // tag name (without the "tag::" prefix)
    Winner(String),     // match name
    Loser(String),      // match name
}

fn parse_ass_atom(raw: &str) -> AssAtom {
    let s = raw.trim();
    if let Some(rest) = s.strip_suffix("::winner") {
        return AssAtom::Winner(rest.trim().to_string());
    }
    if let Some(rest) = s.strip_suffix("::loser") {
        return AssAtom::Loser(rest.trim().to_string());
    }
    if s.len() >= 5 && s[..5].eq_ignore_ascii_case("tag::") {
        return AssAtom::Tag(s[5..].trim().to_string());
    }
    AssAtom::Team(s.to_string())
}

/// Render an ASS atom as a compact inline pill: avatar + shortname for teams, an
/// icon + label for tags / winner / loser. Used in the match autocomplete to show
/// who's playing and reffing without taking much space.
fn render_atom_compact(
    raw: &str,
    base_url: &str,
    team_options: &[TeamOption],
    tags: &[TagSetupData],
) -> Element {
    let atom = parse_ass_atom(raw);
    match atom {
        AssAtom::Team(id) => {
            if let Some(t) = team_options.iter().find(|t| t.id.eq_ignore_ascii_case(&id)) {
                let label = team_short_label(t);
                if let Some(p) = t.profile_photo.clone() {
                    rsx! {
                        span { class: "ass-atom",
                            img {
                                src: "{base_url}/static/{p}",
                                alt: "",
                                class: "ass-atom-avatar rounded-circle",
                            }
                            span { class: "ass-atom-label", "{label}" }
                        }
                    }
                } else {
                    let initial = label.chars().next().unwrap_or('?').to_string();
                    rsx! {
                        span { class: "ass-atom",
                            span { class: "ass-atom-avatar ass-atom-avatar-text", "{initial}" }
                            span { class: "ass-atom-label", "{label}" }
                        }
                    }
                }
            } else {
                rsx! {
                    span { class: "ass-atom ass-atom-unknown",
                        span { class: "ass-atom-avatar ass-atom-avatar-text", "?" }
                        span { class: "ass-atom-label", "{id}" }
                    }
                }
            }
        }
        AssAtom::Tag(name) => {
            let known = tags.iter().any(|t| t.name.eq_ignore_ascii_case(&name));
            let cls = if known { "ass-atom" } else { "ass-atom ass-atom-unknown" };
            rsx! {
                span { class: "{cls}",
                    img { class: "ass-atom-icon icon-primary-svg", src: "{base_url}/static/tag.svg", alt: "" }
                    span { class: "ass-atom-label", "{name}" }
                }
            }
        }
        AssAtom::Winner(name) => rsx! {
            span { class: "ass-atom",
                img { class: "ass-atom-icon icon-primary-svg", src: "{base_url}/static/reference.svg", alt: "" }
                span { class: "ass-atom-label", "{name}" }
                span { class: "ass-atom-badge winner-badge", "W" }
            }
        },
        AssAtom::Loser(name) => rsx! {
            span { class: "ass-atom",
                img { class: "ass-atom-icon icon-primary-svg", src: "{base_url}/static/reference.svg", alt: "" }
                span { class: "ass-atom-label", "{name}" }
                span { class: "ass-atom-badge loser-badge", "L" }
            }
        },
    }
}

/// Split a comma-separated list of ASS atoms ("team1, tag::Foo, Match1::winner") into trimmed pieces.
fn split_atoms(raw: &str) -> Vec<String> {
    raw.split(',').map(str::trim).filter(|s| !s.is_empty()).map(str::to_string).collect()
}

/// Render an ASS expression string as a row of chips: literals (`[..]`/`{..}`) and the
/// `(winner ...)` / `(loser ...)` patterns become labeled chips with resolution arrows;
/// everything else passes through as plain text.
fn render_expression_chips(
    s: &str,
    team_options: &[TeamOption],
    tags: &[TagSetupData],
    matches: &[MatchSetupData],
    base_url: &str,
    key_prefix: &str,
) -> Vec<Element> {
    tokenize_preview(s)
        .into_iter()
        .enumerate()
        .map(|(i, tok)| match tok {
            PreviewToken::Text(s) => {
                let key = format!("{key_prefix}-{i}");
                rsx! { span { key: "{key}", class: "ass-entry-preview-text", "{s}" } }
            }
            PreviewToken::OpenBracket(c) | PreviewToken::CloseBracket(c) => {
                let key = format!("{key_prefix}-{i}");
                let txt = c.to_string();
                rsx! { span { key: "{key}", class: "ass-entry-preview-bracket text-warning", "{txt}" } }
            }
            PreviewToken::Team(inner) => {
                let key = format!("{key_prefix}-{i}");
                let (kind, resolved) = resolve_team_literal(&inner, team_options, tags, matches);
                let (chip_class, label, icon) = match &kind {
                    TeamRefKind::Team(name) => ("team-token-chip team-token-chip-team", name.clone(), None),
                    TeamRefKind::Tag(name) => (
                        "team-token-chip team-token-chip-tag",
                        name.clone(),
                        Some(("tag.svg", "Tag")),
                    ),
                    TeamRefKind::Winner(name) => (
                        "team-token-chip team-token-chip-winner",
                        format!("{} winner", name),
                        Some(("reference.svg", "Reference")),
                    ),
                    TeamRefKind::Loser(name) => (
                        "team-token-chip team-token-chip-loser",
                        format!("{} loser", name),
                        Some(("reference.svg", "Reference")),
                    ),
                };
                let avatar = match (&kind, &resolved) {
                    (TeamRefKind::Team(_), Some(r)) => {
                        if let Some(p) = r.profile_photo.clone() {
                            rsx! { img {
                                src: "{base_url}/static/{p}",
                                alt: "",
                                class: "team-token-avatar rounded-circle",
                                style: "width: 1.4em; height: 1.4em; object-fit: cover;"
                            } }
                        } else {
                            rsx! { span { class: "team-token-avatar", "{r.display.chars().next().unwrap_or('?')}" } }
                        }
                    }
                    (TeamRefKind::Team(name), None) => {
                        rsx! { span { class: "team-token-avatar", "{name.chars().next().unwrap_or('?')}" } }
                    }
                    _ => {
                        if let Some((icon_name, alt)) = icon {
                            rsx! { img { class: "team-token-icon icon-primary-svg", src: "{base_url}/static/{icon_name}", alt: "{alt}" } }
                        } else {
                            rsx! {}
                        }
                    }
                };
                let resolved_arrow = match (&kind, resolved.clone()) {
                    (TeamRefKind::Team(_), _) => rsx! {},
                    (_, Some(r)) => {
                        let disp = r.display.clone();
                        let photo = r.profile_photo.clone();
                        rsx! {
                            span { class: "team-token-resolved text-muted ms-1",
                                " → "
                                if let Some(p) = photo {
                                    img {
                                        src: "{base_url}/static/{p}",
                                        alt: "",
                                        class: "team-token-avatar small rounded-circle ms-1",
                                        style: "width: 1em; height: 1em; object-fit: cover; vertical-align: middle;"
                                    }
                                } else {
                                    span { class: "team-token-avatar small ms-1", style: "display: inline-flex; width: 1em; height: 1em; align-items: center; justify-content: center; font-size: 0.85em;", "{disp.chars().next().unwrap_or('?')}" }
                                }
                                span { "{disp}" }
                            }
                        }
                    }
                    _ => rsx! {},
                };
                rsx! {
                    span { key: "{key}", class: "{chip_class}",
                        {avatar}
                        span { class: "team-token-label", "{label}" }
                        {resolved_arrow}
                    }
                }
            }
            PreviewToken::Match(inner) => {
                let key = format!("{key_prefix}-{i}");
                let name = inner.trim().to_string();
                let known = matches.iter().any(|m| m.name.eq_ignore_ascii_case(&name));
                let extra_class = if known { "" } else { " ass-entry-preview-unknown" };
                rsx! {
                    span { key: "{key}", class: "team-token-chip team-token-chip-match{extra_class}",
                        img { class: "team-token-icon icon-primary-svg", src: "{base_url}/static/reference.svg", alt: "Match" }
                        span { class: "team-token-label", "{name}" }
                    }
                }
            }
            ref tok @ (PreviewToken::WinnerCall(_) | PreviewToken::LoserCall(_)) => {
                let key = format!("{key_prefix}-{i}");
                let (name, is_winner) = match tok {
                    PreviewToken::WinnerCall(n) => (n.clone(), true),
                    PreviewToken::LoserCall(n) => (n.clone(), false),
                    _ => unreachable!(),
                };
                let chip_class = if is_winner {
                    "team-token-chip team-token-chip-winner"
                } else {
                    "team-token-chip team-token-chip-loser"
                };
                let label = if is_winner {
                    format!("{} winner", name)
                } else {
                    format!("{} loser", name)
                };
                let resolved = matches
                    .iter()
                    .find(|m| m.name.eq_ignore_ascii_case(&name) && m.status.eq_ignore_ascii_case("COMPLETED"))
                    .and_then(|m| {
                        let side = m.match_winner.as_deref()?;
                        let id = if is_winner {
                            if side.eq_ignore_ascii_case("TEAM1") { m.team1.clone() } else if side.eq_ignore_ascii_case("TEAM2") { m.team2.clone() } else { None }
                        } else if side.eq_ignore_ascii_case("TEAM1") { m.team2.clone() } else if side.eq_ignore_ascii_case("TEAM2") { m.team1.clone() } else { None }?;
                        Some(id)
                    })
                    .and_then(|tid| team_options.iter().find(|t| t.id == tid).cloned());
                let resolved_arrow = if let Some(t) = resolved {
                    let team_label = team_short_label(&t);
                    let photo = t.profile_photo.clone();
                    rsx! {
                        span { class: "team-token-resolved text-muted ms-1",
                            " → "
                            if let Some(p) = photo {
                                img {
                                    src: "{base_url}/static/{p}",
                                    alt: "",
                                    class: "team-token-avatar small rounded-circle ms-1",
                                    style: "width: 1em; height: 1em; object-fit: cover; vertical-align: middle;"
                                }
                            } else {
                                span { class: "team-token-avatar small ms-1", style: "display: inline-flex; width: 1em; height: 1em; align-items: center; justify-content: center; font-size: 0.85em;", "{team_label.chars().next().unwrap_or('?')}" }
                            }
                            span { "{team_label}" }
                        }
                    }
                } else {
                    rsx! {}
                };
                rsx! {
                    span { key: "{key}", class: "{chip_class}",
                        img { class: "team-token-icon icon-primary-svg", src: "{base_url}/static/reference.svg", alt: "Reference" }
                        span { class: "team-token-label", "{label}" }
                        {resolved_arrow}
                    }
                }
            }
        })
        .collect()
}

#[derive(Clone, Debug)]
enum AcOption {
    Function {
        name: String,
        signature: String,
        description: String,
    },
    Team {
        insert: String,
        display: String,
        photo: Option<String>,
    },
    Tag {
        insert: String,
        display: String,
        resolved_team: Option<String>,
    },
    MatchRef {
        insert: String,
        display: String,
        is_winner: bool,
    },
    Match {
        insert: String,
        display: String,
        field: Option<String>,
        team1: Option<String>,
        team2: Option<String>,
        refs: Vec<String>,
    },
}

fn collect_function_options(prefix: &str) -> Vec<AcOption> {
    let q = prefix.to_lowercase();
    DSL_FUNCTIONS
        .iter()
        .filter(|(n, _, _)| q.is_empty() || n.to_lowercase().starts_with(&q))
        .take(20)
        .map(|(n, s, d)| AcOption::Function {
            name: (*n).to_string(),
            signature: (*s).to_string(),
            description: (*d).to_string(),
        })
        .collect()
}

fn collect_team_options(
    query: &str,
    team_options: &[TeamOption],
    tags: &[TagSetupData],
    matches: &[MatchSetupData],
) -> Vec<AcOption> {
    let q = query.to_lowercase();
    // Build each kind separately, then interleave with per-kind caps so tags/matches always
    // get a fair slice when there's no query (otherwise a long team list can starve them).
    let team_opts: Vec<AcOption> = team_options
        .iter()
        .filter(|t| {
            q.is_empty()
                || t.id.to_lowercase().contains(&q)
                || t.pseudonym.as_deref().unwrap_or("").to_lowercase().contains(&q)
        })
        .map(|t| AcOption::Team {
            insert: t.id.clone(),
            display: t
                .pseudonym
                .clone()
                .map(|p| format!("{p} ({})", t.id))
                .unwrap_or_else(|| t.id.clone()),
            photo: t.profile_photo.clone(),
        })
        .collect();
    let tag_opts: Vec<AcOption> = tags
        .iter()
        .filter(|tag| q.is_empty() || tag.name.to_lowercase().contains(&q))
        .map(|tag| AcOption::Tag {
            insert: format!("tag::{}", tag.name),
            display: tag.name.clone(),
            resolved_team: tag.team.clone(),
        })
        .collect();
    let mut match_ref_opts: Vec<AcOption> = Vec::new();
    for m in matches.iter() {
        if q.is_empty() || m.name.to_lowercase().contains(&q) {
            match_ref_opts.push(AcOption::MatchRef {
                insert: format!("{}::winner", m.name),
                display: format!("{} winner", m.name),
                is_winner: true,
            });
            match_ref_opts.push(AcOption::MatchRef {
                insert: format!("{}::loser", m.name),
                display: format!("{} loser", m.name),
                is_winner: false,
            });
        }
    }
    // Caps: when the query is empty, give each kind a fair slice. With a query, prefer the
    // best matches but keep tag/match-ref space available.
    let (team_cap, tag_cap, match_cap) = if q.is_empty() { (12, 8, 10) } else { (15, 8, 10) };
    let mut out: Vec<AcOption> = Vec::new();
    out.extend(team_opts.into_iter().take(team_cap));
    out.extend(tag_opts.into_iter().take(tag_cap));
    out.extend(match_ref_opts.into_iter().take(match_cap));
    out.into_iter().take(30).collect()
}

fn collect_match_options(query: &str, matches: &[MatchSetupData]) -> Vec<AcOption> {
    let q = query.to_lowercase();
    matches
        .iter()
        .filter(|m| q.is_empty() || m.name.to_lowercase().contains(&q))
        .take(25)
        .map(|m| AcOption::Match {
            insert: m.name.clone(),
            display: m.name.clone(),
            field: m.field.clone(),
            team1: m.team1_initial.clone().or_else(|| m.team1.clone()),
            team2: m.team2_initial.clone().or_else(|| m.team2.clone()),
            refs: m
                .refs_initial
                .as_deref()
                .or(m.refs.as_deref())
                .map(split_atoms)
                .unwrap_or_default(),
        })
        .collect()
}

#[component]
pub fn AssEntry(
    /// Unique suffix for input ID (e.g. "create", "edit", "modal"). Multiple instances need distinct IDs.
    id_suffix: String,
    value: String,
    on_change: EventHandler<String>,
    team_options: Vec<TeamOption>,
    tags: Vec<TagSetupData>,
    matches: Vec<MatchSetupData>,
    /// For server-side validate-dsl on blur. Pass empty to skip server validation.
    tournament_url: String,
    #[props(default = String::from("e.g. (== 0 (losses [Team]))"))] placeholder: String,
) -> Element {
    let input_id = format!("ass-entry-{}", id_suffix);

    let value_rc = Rc::new(value.clone());
    let team_options_rc = Rc::new(team_options);
    let tags_rc = Rc::new(tags);
    let matches_rc = Rc::new(matches);

    let mut cursor_pos = use_signal(|| None::<usize>);
    let mut pending_cursor = use_signal(|| None::<usize>);
    let mut ac_index = use_signal(|| 0usize);
    let mut ac_open = use_signal(|| false);
    let mut error_msg = use_signal(|| None::<String>);
    // Tagged with the input string the simplification was computed for, so we can hide it
    // when the user has typed something that no longer matches.
    let mut simplified_msg = use_signal(|| None::<(String, String)>);

    // After auto-close insertions, we need to reposition the cursor on the next tick.
    #[cfg(target_arch = "wasm32")]
    {
        let id_eff = input_id.clone();
        use_effect(move || {
            if let Some(p) = pending_cursor() {
                pending_cursor.set(None);
                let id = id_eff.clone();
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
    }

    // Debounced re-validation: when the value settles for ~500ms, ask the server for a
    // fresh simplification. Without this, the simplified row only refreshes on blur,
    // which is rare while the user is actively editing.
    #[cfg(target_arch = "wasm32")]
    {
        let v_for_effect = value_rc.as_ref().clone();
        let url_for_effect = tournament_url.clone();
        use_effect(move || {
            let v = v_for_effect.clone();
            let url = url_for_effect.clone();
            if v.trim().is_empty() || url.is_empty() {
                return;
            }
            spawn(async move {
                gloo_timers::future::TimeoutFuture::new(500).await;
                let validated_for = v.clone();
                if let Ok(res) = api::validate_dsl(&url, &v).await {
                    if res.valid {
                        error_msg.set(None);
                        if let Some(simp) = res.simplified {
                            simplified_msg.set(Some((validated_for, simp)));
                        }
                    } else {
                        error_msg.set(res.error);
                    }
                }
            });
        });
    }

    // Compute autocomplete state from the current value and cursor.
    let v = value_rc.as_ref().clone();
    let cur = cursor_pos();
    let inn = cur.and_then(|c| innermost_around_cursor(&v, c));
    let cursor_b = cur.map(|c| cursor_byte(&v, c)).unwrap_or(0);

    let ac_options: Vec<AcOption> = if ac_open() {
        match &inn {
            Some(InnermostBracket::Paren(cs, ce)) => {
                let end = (*ce).min(cursor_b).max(*cs);
                let prefix = v[*cs..end].split_whitespace().next().unwrap_or("");
                collect_function_options(prefix)
            }
            Some(InnermostBracket::Square(cs, ce)) => {
                let end = (*ce).min(cursor_b).max(*cs);
                let q = v[*cs..end].trim();
                collect_team_options(q, team_options_rc.as_ref(), tags_rc.as_ref(), matches_rc.as_ref())
            }
            Some(InnermostBracket::Curly(cs, ce)) => {
                let end = (*ce).min(cursor_b).max(*cs);
                let q = v[*cs..end].trim();
                collect_match_options(q, matches_rc.as_ref())
            }
            None => vec![],
        }
    } else {
        vec![]
    };

    let ac_idx = ac_index().min(ac_options.len().saturating_sub(1));

    let preview_tokens = tokenize_preview(&v);
    let base_url = api::base_url();

    let v_for_oninput = v.clone();
    let value_rc_input = value_rc.clone();
    let on_change_input = on_change.clone();
    let oninput_handler = move |e: Event<FormData>| {
        let new_val = e.value();
        let old = value_rc_input.as_ref().clone();
        let _ = v_for_oninput;
        // Auto-close brackets on single-char insert.
        let (out, after_open) = if let Some(byte_i) = new_char_index(&old, &new_val) {
            let open_c = new_val[byte_i..].chars().next().unwrap_or('\0');
            let closing = match open_c {
                '(' => Some(')'),
                '[' => Some(']'),
                '{' => Some('}'),
                _ => None,
            };
            if let Some(close_c) = closing {
                let char_end = byte_i + open_c.len_utf8();
                let out_str = format!("{}{}{}", &new_val[..char_end], close_c, &new_val[char_end..]);
                (out_str, Some(char_end))
            } else {
                (new_val, None)
            }
        } else {
            (new_val, None)
        };
        on_change_input.call(out);
        ac_open.set(true);
        ac_index.set(0);
        error_msg.set(None);
        // Don't wipe simplified_msg here. It's tagged with the input it was computed for, so
        // the rsx guard hides it automatically once the input no longer matches; that's
        // gentler than the row blinking out on every keystroke.
        if let Some(byte_after_open) = after_open {
            // ASCII brackets only — byte position equals char position.
            pending_cursor.set(Some(byte_after_open));
        }
    };

    let id_for_keydown = input_id.clone();
    let value_rc_kd = value_rc.clone();
    let on_change_kd = on_change.clone();
    let ac_options_kd = ac_options.clone();
    let onkeydown_handler = move |ev: Event<KeyboardData>| {
        let key = ev.key().to_string();
        let n = ac_options_kd.len();
        if ac_open() && n > 0 {
            if key == "ArrowDown" {
                ev.prevent_default();
                ac_index.set((ac_idx + 1) % n);
                return;
            }
            if key == "ArrowUp" {
                ev.prevent_default();
                ac_index.set((ac_idx + n - 1) % n);
                return;
            }
            if key == "Tab" || (key == "Enter" && !ev.modifiers().contains(Modifiers::SHIFT)) {
                if let Some(opt) = ac_options_kd.get(ac_idx) {
                    ev.prevent_default();
                    let v_now = value_rc_kd.as_ref().clone();
                    let cur_char = cursor_pos().unwrap_or(0);
                    let cur_b = cursor_byte(&v_now, cur_char);
                    let inn_now = innermost_around_cursor(&v_now, cur_char);
                    match (opt, inn_now) {
                        (AcOption::Function { name, .. }, Some(InnermostBracket::Paren(cs, ce))) => {
                            // Replace the prefix word inside the parens with the function name.
                            let end = ce.min(cur_b).max(cs);
                            let prefix_end = v_now[cs..end]
                                .find(|c: char| c.is_whitespace())
                                .map(|i| cs + i)
                                .unwrap_or(end);
                            let new_v = format!("{}{}{}", &v_now[..cs], name, &v_now[prefix_end..]);
                            let cs_chars = v_now[..cs].chars().count();
                            let new_cursor = cs_chars + name.chars().count();
                            on_change_kd.call(new_v);
                            pending_cursor.set(Some(new_cursor));
                            ac_open.set(false);
                            return;
                        }
                        (
                            AcOption::Team { insert, .. }
                            | AcOption::Tag { insert, .. }
                            | AcOption::MatchRef { insert, .. },
                            Some(InnermostBracket::Square(cs, ce)),
                        ) => {
                            let end = ce.min(cur_b).max(cs);
                            // Replace from cs to end with insert
                            let new_v = format!("{}{}{}", &v_now[..cs], insert, &v_now[end..]);
                            let cs_chars = v_now[..cs].chars().count();
                            let new_cursor = cs_chars + insert.chars().count();
                            on_change_kd.call(new_v);
                            pending_cursor.set(Some(new_cursor));
                            ac_open.set(false);
                            return;
                        }
                        (AcOption::Match { insert, .. }, Some(InnermostBracket::Curly(cs, ce))) => {
                            let end = ce.min(cur_b).max(cs);
                            let new_v = format!("{}{}{}", &v_now[..cs], insert, &v_now[end..]);
                            let cs_chars = v_now[..cs].chars().count();
                            let new_cursor = cs_chars + insert.chars().count();
                            on_change_kd.call(new_v);
                            pending_cursor.set(Some(new_cursor));
                            ac_open.set(false);
                            return;
                        }
                        _ => {}
                    }
                }
            }
            if key == "Escape" {
                ev.prevent_default();
                ac_open.set(false);
                return;
            }
        }
        // Block raw Enter so it doesn't submit the form (Shift+Enter still bubbles up).
        if key == "Enter" && !ev.modifiers().contains(Modifiers::SHIFT) {
            ev.prevent_default();
        }
        let _ = id_for_keydown.clone();
    };

    let id_for_keyup = input_id.clone();
    let onkeyup_handler = move |_| {
        let id = id_for_keyup.clone();
        spawn(async move {
            #[cfg(target_arch = "wasm32")]
            {
                gloo_timers::future::TimeoutFuture::new(0).await;
                if let Some(window) = web_sys::window() {
                    if let Some(doc) = window.document() {
                        if let Ok(Some(el)) = doc.query_selector(&format!("#{}", id)) {
                            if let Ok(input) = el.dyn_into::<web_sys::HtmlInputElement>() {
                                if let Ok(Some(sel)) = input.selection_start() {
                                    cursor_pos.set(Some(sel as usize));
                                }
                            }
                        }
                    }
                }
            }
            #[cfg(not(target_arch = "wasm32"))]
            let _ = id;
        });
    };

    let id_for_focus = input_id.clone();
    let onfocus_handler = move |_| {
        ac_open.set(true);
        let id = id_for_focus.clone();
        spawn(async move {
            #[cfg(target_arch = "wasm32")]
            {
                gloo_timers::future::TimeoutFuture::new(0).await;
                if let Some(window) = web_sys::window() {
                    if let Some(doc) = window.document() {
                        if let Ok(Some(el)) = doc.query_selector(&format!("#{}", id)) {
                            if let Ok(input) = el.dyn_into::<web_sys::HtmlInputElement>() {
                                if let Ok(Some(sel)) = input.selection_start() {
                                    cursor_pos.set(Some(sel as usize));
                                }
                            }
                        }
                    }
                }
            }
            #[cfg(not(target_arch = "wasm32"))]
            let _ = id;
        });
    };

    let url_for_blur = tournament_url.clone();
    let value_rc_blur = value_rc.clone();
    let onblur_handler = move |_| {
        ac_open.set(false);
        let expr = value_rc_blur.as_ref().clone();
        let url = url_for_blur.clone();
        if expr.trim().is_empty() {
            error_msg.set(None);
            simplified_msg.set(None);
            return;
        }
        if url.is_empty() {
            return;
        }
        spawn(async move {
            let validated_for = expr.clone();
            match api::validate_dsl(&url, &expr).await {
                Ok(res) => {
                    if res.valid {
                        error_msg.set(None);
                        simplified_msg.set(res.simplified.map(|s| (validated_for, s)));
                    } else {
                        error_msg.set(res.error);
                        simplified_msg.set(None);
                    }
                }
                Err(e) => {
                    error_msg.set(Some(e));
                    simplified_msg.set(None);
                }
            }
        });
    };

    // Build dropdown items.
    let team_options_for_render = team_options_rc.clone();
    let tags_for_render = tags_rc.clone();
    let matches_for_render = matches_rc.clone();
    let value_rc_click = value_rc.clone();
    let on_change_click = on_change.clone();
    let click_rc: Rc<RefCell<Box<dyn FnMut(usize)>>> = {
        let opts = ac_options.clone();
        Rc::new(RefCell::new(Box::new(move |idx: usize| {
            let Some(opt) = opts.get(idx).cloned() else {
                return;
            };
            let v_now = value_rc_click.as_ref().clone();
            let cur_char = cursor_pos().unwrap_or(v_now.chars().count());
            let cur_b = cursor_byte(&v_now, cur_char);
            let inn_now = innermost_around_cursor(&v_now, cur_char);
            match (opt, inn_now) {
                (AcOption::Function { name, .. }, Some(InnermostBracket::Paren(cs, ce))) => {
                    let end = ce.min(cur_b).max(cs);
                    let prefix_end = v_now[cs..end]
                        .find(|c: char| c.is_whitespace())
                        .map(|i| cs + i)
                        .unwrap_or(end);
                    let new_v = format!("{}{}{}", &v_now[..cs], name, &v_now[prefix_end..]);
                    let cs_chars = v_now[..cs].chars().count();
                    let new_cursor = cs_chars + name.chars().count();
                    on_change_click.call(new_v);
                    pending_cursor.set(Some(new_cursor));
                    ac_open.set(false);
                }
                (
                    AcOption::Team { insert, .. }
                    | AcOption::Tag { insert, .. }
                    | AcOption::MatchRef { insert, .. },
                    Some(InnermostBracket::Square(cs, ce)),
                ) => {
                    let end = ce.min(cur_b).max(cs);
                    let new_v = format!("{}{}{}", &v_now[..cs], insert, &v_now[end..]);
                    let cs_chars = v_now[..cs].chars().count();
                    let new_cursor = cs_chars + insert.chars().count();
                    on_change_click.call(new_v);
                    pending_cursor.set(Some(new_cursor));
                    ac_open.set(false);
                }
                (AcOption::Match { insert, .. }, Some(InnermostBracket::Curly(cs, ce))) => {
                    let end = ce.min(cur_b).max(cs);
                    let new_v = format!("{}{}{}", &v_now[..cs], insert, &v_now[end..]);
                    let cs_chars = v_now[..cs].chars().count();
                    let new_cursor = cs_chars + insert.chars().count();
                    on_change_click.call(new_v);
                    pending_cursor.set(Some(new_cursor));
                    ac_open.set(false);
                }
                _ => {}
            }
        })))
    };

    let dropdown_items: Vec<_> = ac_options
        .iter()
        .enumerate()
        .map(|(idx, opt)| {
            let click = click_rc.clone();
            let is_active = idx == ac_idx;
            let li_class = if is_active {
                "ass-entry-ac-item ass-entry-ac-item-active"
            } else {
                "ass-entry-ac-item"
            };
            let inner = match opt {
                AcOption::Function { name, signature, description } => {
                    let n = name.clone();
                    let s = signature.clone();
                    let d = description.clone();
                    rsx! {
                        span { class: "ass-entry-ac-fn-name", "{n}" }
                        span { class: "ass-entry-ac-fn-sig text-muted", " {s}" }
                        div { class: "ass-entry-ac-fn-desc text-muted small", "{d}" }
                    }
                }
                AcOption::Team { display, photo, .. } => {
                    let d = display.clone();
                    if let Some(p) = photo.clone() {
                        rsx! {
                            img {
                                class: "team-token-avatar small me-1 rounded-circle",
                                style: "width: 1.4em; height: 1.4em; object-fit: cover;",
                                src: "{base_url}/static/{p}",
                                alt: "{d}",
                            }
                            span { "{d}" }
                        }
                    } else {
                        rsx! {
                            span { class: "team-token-avatar small me-1", "{d.chars().next().unwrap_or('?')}" }
                            span { "{d}" }
                        }
                    }
                }
                AcOption::Tag { display, resolved_team, .. } => {
                    let d = display.clone();
                    let resolved_node = resolved_team
                        .as_ref()
                        .and_then(|tid| team_options_for_render.iter().find(|t| &t.id == tid))
                        .map(|t| {
                            let label = team_short_label(t);
                            let photo = t.profile_photo.clone();
                            rsx! {
                                span { class: "ass-entry-ac-resolved text-muted ms-2",
                                    " → "
                                    if let Some(p) = photo {
                                        img {
                                            src: "{base_url}/static/{p}",
                                            alt: "",
                                            class: "ass-atom-avatar rounded-circle",
                                        }
                                    } else {
                                        span { class: "ass-atom-avatar ass-atom-avatar-text", "{label.chars().next().unwrap_or('?')}" }
                                    }
                                    span { "{label}" }
                                }
                            }
                        });
                    rsx! {
                        span { class: "ass-entry-ac-row",
                            img { class: "icon-primary-svg me-1", src: "{base_url}/static/tag.svg", alt: "Tag", style: "width: 1.25em; height: 1.25em;" }
                            span { "{d}" }
                            if let Some(r) = resolved_node { {r} }
                        }
                    }
                }
                AcOption::MatchRef { display, is_winner, .. } => {
                    let d = display.clone();
                    let badge = if *is_winner { "winner" } else { "loser" };
                    rsx! {
                        img { class: "icon-primary-svg me-1", src: "{base_url}/static/reference.svg", alt: "Reference", style: "width: 1.25em; height: 1.25em;" }
                        span { "{d}" }
                        span { class: "team-token-badge ms-1 {badge}-badge small", "{badge}" }
                    }
                }
                AcOption::Match { display, field, team1, team2, refs, .. } => {
                    let d = display.clone();
                    let field_str = field.clone().unwrap_or_default();
                    let teams_for_atom = team_options_for_render.clone();
                    let tags_for_atom = tags_for_render.clone();
                    let team1_node = team1.as_deref().map(|raw| render_atom_compact(raw, &base_url, teams_for_atom.as_ref(), tags_for_atom.as_ref()));
                    let teams_for_atom2 = team_options_for_render.clone();
                    let tags_for_atom2 = tags_for_render.clone();
                    let team2_node = team2.as_deref().map(|raw| render_atom_compact(raw, &base_url, teams_for_atom2.as_ref(), tags_for_atom2.as_ref()));
                    let teams_for_refs = team_options_for_render.clone();
                    let tags_for_refs = tags_for_render.clone();
                    let refs_clone = refs.clone();
                    let ref_nodes: Vec<_> = refs_clone
                        .iter()
                        .map(|raw| render_atom_compact(raw, &base_url, teams_for_refs.as_ref(), tags_for_refs.as_ref()))
                        .collect();
                    rsx! {
                        div { class: "ass-entry-ac-match-head",
                            img { class: "icon-primary-svg me-1", src: "{base_url}/static/reference.svg", alt: "Match", style: "width: 1.25em; height: 1.25em;" }
                            span { class: "ass-entry-ac-match-name", "{d}" }
                            if !field_str.is_empty() {
                                span { class: "ass-entry-ac-match-field text-muted ms-2", "on {field_str}" }
                            }
                        }
                        div { class: "ass-entry-ac-match-meta small text-muted",
                            if let Some(t) = team1_node { {t} }
                            span { class: "ass-entry-ac-vs mx-1", "vs" }
                            if let Some(t) = team2_node { {t} }
                            if !ref_nodes.is_empty() {
                                span { class: "ass-entry-ac-refs ms-2",
                                    span { class: "me-1", "refs:" }
                                    for ref_n in ref_nodes.iter() {
                                        {ref_n.clone()}
                                    }
                                }
                            }
                        }
                    }
                }
            };
            rsx! {
                li {
                    key: "{idx}",
                    class: "{li_class}",
                    onmousedown: move |ev: Event<MouseData>| { ev.prevent_default(); },
                    onclick: move |_| { click.borrow_mut()(idx); },
                    onmouseenter: move |_| { ac_index.set(idx); },
                    {inner}
                }
            }
        })
        .collect();

    let preview_chips = render_expression_chips(
        &v,
        team_options_for_render.as_ref(),
        tags_for_render.as_ref(),
        matches_for_render.as_ref(),
        &base_url,
        "input",
    );
    // Show the simplified row only when the cached simplification was computed for the
    // exact value currently in the input — keeps stale results from confusing the user.
    let simplified_value: Option<String> = simplified_msg().and_then(|(input_at, simp)| {
        if input_at.trim() == v.trim() {
            Some(simp)
        } else {
            None
        }
    });
    let simplified_chips = simplified_value.as_deref().map(|simp| {
        render_expression_chips(
            simp,
            team_options_for_render.as_ref(),
            tags_for_render.as_ref(),
            matches_for_render.as_ref(),
            &base_url,
            "simp",
        )
    });
    let _ = preview_tokens;

    rsx! {
        div { class: "ass-entry position-relative",
            input {
                id: "{input_id}",
                class: "form-control font-monospace ass-entry-input",
                "type": "text",
                placeholder: "{placeholder}",
                value: "{value}",
                oninput: oninput_handler,
                onkeydown: onkeydown_handler,
                onkeyup: onkeyup_handler,
                onfocus: onfocus_handler,
                onblur: onblur_handler,
            }
            if ac_open() && !ac_options.is_empty() {
                ul { class: "ass-entry-ac dropdown-menu show",
                    for item in dropdown_items.iter() {
                        {item.clone()}
                    }
                }
            }
            if !value.trim().is_empty() {
                div { class: "ass-entry-preview small",
                    for chip in preview_chips.iter() {
                        {chip.clone()}
                    }
                }
            }
            if let Some(chips) = simplified_chips.as_ref() {
                div { class: "ass-entry-simplified small",
                    span { class: "ass-entry-simplified-label text-muted me-1", "simplified:" }
                    for chip in chips.iter() {
                        {chip.clone()}
                    }
                }
            }
            if let Some(err) = error_msg() {
                div { class: "form-text text-danger ass-entry-error", "✗ {err}" }
            } else if simplified_value.is_some() {
                div { class: "form-text text-success", "✓ Valid" }
            } else if !value.trim().is_empty() {
                div { class: "form-text text-success", "✓" }
            }
        }
    }
}
