//! Display API timestamps in the browser's local timezone.

use chrono::NaiveDateTime;

/// Browser timezone offset in minutes (local = UTC + offset). Matches `schedule.rs`.
pub fn browser_tz_offset_minutes() -> i64 {
    #[cfg(target_arch = "wasm32")]
    {
        let date = js_sys::Date::new_0();
        let offset = date.get_timezone_offset();
        -offset as i64
    }
    #[cfg(not(target_arch = "wasm32"))]
    {
        0_i64
    }
}

fn parse_iso_utc_naive(s: &str) -> Option<NaiveDateTime> {
    let s = s.trim();
    if s.is_empty() {
        return None;
    }
    if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(s) {
        return Some(dt.naive_utc());
    }
    if let Ok(dt) = NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M:%S%.f") {
        return Some(dt);
    }
    if let Ok(dt) = NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M:%S") {
        return Some(dt);
    }
    if let Ok(dt) = NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M") {
        return Some(dt);
    }
    if let Ok(dt) = NaiveDateTime::parse_from_str(s, "%Y-%m-%d %H:%M:%S") {
        return Some(dt);
    }
    if let Ok(dt) = NaiveDateTime::parse_from_str(s, "%Y-%m-%d %H:%M") {
        return Some(dt);
    }
    None
}

/// `mm/dd hh:mm AM/PM` in the user's local timezone (browser on wasm).
pub fn format_match_display_local(iso: &str) -> String {
    let Some(utc_dt) = parse_iso_utc_naive(iso) else {
        return iso.to_string();
    };
    let local = utc_dt + chrono::Duration::minutes(browser_tz_offset_minutes());
    local.format("%m/%d %I:%M %p").to_string()
}
