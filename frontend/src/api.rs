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

fn truncate_error_body(text: &str, max_len: usize) -> String {
    let t = text.trim();
    if t.len() <= max_len {
        t.to_string()
    } else {
        format!("{}... ({} bytes total). Check server logs for full error.", &t[..max_len], t.len())
    }
}

#[derive(serde::Deserialize)]
pub struct StatusResponse {
    pub success: bool,
    pub message: Option<String>,
    pub error: Option<String>,
}

async fn response_json<T: serde::de::DeserializeOwned>(
    resp: reqwest::Response,
) -> Result<T, String> {
    if !resp.status().is_success() {
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        let truncated = truncate_error_body(&text, 200);
        return Err(format!("Server returned error {}: {}", status, truncated));
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
            let truncated = truncate_error_body(&text, 200);
            return Err(format!(
                "Server returned non-JSON (content-type: {}). Maybe the backend is not running or /_api/ routes are missing. Body: {}",
                ct,
                truncated
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

async fn post_form_status(
    url: &str,
    params: &[(String, String)],
) -> Result<StatusResponse, String> {
    let c = client();
    let r = with_credentials(c.post(url).form(params))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn update_tournament_settings(
    tournament_url: &str,
    params: &[(String, String)],
) -> Result<StatusResponse, String> {
    let url = format!("{}/{}/update-settings", base(), tournament_url);
    post_form_status(&url, params).await
}

pub async fn mark_team_paid(
    tournament_url: &str,
    registration_id: u32,
    amount_paid: f64,
    paid: bool,
    payment_method: &str,
    payment_reference: &str,
    payment_notes: &str,
) -> Result<StatusResponse, String> {
    let mut params = vec![
        ("registration_id".into(), registration_id.to_string()),
        ("amount_paid".into(), amount_paid.to_string()),
        ("payment_method".into(), payment_method.to_string()),
        ("payment_reference".into(), payment_reference.to_string()),
        ("payment_notes".into(), payment_notes.to_string()),
    ];
    if paid {
        params.push(("paid".into(), "on".to_string()));
    }
    let url = format!("{}/{}/mark-team-paid", base(), tournament_url);
    post_form_status(&url, &params).await
}

pub async fn mark_player_paid(
    tournament_url: &str,
    registration_id: u32,
    amount_paid: f64,
    paid: bool,
    payment_method: &str,
    payment_reference: &str,
    payment_notes: &str,
) -> Result<StatusResponse, String> {
    let mut params = vec![
        ("registration_id".into(), registration_id.to_string()),
        ("amount_paid".into(), amount_paid.to_string()),
        ("payment_method".into(), payment_method.to_string()),
        ("payment_reference".into(), payment_reference.to_string()),
        ("payment_notes".into(), payment_notes.to_string()),
    ];
    if paid {
        params.push(("paid".into(), "on".to_string()));
    }
    let url = format!("{}/{}/mark-player-paid", base(), tournament_url);
    post_form_status(&url, &params).await
}

pub async fn deregister_any_team(
    tournament_url: &str,
    team_id: &str,
) -> Result<StatusResponse, String> {
    let params = vec![("team_id".into(), team_id.to_string())];
    let url = format!("{}/{}/deregister-any-team", base(), tournament_url);
    post_form_status(&url, &params).await
}

pub async fn deregister_any_player(
    tournament_url: &str,
    player_id: &str,
) -> Result<StatusResponse, String> {
    let params = vec![("player_id".into(), player_id.to_string())];
    let url = format!("{}/{}/deregister-any-player", base(), tournament_url);
    post_form_status(&url, &params).await
}

pub async fn register_player(
    tournament_url: &str,
    jersey_name: &str,
    jersey_number: &str,
    team: &str,
    agree_terms: bool,
) -> Result<StatusResponse, String> {
    let mut params = vec![
        ("jersey_name".into(), jersey_name.to_string()),
        ("jersey_number".into(), jersey_number.to_string()),
        ("team".into(), team.to_string()),
    ];
    if agree_terms {
        params.push(("agree_terms".into(), "on".into()));
    }
    let url = format!("{}/{}/register-player", base(), tournament_url);
    post_form_status(&url, &params).await
}

pub async fn register_team(
    tournament_url: &str,
    pseudonym: &str,
    agree_terms: bool,
) -> Result<StatusResponse, String> {
    let mut params = vec![("pseudonym".into(), pseudonym.to_string())];
    if agree_terms {
        params.push(("agree_terms".into(), "on".into()));
    }
    let url = format!("{}/{}/register-team", base(), tournament_url);
    post_form_status(&url, &params).await
}

pub async fn deregister_player(tournament_url: &str) -> Result<StatusResponse, String> {
    let url = format!("{}/{}/deregister-player", base(), tournament_url);
    post_form_status(&url, &[]).await
}

pub async fn deregister_team(tournament_url: &str) -> Result<StatusResponse, String> {
    let url = format!("{}/{}/deregister-team", base(), tournament_url);
    post_form_status(&url, &[]).await
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

pub async fn results_team_matches(
    tournament_url: &str,
    team_id: &str,
) -> Result<crate::types::TeamMatchesResponse, String> {
    let c = client();
    let url = format!(
        "{}/_api/tournaments/{}/results/team/{}",
        base(),
        tournament_url,
        urlencoding::encode(team_id)
    );
    let r = with_credentials(c.get(&url))
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

pub async fn record_match_status(
    tournament_url: &str,
    field_name: &str,
    current_match_id: Option<&str>,
) -> Result<RecordMatchStatusResponse, String> {
    let c = client();
    let mut req = c
        .get(format!("{}/_api/record/match-status", base()))
        .query(&[("tournament", tournament_url), ("field", field_name)]);
    if let Some(mid) = current_match_id {
        req = req.query(&[("current_match_id", mid)]);
    }
    let r = req.send().await.map_err(|e| e.to_string())?;
    response_json(r).await
}

/// Metadata for a single chunk upload (record page).
#[cfg(target_arch = "wasm32")]
#[derive(Clone)]
pub struct RecordChunkMeta {
    pub tournament_url: String,
    pub field: String,
    pub match_id: String,
    pub session_id: String,
    pub point_id: Option<String>,
    pub chunk_start_timestamp: f64,
    pub recording_session_start_time: f64,
    pub chunk_length_ms: u32,
    pub camera_name: String,
    pub key: Option<String>,
}

#[cfg(target_arch = "wasm32")]
pub async fn record_upload_chunk(meta: &RecordChunkMeta, chunk_blob: &web_sys::Blob) -> Result<(), String> {
    use wasm_bindgen::JsCast;
    use web_sys::window;

    let form = web_sys::FormData::new().map_err(|_| "FormData::new failed")?;
    form.append_with_str("tournament", &meta.tournament_url)
        .map_err(|_| "append tournament failed")?;
    form.append_with_str("field", &meta.field)
        .map_err(|_| "append field failed")?;
    form.append_with_str("match_id", &meta.match_id)
        .map_err(|_| "append match_id failed")?;
    form.append_with_str("session_id", &meta.session_id)
        .map_err(|_| "append session_id failed")?;
    form.append_with_str("chunk_start_timestamp", &meta.chunk_start_timestamp.to_string())
        .map_err(|_| "append chunk_start_timestamp failed")?;
    form.append_with_str("recording_session_start_time", &meta.recording_session_start_time.to_string())
        .map_err(|_| "append recording_session_start_time failed")?;
    form.append_with_str("chunk_duration", &meta.chunk_length_ms.to_string())
        .map_err(|_| "append chunk_duration failed")?;
    form.append_with_str("camera_name", &meta.camera_name)
        .map_err(|_| "append camera_name failed")?;
    if let Some(ref pid) = meta.point_id {
        form.append_with_str("point_id", pid)
            .map_err(|_| "append point_id failed")?;
    }
    if let Some(ref k) = meta.key {
        form.append_with_str("camera_key", k).map_err(|_| "append key failed")?;
    }
    form.append_with_blob("chunk", chunk_blob)
        .map_err(|_| "append chunk failed")?;

    let window = window().ok_or("no window")?;
    let url = format!("{}/_api/record/upload-chunk", base());
    let opts = web_sys::RequestInit::new();
    opts.set_method("POST");
    let form_js = wasm_bindgen::JsValue::from(form);
    opts.set_body(form_js.as_ref());

    let request = web_sys::Request::new_with_str_and_init(&url, &opts)
        .map_err(|_| "Request::new_with_str_and_init failed")?;
    let resp = wasm_bindgen_futures::JsFuture::from(window.fetch_with_request(&request))
        .await
        .map_err(|_| "fetch failed")?;
    let resp: web_sys::Response = resp.dyn_into().map_err(|_| "response cast failed")?;
    if !resp.ok() {
        let text = wasm_bindgen_futures::JsFuture::from(resp.text().map_err(|_| "text() failed")?)
            .await
            .map_err(|_| "text await failed")?;
        let msg = text.as_string().unwrap_or_else(|| "Unknown error".to_string());
        return Err(format!("Upload failed: {}", msg));
    }
    Ok(())
}

#[cfg(not(target_arch = "wasm32"))]
pub async fn record_upload_chunk(
    _meta: &crate::api::RecordChunkMeta,
    _chunk_blob: &[u8],
) -> Result<(), String> {
    Err("record_upload_chunk only supported on wasm".to_string())
}

#[cfg(not(target_arch = "wasm32"))]
pub struct RecordChunkMeta {
    pub tournament_url: String,
    pub field: String,
    pub match_id: String,
    pub session_id: String,
    pub point_id: Option<String>,
    pub chunk_start_timestamp: f64,
    pub recording_session_start_time: f64,
    pub chunk_length_ms: u32,
    pub camera_name: String,
    pub key: Option<String>,
}

pub async fn record_finalize(
    tournament_url: &str,
    field_name: &str,
    match_id: &str,
    camera_name: &str,
    key: Option<&str>,
) -> Result<(), String> {
    let c = client();
    let mut body = serde_json::json!({
        "tournament": tournament_url,
        "field": field_name,
        "match_id": match_id,
        "camera_name": camera_name,
    });
    if let Some(k) = key {
        body["camera_key"] = serde_json::json!(k);
    }
    let r = c
        .post(format!("{}/_api/record/finalize", base()))
        .json(&body)
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !r.status().is_success() {
        let text = r.text().await.unwrap_or_default();
        return Err(format!("Finalize failed: {}", text));
    }
    Ok(())
}

pub async fn server_time() -> Result<ServerTimeResponse, String> {
    let c = client();
    let r = with_credentials(c.get(format!("{}/_api/server-time", base())))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn bracket_setup_data(url: &str) -> Result<BracketSetupResponse, String> {
    let c = client();
    let r = with_credentials(
        c.get(format!(
            "{}/_api/tournaments/{}/bracket-setup-data",
            base(),
            url
        )),
    )
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
        "{}/_api/tournaments/{}/match-state?match_id={}",
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

pub async fn get_point_notes(
    tournament_url: &str,
    match_id: &str,
    point_id: &str,
) -> Result<Value, String> {
    let c = client();
    let url = format!(
        "{}/{}/get-point-notes?match_id={}&point_id={}",
        base(),
        tournament_url,
        urlencoding::encode(match_id),
        urlencoding::encode(point_id),
    );
    let r = with_credentials(c.get(url))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    response_json(r).await
}

/// Get selection notes for a team and selected player IDs (start-match page).
/// Uses credentials so the backend @login_required sees the session.
pub async fn get_selection_notes(
    tournament_url: &str,
    match_id: &str,
    team: &str,
    player_ids: &str,
) -> Result<Value, String> {
    let c = client();
    let url = format!(
        "{}/{}/get-selection-notes?match_id={}&team={}&player_ids={}",
        base(),
        tournament_url,
        urlencoding::encode(match_id),
        urlencoding::encode(team),
        urlencoding::encode(player_ids),
    );
    let r = with_credentials(c.get(url))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn add_point_note(
    tournament_url: &str,
    match_id: &str,
    point_id: &str,
    text: &str,
    target: &str,
    player_id: Option<&str>,
) -> Result<Value, String> {
    let c = client();
    let body = serde_json::json!({
        "match_id": match_id,
        "point_id": point_id,
        "text": text,
        "target": target,
        "player_id": player_id,
    });
    let r = with_credentials(
        c.post(format!("{}/{}/add-point-note", base(), tournament_url)).json(&body),
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

pub async fn update_stones(
    tournament_url: &str,
    match_id: &str,
    stones_remaining: u32,
) -> Result<Value, String> {
    let c = client();
    let body = serde_json::json!({
        "match_id": match_id,
        "stones_remaining": stones_remaining,
    });
    let r = with_credentials(
        c.post(format!(
            "{}/{}/match-actions/update-stones",
            base(),
            tournament_url
        ))
        .json(&body),
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

pub async fn save_bracket_setup(
    tournament_url: &str,
    brackets: &[crate::types::BracketConfig],
) -> Result<(), String> {
    let c = client();
    let body = serde_json::json!({ "brackets": brackets });
    let r = with_credentials(
        c.post(format!(
            "{}/_api/tournaments/{}/bracket-setup",
            base(),
            tournament_url
        ))
        .json(&body),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    let v: serde_json::Value = response_json(r).await?;
    if v.get("success").and_then(|v| v.as_bool()).unwrap_or(false) {
        Ok(())
    } else {
        Err(v.get("error")
            .and_then(|v| v.as_str())
            .unwrap_or("Failed to save bracket configuration")
            .to_string())
    }
}

/// Upload a single bracket image as raw bytes and return its relative static path.
#[cfg(target_arch = "wasm32")]
pub async fn upload_bracket_image_bytes(
    tournament_url: &str,
    bracket_index: u32,
    filename: &str,
    bytes: bytes::Bytes,
) -> Result<String, String> {
    let c = client();
    let r = with_credentials(
        c.post(format!(
            "{}/_api/tournaments/{}/bracket-upload-bytes",
            base(),
            tournament_url
        ))
        .query(&[
            ("bracket_index", bracket_index.to_string()),
            ("filename", filename.to_string()),
        ])
        .body(bytes),
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    let v: serde_json::Value = response_json(r).await?;
    if v
        .get("success")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
    {
        if let Some(path) = v.get("path").and_then(|v| v.as_str()) {
            Ok(path.to_string())
        } else {
            Err("Upload succeeded but no path returned".to_string())
        }
    } else {
        Err(v.get("error")
            .and_then(|v| v.as_str())
            .unwrap_or("Failed to upload bracket image")
            .to_string())
    }
}

/// Fetch YouTube stream start time (ISO UTC) for a video ID or URL. Returns Ok(None) if not available.
pub async fn youtube_stream_start(video_id_or_url: &str) -> Result<Option<String>, String> {
    let video_id = extract_youtube_video_id(video_id_or_url).unwrap_or_else(|| video_id_or_url.to_string());
    if video_id.is_empty() {
        return Ok(None);
    }
    let c = client();
    let url = format!("{}/youtube-stream-start", base());
    let r = with_credentials(c.get(&url).query(&[("video_id", video_id.as_str())]))
    .send()
    .await
    .map_err(|e| e.to_string())?;
    let data: Value = response_json(r).await?;
    let start = data.get("start_time");
    Ok(start.and_then(|v| v.as_str()).map(String::from))
}

fn extract_youtube_video_id(s: &str) -> Option<String> {
    let s = s.trim();
    if s.is_empty() {
        return None;
    }
    // youtu.be/ID
    if let Some(rest) = s.strip_prefix("https://youtu.be/") {
        let id = rest.split(&['?', '&', '#'][..]).next().unwrap_or(rest);
        if id.len() >= 11 && id.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') {
            return Some(id[..11].to_string());
        }
    }
    if let Some(rest) = s.strip_prefix("http://youtu.be/") {
        let id = rest.split(&['?', '&', '#'][..]).next().unwrap_or(rest);
        if id.len() >= 11 && id.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') {
            return Some(id[..11].to_string());
        }
    }
    // youtube.com/watch?v=ID or embed/ID or v/ID
    if s.contains("youtube.com") {
        if let Some(v) = s.find("v=") {
            let after = &s[v + 2..];
            let id = after.split(&['&', '#'][..]).next().unwrap_or(after);
            if id.len() >= 11 && id.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') {
                return Some(id[..11].to_string());
            }
        }
        for prefix in ["/embed/", "/v/"] {
            if let Some(i) = s.find(prefix) {
                let after = &s[i + prefix.len()..];
                let id = after.split(&['?', '&', '#'][..]).next().unwrap_or(after);
                if id.len() >= 11 && id.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') {
                    return Some(id[..11].to_string());
                }
            }
        }
    }
    // Bare 11-char ID
    if s.len() == 11 && s.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') {
        return Some(s.to_string());
    }
    None
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

pub async fn render_markdown(markdown: &str) -> Result<String, String> {
    let c = client();
    let r = with_credentials(
        c.post(format!("{}/_api/render-markdown", base())).json(&serde_json::json!({ "markdown": markdown }))
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    let res: RenderMarkdownResponse = response_json(r).await?;
    Ok(res.html)
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

pub async fn schedule_setup(tournament_url: &str) -> Result<ScheduleSetupResponse, String> {
    let c = client();
    let r = with_credentials(c.get(format!(
        "{}/_api/tournaments/{}/schedule-setup",
        base(),
        tournament_url
    )))
    .send()
    .await
    .map_err(|e| e.to_string())?;
    
    if r.status().as_u16() == 403 {
        return Err("Schedule not published".to_string());
    }
    response_json(r).await
}

pub async fn create_match(
    tournament_url: &str,
    req: &CreateMatchRequest,
) -> Result<CreateMatchResponse, String> {
    let c = client();
    let r = with_credentials(
        c.post(format!("{}/_api/tournaments/{}/matches", base(), tournament_url))
        .json(req)
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

/// Validate a DSL skip-condition expression. Uses the tournaments blueprint route.
pub async fn validate_dsl(tournament_url: &str, expression: &str) -> Result<ValidateDslResponse, String> {
    let c = client();
    let body = serde_json::json!({ "expression": expression });
    let r = with_credentials(
        c.post(format!("{}/{}/_api/validate-dsl", base(), tournament_url))
        .json(&body)
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn delete_match(tournament_url: &str, match_id: &str) -> Result<(), String> {
    let c = client();
    let r = with_credentials(
        c.delete(format!("{}/_api/tournaments/{}/matches/{}", base(), tournament_url, match_id))
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

pub async fn create_field(
    tournament_url: &str,
    req: &CreateFieldRequest,
) -> Result<CreateFieldResponse, String> {
    let c = client();
    let r = with_credentials(
        c.post(format!("{}/_api/tournaments/{}/fields", base(), tournament_url))
        .json(req)
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn delete_field(tournament_url: &str, field_id: u32) -> Result<(), String> {
    let c = client();
    let r = with_credentials(
        c.delete(format!("{}/_api/tournaments/{}/fields/{}", base(), tournament_url, field_id))
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

pub async fn create_tag(
    tournament_url: &str,
    req: &CreateTagRequest,
) -> Result<CreateTagResponse, String> {
    let c = client();
    let r = with_credentials(
        c.post(format!("{}/_api/tournaments/{}/tags", base(), tournament_url))
        .json(req)
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn delete_tag(tournament_url: &str, tag_id: u32) -> Result<(), String> {
    let c = client();
    let resp = with_credentials(
        c.delete(format!("{}/_api/tournaments/{}/tags/{}", base(), tournament_url, tag_id))
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;

    if resp.status().is_success() {
        let data: Value = resp.json().await.map_err(|e| e.to_string())?;
        if data.get("success").and_then(|v| v.as_bool()) == Some(true) {
            return Ok(());
        }
        return Err(
            data.get("error")
                .and_then(|v| v.as_str())
                .unwrap_or("Unknown error")
                .to_string(),
        );
    }
    let text = resp.text().await.unwrap_or_default();
    let err_msg = serde_json::from_str::<Value>(&text)
        .ok()
        .and_then(|v| v.get("error").cloned())
        .and_then(|v| v.as_str().map(String::from))
        .unwrap_or_else(|| format!("Delete failed: {}", truncate_error_body(&text, 200)));
    Err(err_msg)
}

pub async fn recompute_schedule(tournament_url: &str) -> Result<(), String> {
    let c = client();
    let r = with_credentials(
        c.post(format!("{}/_api/tournaments/{}/recompute-schedule", base(), tournament_url))
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
pub async fn update_all_references(tournament_url: &str) -> Result<(), String> {
    let c = client();
    let r = with_credentials(
        c.post(format!("{}/_api/tournaments/{}/update-all-references", base(), tournament_url))
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
pub async fn push_back_matches(
    tournament_url: &str,
    req: &PushBackRequest,
) -> Result<(), String> {
    let c = client();
    let r = with_credentials(
        c.post(format!("{}/_api/tournaments/{}/push-back-matches", base(), tournament_url))
        .json(req)
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

pub async fn update_tags(
    tournament_url: &str,
    req: &UpdateTagsRequest,
) -> Result<(), String> {
    let c = client();
    let r = with_credentials(
        c.post(format!("{}/_api/tournaments/{}/update-tags", base(), tournament_url))
        .json(req)
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

pub async fn export_schedule(tournament_url: &str) -> Result<ExportScheduleResponse, String> {
    let c = client();
    let r = with_credentials(
        c.get(format!("{}/_api/tournaments/{}/export-schedule", base(), tournament_url))
    )
    .send()
    .await
    .map_err(|e| e.to_string())?;
    response_json(r).await
}

pub async fn import_schedule(
    tournament_url: &str,
    req: &ImportScheduleRequest,
) -> Result<(), String> {
    let c = client();
    let r = with_credentials(
        c.post(format!("{}/_api/tournaments/{}/import-schedule", base(), tournament_url))
        .json(req)
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
