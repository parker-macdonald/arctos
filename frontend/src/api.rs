use crate::types::*;
use dioxus::prelude::*;
use reqwest::Client;
use serde_json::Value;

pub fn base_url() -> String {
    if cfg!(debug_assertions) {
        "http://127.0.0.1:5006".to_string()
    } else {
        let window = web_sys::window().unwrap();
        let location = window.location();
        let origin = location.origin().unwrap();
        origin
    }
}

fn base() -> String {
    base_url()
}

fn client() -> Client {
    Client::new()
}

fn with_credentials(req: reqwest::RequestBuilder) -> reqwest::RequestBuilder {
    #[cfg(target_arch = "wasm32")]
    {
        req.fetch_credentials_include()
    }
    #[cfg(not(target_arch = "wasm32"))]
    {
        req
    }
}

async fn response_json<T: serde::de::DeserializeOwned>(
    resp: reqwest::Response,
) -> Result<T, String> {
    if !resp.status().is_success() {
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        return Err(format!("Server returned error {}: {}", status, text));
    }
    
    // Check content type
    let ct_str = resp
        .headers()
        .get("content-type")
        .and_then(|ct| ct.to_str().ok())
        .map(|s| s.to_string());
    if let Some(ct) = ct_str.as_deref() {
        if !ct.contains("application/json") {
            let text = resp.text().await.unwrap_or_default();
            return Err(format!(
                "Server returned non-JSON (content-type: {}). Maybe the backend is not running or /_api/ routes are missing. Body: {}",
                ct,
                text
            ));
        }
    }

    resp.json::<T>().await.map_err(|e| e.to_string())
}

pub async fn me() -> Result<User, String> {
    let c = client();
    let r = with_credentials(c.get(format!("{}/_api/me", base())))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn login(username: &str, password: &str) -> Result<User, String> {
    let c = client();
    let body = serde_json::json!({ "username": username, "password": password });
    let r = with_credentials(c.post(format!("{}/_api/login", base())).json(&body))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn logout() -> Result<(), String> {
    let c = client();
    let r = with_credentials(c.post(format!("{}/_api/logout", base())))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !r.status().is_success() {
        return Err("Logout failed".to_string());
    }
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
    response_json(r).await
}

pub async fn check_username(username: &str) -> Result<CheckUsernameResponse, String> {
    let c = client();
    let r = c
        .get(format!("{}/_api/check-username", base()))
        .query(&[("username", username)])
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
    let r = with_credentials(c.get(format!(
        "{}/_api/tournaments/{}",
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

pub async fn start_match_data(
    tournament_url: &str,
    match_id: &str,
) -> Result<StartMatchResponse, String> {
    let c = client();
    let r = with_credentials(c.get(format!(
        "{}/_api/tournaments/{}/start-match?match_id={}",
        base(),
        tournament_url,
        match_id
    )))
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn start_match(
    tournament_url: &str,
    req: &StartMatchRequest,
) -> Result<StartMatchPostResponse, String> {
    let c = client();
    let r = with_credentials(
        c.post(format!("{}/_api/tournaments/{}/start-match", base(), tournament_url))
            .json(req),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn finalize_match_data(
    tournament_url: &str,
    match_id: &str,
) -> Result<FinalizeMatchResponse, String> {
    let c = client();
    let r = with_credentials(c.get(format!(
        "{}/_api/tournaments/{}/finalize-match?match_id={}",
        base(),
        tournament_url,
        match_id
    )))
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn finalize_match(
    tournament_url: &str,
    req: &FinalizeMatchRequest,
) -> Result<FinalizeMatchPostResponse, String> {
    let c = client();
    let r = with_credentials(
        c.post(format!(
            "{}/_api/tournaments/{}/finalize-match",
            base(),
            tournament_url
        ))
        .json(req),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn tournament_manage(
    tournament_url: &str,
    search: &str,
    search_type: &str,
) -> Result<TournamentManageResponse, String> {
    let c = client();
    let mut url = format!("{}/_api/tournaments/{}/manage", base(), tournament_url);
    if !search.is_empty() || !search_type.is_empty() {
        let st = if search_type.is_empty() { "both" } else { search_type };
        url = format!("{}?search={}&type={}", url, urlencoding::encode(search), st);
    }
    let r = with_credentials(c.get(url))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn tournament_invitations(
    tournament_url: &str,
) -> Result<TournamentInvitationsResponse, String> {
    let c = client();
    let r = with_credentials(c.get(format!(
        "{}/_api/tournaments/{}/invitations",
        base(),
        tournament_url
    )))
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn tournament_bracket(tournament_url: &str) -> Result<BracketResponse, String> {
    let c = client();
    let r = with_credentials(c.get(format!(
        "{}/_api/tournaments/{}/bracket",
        base(),
        tournament_url
    )))
    .send()
    .await
    .map_err(|e| e.to_string())?;
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
    if r.status().as_u16() == 404 {
        return Err("Not found".to_string());
    }
    if r.status().as_u16() == 403 {
        return Err("Schedule not published".to_string());
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

#[allow(dead_code)]
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
        return Err("Failed to get camera URL".to_string());
    }
    let data: Value = response_json(r).await?;
    data.get("url")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .ok_or_else(|| "No URL in response".to_string())
}

pub async fn server_time() -> Result<ServerTimeResponse, String> {
    let c = client();
    let r = with_credentials(c.get(format!("{}/_api/server-time", base())))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn scoreboard_state(
    tournament_url: &str,
    field_name: &str,
) -> Result<ScoreboardStateResponse, String> {
    let c = client();
    let r = with_credentials(
        c.get(format!("{}/_api/scoreboard-state", base()))
            .query(&[("tournament", tournament_url), ("field", field_name)]),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn fetch_bytes(url: &str) -> Result<Vec<u8>, String> {
    let c = client();
    let r = with_credentials(c.get(url))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !r.status().is_success() {
        return Err(format!("Failed to fetch bytes: {}", r.status()));
    }
    let bytes = r.bytes().await.map_err(|e| e.to_string())?;
    Ok(bytes.to_vec())
}

pub async fn get_injury(player_id: &str, injury_id: u32) -> Result<PlayerInjury, String> {
    let c = client();
    let r = with_credentials(c.get(format!(
        "{}/_api/players/{}/injuries/{}",
        base(),
        player_id,
        injury_id
    )))
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn create_injury(
    player_id: &str,
    req: &serde_json::Value,
) -> Result<PlayerInjury, String> {
    let c = client();
    let r = with_credentials(
        c.post(format!("{}/_api/players/{}/injuries", base(), player_id))
            .json(req),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    
    response_json(r).await
}

pub async fn update_injury(
    player_id: &str,
    injury_id: u32,
    req: &serde_json::Value,
) -> Result<PlayerInjury, String> {
    let c = client();
    let r = with_credentials(
        c.put(format!("{}/_api/players/{}/injuries/{}", base(), player_id, injury_id))
            .json(req),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    
    response_json(r).await
}

pub async fn delete_injury(player_id: &str, injury_id: u32) -> Result<(), String> {
    let c = client();
    let r = with_credentials(
        c.delete(format!("{}/_api/players/{}/injuries/{}", base(), player_id, injury_id)),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    
    let data: Value = response_json(r).await?;
    if data.get("success").and_then(|v| v.as_bool()) == Some(true) {
        Ok(())
    } else {
        Err(data.get("error").and_then(|v| v.as_str()).unwrap_or("Unknown error").to_string())
    }
}

pub async fn match_state(tournament_url: &str, match_id: &str) -> Result<Value, String> {
    let c = client();
    let r = with_credentials(c.get(format!(
        "{}/{}/match-state?id={}",
        base(),
        tournament_url,
        match_id
    )))
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

#[allow(dead_code)]
pub async fn set_match_status(
    tournament_url: &str,
    match_id: &str,
    status: &str,
) -> Result<Value, String> {
    let c = client();
    let body = serde_json::json!({ "match_id": match_id, "status": status });
    let r = with_credentials(
        c.post(format!("{}/{}/match-actions/set-status", base(), tournament_url)).json(&body),
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

pub async fn get_field(tournament_url: &str, field_id: u32) -> Result<FieldResponse, String> {
    let c = client();
    let r = with_credentials(c.get(format!(
        "{}/_api/tournaments/{}/fields/{}",
        base(),
        tournament_url,
        field_id
    )))
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn delete_point(tournament_url: &str, point_id: &str) -> Result<Value, String> {
    let c = client();
    let body = serde_json::json!({ "point_id": point_id });
    let r = with_credentials(
        c.post(format!(
            "{}/{}/match-actions/delete-point",
            base(),
            tournament_url
        ))
        .json(&body),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn update_field(
    tournament_url: &str,
    field_id: u32,
    req: &UpdateFieldRequest,
) -> Result<(), String> {
    let c = client();
    let r = with_credentials(
        c.put(format!(
            "{}/_api/tournaments/{}/fields/{}",
            base(),
            tournament_url,
            field_id
        ))
        .json(req),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    
    let data: Value = response_json(r).await?;
    if data.get("success").and_then(|v| v.as_bool()) == Some(true) {
        Ok(())
    } else {
        Err(data.get("error").and_then(|v| v.as_str()).unwrap_or("Unknown error").to_string())
    }
}

pub async fn get_tag(tournament_url: &str, tag_id: u32) -> Result<TagResponse, String> {
    let c = client();
    let r = with_credentials(c.get(format!(
        "{}/_api/tournaments/{}/tags/{}",
        base(),
        tournament_url,
        tag_id
    )))
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn update_tag(
    tournament_url: &str,
    tag_id: u32,
    req: &UpdateTagRequest,
) -> Result<(), String> {
    let c = client();
    let r = with_credentials(
        c.put(format!(
            "{}/_api/tournaments/{}/tags/{}",
            base(),
            tournament_url,
            tag_id
        ))
        .json(req),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    
    let data: Value = response_json(r).await?;
    if data.get("success").and_then(|v| v.as_bool()) == Some(true) {
        Ok(())
    } else {
        Err(data.get("error").and_then(|v| v.as_str()).unwrap_or("Unknown error").to_string())
    }
}

#[allow(dead_code)]
pub async fn tags_list(tournament_url: &str) -> Result<TagsListResponse, String> {
    let c = client();
    let r = with_credentials(c.get(format!(
        "{}/_api/tournaments/{}/tags",
        base(),
        tournament_url
    )))
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn markdown_page(slug: &str) -> Result<MarkdownPageResponse, String> {
    let c = client();
    let r = with_credentials(c.get(format!(
        "{}/_api/markdown/{}",
        base(),
        slug
    )))
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn google_choose_account_type_info() -> Result<GoogleChooseAccountTypeResponse, String> {
    let c = client();
    let r = with_credentials(c.get(format!(
        "{}/_api/google/choose-account-type",
        base()
    )))
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn google_choose_account_type(
    req: &GoogleChooseAccountTypeRequest,
) -> Result<(), String> {
    let c = client();
    let r = with_credentials(
        c.post(format!("{}/_api/google/choose-account-type", base()))
            .json(req),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    let data: Value = response_json(r).await?;
    if data.get("ok").and_then(|v| v.as_bool()) == Some(true) {
        Ok(())
    } else {
        Err(data.get("error").and_then(|v| v.as_str()).unwrap_or("Unknown error").to_string())
    }
}

pub async fn google_complete_profile_info() -> Result<GoogleCompleteProfileResponse, String> {
    let c = client();
    let r = with_credentials(c.get(format!(
        "{}/_api/google/complete-profile",
        base()
    )))
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn google_complete_profile(
    req: &GoogleCompleteProfileRequest,
) -> Result<(), String> {
    let c = client();
    let r = with_credentials(
        c.post(format!("{}/_api/google/complete-profile", base()))
            .json(req),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    let data: Value = response_json(r).await?;
    if data.get("ok").and_then(|v| v.as_bool()) == Some(true) {
        Ok(())
    } else {
        Err(data.get("error").and_then(|v| v.as_str()).unwrap_or("Unknown error").to_string())
    }
}

pub async fn update_match(
    tournament_url: &str,
    match_id: &str,
    req: &UpdateMatchRequest,
) -> Result<(), String> {
    let c = client();
    let r = with_credentials(
        c.put(format!(
            "{}/_api/tournaments/{}/matches/{}",
            base(),
            tournament_url,
            match_id
        ))
        .json(req),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    
    let data: Value = response_json(r).await?;
    if data.get("success").and_then(|v| v.as_bool()) == Some(true) {
        Ok(())
    } else {
        Err(data.get("error").and_then(|v| v.as_str()).unwrap_or("Unknown error").to_string())
    }
}

pub async fn update_player_profile(
    player_id: &str,
    req: &UpdatePlayerProfileRequest,
) -> Result<(), String> {
    let c = client();
    let r = with_credentials(
        c.put(format!("{}/_api/players/{}", base(), player_id))
        .json(req),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    
    let data: Value = response_json(r).await?;
    if data.get("success").and_then(|v| v.as_bool()) == Some(true) {
        Ok(())
    } else {
        Err(data.get("error").and_then(|v| v.as_str()).unwrap_or("Unknown error").to_string())
    }
}

pub async fn update_team_profile(
    team_id: &str,
    req: &UpdateTeamProfileRequest,
) -> Result<(), String> {
    let c = client();
    let r = with_credentials(
        c.put(format!("{}/_api/teams/{}", base(), team_id))
        .json(req),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    
    let data: Value = response_json(r).await?;
    if data.get("success").and_then(|v| v.as_bool()) == Some(true) {
        Ok(())
    } else {
        Err(data.get("error").and_then(|v| v.as_str()).unwrap_or("Unknown error").to_string())
    }
}

pub async fn get_my_player_registration(
    tournament_url: &str,
) -> Result<MyPlayerRegistrationResponse, String> {
    let c = client();
    let r = with_credentials(c.get(format!(
        "{}/_api/tournaments/{}/registrations/player/me",
        base(),
        tournament_url
    )))
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn update_my_player_registration(
    tournament_url: &str,
    req: &UpdatePlayerRegistrationRequest,
) -> Result<(), String> {
    let c = client();
    let r = with_credentials(
        c.put(format!(
            "{}/_api/tournaments/{}/registrations/player/me",
            base(),
            tournament_url
        ))
        .json(req),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    
    let data: Value = response_json(r).await?;
    if data.get("success").and_then(|v| v.as_bool()) == Some(true) {
        Ok(())
    } else {
        Err(data.get("error").and_then(|v| v.as_str()).unwrap_or("Unknown error").to_string())
    }
}

pub async fn get_my_team_registration(
    tournament_url: &str,
) -> Result<MyTeamRegistrationResponse, String> {
    let c = client();
    let r = with_credentials(c.get(format!(
        "{}/_api/tournaments/{}/registrations/team/me",
        base(),
        tournament_url
    )))
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn update_my_team_registration(
    tournament_url: &str,
    req: &UpdateTeamRegistrationRequest,
) -> Result<(), String> {
    let c = client();
    let r = with_credentials(
        c.put(format!(
            "{}/_api/tournaments/{}/registrations/team/me",
            base(),
            tournament_url
        ))
        .json(req),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    
    let data: Value = response_json(r).await?;
    if data.get("success").and_then(|v| v.as_bool()) == Some(true) {
        Ok(())
    } else {
        Err(data.get("error").and_then(|v| v.as_str()).unwrap_or("Unknown error").to_string())
    }
}
