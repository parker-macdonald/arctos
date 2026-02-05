use crate::types::*;
use reqwest::Client;
use serde::de::DeserializeOwned;
use serde_json::Value;

/// Compile-time API base for dev (build with ARCTOS_API_BASE=http://127.0.0.1:5006 cargo build)
const COMPILE_TIME_API_BASE: Option<&'static str> = option_env!("ARCTOS_API_BASE");

/// Base URL of the backend (for redirects e.g. Google login).
pub fn base_url() -> String {
    base()
}

fn base() -> String {
    #[cfg(target_arch = "wasm32")]
    {
        let window = web_sys::window().expect("window");
        let location = window.location();

        // 0) Compile-time default (build with: ARCTOS_API_BASE=http://127.0.0.1:5006 cargo build)
        if let Some(url) = COMPILE_TIME_API_BASE {
            if !url.trim().is_empty() {
                return url.trim_end_matches('/').to_string();
            }
        }

        // 1) Runtime override (set in console or script before load)
        let override_base = js_sys::Reflect::get(
            window.as_ref(),
            &js_sys::JsString::from("ARCTOS_API_BASE"),
        )
        .ok()
        .and_then(|v| v.as_string())
        .filter(|s| !s.trim().is_empty());
        if let Some(url) = override_base {
            return url.trim_end_matches('/').to_string();
        }

        // 2) URL param ?api_port=5006
        let api_port_from_url = location
            .search()
            .ok()
            .as_ref()
            .and_then(|s| web_sys::UrlSearchParams::new_with_str(s).ok())
            .and_then(|p| p.get("api_port"))
            .filter(|s| !s.trim().is_empty());

        // 3) window.ARCTOS_API_PORT
        let api_port_from_window = js_sys::Reflect::get(
            window.as_ref(),
            &js_sys::JsString::from("ARCTOS_API_PORT"),
        )
        .ok()
        .and_then(|v| {
            v.as_string()
                .or_else(|| v.as_f64().map(|n| n as i32).map(|n| n.to_string()))
        })
        .filter(|s| !s.trim().is_empty());

        let api_port = api_port_from_url.or(api_port_from_window);
        if let Some(port) = api_port {
            if let Ok(host) = location.host() {
                let host = host.trim();
                if !host.is_empty() {
                    return format!("http://{}:{}", host, port.trim());
                }
            }
        }

        // 4) Fallback: if origin looks like localhost, point API at port 5006 (parse origin; no reliance on host()/port())
        let origin = location.origin().expect("origin");
        if origin.contains("localhost") || origin.contains("127.0.0.1") {
            // Replace port with 5006 (e.g. http://localhost:8080 -> http://localhost:5006)
            if let Some(last_colon) = origin.rfind(':') {
                let after_colon = &origin[last_colon + 1..];
                if after_colon.chars().all(|c| c.is_ascii_digit()) {
                    return format!("{}:5006", &origin[..last_colon]);
                }
            }
            // No port in origin (e.g. http://localhost) -> add :5006
            if !origin.ends_with(':') {
                return format!("{}:5006", origin.trim_end_matches('/'));
            }
        }

        origin
    }
    #[cfg(not(target_arch = "wasm32"))]
    {
        if let Some(url) = COMPILE_TIME_API_BASE {
            if !url.trim().is_empty() {
                return url.trim_end_matches('/').to_string();
            }
        }
        "http://127.0.0.1:5006".to_string()
    }
}

fn client() -> Client {
    Client::builder().build().expect("reqwest client")
}

/// On wasm, include cookies/credentials so session is sent to the backend (required when SPA and API are cross-origin).
#[cfg(target_arch = "wasm32")]
fn with_credentials(
    builder: reqwest::RequestBuilder,
) -> reqwest::RequestBuilder {
    builder.fetch_credentials_include()
}

#[cfg(not(target_arch = "wasm32"))]
fn with_credentials(builder: reqwest::RequestBuilder) -> reqwest::RequestBuilder {
    builder
}

/// Read response as text then parse as JSON. Returns a clear error if the server
/// returned HTML or non-JSON (e.g. login redirect, 500 error page).
async fn response_json<T: DeserializeOwned>(r: reqwest::Response) -> Result<T, String> {
    let status = r.status();
    let content_type: String = r
        .headers()
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();
    let text = r.text().await.map_err(|e| e.to_string())?;
    let preview: String = text.chars().take(400).collect();
    if !status.is_success() {
        return Err(format!("{} {}", status.as_u16(), preview));
    }
    if !content_type.contains("json") && !text.trim_start().starts_with('{') && !text.trim_start().starts_with('[') {
        return Err(format!(
            "Server returned non-JSON (content-type: {:?}). Maybe the backend is not running or /_api/ routes are missing. Body: {}",
            content_type,
            preview
        ));
    }
    serde_json::from_str(&text).map_err(|e| format!("JSON error: {}. Body: {}", e, preview))
}

pub async fn me() -> Result<User, String> {
    let c = client();
    let r = with_credentials(c.get(format!("{}/_api/me", base())))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if r.status().as_u16() == 401 {
        return Err("Not authenticated".to_string());
    }
    response_json(r).await
}

pub async fn login(username: &str, password: &str) -> Result<User, String> {
    let c = client();
    let body = serde_json::json!({ "username": username, "password": password });
    let r = with_credentials(c.post(format!("{}/_api/login", base())).json(&body))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if r.status().as_u16() == 401 {
        return Err("Invalid username or password".to_string());
    }
    response_json(r).await
}

pub async fn logout() -> Result<(), String> {
    let c = client();
    let r = with_credentials(c.post(format!("{}/_api/logout", base())))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let _ = response_json::<serde_json::Value>(r).await;
    Ok(())
}

pub async fn register(
    username: &str,
    password: &str,
    name: &str,
    user_type: &str,
) -> Result<User, String> {
    let c = client();
    let body = serde_json::json!({
        "username": username,
        "password": password,
        "name": name,
        "user_type": user_type
    });
    let r = with_credentials(c.post(format!("{}/_api/register", base())).json(&body))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if r.status().as_u16() == 409 {
        return Err("Username already exists".to_string());
    }
    response_json(r).await
}

pub async fn check_username(username: &str) -> Result<CheckUsernameResponse, String> {
    let c = client();
    let r = with_credentials(
        c.get(format!("{}/_api/check-username", base())).query(&[("username", username)]),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn tournaments() -> Result<TournamentsResponse, String> {
    let c = client();
    let r = with_credentials(c.get(format!("{}/_api/tournaments", base())))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn tournament_detail(tournament_url: &str) -> Result<TournamentDetailResponse, String> {
    let c = client();
    let r = with_credentials(c.get(format!("{}/_api/tournaments/{}", base(), tournament_url)))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if r.status().as_u16() == 404 {
        return Err("Not found".to_string());
    }
    response_json(r).await
}

pub async fn schedule(tournament_url: &str) -> Result<ScheduleResponse, String> {
    let c = client();
    let r = with_credentials(c.get(format!(
        "{}/_api/tournaments/{}/schedule",
        base(),
        tournament_url
    )))
    .send()
    .await
    .map_err(|e| e.to_string())?;
    if r.status().as_u16() == 403 {
        return Err("Schedule not published".to_string());
    }
    if r.status().as_u16() == 404 {
        return Err("Not found".to_string());
    }
    response_json(r).await
}

pub async fn results(tournament_url: &str) -> Result<ResultsResponse, String> {
    let c = client();
    let r = with_credentials(c.get(format!(
        "{}/_api/tournaments/{}/results",
        base(),
        tournament_url
    )))
    .send()
    .await
    .map_err(|e| e.to_string())?;
    if r.status().as_u16() == 404 {
        return Err("Not found".to_string());
    }
    response_json(r).await
}

pub async fn match_detail(
    tournament_url: &str,
    match_id: Option<&str>,
    match_name: Option<&str>,
) -> Result<MatchDetailResponse, String> {
    let c = client();
    let mut req = c.get(format!("{}/_api/tournaments/{}/match", base(), tournament_url));
    if let Some(id) = match_id {
        req = req.query(&[("id", id)]);
    } else if let Some(name) = match_name {
        req = req.query(&[("name", name)]);
    } else {
        return Err("id or name required".to_string());
    }
    let r = with_credentials(req).send().await.map_err(|e| e.to_string())?;
    if r.status().as_u16() == 404 {
        return Err("Match not found".to_string());
    }
    response_json(r).await
}

pub async fn players_list(search: &str, page: u32) -> Result<PlayersListResponse, String> {
    let c = client();
    let mut req = c.get(format!("{}/_api/players", base())).query(&[("page", page)]);
    if !search.is_empty() {
        req = req.query(&[("search", search)]);
    }
    let r = with_credentials(req).send().await.map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn player_profile(player_id: &str) -> Result<PlayerProfileResponse, String> {
    let c = client();
    let r = with_credentials(c.get(format!("{}/_api/players/{}", base(), player_id)))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if r.status().as_u16() == 404 {
        return Err("Not found".to_string());
    }
    response_json(r).await
}

pub async fn teams_list(search: &str) -> Result<TeamsListResponse, String> {
    let c = client();
    let mut req = c.get(format!("{}/_api/teams", base()));
    if !search.is_empty() {
        req = req.query(&[("search", search)]);
    }
    let r = with_credentials(req).send().await.map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn team_profile(team_id: &str) -> Result<TeamProfileResponse, String> {
    let c = client();
    let r = with_credentials(c.get(format!("{}/_api/teams/{}", base(), team_id)))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if r.status().as_u16() == 404 {
        return Err("Not found".to_string());
    }
    response_json(r).await
}

pub async fn stones_list() -> Result<StonesResponse, String> {
    let c = client();
    let r = with_credentials(c.get(format!("{}/_api/stones", base())))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn camera_url(tournament_url: &str, field_name: &str) -> Result<String, String> {
    let c = client();
    let r = with_credentials(
        c.get(format!("{}/_api/camera-url", base()))
            .query(&[("tournament", tournament_url), ("field", field_name)]),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    if !r.status().is_success() {
        let status = r.status();
        let body = r.text().await.unwrap_or_default();
        return Err(format!("{}: {}", status, body));
    }
    let data: Value = response_json(r).await?;
    data.get("url")
        .and_then(|v| v.as_str())
        .map(String::from)
        .ok_or_else(|| "No url in response".to_string())
}

pub async fn server_time() -> Result<ServerTimeResponse, String> {
    let c = client();
    let r = with_credentials(c.get(format!("{}/_api/server-time", base())))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    response_json(r).await
}

/// Fetch raw bytes from a URL (e.g. static file) with credentials for cross-origin.
pub async fn fetch_bytes(url: &str) -> Result<Vec<u8>, String> {
    let c = client();
    let r = with_credentials(c.get(url))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !r.status().is_success() {
        return Err(format!("HTTP {}", r.status()));
    }
    let bytes = r.bytes().await.map_err(|e| e.to_string())?;
    Ok(bytes.to_vec())
}

pub async fn scoreboard_state(
    tournament_url: &str,
    field_name: &str,
) -> Result<ScoreboardStateResponse, String> {
    let c = client();
    let r = with_credentials(
        c.get(format!("{}/_api/scoreboard-state", base())).query(&[
            ("tournament", tournament_url),
            ("field", field_name),
        ]),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn match_state(tournament_url: &str, match_id: &str) -> Result<Value, String> {
    let c = client();
    let r = with_credentials(
        c.get(format!("{}/{}/match-state", base(), tournament_url))
            .query(&[("id", match_id)]),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    if r.status().as_u16() == 404 {
        return Err("Not found".to_string());
    }
    response_json(r).await
}

pub async fn get_points(tournament_url: &str, match_id: &str) -> Result<Value, String> {
    let c = client();
    let r = with_credentials(
        c.get(format!("{}/{}/get-points", base(), tournament_url))
            .query(&[("match_id", match_id)]),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    let data: Value = response_json(r).await?;
    let success = data.get("success").and_then(|v| v.as_bool()).unwrap_or(false);
    if !success {
        return Err(
            data.get("error")
                .and_then(|v| v.as_str())
                .unwrap_or("Request failed")
                .to_string(),
        );
    }
    Ok(data)
}

pub async fn add_point(
    tournament_url: &str,
    match_id: &str,
    set_number: u32,
    timestamp_ms: Option<u64>,
    stones_at_start: Option<u32>,
) -> Result<Value, String> {
    let c = client();
    let body = serde_json::json!({
        "match_id": match_id,
        "set_number": set_number,
        "timestamp": timestamp_ms,
        "stones_at_start": stones_at_start,
    });
    let r = with_credentials(
        c.post(format!("{}/{}/match-actions/add-point", base(), tournament_url)).json(&body),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    let data: Value = response_json(r).await?;
    let success = data.get("success").and_then(|v| v.as_bool()).unwrap_or(false);
    if !success {
        return Err(
            data.get("error")
                .and_then(|v| v.as_str())
                .unwrap_or("Request failed")
                .to_string(),
        );
    }
    Ok(data)
}

pub async fn update_point(
    tournament_url: &str,
    point_id: &str,
    data: &serde_json::Value,
) -> Result<Value, String> {
    let c = client();
    let mut body = serde_json::Map::new();
    body.insert("point_id".to_string(), serde_json::Value::String(point_id.to_string()));
    if let Some(obj) = data.as_object() {
        for (k, v) in obj {
            body.insert(k.clone(), v.clone());
        }
    }
    let r = with_credentials(
        c.post(format!("{}/{}/match-actions/update-point", base(), tournament_url)).json(&body),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    let resp: Value = response_json(r).await?;
    let success = resp.get("success").and_then(|v| v.as_bool()).unwrap_or(false);
    if !success {
        return Err(
            resp.get("error")
                .and_then(|v| v.as_str())
                .unwrap_or("Request failed")
                .to_string(),
        );
    }
    Ok(resp)
}

pub async fn complete_match(tournament_url: &str, match_id: &str) -> Result<Value, String> {
    let c = client();
    let body = serde_json::json!({ "match_id": match_id });
    let r = with_credentials(
        c.post(format!("{}/{}/match-actions/complete-match", base(), tournament_url)).json(&body),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    let data: Value = response_json(r).await?;
    let success = data.get("success").and_then(|v| v.as_bool()).unwrap_or(false);
    if !success {
        return Err(
            data.get("error")
                .and_then(|v| v.as_str())
                .unwrap_or("Request failed")
                .to_string(),
        );
    }
    Ok(data)
}

// Injury management

pub async fn get_injury(
    player_id: &str,
    injury_id: u32,
) -> Result<crate::types::PlayerInjury, String> {
    let c = client();
    let r = with_credentials(
        c.get(format!(
            "{}/_api/players/{}/injuries/{}",
            base(),
            player_id,
            injury_id
        )),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    let data: crate::types::PlayerInjury = response_json(r).await?;
    Ok(data)
}

pub async fn create_injury(
    player_id: &str,
    message: &str,
    date: Option<&str>,
    active: bool,
    show: bool,
) -> Result<crate::types::PlayerInjury, String> {
    let c = client();
    let body = serde_json::json!({
        "message": message,
        "date": date,
        "active": active,
        "show": show,
    });
    let r = with_credentials(
        c.post(format!("{}/_api/players/{}/injuries", base(), player_id)).json(&body),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    let data: crate::types::PlayerInjury = response_json(r).await?;
    Ok(data)
}

pub async fn update_injury(
    player_id: &str,
    injury_id: u32,
    message: &str,
    date: Option<&str>,
    active: bool,
    show: bool,
) -> Result<crate::types::PlayerInjury, String> {
    let c = client();
    let body = serde_json::json!({
        "message": message,
        "date": date,
        "active": active,
        "show": show,
    });
    let r = with_credentials(
        c.put(format!(
            "{}/_api/players/{}/injuries/{}",
            base(),
            player_id,
            injury_id
        ))
        .json(&body),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    let data: crate::types::PlayerInjury = response_json(r).await?;
    Ok(data)
}

pub async fn delete_injury(player_id: &str, injury_id: u32) -> Result<(), String> {
    let c = client();
    let r = with_credentials(
        c.delete(format!(
            "{}/_api/players/{}/injuries/{}",
            base(),
            player_id,
            injury_id
        )),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    let _data: Value = response_json(r).await?;
    Ok(())
}
