use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct User {
    pub id: String,
    pub name: String,
    #[serde(rename = "type")]
    pub user_type: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Tournament {
    pub url: String,
    pub name: String,
    pub start_date: String,
    pub end_date: Option<String>,
    pub location: Option<String>,
    pub published: bool,
    pub n_max_teams: Option<u32>,
    #[serde(default)]
    pub schedule_published: bool,
    #[serde(default)]
    pub registration_open: bool,
    #[serde(default)]
    pub bracket: bool,
    pub about: Option<String>,
    pub team_reg_fee: Option<f64>,
    pub player_reg_fee: Option<f64>,
    pub num_fields: Option<u32>,
    pub max_team_size_roster: Option<u32>,
    pub max_team_size_field: Option<u32>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TournamentsResponse {
    pub upcoming: Vec<Tournament>,
    pub past: Vec<Tournament>,
    pub team_counts: std::collections::HashMap<String, u32>,
    pub user_reg_status: std::collections::HashMap<String, UserRegStatus>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct UserRegStatus {
    #[serde(rename = "type")]
    pub reg_type: String,
    pub status: String,
    pub paid: bool,
    pub amount_paid: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CheckUsernameResponse {
    pub available: bool,
    pub message: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TeamWithCount {
    pub team_id: String,
    pub team_name: String,
    pub pseudonym: Option<String>,
    pub player_count: u32,
    pub registered_at: Option<String>,
    pub profile_photo: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct UnattachedPlayer {
    pub player_id: String,
    pub player_name: String,
    pub jersey_number: Option<String>,
    pub jersey_name: Option<String>,
    pub registered_at: Option<String>,
    pub profile_photo: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TournamentDetailResponse {
    pub tournament: Tournament,
    pub teams_with_counts: Vec<TeamWithCount>,
    pub unattached_players: Vec<UnattachedPlayer>,
    pub to_entries: Vec<ToEntry>,
    pub is_current_team_registered: bool,
    pub is_current_player_registered: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ToEntry {
    pub user_id: String,
    pub user_type: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ScheduleMatch {
    pub uuid: String,
    pub name: String,
    pub field: Option<String>,
    pub team1: Option<String>,
    pub team2: Option<String>,
    pub team1_initial: Option<String>,
    pub team2_initial: Option<String>,
    pub status: String,
    pub nominal_start_time: Option<String>,
    pub confirmed_start_time: Option<String>,
    pub completed_time: Option<String>,
    pub schedule_type: Option<String>,
    pub set_type: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ScheduleField {
    pub id: u32,
    pub name: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TeamOption {
    pub id: String,
    pub pseudonym: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ScheduleResponse {
    pub tournament: Tournament,
    pub matches: Vec<ScheduleMatch>,
    pub fields: Vec<ScheduleField>,
    pub team_options: Vec<TeamOption>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PointData {
    pub uuid: String,
    pub set_number: Option<u32>,
    pub winner: Option<String>,
    pub rerolled: bool,
    pub stamp: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct MatchResultItem {
    pub uuid: String,
    pub name: String,
    pub field: Option<String>,
    pub team1: Option<String>,
    pub team2: Option<String>,
    pub match_winner: Option<String>,
    pub points: Vec<PointData>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ResultsResponse {
    pub tournament: Tournament,
    pub matches: Vec<MatchResultItem>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct MatchDetailData {
    pub uuid: String,
    pub name: String,
    pub field: Option<String>,
    pub team1: Option<String>,
    pub team2: Option<String>,
    pub team1_name: String,
    pub team2_name: String,
    pub status: String,
    pub nominal_start_time: Option<String>,
    pub confirmed_start_time: Option<String>,
    pub completed_time: Option<String>,
    pub set_type: Option<String>,
    pub stones_per_set: Option<u32>,
    pub stones_remaining: Option<u32>,
    pub match_winner: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct MatchDetailResponse {
    #[serde(rename = "match")]
    pub match_data: MatchDetailData,
    pub points: Vec<PointData>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PlayerListItem {
    pub id: String,
    pub name: String,
    pub profile_photo: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PlayersListResponse {
    pub players: Vec<PlayerListItem>,
    pub page: u32,
    pub total_pages: u32,
    pub total: u32,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PlayerProfileData {
    pub id: String,
    pub name: String,
    pub profile_photo: Option<String>,
    pub phone: Option<String>,
    pub location: Option<String>,
    pub bio: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PlayerProfileResponse {
    pub player: PlayerProfileData,
    pub registrations: Vec<PlayerRegItem>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PlayerRegItem {
    pub event: String,
    pub team: Option<String>,
    pub status: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TeamListItem {
    pub id: String,
    pub name: String,
    pub profile_photo: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TeamsListResponse {
    pub teams: Vec<TeamListItem>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TeamProfileData {
    pub id: String,
    pub name: String,
    pub profile_photo: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TeamProfileResponse {
    pub team: TeamProfileData,
    pub registrations: Vec<TeamRegItem>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TeamRegItem {
    pub event: String,
    pub pseudonym: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StoneFile {
    pub filename: String,
    pub filename_encoded: String,
    pub display_name: String,
    pub sort_order: u32,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StonesResponse {
    pub stones: Vec<StoneFile>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ServerTimeResponse {
    pub server_time: f64,
    pub timestamp: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ScoreboardStateResponse {
    pub has_active_match: bool,
    pub match_id: Option<String>,
    pub team1_name: Option<String>,
    pub team2_name: Option<String>,
    pub team1_photo: Option<String>,
    pub team2_photo: Option<String>,
    pub scores_by_set: Option<std::collections::HashMap<String, std::collections::HashMap<String, u32>>>,
    pub sets: Option<Vec<u32>>,
    pub stones_info: Option<StonesInfo>,
    pub prev_match: Option<PrevNextMatch>,
    pub next_match: Option<PrevNextMatch>,
    pub timestamp: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StonesInfo {
    pub stones_per_set: u32,
    pub stones_remaining: Option<u32>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PrevNextMatch {
    pub team1_name: String,
    pub team2_name: String,
    pub team1_photo: Option<String>,
    pub team2_photo: Option<String>,
    pub winner: Option<String>,
}
