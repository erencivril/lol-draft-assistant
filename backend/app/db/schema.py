SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS champions (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    image_url TEXT NOT NULL,
    roles_json TEXT NOT NULL,
    patch TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tier_stats (
    champion_id INTEGER NOT NULL,
    region TEXT NOT NULL,
    rank_tier TEXT NOT NULL,
    role TEXT NOT NULL,
    tier_rank INTEGER NOT NULL DEFAULT 0,
    win_rate REAL NOT NULL,
    pick_rate REAL NOT NULL,
    ban_rate REAL NOT NULL,
    tier_grade TEXT NOT NULL,
    pbi REAL NOT NULL DEFAULT 0,
    games INTEGER NOT NULL,
    scope_generation_id TEXT,
    patch TEXT NOT NULL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (champion_id, region, rank_tier, role, patch)
);

CREATE TABLE IF NOT EXISTS matchups (
    champion_id INTEGER NOT NULL,
    opponent_id INTEGER NOT NULL,
    region TEXT NOT NULL,
    rank_tier TEXT NOT NULL,
    role TEXT NOT NULL,
    opponent_role TEXT NOT NULL,
    win_rate REAL NOT NULL,
    delta1 REAL NOT NULL,
    delta2 REAL NOT NULL,
    games INTEGER NOT NULL,
    patch TEXT NOT NULL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (champion_id, opponent_id, region, rank_tier, role, opponent_role, patch)
);

CREATE TABLE IF NOT EXISTS synergies (
    champion_id INTEGER NOT NULL,
    teammate_id INTEGER NOT NULL,
    region TEXT NOT NULL,
    rank_tier TEXT NOT NULL,
    role TEXT NOT NULL,
    teammate_role TEXT NOT NULL,
    duo_win_rate REAL NOT NULL,
    synergy_delta REAL NOT NULL,
    normalised_delta REAL NOT NULL DEFAULT 0,
    games INTEGER NOT NULL,
    patch TEXT NOT NULL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (champion_id, teammate_id, region, rank_tier, role, teammate_role, patch)
);

CREATE TABLE IF NOT EXISTS provider_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_name TEXT NOT NULL,
    region TEXT NOT NULL,
    rank_tier TEXT NOT NULL,
    role TEXT NOT NULL,
    patch TEXT NOT NULL,
    status TEXT NOT NULL,
    pages_total INTEGER NOT NULL DEFAULT 0,
    pages_done INTEGER NOT NULL DEFAULT 0,
    retries INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS patch_generations (
    patch TEXT PRIMARY KEY,
    is_active INTEGER NOT NULL DEFAULT 0,
    detected_at TEXT NOT NULL,
    ready_at TEXT,
    scope_total INTEGER NOT NULL DEFAULT 0,
    ready_scopes INTEGER NOT NULL DEFAULT 0,
    partial_scopes INTEGER NOT NULL DEFAULT 0,
    stale_scopes INTEGER NOT NULL DEFAULT 0,
    failed_scopes INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS scope_status (
    region TEXT NOT NULL,
    rank_tier TEXT NOT NULL,
    role TEXT NOT NULL,
    patch TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'stale',
    empty_scope INTEGER NOT NULL DEFAULT 0,
    last_success_at TEXT,
    last_error TEXT NOT NULL DEFAULT '',
    last_tier_refresh_at TEXT,
    last_build_refresh_at TEXT,
    next_tier_due_at TEXT,
    next_build_due_at TEXT,
    tier_rows INTEGER NOT NULL DEFAULT 0,
    matchup_rows INTEGER NOT NULL DEFAULT 0,
    synergy_rows INTEGER NOT NULL DEFAULT 0,
    http_ok INTEGER NOT NULL DEFAULT 1,
    fallback_used INTEGER NOT NULL DEFAULT 0,
    fallback_used_recently INTEGER NOT NULL DEFAULT 0,
    fallback_failures INTEGER NOT NULL DEFAULT 0,
    tier_signature TEXT NOT NULL DEFAULT '',
    build_signature TEXT NOT NULL DEFAULT '',
    patch_generation_id TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (region, rank_tier, role, patch)
);

CREATE TABLE IF NOT EXISTS scope_refresh_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    region TEXT NOT NULL,
    rank_tier TEXT NOT NULL,
    role TEXT NOT NULL,
    patch TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    fallback_used INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    scheduled_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS parser_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    region TEXT NOT NULL,
    rank_tier TEXT NOT NULL,
    role TEXT NOT NULL,
    patch TEXT NOT NULL,
    champion_id INTEGER,
    stage TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    used_fallback INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bridge_sessions (
    device_id TEXT PRIMARY KEY,
    label TEXT NOT NULL DEFAULT '',
    token_hash TEXT NOT NULL DEFAULT '',
    connected INTEGER NOT NULL DEFAULT 0,
    last_seen_at TEXT,
    auto_region TEXT,
    auto_rank_tier TEXT,
    client_patch TEXT,
    queue_type TEXT,
    source TEXT NOT NULL DEFAULT 'bridge',
    draft_state_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tier_stats_lookup ON tier_stats (region, rank_tier, role, patch, champion_id);
CREATE INDEX IF NOT EXISTS idx_matchups_lookup ON matchups (region, rank_tier, role, patch, champion_id, opponent_id);
CREATE INDEX IF NOT EXISTS idx_synergies_lookup ON synergies (region, rank_tier, role, patch, champion_id, teammate_id);
CREATE INDEX IF NOT EXISTS idx_provider_runs_status ON provider_runs (status, region, rank_tier, role, patch);
CREATE INDEX IF NOT EXISTS idx_scope_status_status ON scope_status (patch, status, next_tier_due_at, next_build_due_at);
CREATE INDEX IF NOT EXISTS idx_scope_refresh_jobs_status ON scope_refresh_jobs (status, scheduled_at, patch);
CREATE INDEX IF NOT EXISTS idx_parser_events_created ON parser_events (created_at, severity, stage);
CREATE INDEX IF NOT EXISTS idx_bridge_sessions_seen ON bridge_sessions (connected, last_seen_at);
"""
