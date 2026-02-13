use crate::api;
use crate::Route;
use dioxus::prelude::*;
use serde_json::Value;
#[cfg(target_arch = "wasm32")]
use gloo_timers::callback::Interval;

/// Parse ISO timestamp to epoch seconds (for stones elapsed).
fn parse_iso_epoch(s: &str) -> Option<i64> {
    let s = s.trim();
    chrono::DateTime::parse_from_rfc3339(s)
        .ok()
        .map(|dt| dt.timestamp())
        .or_else(|| {
            let with_z = if s.ends_with('Z') || s.contains('+') || (s.contains('-') && s.len() > 10) {
                s.to_string()
            } else {
                format!("{}Z", s.trim_end_matches('z').trim_end_matches('Z'))
            };
            chrono::DateTime::parse_from_rfc3339(&with_z).ok().map(|dt| dt.timestamp())
        })
        .or_else(|| {
            chrono::NaiveDateTime::parse_from_str(
                s.trim_end_matches('Z').trim_end_matches('z'),
                "%Y-%m-%dT%H:%M:%S",
            )
            .ok()
            .map(|t| t.and_utc().timestamp())
        })
}

#[cfg(target_arch = "wasm32")]
fn now_epoch_secs() -> f64 {
    js_sys::Date::new_0().get_time() / 1000.0
}

#[cfg(not(target_arch = "wasm32"))]
fn now_epoch_secs() -> f64 {
    chrono::Utc::now().timestamp() as f64
}

/// Compute scores_by_set from points array (client-authoritative; same logic as server).
fn scores_by_set_from_points(points: &[&Value]) -> Vec<(String, u64, u64)> {
    let mut by_set: std::collections::BTreeMap<u64, (u64, u64)> = std::collections::BTreeMap::new();
    for pt in points {
        let set_num = pt.get("set_number").and_then(|n| n.as_u64()).unwrap_or(1);
        let winner = pt.get("winner").and_then(|w| w.as_str()).unwrap_or("none");
        let rerolled = pt.get("rerolled").and_then(|r| r.as_bool()).unwrap_or(false);
        if rerolled {
            continue;
        }
        let entry = by_set.entry(set_num).or_insert((0, 0));
        if winner == "TEAM1" {
            entry.0 += 1;
        } else if winner == "TEAM2" {
            entry.1 += 1;
        }
    }
    by_set
        .into_iter()
        .map(|(k, (t1, t2))| (k.to_string(), t1, t2))
        .collect()
}

/// Stones elapsed (1.5s beats) between stamp and end (or now if end is None).
fn stones_elapsed_beats(stamp_opt: Option<&str>, end_opt: Option<&str>) -> u32 {
    let start = stamp_opt
        .and_then(parse_iso_epoch)
        .unwrap_or(0) as f64;
    let end = end_opt
        .and_then(parse_iso_epoch)
        .map(|t| t as f64)
        .unwrap_or_else(now_epoch_secs);
    ((end - start) / 1.5).floor().max(0.0) as u32
}

#[component]
pub fn RunMatch(url: String, match_id: String) -> Element {
    let navigator = use_navigator();
    let url_for_detail = url.clone();
    let id_for_detail = match_id.clone();
    let detail = use_resource(move || {
        let u = url_for_detail.clone();
        let id = id_for_detail.clone();
        async move {
            api::match_detail(&u, Some(&id), None)
                .await
                .map_err(|e| e.to_string())
        }
    });

    let state_signal = use_signal(|| None as Option<Result<Value, String>>);
    let state_loaded = use_signal(|| false);
    let url_for_state = url.clone();
    let id_for_state = match_id.clone();
    use_effect(move || {
        if state_loaded() {
            return;
        }
        let u = url_for_state.clone();
        let id = id_for_state.clone();
        let mut state_signal = state_signal;
        let mut state_loaded = state_loaded;
        state_loaded.set(true);
        spawn(async move {
            match api::match_state(&u, &id).await {
                Ok(v) => state_signal.set(Some(Ok(v))),
                Err(e) => state_signal.set(Some(Err(e))),
            }
        });
    });

    // In-progress point: when Some, button shows "End Point" and we tick stones.
    let mut current_point = use_signal(|| None as Option<String>);
    // Sync current_point from state: if latest point has no end_stamp, we're in End Point mode.
    let state_for_sync = state_signal();
    if let Some(Ok(ref v)) = state_for_sync {
        let points_arr = v.get("points").and_then(|p| p.as_array());
        let points: Vec<&Value> = points_arr.map(|a| a.iter().collect()).unwrap_or_default();
        if let Some(last) = points.last() {
            let end_stamp = last.get("end_stamp").and_then(|e| e.as_str());
            if end_stamp.is_none() || end_stamp == Some("") {
                let uuid = last.get("uuid").and_then(|u| u.as_str()).unwrap_or("");
                if !uuid.is_empty() && current_point().as_deref() != Some(uuid) {
                    current_point.set(Some(uuid.to_string()));
                }
            } else if current_point().as_deref() == last.get("uuid").and_then(|u| u.as_str()) {
                current_point.set(None);
            }
        }
    }

    // Tick for live stones elapsed and time elapsed (re-render every 500ms / 1s when needed).
    let live_tick = use_signal(|| 0u32);
    #[cfg(target_arch = "wasm32")]
    {
        let has_current = current_point().is_some();
        let mut live_tick = live_tick;
        use_effect(move || {
            let _ = current_point();
            let handle = Interval::new(500, move || {
                live_tick.set(live_tick() + 1);
            });
            std::mem::forget(handle);
        });
    }

    let action_error = use_signal(|| Option::<String>::None);
    let mut notes_modal_point_id = use_signal(|| None as Option<String>);
    let mut notes_modal_notes = use_signal(|| None as Option<Result<Vec<Value>, String>>);
    let mut notes_modal_new_text = use_signal(|| String::new());
    let mut notes_modal_target = use_signal(|| "match".to_string());
    let mut notes_modal_player_id = use_signal(|| None as Option<String>);
    let mut notes_modal_player_query = use_signal(|| String::new());
    let mut point_notes_map_signal =
        use_signal(|| std::collections::HashMap::<String, Vec<Value>>::new());
    let mut point_notes_seeded = use_signal(|| false);
    // Local stones remaining (for STONES set type); synced from match/state when not ticking.
    let mut stones_remaining = use_signal(|| 100u32);
    // Time elapsed (seconds) from match start.
    let mut time_elapsed_secs = use_signal(|| 0u64);

    use_effect(move || {
        if point_notes_seeded() {
            return;
        }
        let binding = detail.value();
        let Ok(guard) = binding.try_read() else { return };
        let Some(Ok(ref d)) = guard.as_ref() else { return };
        point_notes_seeded.set(true);
        let mut map = point_notes_map_signal();
        for (pid, notes) in &d.point_notes_map {
            let v: Vec<Value> = notes
                .iter()
                .filter_map(|n| serde_json::to_value(n).ok())
                .collect();
            map.insert(pid.clone(), v);
        }
        point_notes_map_signal.set(map);
    });

    let detail_view = match detail.value().try_read() {
        Ok(guard) => match guard.as_ref() {
            Some(Ok(d)) => {
                let m = &d.match_data;
                let set_type_stones = m.set_type.as_deref() == Some("STONES");
                let initial_stones = m
                    .stones_remaining
                    .or(m.stones_per_set)
                    .unwrap_or(100);
                // Initialize stones once from match
                if stones_remaining() == 100 && initial_stones != 100 {
                    stones_remaining.set(initial_stones);
                }
                let team1 = m.team1_name.as_str();
                let team2 = m.team2_name.as_str();
                let refs_display = m
                    .refs_initial
                    .as_deref()
                    .unwrap_or("-");
                let field_display = m.field.as_deref().unwrap_or("TBA");
                let length_display = m.nominal_length.map(|n| format!("{} min", n));
                // Compute time elapsed from confirmed_start_time or nominal_start_time
                let start_iso = m
                    .confirmed_start_time
                    .as_deref()
                    .or(m.nominal_start_time.as_deref());
                let _ = live_tick();
                let now_secs = now_epoch_secs() as u64;
                let start_secs = start_iso
                    .and_then(parse_iso_epoch)
                    .map(|t| t as u64)
                    .unwrap_or(now_secs);
                time_elapsed_secs.set(now_secs.saturating_sub(start_secs));
                let elapsed = time_elapsed_secs();
                let time_elapsed_str = format!(
                    "{:02}:{:02}",
                    elapsed / 60,
                    elapsed % 60
                );

                let state_opt = state_signal();
                let state_value: Option<&Value> = state_opt.as_ref().and_then(|r| r.as_ref().ok());
                let points: Vec<&Value> = state_value
                    .and_then(|v| v.get("points").and_then(|p| p.as_array()))
                    .map(|a| a.iter().collect())
                    .unwrap_or_default();
                let score_rows: Vec<(String, u64, u64)> = scores_by_set_from_points(&points);
                let finalized = state_value
                    .and_then(|v| v.get("finalized_at").and_then(|f| f.as_str()))
                    .is_some();
                let show_notes_modal = notes_modal_point_id().is_some();
                let notes_modal_pid = notes_modal_point_id().clone().unwrap_or_default();
                let url_notes = url.clone();
                let id_notes = match_id.clone();
                let team1_notes = team1.to_string();
                let team2_notes = team2.to_string();

                let default_set = points
                    .last()
                    .and_then(|p| p.get("set_number").and_then(|n| n.as_u64()))
                    .unwrap_or(1) as u32;

                struct PointRow {
                    point_id: String,
                    set_num: u32,
                    winner: String,
                    rerolled: bool,
                    elapsed: u32,
                }
                let point_rows: Vec<PointRow> = points
                    .iter()
                    .map(|pt| {
                        let point_id = pt.get("uuid").and_then(|v| v.as_str()).unwrap_or("").to_string();
                        let set_num = pt.get("set_number").and_then(|v| v.as_u64()).unwrap_or(1) as u32;
                        let winner = pt.get("winner").and_then(|v| v.as_str()).unwrap_or("none").to_string();
                        let rerolled = pt.get("rerolled").and_then(|v| v.as_bool()).unwrap_or(false);
                        let stamp = pt.get("stamp").and_then(|s| s.as_str());
                        let end_stamp = pt.get("end_stamp").and_then(|e| e.as_str());
                        let elapsed = stones_elapsed_beats(stamp, end_stamp);
                        PointRow { point_id, set_num, winner, rerolled, elapsed }
                    })
                    .collect();

                // Stones display: during an active point show stones_at_start - elapsed (ticks down); otherwise show stones_remaining.
                let display_stones = if set_type_stones {
                    if let Some(ref cp) = current_point() {
                        points
                            .iter()
                            .find(|p| p.get("uuid").and_then(|u| u.as_str()) == Some(cp.as_str()))
                            .and_then(|pt| {
                                let at_start = pt.get("stones_at_start").and_then(|s| s.as_u64())?;
                                let stamp = pt.get("stamp").and_then(|s| s.as_str());
                                let elapsed = stones_elapsed_beats(stamp, None) as u64;
                                Some((at_start.saturating_sub(elapsed)) as u32)
                            })
                            .unwrap_or(stones_remaining())
                    } else {
                        stones_remaining()
                    }
                } else {
                    stones_remaining()
                };

                let url_start = url.clone();
                let id_start = match_id.clone();
                let mut current_point = current_point;
                let mut stones_remaining = stones_remaining;
                let mut state_signal_start = state_signal;
                let on_start_end_point = move |_| {
                    let u = url_start.clone();
                    let id = id_start.clone();
                    let point_opt = current_point();
                    let mut err_out = action_error;
                    let mut current_point = current_point;
                    let mut stones_remaining = stones_remaining;
                    let mut state_signal = state_signal_start;
                    let set_type_stones = set_type_stones;
                    let default_set = default_set;
                    let stones_val = stones_remaining();
                    if let Some(point_id) = point_opt {
                        // End current point — optimistic: set end_stamp and clear current_point
                        let end_iso = chrono::Utc::now().to_rfc3339();
                        let prev = state_signal().clone();
                        if let Some(Ok(ref state)) = prev.clone() {
                            let mut state = state.clone();
                            if let Some(points) = state.get_mut("points").and_then(|p| p.as_array_mut()) {
                                for p in points.iter_mut() {
                                    if p.get("uuid").and_then(|v| v.as_str()) == Some(point_id.as_str()) {
                                        p["end_stamp"] = serde_json::json!(end_iso);
                                        if set_type_stones {
                                            let at_start = p.get("stones_at_start").and_then(|s| s.as_u64()).unwrap_or(0);
                                            let stamp = p.get("stamp").and_then(|s| s.as_str());
                                            let elapsed = stones_elapsed_beats(stamp, Some(end_iso.as_str())) as u64;
                                            stones_remaining.set((at_start.saturating_sub(elapsed)) as u32);
                                        }
                                        break;
                                    }
                                }
                            }
                            state_signal.set(Some(Ok(state)));
                        }
                        current_point.set(None);
                        let point_id = point_id.clone();
                        spawn(async move {
                            err_out.set(None);
                            let body = serde_json::json!({ "point_id": point_id, "end_stamp": end_iso });
                            match api::update_point(&u, &point_id, &body).await {
                                Ok(_) => err_out.set(None),
                                Err(e) => {
                                    err_out.set(Some(e));
                                    state_signal.set(prev);
                                    current_point.set(Some(point_id));
                                }
                            }
                        });
                    } else {
                        // Start new point — optimistic: add pending point, set current_point
                        let pending_id = format!("pending-{}", chrono::Utc::now().timestamp_millis());
                        let stamp_iso = chrono::Utc::now().to_rfc3339();
                        let new_point = serde_json::json!({
                            "uuid": pending_id,
                            "set_number": default_set,
                            "winner": "none",
                            "rerolled": false,
                            "stamp": stamp_iso,
                            "end_stamp": serde_json::Value::Null,
                            "stones_at_start": if set_type_stones { serde_json::json!(stones_val) } else { serde_json::Value::Null },
                        });
                        let prev = state_signal().clone();
                        if let Some(Ok(ref state)) = prev.clone() {
                            let mut state = state.clone();
                            if let Some(points) = state.get_mut("points").and_then(|p| p.as_array_mut()) {
                                points.push(new_point);
                            }
                            state_signal.set(Some(Ok(state)));
                        }
                        current_point.set(Some(pending_id.clone()));
                        let stones_at_start = if set_type_stones { Some(stones_val) } else { None };
                        spawn(async move {
                            err_out.set(None);
                            match api::add_point(&u, &id, default_set, Some(chrono::Utc::now().timestamp_millis() as u64), stones_at_start).await {
                                Ok(resp) => {
                                    let real_id = resp.get("point_id").and_then(|v| v.as_str()).unwrap_or("").to_string();
                                    if !real_id.is_empty() {
                                        if let Some(Ok(ref state)) = state_signal() {
                                            let mut state = state.clone();
                                            if let Some(points) = state.get_mut("points").and_then(|p| p.as_array_mut()) {
                                                for p in points.iter_mut() {
                                                    if p.get("uuid").and_then(|v| v.as_str()) == Some(pending_id.as_str()) {
                                                        p["uuid"] = serde_json::json!(real_id);
                                                        break;
                                                    }
                                                }
                                            }
                                            state_signal.set(Some(Ok(state)));
                                        }
                                        current_point.set(Some(real_id));
                                    }
                                    err_out.set(None);
                                }
                                Err(e) => {
                                    err_out.set(Some(e));
                                    state_signal.set(prev);
                                    current_point.set(None);
                                }
                            }
                        });
                    }
                };

                let url_mobile = url.clone();
                let id_mobile = match_id.clone();
                let mut current_point_mobile = current_point;
                let mut stones_remaining_mobile = stones_remaining;
                let mut state_signal_mobile = state_signal;
                let on_start_end_point_mobile = move |_| {
                    let u = url_mobile.clone();
                    let id = id_mobile.clone();
                    let point_opt = current_point_mobile();
                    let mut err_out = action_error;
                    let mut current_point = current_point_mobile;
                    let mut stones_remaining = stones_remaining_mobile;
                    let mut state_signal = state_signal_mobile;
                    let set_type_stones = set_type_stones;
                    let default_set = default_set;
                    let stones_val = stones_remaining();
                    if let Some(point_id) = point_opt {
                        let end_iso = chrono::Utc::now().to_rfc3339();
                        let prev = state_signal().clone();
                        if let Some(Ok(ref state)) = prev.clone() {
                            let mut state = state.clone();
                            if let Some(points) = state.get_mut("points").and_then(|p| p.as_array_mut()) {
                                for p in points.iter_mut() {
                                    if p.get("uuid").and_then(|v| v.as_str()) == Some(point_id.as_str()) {
                                        p["end_stamp"] = serde_json::json!(end_iso);
                                        if set_type_stones {
                                            let at_start = p.get("stones_at_start").and_then(|s| s.as_u64()).unwrap_or(0);
                                            let stamp = p.get("stamp").and_then(|s| s.as_str());
                                            let elapsed = stones_elapsed_beats(stamp, Some(end_iso.as_str())) as u64;
                                            stones_remaining.set((at_start.saturating_sub(elapsed)) as u32);
                                        }
                                        break;
                                    }
                                }
                            }
                            state_signal.set(Some(Ok(state)));
                        }
                        current_point.set(None);
                        let point_id = point_id.clone();
                        spawn(async move {
                            err_out.set(None);
                            let body = serde_json::json!({ "point_id": point_id, "end_stamp": end_iso });
                            match api::update_point(&u, &point_id, &body).await {
                                Ok(_) => err_out.set(None),
                                Err(e) => {
                                    err_out.set(Some(e));
                                    state_signal.set(prev);
                                    current_point.set(Some(point_id));
                                }
                            }
                        });
                    } else {
                        let pending_id = format!("pending-{}", chrono::Utc::now().timestamp_millis());
                        let stamp_iso = chrono::Utc::now().to_rfc3339();
                        let new_point = serde_json::json!({
                            "uuid": pending_id,
                            "set_number": default_set,
                            "winner": "none",
                            "rerolled": false,
                            "stamp": stamp_iso,
                            "end_stamp": serde_json::Value::Null,
                            "stones_at_start": if set_type_stones { serde_json::json!(stones_val) } else { serde_json::Value::Null },
                        });
                        let prev = state_signal().clone();
                        if let Some(Ok(ref state)) = prev.clone() {
                            let mut state = state.clone();
                            if let Some(points) = state.get_mut("points").and_then(|p| p.as_array_mut()) {
                                points.push(new_point);
                            }
                            state_signal.set(Some(Ok(state)));
                        }
                        current_point.set(Some(pending_id.clone()));
                        let stones_at_start = if set_type_stones { Some(stones_val) } else { None };
                        spawn(async move {
                            err_out.set(None);
                            match api::add_point(&u, &id, default_set, Some(chrono::Utc::now().timestamp_millis() as u64), stones_at_start).await {
                                Ok(resp) => {
                                    let real_id = resp.get("point_id").and_then(|v| v.as_str()).unwrap_or("").to_string();
                                    if !real_id.is_empty() {
                                        if let Some(Ok(ref state)) = state_signal() {
                                            let mut state = state.clone();
                                            if let Some(points) = state.get_mut("points").and_then(|p| p.as_array_mut()) {
                                                for p in points.iter_mut() {
                                                    if p.get("uuid").and_then(|v| v.as_str()) == Some(pending_id.as_str()) {
                                                        p["uuid"] = serde_json::json!(real_id);
                                                        break;
                                                    }
                                                }
                                            }
                                            state_signal.set(Some(Ok(state)));
                                        }
                                        current_point.set(Some(real_id));
                                    }
                                    err_out.set(None);
                                }
                                Err(e) => {
                                    err_out.set(Some(e));
                                    state_signal.set(prev);
                                    current_point.set(None);
                                }
                            }
                        });
                    }
                };

                let url_finalize_btn = url.clone();
                let id_finalize_btn = match_id.clone();
                let url_finalize_mobile = url.clone();
                let id_finalize_mobile = match_id.clone();

                let has_in_progress = current_point().is_some();
                let point_button_text = if has_in_progress {
                    "End Point"
                } else {
                    "Start Point"
                };
                let point_button_class = if has_in_progress {
                    "btn btn-danger btn-lg w-100 mobile-sticky-button"
                } else {
                    "btn btn-success btn-lg w-100 mobile-sticky-button"
                };

                let run_match_css = ".set-number-controls{display:flex;flex-direction:column;align-items:center;gap:2px;width:40px}\
                    .set-number-controls .set-number-display{font-size:1rem;font-weight:600;text-align:center;min-width:30px;padding:4px 0}\
                    .set-number-controls button{width:28px;height:24px;padding:0;font-size:14px}\
                    .delete-point-btn{background:#dc3545;color:white;border:none;width:28px;height:28px;padding:0;border-radius:3px;display:flex;align-items:center;justify-content:center;font-size:16px;line-height:1;cursor:pointer}\
                    .delete-point-btn:hover{background:#c82333}\
                    @media (max-width:768px){.mobile-button-wrapper{position:fixed;bottom:0;left:0;right:0;z-index:1000;background:white;padding:0;margin:0;box-shadow:0 -2px 10px rgba(0,0,0,0.1);display:flex;flex-direction:row}\
                    .mobile-button-wrapper .btn{border-radius:0;margin:0;flex:1}\
                    .container .mobile-sticky-button,.container #finalize-match-btn{display:none}}";
                let mut state_signal = state_signal;
                let mut action_error = action_error;
                let point_table_rows: Vec<_> = point_rows
                    .iter()
                    .map(|r| {
                        let pt_id = r.point_id.as_str();
                        let set_num = r.set_num;
                        let winner_val = r.winner.as_str();
                        let rerolled = r.rerolled;
                        let elapsed = r.elapsed;
                        let u_inc = url.clone();
                        let u_dec = url.clone();
                        let u_winner = url.clone();
                        let u_reroll = url.clone();
                        let u_del = url.clone();
                        let u_notes = url.clone();
                        let id_notes = match_id.clone();
                        let pid = r.point_id.clone();
                        let pid_inc = pid.clone();
                        let pid_dec = pid.clone();
                        let pid_winner = pid.clone();
                        let pid_reroll = pid.clone();
                        let pid_del = pid.clone();
                        let team1 = team1.to_string();
                        let team2 = team2.to_string();
                        rsx! {
                            tr { key: "{pt_id}", id: "point-row-{pt_id}",
                                td {
                                    div { class: "set-number-controls",
                                        button {
                                            class: "btn btn-sm btn-outline-secondary",
                                            r#type: "button",
                                            onclick: move |_| {
                                                let new_set = (set_num + 1).max(1);
                                                let prev = state_signal().clone();
                                                if let Some(Ok(ref state)) = prev.clone() {
                                                    let mut state = state.clone();
                                                    if let Some(points) = state.get_mut("points").and_then(|p| p.as_array_mut()) {
                                                        for p in points.iter_mut() {
                                                            if p.get("uuid").and_then(|v| v.as_str()) == Some(pid_inc.as_str()) {
                                                                p["set_number"] = serde_json::json!(new_set);
                                                                break;
                                                            }
                                                        }
                                                    }
                                                    state_signal.set(Some(Ok(state)));
                                                }
                                                let u = u_inc.clone();
                                                let p = pid_inc.clone();
                                                let mut state_signal = state_signal;
                                                let mut action_error = action_error;
                                                spawn(async move {
                                                    let body = serde_json::json!({ "point_id": p, "set_number": new_set });
                                                    match api::update_point(&u, &p, &body).await {
                                                        Ok(_) => { action_error.set(None); }
                                                        Err(e) => { action_error.set(Some(e)); state_signal.set(prev); }
                                                    }
                                                });
                                            },
                                            "+"
                                        }
                                        span { class: "set-number-display", id: "set-display-{pt_id}", "{set_num}" }
                                        button {
                                            class: "btn btn-sm btn-outline-secondary",
                                            r#type: "button",
                                            onclick: move |_| {
                                                let new_set = (set_num as i64 - 1).max(1) as u32;
                                                let prev = state_signal().clone();
                                                if let Some(Ok(ref state)) = prev.clone() {
                                                    let mut state = state.clone();
                                                    if let Some(points) = state.get_mut("points").and_then(|p| p.as_array_mut()) {
                                                        for p in points.iter_mut() {
                                                            if p.get("uuid").and_then(|v| v.as_str()) == Some(pid_dec.as_str()) {
                                                                p["set_number"] = serde_json::json!(new_set);
                                                                break;
                                                            }
                                                        }
                                                    }
                                                    state_signal.set(Some(Ok(state)));
                                                }
                                                let u = u_dec.clone();
                                                let p = pid_dec.clone();
                                                let mut state_signal = state_signal;
                                                let mut action_error = action_error;
                                                spawn(async move {
                                                    let body = serde_json::json!({ "point_id": p, "set_number": new_set });
                                                    match api::update_point(&u, &p, &body).await {
                                                        Ok(_) => { action_error.set(None); }
                                                        Err(e) => { action_error.set(Some(e)); state_signal.set(prev); }
                                                    }
                                                });
                                            },
                                            "−"
                                        }
                                    }
                                }
                                td { id: "stones-{pt_id}", "{elapsed}" }
                                td {
                                    select {
                                        class: "form-select form-select-sm",
                                        value: "{winner_val}",
                                        onchange: move |ev| {
                                            let val = ev.value();
                                            let prev = state_signal().clone();
                                            if let Some(Ok(ref state)) = prev.clone() {
                                                let mut state = state.clone();
                                                if let Some(points) = state.get_mut("points").and_then(|p| p.as_array_mut()) {
                                                    for p in points.iter_mut() {
                                                        if p.get("uuid").and_then(|v| v.as_str()) == Some(pid_winner.as_str()) {
                                                            p["winner"] = serde_json::json!(val);
                                                            break;
                                                        }
                                                    }
                                                }
                                                state_signal.set(Some(Ok(state)));
                                            }
                                            let u = u_winner.clone();
                                            let p = pid_winner.clone();
                                            let mut state_signal = state_signal;
                                            let mut action_error = action_error;
                                            spawn(async move {
                                                let body = serde_json::json!({ "point_id": p, "winner": val });
                                                match api::update_point(&u, &p, &body).await {
                                                    Ok(_) => { action_error.set(None); }
                                                    Err(e) => { action_error.set(Some(e)); state_signal.set(prev); }
                                                }
                                            });
                                        },
                                        option { value: "none", selected: winner_val == "none", "None" }
                                        option { value: "TEAM1", selected: winner_val == "TEAM1", "{team1}" }
                                        option { value: "TEAM2", selected: winner_val == "TEAM2", "{team2}" }
                                    }
                                }
                                td {
                                    div { class: "form-check",
                                        input {
                                            class: "form-check-input",
                                            r#type: "checkbox",
                                            checked: rerolled,
                                            onchange: move |ev| {
                                                let checked = ev.checked();
                                                let prev = state_signal().clone();
                                                if let Some(Ok(ref state)) = prev.clone() {
                                                    let mut state = state.clone();
                                                    if let Some(points) = state.get_mut("points").and_then(|p| p.as_array_mut()) {
                                                        for p in points.iter_mut() {
                                                            if p.get("uuid").and_then(|v| v.as_str()) == Some(pid_reroll.as_str()) {
                                                                p["rerolled"] = serde_json::json!(checked);
                                                                break;
                                                            }
                                                        }
                                                    }
                                                    state_signal.set(Some(Ok(state)));
                                                }
                                                let u = u_reroll.clone();
                                                let p = pid_reroll.clone();
                                                let mut state_signal = state_signal;
                                                let mut action_error = action_error;
                                                spawn(async move {
                                                    let body = serde_json::json!({ "point_id": p, "rerolled": checked });
                                                    match api::update_point(&u, &p, &body).await {
                                                        Ok(_) => { action_error.set(None); }
                                                        Err(e) => { action_error.set(Some(e)); state_signal.set(prev); }
                                                    }
                                                });
                                            },
                                        }
                                    }
                                }
                                td {
                                    button {
                                        class: "btn btn-sm btn-outline-primary",
                                        onclick: move |_| {
                                            notes_modal_point_id.set(Some(pid.clone()));
                                            notes_modal_notes.set(None);
                                            let u = u_notes.clone();
                                            let id = id_notes.clone();
                                            let pid_fetch = pid.clone();
                                            let mut notes_modal_notes = notes_modal_notes;
                                            let mut point_notes_map_signal = point_notes_map_signal;
                                            spawn(async move {
                                                match api::get_point_notes(&u, &id, &pid_fetch).await {
                                                    Ok(v) => {
                                                        let notes = v.get("notes").and_then(|n| n.as_array()).cloned().unwrap_or_default();
                                                        notes_modal_notes.set(Some(Ok(notes.clone())));
                                                        let mut m = point_notes_map_signal();
                                                        m.insert(pid_fetch.clone(), notes);
                                                        point_notes_map_signal.set(m);
                                                    }
                                                    Err(e) => notes_modal_notes.set(Some(Err(e))),
                                                }
                                            });
                                        },
                                        "📝 Notes"
                                    }
                                    div { class: "mt-1",
                                        for note_val in point_notes_map_signal().get(&pid).cloned().unwrap_or_default().iter() {
                                            {
                                                let note_text = note_val.get("text").and_then(|t| t.as_str()).unwrap_or("");
                                                let note_target_d = note_val.get("player_display").and_then(|p| p.as_str())
                                                    .or_else(|| note_val.get("player_name").and_then(|p| p.as_str()))
                                                    .or_else(|| note_val.get("target").and_then(|t| t.as_str()))
                                                    .unwrap_or("Match");
                                                rsx! {
                                                    div { class: "small text-muted border-start border-3 ps-2 mb-1",
                                                        "{note_target_d}: {note_text}"
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                                td {
                                    button {
                                        class: "delete-point-btn",
                                        title: "Delete",
                                        onclick: move |_| {
                                            let prev = state_signal().clone();
                                            if let Some(Ok(ref state)) = prev.clone() {
                                                let mut state = state.clone();
                                                if let Some(points) = state.get_mut("points").and_then(|p| p.as_array_mut()) {
                                                    points.retain(|p| p.get("uuid").and_then(|v| v.as_str()) != Some(pid_del.as_str()));
                                                }
                                                state_signal.set(Some(Ok(state)));
                                            }
                                            let u = u_del.clone();
                                            let p = pid_del.clone();
                                            let mut state_signal = state_signal;
                                            let mut action_error = action_error;
                                            spawn(async move {
                                                match api::delete_point(&u, &p).await {
                                                    Ok(_) => { action_error.set(None); }
                                                    Err(e) => {
                                                        action_error.set(Some(e));
                                                        state_signal.set(prev);
                                                    }
                                                }
                                            });
                                        },
                                        "×"
                                    }
                                }
                            }
                        }
                    })
                    .collect();
                rsx! {
                    div { class: "container mt-4",
                        style { "{run_match_css}" }
                        div { class: "row",
                            div { class: "col-md-12",
                                h2 { "Run Match: {m.name}" }
                                p { class: "small text-muted mb-1",
                                    "Note: although there's a delay when clicking start/end point, the stone count is done correctly (it's computed from when you first click it)."
                                }
                                div { class: "row d-none d-md-flex",
                                    div { class: "col-md-4",
                                        p { class: "mb-0",
                                            strong { "Teams: " }
                                            "{team1} vs {team2}"
                                        }
                                    }
                                    div { class: "col-md-4",
                                        p { class: "mb-0",
                                            strong { "Refs: " }
                                            "{refs_display}"
                                        }
                                    }
                                    div { class: "col-md-2",
                                        if let Some(len) = length_display {
                                            p { class: "mb-0",
                                                strong { "Length: " }
                                                "{len}"
                                            }
                                        }
                                    }
                                    div { class: "col-md-2",
                                        p { class: "mb-0",
                                            strong { "Field: " }
                                            "{field_display}"
                                        }
                                    }
                                }
                                div { class: "row d-md-none",
                                    div { class: "col-12",
                                        p { class: "small mb-0",
                                            "{team1} vs {team2}"
                                            " | Refs: {refs_display}"
                                            if let Some(len) = m.nominal_length {
                                                " | {len}m"
                                            }
                                            " | Field: {field_display}"
                                        }
                                    }
                                }
                            }
                        }

                        div { class: "row mb-4",
                            div { class: "col-md-12",
                                div { class: "card",
                                    div { class: "card-body",
                                        div { class: "row",
                                            div { class: "col-md-6 mb-4 mb-md-0",
                                                div { id: "score-by-set",
                                                    div { class: "row mb-1",
                                                        div { class: "col-12 text-center mb-1",
                                                            h4 { class: "mb-0", "Score" }
                                                        }
                                                    }
                                                    div { class: "row mb-1",
                                                        div { class: "col-5 text-center",
                                                            small { class: "text-muted", "{team1}" }
                                                        }
                                                        div { class: "col-2" }
                                                        div { class: "col-5 text-center",
                                                            small { class: "text-muted", "{team2}" }
                                                        }
                                                    }
                                                    if score_rows.is_empty() {
                                                        div { class: "text-muted text-center", "No points yet" }
                                                    } else {
                                                        for (set_num, t1, t2) in score_rows.iter() {
                                                            div { class: "row mb-0", key: "{set_num}",
                                                                div { class: "col-5 text-center",
                                                                    strong { id: "team1-set-{set_num}-score", "{t1}" }
                                                                }
                                                                div { class: "col-2 text-center",
                                                                    small { class: "text-muted", "Set {set_num}" }
                                                                }
                                                                div { class: "col-5 text-center",
                                                                    strong { id: "team2-set-{set_num}-score", "{t2}" }
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                            div { class: "col-md-6",
                                                div { class: "row",
                                                    if set_type_stones {
                                                        div { class: "col-6 text-center",
                                                            h4 { class: "mb-1", "Stone Count" }
                                                            p { class: "small mb-0", "(click to edit)" }
                                                            input {
                                                                r#type: "number",
                                                                class: "form-control-plaintext text-center display-4 m-0 p-0",
                                                                id: "stones-remaining",
                                                                style: "width: 6ch; line-height: 1; font-size: 3rem; height: 64px;",
                                                                value: "{display_stones}",
                                                                oninput: move |ev| {
                                                                    if let Ok(n) = ev.value().parse::<u32>() {
                                                                        stones_remaining.set(n);
                                                                        let u = url.clone();
                                                                        let id = match_id.clone();
                                                                        spawn(async move {
                                                                            let _ = api::update_stones(&u, &id, n).await;
                                                                        });
                                                                    }
                                                                },
                                                            }
                                                        }
                                                    }
                                                    div { class: if set_type_stones { "col-6 text-center" } else { "col-12 text-center" },
                                                        h4 { class: "mb-1", "Time Elapsed" }
                                                        h2 { id: "time-elapsed", class: "mb-0", "{time_elapsed_str}" }
                                                    }
                                                }
                                                div { class: "row mt-3",
                                                    div { class: "col-12",
                                                        button {
                                                            id: "point-button",
                                                            class: "{point_button_class}",
                                                            onclick: on_start_end_point,
                                                            disabled: finalized,
                                                            "{point_button_text}"
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        if let Some(e) = action_error() {
                            div { class: "alert alert-danger mt-2", "{e}" }
                        }

                        div { class: "row",
                            div { class: "col-md-12",
                                div { class: "card",
                                    div { class: "card-header",
                                        h5 { class: "mb-0", "Points" }
                                    }
                                    div { class: "card-body",
                                        div { class: "table-responsive",
                                            table { class: "table table-sm", id: "points-table",
                                                thead {
                                                    tr {
                                                        th { "Set" }
                                                        th { "🪨" }
                                                        th { "Winner" }
                                                        th { "Rerun" }
                                                        th { "Notes" }
                                                        th { "" }
                                                    }
                                                }
                                                tbody { id: "points-table-body",
                                                    for node in point_table_rows.iter() {
                                                        {node.clone()}
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        div { class: "row mt-4",
                            div { class: "col-12",
                                button {
                                    id: "finalize-match-btn",
                                    class: "btn btn-warning btn-lg w-100",
                                    onclick: move |_| {
                                        navigator.push(Route::FinalizeMatch {
                                            url: url_finalize_btn.clone(),
                                            match_id: id_finalize_btn.clone(),
                                        });
                                    },
                                    disabled: has_in_progress,
                                    if has_in_progress {
                                        "Finalize Match (Point in Progress)"
                                    } else {
                                        "Finalize Match"
                                    }
                                }
                            }
                        }
                    }

                    div { class: "mobile-button-wrapper d-md-none",
                        button {
                            class: "btn btn-warning btn-lg",
                            onclick: move |_| {
                                navigator.push(Route::FinalizeMatch {
                                    url: url_finalize_mobile.clone(),
                                    match_id: id_finalize_mobile.clone(),
                                });
                            },
                            disabled: has_in_progress,
                            if has_in_progress { "Finalize (Point in Progress)" } else { "Finalize Match" }
                        }
                        button {
                            class: "{point_button_class}",
                            onclick: on_start_end_point_mobile,
                            disabled: finalized,
                            "{point_button_text}"
                        }
                    }

                    if show_notes_modal {
                        div {
                            class: "modal show",
                            style: "display: block; background: rgba(0,0,0,0.5);",
                            role: "dialog",
                            tabindex: "-1",
                            onclick: move |_| {
                                notes_modal_point_id.set(None);
                            },
                            div {
                                class: "modal-dialog modal-lg",
                                onclick: move |ev| { ev.stop_propagation(); },
                                div { class: "modal-content",
                                    div { class: "modal-header",
                                        h5 { class: "modal-title", "Notes for Point" }
                                        button {
                                            r#type: "button",
                                            class: "btn-close",
                                            aria_label: "Close",
                                            onclick: move |_| notes_modal_point_id.set(None),
                                        }
                                    }
                                    div { class: "modal-body",
                                        div { class: "mb-4",
                                            h6 { "Existing notes for this point:" }
                                            div { class: "border p-3", style: "max-height: 200px; overflow-y: auto;",
                                                match notes_modal_notes().as_ref() {
                                                    None => rsx! { div { class: "text-muted", "Loading…" } },
                                                    Some(Err(e)) => rsx! { div { class: "text-danger", "{e}" } },
                                                    Some(Ok(notes)) => {
                                                        let rows: Vec<(String, String)> = if notes.is_empty() {
                                                            vec![(String::new(), "No notes yet.".to_string())]
                                                        } else {
                                                            notes.iter().map(|n| {
                                                                let text = n.get("text").and_then(|t| t.as_str()).unwrap_or("").to_string();
                                                                let target_d = n.get("player_display").and_then(|p| p.as_str())
                                                                    .or_else(|| n.get("player_name").and_then(|p| p.as_str()))
                                                                    .or_else(|| n.get("target").and_then(|t| t.as_str()))
                                                                    .unwrap_or("Match").to_string();
                                                                (target_d, text)
                                                            }).collect()
                                                        };
                                                        rsx! {
                                                            div {
                                                                for (target_d, text) in rows.iter() {
                                                                    div {
                                                                        class: if text.as_str() == "No notes yet." { "text-muted" } else { "small text-muted border-start border-3 ps-2 mb-1" },
                                                                        if text.as_str() == "No notes yet." {
                                                                            "{text}"
                                                                        } else {
                                                                            "{target_d}: {text}"
                                                                        }
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                        div { class: "mb-3",
                                            h6 { "Add new note:" }
                                            input {
                                                class: "form-control mb-2",
                                                r#type: "text",
                                                placeholder: "Enter note text",
                                                value: "{notes_modal_new_text()}",
                                                oninput: move |ev| notes_modal_new_text.set(ev.value().clone()),
                                            }
                                            select {
                                                class: "form-select",
                                                value: "{notes_modal_target()}",
                                                onchange: move |ev| {
                                                    let v = ev.value().clone();
                                                    notes_modal_target.set(v.clone());
                                                    if v != "player" {
                                                        notes_modal_player_id.set(None);
                                                        notes_modal_player_query.set(String::new());
                                                    }
                                                },
                                                option { value: "match", "Point" }
                                                option { value: "team1", "{team1_notes}" }
                                                option { value: "team2", "{team2_notes}" }
                                                option { value: "player", "Player" }
                                            }
                                            if notes_modal_target() == "player" {
                                                {
                                                let q = notes_modal_player_query();
                                                let player_query_lower = q.to_lowercase();
                                                let base_url = api::base_url();
                                                let filtered: Vec<_> = d.match_players.iter()
                                                    .filter(|p| player_query_lower.is_empty() || p.display.to_lowercase().contains(player_query_lower.as_str()) || p.name.to_lowercase().contains(player_query_lower.as_str()))
                                                    .take(10)
                                                    .collect();
                                                rsx! {
                                                div { class: "mt-2",
                                                    label { class: "form-label", "Assign to player:" }
                                                    input {
                                                        class: "form-control",
                                                        r#type: "text",
                                                        placeholder: "Type to search by jersey or name...",
                                                        value: "{notes_modal_player_query()}",
                                                        oninput: move |ev| notes_modal_player_query.set(ev.value().clone()),
                                                    }
                                                    div { class: "list-group mt-1", style: "max-height: 180px; overflow-y: auto;",
                                                        for player_item in filtered.iter() {
                                                            {
                                                                let pl_id = player_item.player_id.clone();
                                                                let pl_display = player_item.display.clone();
                                                                let pl_photo = player_item.profile_photo.clone();
                                                                let pl_name = player_item.name.clone();
                                                                rsx! {
                                                                    button {
                                                                        r#type: "button",
                                                                        class: "list-group-item list-group-item-action d-flex align-items-center gap-2",
                                                                        onclick: move |_| {
                                                                            notes_modal_player_id.set(Some(pl_id.clone()));
                                                                            notes_modal_player_query.set(pl_display.clone());
                                                                        },
                                                                        if let Some(ph) = &pl_photo {
                                                                            img {
                                                                                src: "{base_url}/static/{ph}",
                                                                                alt: "",
                                                                                class: "rounded-circle",
                                                                                style: "width: 32px; height: 32px; object-fit: cover;",
                                                                            }
                                                                        }
                                                                        span { "{pl_display}" }
                                                                        small { class: "text-muted", "({pl_name})" }
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                    small { class: "text-muted", "Selecting a player ties this note to that player." }
                                                }
                                            }
                                        }
                                                }
                                                }
                                    }
                                    div { class: "modal-footer",
                                        button {
                                            r#type: "button",
                                            class: "btn btn-secondary",
                                            onclick: move |_| notes_modal_point_id.set(None),
                                            "Close"
                                        }
                                        button {
                                            r#type: "button",
                                            class: "btn btn-primary",
                                            onclick: move |_| {
                                                let text = notes_modal_new_text().trim().to_string();
                                                if text.is_empty() { return; }
                                                let target = notes_modal_target().clone();
                                                let player_id = notes_modal_player_id().clone();
                                                if target == "player" && player_id.is_none() {
                                                    return;
                                                }
                                                let u = url_notes.clone();
                                                let id = id_notes.clone();
                                                let pid = notes_modal_pid.clone();
                                                let mut notes_modal_notes = notes_modal_notes;
                                                notes_modal_new_text.set(String::new());
                                                notes_modal_player_id.set(None);
                                                notes_modal_player_query.set(String::new());
                                                let mut point_notes_map_signal = point_notes_map_signal;
                                                spawn(async move {
                                                    match api::add_point_note(&u, &id, &pid, &text, &target, player_id.as_deref()).await {
                                                        Ok(_) => {
                                                            match api::get_point_notes(&u, &id, &pid).await {
                                                                Ok(v) => {
                                                                    let notes = v.get("notes").and_then(|n| n.as_array()).cloned().unwrap_or_default();
                                                                    notes_modal_notes.set(Some(Ok(notes.clone())));
                                                                    let mut m = point_notes_map_signal();
                                                                    m.insert(pid.clone(), notes);
                                                                    point_notes_map_signal.set(m);
                                                                }
                                                                Err(e) => notes_modal_notes.set(Some(Err(e))),
                                                            }
                                                        }
                                                        Err(e) => notes_modal_notes.set(Some(Err(e.to_string()))),
                                                    }
                                                });
                                            },
                                            "Add Note"
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            Some(Err(e)) => rsx! { p { class: "text-danger", "{e}" } },
            None => rsx! { p { "Loading…" } },
        },
        Err(_) => rsx! { p { "Loading…" } },
    };
    rsx! { {detail_view} }
}
