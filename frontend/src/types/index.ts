export type RoleSource = "lcu" | "manual" | "inferred" | "unknown";

export type RoleCandidate = {
  role: string;
  confidence: number;
};

export type TeamSlot = {
  cell_id: number;
  champion_id: number;
  champion_name?: string | null;
  champion_image_url?: string | null;
  assigned_role?: string | null;
  effective_role?: string | null;
  role_source: RoleSource;
  role_confidence: number;
  role_candidates: RoleCandidate[];
  summoner_id?: number | null;
  is_local_player: boolean;
};

export type DraftState = {
  phase: string;
  timer_seconds_left?: number | null;
  local_player_cell_id?: number | null;
  local_player_assigned_role?: string | null;
  local_player_effective_role?: string | null;
  current_actor_cell_id?: number | null;
  current_action_type?: string | null;
  my_team_picks: TeamSlot[];
  enemy_team_picks: TeamSlot[];
  my_team_declared_roles: string[];
  enemy_team_declared_roles: string[];
  my_bans: number[];
  enemy_bans: number[];
  session_status: string;
  patch?: string | null;
  queue_type?: string | null;
  is_local_players_turn: boolean;
};

export type RecommendationItem = {
  champion_id: number;
  champion_name: string;
  suggested_role: string;
  total_score: number;
  display_band: "elite" | "strong" | "situational" | "risky";
  counter_score: number;
  synergy_score: number;
  tier_score: number;
  role_fit_score: number;
  matchup_coverage: number;
  synergy_coverage: number;
  evidence_score: number;
  role_certainty: number;
  sample_confidence: number;
  thin_evidence: boolean;
  confidence: number;
  reasons: string[];
  explanation: RecommendationExplanation;
};

export type RecommendationBundle = {
  picks: RecommendationItem[];
  bans: RecommendationItem[];
  region?: string | null;
  rank_tier?: string | null;
  patch?: string | null;
  active_patch_generation?: string | null;
  exact_data_available: boolean;
  patch_trusted: boolean;
  scope_complete: boolean;
  scope_ready: boolean;
  scope_last_synced_at?: string | null;
  scope_freshness: string;
  fallback_used_recently: boolean;
  warnings: string[];
  generated_at: string;
};

export type RecommendationScoreComponent = {
  key: string;
  label: string;
  value: number;
  weight: number;
  contribution: number;
  note?: string | null;
};

export type RecommendationRelationDetail = {
  kind: "counter" | "synergy" | "threat" | "enemy_synergy";
  champion_id: number;
  champion_name: string;
  role?: string | null;
  normalized_score: number;
  sample_confidence: number;
  signed_edge: number;
  shrinkage_weight: number;
  net_contribution: number;
  match_role_source: RoleSource;
  metric_label: string;
  metric_value: number;
  win_rate: number;
  games: number;
  summary: string;
};

export type RecommendationExplanation = {
  summary: string;
  scenario_summary: string;
  scoring: RecommendationScoreComponent[];
  counters: RecommendationRelationDetail[];
  synergies: RecommendationRelationDetail[];
  penalties: string[];
};

export type StorageStatus = {
  champion_count: number;
  tier_stats_count: number;
  matchups_count: number;
  synergies_count: number;
  latest_patch?: string | null;
  data_patches: string[];
  historical_rows: number;
  latest_data_fetch_at?: string | null;
  latest_run?: Record<string, unknown> | null;
  active_patch_generation?: {
    patch: string;
    scope_total: number;
    ready_scopes: number;
    partial_scopes: number;
    stale_scopes: number;
    failed_scopes: number;
    ready_at?: string | null;
  } | null;
};

export type UserSettings = {
  region_mode: "auto" | "manual";
  rank_mode: "auto" | "manual";
  role_mode: "auto" | "manual";
  region_override: string;
  rank_override: string;
  role_override: string;
  auto_refresh: boolean;
  top_n: number;
  weights: {
    counter: number;
    synergy: number;
    tier: number;
    role_fit: number;
  };
};

export type StatusPayload = {
  lcu_connected: boolean;
  bridge_connected?: boolean;
  source_device_id?: string | null;
  auto_region?: string | null;
  auto_rank_tier?: string | null;
  auto_role?: string | null;
  client_patch?: string | null;
  effective_region?: string | null;
  effective_rank_tier?: string | null;
  effective_role?: string | null;
  exact_data_available: boolean;
  patch_trusted: boolean;
  scope_complete: boolean;
  scope_ready?: boolean;
  scope_last_synced_at?: string | null;
  scope_freshness?: string;
  fallback_used_recently?: boolean;
  active_patch_generation?: string | null;
  recommendation_warnings: string[];
  draft_phase: string;
  latest_patch?: string | null;
  storage: StorageStatus;
};

export type DraftSocketPayload = {
  type: "state";
  draft_state: DraftState;
  recommendations: RecommendationBundle;
  auto_region?: string | null;
  auto_rank_tier?: string | null;
  auto_role?: string | null;
  lcu_connected: boolean;
  bridge_connected?: boolean;
  source_device_id?: string | null;
};

export type DraftRoleOverridePayload = {
  overrides: Array<{
    team: "ally" | "enemy";
    cell_id: number;
    role: string | null;
  }>;
};

export type DraftRecommendationPreviewResponse = {
  filters: {
    region: string;
    rank_tier: string;
    role?: string | null;
  };
  recommendations: RecommendationBundle;
};

export type ScopeHealthItem = {
  region: string;
  rank_tier: string;
  role: string;
  status: string;
  empty_scope: boolean;
  last_success_at?: string | null;
  last_tier_refresh_at?: string | null;
  last_build_refresh_at?: string | null;
  next_tier_due_at?: string | null;
  next_build_due_at?: string | null;
  tier_rows: number;
  matchup_rows: number;
  synergy_rows: number;
  http_ok: boolean;
  fallback_used: boolean;
  fallback_used_recently: boolean;
  fallback_failures: number;
  last_error: string;
};

export type RefreshJobItem = {
  id: number;
  region: string;
  rank_tier: string;
  role: string;
  patch: string;
  mode: string;
  status: string;
  priority: number;
  fallback_used: boolean;
  notes: string;
  scheduled_at: string;
  started_at?: string | null;
  finished_at?: string | null;
};

export type ParserEventItem = {
  id: number;
  region: string;
  rank_tier: string;
  role: string;
  patch: string;
  champion_id?: number | null;
  stage: string;
  event_type: string;
  severity: string;
  used_fallback: boolean;
  message: string;
  created_at: string;
};

export type AdminOverviewPayload = {
  storage: StorageStatus;
  active_generation?: {
    patch: string;
    scope_total: number;
    ready_scopes: number;
    partial_scopes: number;
    stale_scopes: number;
    failed_scopes: number;
    ready_at?: string | null;
  } | null;
  bridge_sessions: Array<{
    device_id: string;
    label: string;
    connected: boolean;
    last_seen_at?: string | null;
    auto_region?: string | null;
    auto_rank_tier?: string | null;
    client_patch?: string | null;
    queue_type?: string | null;
  }>;
  parser_health: {
    window_hours: number;
    total_events: number;
    fallback_events: number;
    error_events: number;
    recent: ParserEventItem[];
  };
};
