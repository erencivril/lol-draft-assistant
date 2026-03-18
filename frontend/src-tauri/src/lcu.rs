use anyhow::{Context, Result};
use reqwest::StatusCode;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager, State};

#[derive(Clone, Serialize)]
struct RoleCandidatePayload {
    role: String,
    confidence: f64,
}

#[derive(Clone, Serialize)]
struct TeamSlotPayload {
    cell_id: i64,
    champion_id: i64,
    champion_name: Option<String>,
    champion_image_url: Option<String>,
    assigned_role: Option<String>,
    effective_role: Option<String>,
    role_source: String,
    role_confidence: f64,
    role_candidates: Vec<RoleCandidatePayload>,
    summoner_id: Option<i64>,
    is_local_player: bool,
}

#[derive(Clone, Serialize)]
pub struct RunePagePayload {
    pub keystone_id: i64,
    pub primary_style_id: i64,
    pub sub_style_id: i64,
    pub selected_perk_ids: Vec<i64>,
}

#[derive(Clone, Serialize)]
struct DraftStatePayload {
    phase: String,
    timer_seconds_left: Option<i64>,
    local_player_cell_id: Option<i64>,
    local_player_assigned_role: Option<String>,
    local_player_effective_role: Option<String>,
    current_actor_cell_id: Option<i64>,
    current_action_type: Option<String>,
    my_team_picks: Vec<TeamSlotPayload>,
    enemy_team_picks: Vec<TeamSlotPayload>,
    my_team_declared_roles: Vec<String>,
    enemy_team_declared_roles: Vec<String>,
    my_bans: Vec<i64>,
    enemy_bans: Vec<i64>,
    session_status: String,
    patch: Option<String>,
    queue_type: Option<String>,
    is_local_players_turn: bool,
    local_player_runes: Option<RunePagePayload>,
}

#[derive(Clone, Serialize)]
struct InGamePlayer {
    champion_name: String,
    summoner_name: String,
    team: String,
    position: String,
    item_ids: Vec<i64>,
}

#[derive(Clone, Serialize)]
pub struct LcuDraftUpdatePayload {
    connected: bool,
    status: String,
    draft_state: Option<DraftStatePayload>,
    gameflow_phase: Option<String>,
    in_game_players: Option<Vec<InGamePlayer>>,
    local_player_name: Option<String>,
}

/// Shared LCU credentials so Tauri commands can reach the LCU.
pub struct LcuCredentialsState(pub Mutex<Option<LockfileCredentials>>);

#[derive(Clone)]
pub struct LockfileCredentials {
    port: u16,
    password: String,
}

struct CurrentActionPayload {
    actor_cell_id: Option<i64>,
    action_type: Option<String>,
}

// ---------------------------------------------------------------------------
// Tauri command: apply runes via LCU
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
pub struct ApplyRunesRequest {
    pub primary_style_id: i64,
    pub sub_style_id: i64,
    pub selected_perk_ids: Vec<i64>,
}

#[tauri::command]
pub async fn apply_runes(
    request: ApplyRunesRequest,
    credentials_state: State<'_, LcuCredentialsState>,
) -> std::result::Result<String, String> {
    let creds = {
        let guard = credentials_state.0.lock().map_err(|e| e.to_string())?;
        guard.clone().ok_or_else(|| "LCU not connected".to_string())?
    };

    let client = reqwest::Client::builder()
        .danger_accept_invalid_certs(true)
        .timeout(Duration::from_secs(5))
        .build()
        .map_err(|e| e.to_string())?;

    // First, get current rune page ID
    let current_page_url = format!(
        "https://127.0.0.1:{}/lol-perks/v1/currentpage",
        creds.port
    );
    let current_response = client
        .get(&current_page_url)
        .basic_auth("riot", Some(creds.password.as_str()))
        .send()
        .await
        .map_err(|e| format!("Failed to fetch current rune page: {e}"))?;

    if !current_response.status().is_success() {
        return Err(format!(
            "Failed to fetch current rune page ({})",
            current_response.status()
        ));
    }

    let current_page: Value = current_response
        .json()
        .await
        .map_err(|e| format!("Failed to parse current rune page: {e}"))?;

    let page_id = current_page
        .get("id")
        .and_then(Value::as_i64)
        .ok_or_else(|| "Could not find current rune page ID".to_string())?;

    // Build the update payload
    let update_payload = serde_json::json!({
        "selectedPerkIds": request.selected_perk_ids,
        "primaryStyleId": request.primary_style_id,
        "subStyleId": request.sub_style_id,
    });

    // PUT to update the current page
    let put_url = format!(
        "https://127.0.0.1:{}/lol-perks/v1/pages/{}",
        creds.port, page_id
    );
    let put_response = client
        .put(&put_url)
        .basic_auth("riot", Some(creds.password.as_str()))
        .json(&update_payload)
        .send()
        .await
        .map_err(|e| format!("Failed to apply runes: {e}"))?;

    if put_response.status().is_success() {
        Ok("Runes applied successfully".to_string())
    } else {
        let status = put_response.status();
        let body = put_response.text().await.unwrap_or_default();
        Err(format!("Failed to apply runes ({status}): {body}"))
    }
}

// ---------------------------------------------------------------------------
// Polling loop
// ---------------------------------------------------------------------------

pub async fn run_polling(app: AppHandle) {
    let mut previous_payload = String::new();
    let mut previous_gameflow = String::new();

    loop {
        let payload = match poll_lcu(&app).await {
            Ok(payload) => payload,
            Err(error) => LcuDraftUpdatePayload {
                connected: false,
                status: format!("LCU polling failed: {error}"),
                draft_state: None,
                gameflow_phase: None,
                in_game_players: None,
                local_player_name: None,
            },
        };

        // Emit game-phase-change when gameflow phase transitions
        let current_phase = payload.gameflow_phase.clone().unwrap_or_default();
        if current_phase != previous_gameflow {
            let _ = app.emit("game-phase-change", &current_phase);
            previous_gameflow = current_phase;
        }

        let fingerprint = serde_json::to_string(&payload).unwrap_or_default();
        if fingerprint != previous_payload {
            let _ = app.emit("lcu-draft-update", &payload);
            previous_payload = fingerprint;
        }

        tokio::time::sleep(Duration::from_secs(2)).await;
    }
}

async fn poll_lcu(app: &AppHandle) -> Result<LcuDraftUpdatePayload> {
    let Some(lockfile_path) = find_lockfile() else {
        // Clear stored credentials
        if let Some(state) = app.try_state::<LcuCredentialsState>() {
            if let Ok(mut guard) = state.0.lock() {
                *guard = None;
            }
        }
        return Ok(LcuDraftUpdatePayload {
            connected: false,
            status: "Waiting for League Client".to_string(),
            draft_state: None,
            gameflow_phase: None,
            in_game_players: None,
            local_player_name: None,
        });
    };

    let credentials = read_lockfile(lockfile_path).await?;

    // Store credentials for Tauri commands
    if let Some(state) = app.try_state::<LcuCredentialsState>() {
        if let Ok(mut guard) = state.0.lock() {
            *guard = Some(credentials.clone());
        }
    }

    let client = reqwest::Client::builder()
        .danger_accept_invalid_certs(true)
        .timeout(Duration::from_secs(3))
        .build()
        .context("failed to build the LCU HTTP client")?;

    // Fetch gameflow phase
    let gameflow_phase = fetch_optional_text(
        &client,
        credentials.port,
        credentials.password.as_str(),
        "/lol-gameflow/v1/gameflow-phase",
    )
    .await
    .ok()
    .map(|s| s.trim_matches('"').to_string());

    // Check if game is in progress (no champ select session available)
    let phase_str = gameflow_phase.as_deref().unwrap_or("");
    let in_game = matches!(phase_str, "InProgress" | "GameStart" | "WaitingForStats");

    let session_url = format!(
        "https://127.0.0.1:{}/lol-champ-select/v1/session",
        credentials.port
    );
    let session_response = client
        .get(&session_url)
        .basic_auth("riot", Some(credentials.password.as_str()))
        .send()
        .await
        .context("failed to query /lol-champ-select/v1/session")?;

    if session_response.status() == StatusCode::NOT_FOUND {
        let status_msg = if in_game {
            "Game in progress".to_string()
        } else {
            "League Client connected, waiting for champ select".to_string()
        };
        let (in_game_players, local_player_name) = if in_game {
            let players = fetch_live_game_players().await.ok();
            let name = fetch_active_player_name().await.ok();
            (players, name)
        } else {
            (None, None)
        };
        return Ok(LcuDraftUpdatePayload {
            connected: true,
            status: status_msg,
            draft_state: None,
            gameflow_phase,
            in_game_players,
            local_player_name,
        });
    }

    if !session_response.status().is_success() {
        return Ok(LcuDraftUpdatePayload {
            connected: true,
            status: format!("League Client connected ({})", session_response.status()),
            draft_state: None,
            gameflow_phase,
            in_game_players: None,
            local_player_name: None,
        });
    }

    let session_value: Value = session_response
        .json()
        .await
        .context("failed to deserialize LCU session JSON")?;

    // Fetch current rune page during champ select
    let rune_page = fetch_current_rune_page(&client, &credentials).await;

    Ok(LcuDraftUpdatePayload {
        connected: true,
        status: "Champ select detected".to_string(),
        draft_state: Some(build_draft_state(
            &session_value,
            gameflow_phase.as_deref(),
            rune_page,
        )),
        gameflow_phase,
        in_game_players: None,
        local_player_name: None,
    })
}

async fn fetch_current_rune_page(
    client: &reqwest::Client,
    credentials: &LockfileCredentials,
) -> Option<RunePagePayload> {
    let url = format!(
        "https://127.0.0.1:{}/lol-perks/v1/currentpage",
        credentials.port
    );
    let response = client
        .get(&url)
        .basic_auth("riot", Some(credentials.password.as_str()))
        .send()
        .await
        .ok()?;

    if !response.status().is_success() {
        return None;
    }

    let page: Value = response.json().await.ok()?;
    let selected_perk_ids = page
        .get("selectedPerkIds")
        .and_then(Value::as_array)
        .map(|arr| arr.iter().filter_map(Value::as_i64).collect::<Vec<_>>())
        .unwrap_or_default();

    let primary_style_id = page.get("primaryStyleId").and_then(Value::as_i64).unwrap_or(0);
    let sub_style_id = page.get("subStyleId").and_then(Value::as_i64).unwrap_or(0);

    // First perk is the keystone
    let keystone_id = selected_perk_ids.first().copied().unwrap_or(0);

    Some(RunePagePayload {
        keystone_id,
        primary_style_id,
        sub_style_id,
        selected_perk_ids,
    })
}

async fn fetch_optional_text(
    client: &reqwest::Client,
    port: u16,
    password: &str,
    path: &str,
) -> Result<String> {
    let response = client
        .get(format!("https://127.0.0.1:{port}{path}"))
        .basic_auth("riot", Some(password))
        .send()
        .await
        .with_context(|| format!("failed to query {path}"))?;

    if !response.status().is_success() {
        anyhow::bail!("{path} returned {}", response.status());
    }

    response.text().await.with_context(|| format!("failed to read {path} response"))
}

async fn fetch_live_game_players() -> Result<Vec<InGamePlayer>> {
    let client = reqwest::Client::builder()
        .danger_accept_invalid_certs(true)
        .timeout(Duration::from_secs(2))
        .build()?;

    let resp = client
        .get("https://127.0.0.1:2999/liveclientdata/playerlist")
        .send()
        .await?;

    let players: Vec<Value> = resp.json().await?;

    Ok(players
        .iter()
        .map(|p| InGamePlayer {
            champion_name: p["championName"]
                .as_str()
                .unwrap_or("")
                .to_string(),
            summoner_name: p["summonerName"]
                .as_str()
                .unwrap_or("")
                .to_string(),
            team: p["team"].as_str().unwrap_or("").to_string(),
            position: normalize_role(p["position"].as_str().unwrap_or(""))
                .unwrap_or_default(),
            item_ids: p["items"]
                .as_array()
                .map(|items| {
                    items
                        .iter()
                        .filter_map(|i| i["itemID"].as_i64())
                        .collect()
                })
                .unwrap_or_default(),
        })
        .collect())
}

async fn fetch_active_player_name() -> Result<String> {
    let client = reqwest::Client::builder()
        .danger_accept_invalid_certs(true)
        .timeout(Duration::from_secs(2))
        .build()?;

    let resp = client
        .get("https://127.0.0.1:2999/liveclientdata/activeplayer")
        .send()
        .await?;

    let player: Value = resp.json().await?;
    Ok(player["summonerName"]
        .as_str()
        .unwrap_or("")
        .to_string())
}

fn build_draft_state(
    session_value: &Value,
    gameflow_phase: Option<&str>,
    rune_page: Option<RunePagePayload>,
) -> DraftStatePayload {
    let local_player_cell_id = session_value
        .get("localPlayerCellId")
        .and_then(Value::as_i64);
    let current_action = find_current_action(session_value.get("actions"));
    let my_team_picks = build_team_slots(
        session_value.get("myTeam"),
        local_player_cell_id,
    );
    let enemy_team_picks = build_team_slots(session_value.get("theirTeam"), None);
    let local_player_slot = my_team_picks
        .iter()
        .find(|slot| Some(slot.cell_id) == local_player_cell_id);
    let timer_seconds_left = session_value
        .get("timer")
        .and_then(|timer| {
            timer
                .get("adjustedTimeLeftInPhase")
                .and_then(Value::as_i64)
                .or_else(|| timer.get("timeLeftInPhase").and_then(Value::as_i64))
        })
        .map(|value| if value > 1000 { value / 1000 } else { value });

    DraftStatePayload {
        phase: session_value
            .get("timer")
            .and_then(|timer| timer.get("phase"))
            .and_then(Value::as_str)
            .or(gameflow_phase)
            .unwrap_or("CHAMP_SELECT")
            .to_string(),
        timer_seconds_left,
        local_player_cell_id,
        local_player_assigned_role: local_player_slot.and_then(|slot| slot.assigned_role.clone()),
        local_player_effective_role: local_player_slot.and_then(|slot| slot.effective_role.clone()),
        current_actor_cell_id: current_action.actor_cell_id,
        current_action_type: current_action.action_type.clone(),
        my_team_declared_roles: my_team_picks
            .iter()
            .filter_map(|slot| slot.effective_role.clone())
            .collect(),
        enemy_team_declared_roles: enemy_team_picks
            .iter()
            .filter_map(|slot| slot.effective_role.clone())
            .collect(),
        my_team_picks,
        enemy_team_picks,
        my_bans: extract_bans(session_value.get("bans"), "myTeamBans"),
        enemy_bans: extract_bans(session_value.get("bans"), "theirTeamBans"),
        session_status: "active".to_string(),
        patch: None,
        queue_type: session_value
            .get("gameType")
            .and_then(Value::as_str)
            .map(ToString::to_string),
        is_local_players_turn: current_action.actor_cell_id == local_player_cell_id,
        local_player_runes: rune_page,
    }
}

fn build_team_slots(team_value: Option<&Value>, local_player_cell_id: Option<i64>) -> Vec<TeamSlotPayload> {
    let Some(team_array) = team_value.and_then(Value::as_array) else {
        return Vec::new();
    };

    team_array
        .iter()
        .map(|member| {
            let cell_id = member.get("cellId").and_then(Value::as_i64).unwrap_or_default();
            let assigned_role = member
                .get("assignedPosition")
                .and_then(Value::as_str)
                .and_then(normalize_role)
                .or_else(|| {
                    member
                        .get("selectedPosition")
                        .and_then(Value::as_str)
                        .and_then(normalize_role)
                });
            let effective_role = member
                .get("selectedPosition")
                .and_then(Value::as_str)
                .and_then(normalize_role)
                .or_else(|| assigned_role.clone());
            let champion_id = member
                .get("championId")
                .and_then(Value::as_i64)
                .filter(|value| *value > 0)
                .or_else(|| {
                    member
                        .get("championPickIntent")
                        .and_then(Value::as_i64)
                        .filter(|value| *value > 0)
                })
                .unwrap_or_default();

            TeamSlotPayload {
                cell_id,
                champion_id,
                champion_name: None,
                champion_image_url: None,
                assigned_role: assigned_role.clone(),
                effective_role: effective_role.clone(),
                role_source: if effective_role.is_some() {
                    "lcu".to_string()
                } else {
                    "unknown".to_string()
                },
                role_confidence: if effective_role.is_some() { 1.0 } else { 0.0 },
                role_candidates: effective_role
                    .into_iter()
                    .map(|role| RoleCandidatePayload {
                        role,
                        confidence: 1.0,
                    })
                    .collect(),
                summoner_id: member.get("summonerId").and_then(Value::as_i64),
                is_local_player: Some(cell_id) == local_player_cell_id,
            }
        })
        .collect()
}

fn extract_bans(bans_value: Option<&Value>, field_name: &str) -> Vec<i64> {
    bans_value
        .and_then(|value| value.get(field_name))
        .and_then(Value::as_array)
        .map(|items| {
            items.iter()
                .filter_map(Value::as_i64)
                .map(|value| if value > 0 { value } else { 0 })
                .collect()
        })
        .unwrap_or_else(|| vec![0, 0, 0, 0, 0])
}

fn find_current_action(actions_value: Option<&Value>) -> CurrentActionPayload {
    let Some(action_groups) = actions_value.and_then(Value::as_array) else {
        return CurrentActionPayload {
            actor_cell_id: None,
            action_type: None,
        };
    };

    for group in action_groups {
        let Some(actions) = group.as_array() else {
            continue;
        };

        for action in actions {
            if action
                .get("isInProgress")
                .and_then(Value::as_bool)
                .unwrap_or(false)
            {
                return CurrentActionPayload {
                    actor_cell_id: action.get("actorCellId").and_then(Value::as_i64),
                    action_type: action
                        .get("type")
                        .and_then(Value::as_str)
                        .map(|value| value.to_lowercase()),
                };
            }
        }
    }

    CurrentActionPayload {
        actor_cell_id: None,
        action_type: None,
    }
}

fn normalize_role(value: &str) -> Option<String> {
    match value.to_ascii_lowercase().as_str() {
        "top" => Some("top".to_string()),
        "jungle" => Some("jungle".to_string()),
        "middle" | "mid" => Some("middle".to_string()),
        "bottom" | "bot" | "adc" => Some("bottom".to_string()),
        "utility" | "support" => Some("support".to_string()),
        _ => None,
    }
}

async fn read_lockfile(path: PathBuf) -> Result<LockfileCredentials> {
    let content = tokio::fs::read_to_string(&path)
        .await
        .with_context(|| format!("failed to read lockfile at {}", path.display()))?;
    let mut parts = content.trim().split(':');
    let _process = parts.next();
    let _pid = parts.next();
    let port = parts
        .next()
        .context("lockfile is missing the LCU port")?
        .parse::<u16>()
        .context("lockfile contains an invalid LCU port")?;
    let password = parts
        .next()
        .context("lockfile is missing the auth token")?
        .to_string();

    Ok(LockfileCredentials { port, password })
}

fn find_lockfile() -> Option<PathBuf> {
    let mut candidates = vec![
        PathBuf::from(r"C:\Riot Games\League of Legends\lockfile"),
        PathBuf::from(r"D:\Riot Games\League of Legends\lockfile"),
        PathBuf::from(r"E:\Riot Games\League of Legends\lockfile"),
        PathBuf::from(r"C:\ProgramData\Riot Games\Metadata\league_of_legends.live\league_of_legends.live.lockfile"),
    ];

    #[cfg(target_os = "windows")]
    {
        candidates.extend(registry_install_roots().into_iter().map(|path| path.join("lockfile")));
    }

    candidates.into_iter().find(|path| path.exists())
}

#[cfg(target_os = "windows")]
fn registry_install_roots() -> Vec<PathBuf> {
    use winreg::enums::HKEY_LOCAL_MACHINE;
    use winreg::RegKey;

    let mut roots = Vec::new();
    let hklm = RegKey::predef(HKEY_LOCAL_MACHINE);
    let keys = [
        r"SOFTWARE\WOW6432Node\Riot Games, Inc\League of Legends",
        r"SOFTWARE\Riot Games, Inc\League of Legends",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Riot Game league_of_legends.live",
    ];
    let value_names = ["Location", "InstallLocation", "Path"];

    for key_path in keys {
        if let Ok(key) = hklm.open_subkey(key_path) {
            for value_name in value_names {
                if let Ok(value) = key.get_value::<String, _>(value_name) {
                    roots.push(PathBuf::from(value));
                }
            }
        }
    }

    roots
}
