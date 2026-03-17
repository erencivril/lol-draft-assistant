import { startTransition, useEffect, useMemo, useRef, useState } from "react";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import {
  fetchChampions,
  fetchItems,
  fetchRunes,
  fetchStatus,
  getApiBaseUrl,
  recommendBuild,
  recommendDraft,
  recommendRunes,
  type ChampionCatalogItem,
  type RecommendPayload,
} from "./api/client";
import { AnalysisFiltersPanel, type AnalysisFilters } from "./components/AnalysisFiltersPanel";
import { ConnectionStatus, type LcuConnectionState } from "./components/ConnectionStatus";
import { DraftBoard } from "./components/DraftBoard";
import { PhaseIndicator } from "./components/PhaseIndicator";
import { RecommendationPanel } from "./components/RecommendationPanel";
import { inferDraftRoles } from "./lib/draftRoleInference";
import { buildFullRunePage } from "./lib/runePageBuilder";
import { Toast } from "./components/Toast";
import { roleOptions } from "./constants/filters";
import type {
  BuildRecommendResponse,
  DraftState,
  ItemDefinition,
  RecommendationBundle,
  RuneDefinition,
  RunePagePayload,
  RuneRecommendResponse,
  StatusPayload,
  TeamSlot,
} from "./types";

type ToastState = {
  text: string;
  tone: "success" | "error";
};

type LcuDraftUpdatePayload = {
  connected: boolean;
  status?: string;
  draft_state?: (DraftState & { local_player_runes?: RunePagePayload | null }) | null;
  gameflow_phase?: string | null;
};

type SlotOverride = {
  championId?: number;
  clearRole?: boolean;
  role?: string | null;
};

const FILTERS_STORAGE_KEY = "ourtbx.filters";
const roleOrder = roleOptions.map((option) => option.value);

const emptyRecommendations: RecommendationBundle = {
  picks: [],
  bans: [],
  active_patch_generation: null,
  exact_data_available: false,
  patch_trusted: true,
  scope_complete: true,
  scope_ready: false,
  scope_last_synced_at: null,
  scope_freshness: "unknown",
  fallback_used_recently: false,
  warnings: [],
  generated_at: new Date(0).toISOString(),
};

function defaultFilters(): AnalysisFilters {
  return {
    region: "TR",
    rank_tier: "emerald",
  };
}

function loadStoredFilters(): AnalysisFilters {
  if (typeof window === "undefined") {
    return defaultFilters();
  }

  try {
    const raw = window.localStorage.getItem(FILTERS_STORAGE_KEY);
    if (!raw) {
      return defaultFilters();
    }
    const parsed = JSON.parse(raw) as Partial<AnalysisFilters>;
    if (!parsed.region || !parsed.rank_tier) {
      return defaultFilters();
    }
    return {
      region: parsed.region,
      rank_tier: parsed.rank_tier,
    };
  } catch {
    return defaultFilters();
  }
}

function createBaseSlot(
  cellId: number,
  role: string | null,
  isLocalPlayer = false,
): TeamSlot {
  const normalizedRole = role && roleOrder.includes(role) ? role : null;

  return {
    cell_id: cellId,
    champion_id: 0,
    champion_name: null,
    champion_image_url: null,
    assigned_role: normalizedRole,
    effective_role: normalizedRole,
    role_source: normalizedRole ? "manual" : "unknown",
    role_confidence: normalizedRole ? 1 : 0,
    role_candidates: normalizedRole ? [{ role: normalizedRole, confidence: 1 }] : [],
    is_local_player: isLocalPlayer,
  };
}

function createManualDraftState(localRole: string): DraftState {
  const safeRole = roleOrder.includes(localRole) ? localRole : "middle";
  const localPlayerCellId = roleOrder.indexOf(safeRole) + 1;
  return {
    phase: "MANUAL",
    timer_seconds_left: null,
    local_player_cell_id: localPlayerCellId,
    local_player_assigned_role: safeRole,
    local_player_effective_role: safeRole,
    current_actor_cell_id: localPlayerCellId,
    current_action_type: "pick",
    my_team_picks: roleOrder.map((role, index) => createBaseSlot(index + 1, role, role === safeRole)),
    enemy_team_picks: roleOrder.map((_, index) => createBaseSlot(index + 6, null)),
    my_team_declared_roles: [safeRole],
    enemy_team_declared_roles: [],
    my_bans: [0, 0, 0, 0, 0],
    enemy_bans: [0, 0, 0, 0, 0],
    session_status: "manual",
    patch: null,
    queue_type: null,
    is_local_players_turn: true,
  };
}

function createRoleSnapshot(role: string | null): Pick<TeamSlot, "assigned_role" | "effective_role" | "role_source" | "role_confidence" | "role_candidates"> {
  if (!role) {
    return {
      assigned_role: null,
      effective_role: null,
      role_source: "unknown",
      role_confidence: 0,
      role_candidates: [],
    };
  }

  return {
    assigned_role: role,
    effective_role: role,
    role_source: "manual",
    role_confidence: 1,
    role_candidates: [{ role, confidence: 1 }],
  };
}

function formatRoleName(role: string): string {
  return role.charAt(0).toUpperCase() + role.slice(1);
}

function enemySlotLabel(cellId: number): string {
  return `Enemy ${Math.max(1, cellId - 5)}`;
}

function findEnemyRoleOwner(draftState: DraftState, cellId: number, role: string | null): TeamSlot | undefined {
  if (!role) {
    return undefined;
  }

  return draftState.enemy_team_picks.find(
    (slot) => slot.cell_id !== cellId && (slot.effective_role ?? slot.assigned_role ?? null) === role
  );
}

export function resolveEnemyRoleSelection(
  draftState: DraftState,
  cellId: number,
  role: string
): {
  releasedCellId: number | null;
  toastText: string | null;
} {
  const nextRole = role || null;
  const previousOwner = findEnemyRoleOwner(draftState, cellId, nextRole);

  if (!previousOwner || !nextRole) {
    return {
      releasedCellId: null,
      toastText: null,
    };
  }

  return {
    releasedCellId: previousOwner.cell_id,
    toastText: `${enemySlotLabel(cellId)} took ${formatRoleName(nextRole)}. ${enemySlotLabel(previousOwner.cell_id)} was re-inferred.`,
  };
}

function isTauriRuntime(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return Boolean((window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__);
}

function hydrateDraftState(
  draftState: DraftState,
  championLookup: Map<number, ChampionCatalogItem>
): DraftState {
  const hydrateSlot = (slot: TeamSlot) => {
    const champion = slot.champion_id > 0 ? championLookup.get(slot.champion_id) : undefined;
    return {
      ...slot,
      champion_name: champion?.name ?? (slot.champion_id > 0 ? slot.champion_name : null),
      champion_image_url: champion?.image_url ?? (slot.champion_id > 0 ? slot.champion_image_url : null),
    };
  };

  return {
    ...draftState,
    my_team_picks: draftState.my_team_picks.map(hydrateSlot),
    enemy_team_picks: draftState.enemy_team_picks.map(hydrateSlot),
  };
}

function findLocalPlayerSlot(draftState: DraftState): TeamSlot | undefined {
  return (
    draftState.my_team_picks.find((slot) => slot.is_local_player) ??
    draftState.my_team_picks.find((slot) => slot.cell_id === draftState.local_player_cell_id)
  );
}

function findSlotByCellId(slots: TeamSlot[], cellId: number | null | undefined): TeamSlot | undefined {
  if (cellId == null) {
    return undefined;
  }
  return slots.find((slot) => slot.cell_id === cellId);
}

function resolveRecommendTargetCellId(draftState: DraftState, targetCellId: number | null): number {
  const requestedTarget = findSlotByCellId(draftState.my_team_picks, targetCellId);
  if (requestedTarget) {
    return requestedTarget.cell_id;
  }
  const localSlot = findLocalPlayerSlot(draftState);
  if (localSlot) {
    return localSlot.cell_id;
  }
  return draftState.my_team_picks[0]?.cell_id ?? 0;
}

function applyLocalRoleOverride(draftState: DraftState, localRoleOverride: string | null): DraftState {
  if (!localRoleOverride) {
    return draftState;
  }

  const localSlot = findLocalPlayerSlot(draftState);
  if (!localSlot) {
    return draftState;
  }

  const roleCandidates = [{ role: localRoleOverride, confidence: 1 }];

  return {
    ...draftState,
    local_player_assigned_role: localRoleOverride,
    local_player_effective_role: localRoleOverride,
    my_team_declared_roles: draftState.my_team_picks.map((slot) =>
      slot.cell_id === localSlot.cell_id
        ? localRoleOverride
        : slot.effective_role ?? slot.assigned_role ?? ""
    ),
    my_team_picks: draftState.my_team_picks.map((slot) =>
      slot.cell_id === localSlot.cell_id
        ? {
            ...slot,
            assigned_role: localRoleOverride,
            effective_role: localRoleOverride,
            role_source: "manual",
            role_confidence: 1,
            role_candidates: roleCandidates,
          }
        : slot
    ),
  };
}

function applyDraftOverrides(
  draftState: DraftState,
  slotOverrides: Record<string, SlotOverride>,
  banOverrides: Record<string, number>
): DraftState {
  const applySlotOverride = (team: "ally" | "enemy", slot: TeamSlot): TeamSlot => {
    const override = slotOverrides[`${team}:${slot.cell_id}`];
    if (!override) {
      return slot;
    }
    const nextRole =
      override.role === undefined
        ? override.clearRole
          ? null
          : slot.effective_role ?? slot.assigned_role ?? null
        : override.role;
    return {
      ...slot,
      champion_id: override.championId ?? slot.champion_id,
      champion_name: override.championId === 0 ? null : slot.champion_name,
      champion_image_url: override.championId === 0 ? null : slot.champion_image_url,
      assigned_role: nextRole,
      effective_role: nextRole,
      role_source: nextRole ? "manual" : "unknown",
      role_confidence: nextRole ? 1 : 0,
      role_candidates: nextRole ? [{ role: nextRole, confidence: 1 }] : [],
    };
  };

  const applyBanOverride = (team: "ally" | "enemy", sourceBans: number[]) => {
    const nextBans = [...sourceBans];
    while (nextBans.length < 5) {
      nextBans.push(0);
    }
    for (let index = 0; index < nextBans.length; index += 1) {
      const override = banOverrides[`${team}:${index}`];
      if (override !== undefined) {
        nextBans[index] = override;
      }
    }
    return nextBans;
  };

  return {
    ...draftState,
    my_team_picks: draftState.my_team_picks.map((slot) => applySlotOverride("ally", slot)),
    enemy_team_picks: draftState.enemy_team_picks.map((slot) => applySlotOverride("enemy", slot)),
    my_bans: applyBanOverride("ally", draftState.my_bans),
    enemy_bans: applyBanOverride("enemy", draftState.enemy_bans),
  };
}

export function buildRecommendPayload(
  filters: AnalysisFilters,
  draftState: DraftState,
  targetCellId: number
): RecommendPayload {
  const targetSlot = findSlotByCellId(draftState.my_team_picks, targetCellId);
  const targetRole =
    targetSlot?.effective_role ??
    targetSlot?.assigned_role ??
    draftState.local_player_effective_role ??
    draftState.local_player_assigned_role ??
    "middle";

  return {
    region: filters.region,
    rank_tier: filters.rank_tier,
    target_cell_id: targetCellId,
    ally_slots: draftState.my_team_picks.map((slot) => ({
      cell_id: slot.cell_id,
      champion_id: slot.champion_id,
      role: slot.effective_role ?? slot.assigned_role ?? null,
      is_local_player: slot.is_local_player,
    })),
    enemy_slots: draftState.enemy_team_picks.map((slot) => ({
      cell_id: slot.cell_id,
      champion_id: slot.champion_id,
      role: slot.effective_role ?? slot.assigned_role ?? null,
    })),
    bans: [...draftState.my_bans, ...draftState.enemy_bans].filter((championId) => championId > 0),
  };
}

function localOverrideApplied(
  slotOverrides: Record<string, SlotOverride>,
  banOverrides: Record<string, number>,
  localRoleOverride: string | null
): boolean {
  return Object.keys(slotOverrides).length > 0 || Object.keys(banOverrides).length > 0 || localRoleOverride != null;
}

export default function App() {
  const initialFilters = loadStoredFilters();
  const enemyRoleLockOrderRef = useRef(0);
  const [filters, setFilters] = useState<AnalysisFilters>(initialFilters);
  const [status, setStatus] = useState<StatusPayload | null>(null);
  const [champions, setChampions] = useState<ChampionCatalogItem[]>([]);
  const [manualDraftState, setManualDraftState] = useState<DraftState>(() => createManualDraftState("middle"));
  const [lcuDraftState, setLcuDraftState] = useState<DraftState | null>(null);
  const [targetCellId, setTargetCellId] = useState<number | null>(null);
  const [localRoleOverride, setLocalRoleOverride] = useState<string | null>(null);
  const [enemyRoleLockOrder, setEnemyRoleLockOrder] = useState<Record<number, number>>({});
  const [slotOverrides, setSlotOverrides] = useState<Record<string, SlotOverride>>({});
  const [banOverrides, setBanOverrides] = useState<Record<string, number>>({});
  const [recommendations, setRecommendations] = useState<RecommendationBundle>(emptyRecommendations);
  const [loading, setLoading] = useState(true);
  const [recommendLoading, setRecommendLoading] = useState(false);
  const [toastMessage, setToastMessage] = useState<ToastState | null>(null);
  const [lcuState, setLcuState] = useState<LcuConnectionState>({
    connected: false,
    status: isTauriRuntime() ? "Waiting for League Client" : "Tauri runtime not detected",
    lastUpdatedAt: null,
  });
  const [gameflowPhase, setGameflowPhase] = useState<string>("");
  const [playerRunes, setPlayerRunes] = useState<RunePagePayload | null>(null);
  const [runeRecommendations, setRuneRecommendations] = useState<RuneRecommendResponse | null>(null);
  const [buildRecommendation, setBuildRecommendation] = useState<BuildRecommendResponse | null>(null);
  const [runeLoading, setRuneLoading] = useState(false);
  const [buildLoading, setBuildLoading] = useState(false);
  const [runeLookup, setRuneLookup] = useState<Record<string, RuneDefinition>>({});
  const [itemLookup, setItemLookup] = useState<Record<string, ItemDefinition>>({});

  const apiBaseUrl = getApiBaseUrl();
  const championLookup = useMemo(
    () => new Map(champions.map((champion) => [champion.champion_id, champion])),
    [champions]
  );

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(FILTERS_STORAGE_KEY, JSON.stringify(filters));
  }, [filters]);

  useEffect(() => {
    let cancelled = false;

    const loadBootstrap = async () => {
      try {
        const [nextStatus, nextChampions, nextItems, nextRunes] = await Promise.all([
          fetchStatus(),
          fetchChampions(),
          fetchItems().catch(() => ({} as Record<string, ItemDefinition>)),
          fetchRunes().catch(() => ({} as Record<string, RuneDefinition>)),
        ]);
        if (cancelled) {
          return;
        }
        startTransition(() => {
          setStatus(nextStatus);
          setChampions(nextChampions);
          setItemLookup(nextItems);
          setRuneLookup(nextRunes);
          setLoading(false);
        });
      } catch {
        if (!cancelled) {
          setToastMessage({ text: "Failed to reach the Hetzner backend.", tone: "error" });
          setLoading(false);
        }
      }
    };

    const refreshStatus = async () => {
      try {
        const nextStatus = await fetchStatus();
        if (!cancelled) {
          setStatus(nextStatus);
        }
      } catch {
        if (!cancelled) {
          setStatus(null);
        }
      }
    };

    void loadBootstrap();
    const intervalId = window.setInterval(() => {
      void refreshStatus();
    }, 30000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, []);

  useEffect(() => {
    if (!isTauriRuntime()) {
      return;
    }

    let active = true;
    let dispose: UnlistenFn | null = null;

    const attachListener = async () => {
      try {
        dispose = await listen<LcuDraftUpdatePayload>("lcu-draft-update", (event) => {
          if (!active) {
            return;
          }
          const rawDraft = event.payload.connected && event.payload.draft_state ? event.payload.draft_state : null;
          const nextPlayerRunes = rawDraft?.local_player_runes ?? null;
          const nextDraftState = rawDraft;
          const gamePhase = event.payload.gameflow_phase ?? "";
          const isInGame = ["InProgress", "GameStart", "WaitingForStats"].includes(gamePhase);
          startTransition(() => {
            setLcuState({
              connected: event.payload.connected,
              status:
                event.payload.status ??
                (event.payload.connected ? "Champ select session detected" : "Waiting for League Client"),
              lastUpdatedAt: new Date().toISOString(),
            });
            // Preserve last known draft state during game (LCU champ-select session unavailable)
            if (nextDraftState !== null || !isInGame) {
              setLcuDraftState(nextDraftState);
            }
            setGameflowPhase(gamePhase);
            if (nextPlayerRunes) {
              setPlayerRunes(nextPlayerRunes);
            }
          });
        });
      } catch (error) {
        console.error("Failed to attach Tauri event listener", error);
        const message = error instanceof Error ? error.message : String(error);
        if (active) {
          setLcuState({
            connected: false,
            status: message ? `Tauri event bridge unavailable: ${message}` : "Tauri event bridge unavailable",
            lastUpdatedAt: null,
          });
        }
      }
    };

    void attachListener();

    return () => {
      active = false;
      if (dispose) {
        void dispose();
      }
    };
  }, []);

  const effectiveDraftState = useMemo(() => {
    const baseDraft =
      lcuState.connected && lcuDraftState
        ? applyDraftOverrides(lcuDraftState, slotOverrides, banOverrides)
        : manualDraftState;
    const draftWithLocalRole = applyLocalRoleOverride(baseDraft, localRoleOverride);
    const inferredDraft = inferDraftRoles(draftWithLocalRole, championLookup, {
      enemyManualLockOrderByCellId: enemyRoleLockOrder,
    });
    const result = hydrateDraftState(inferredDraft, championLookup);
    console.debug("[draft-inference]", {
      championLookupSize: championLookup.size,
      enemyRoles: result.enemy_team_picks.map((s) => ({
        cellId: s.cell_id,
        champId: s.champion_id,
        role: s.effective_role,
        source: s.role_source,
      })),
    });
    return result;
  }, [
    banOverrides,
    championLookup,
    enemyRoleLockOrder,
    lcuDraftState,
    lcuState.connected,
    localRoleOverride,
    manualDraftState,
    slotOverrides,
  ]);

  const recommendTargetCellId = useMemo(
    () => resolveRecommendTargetCellId(effectiveDraftState, targetCellId),
    [effectiveDraftState, targetCellId]
  );

  const recommendPayload = useMemo(
    () => buildRecommendPayload(filters, effectiveDraftState, recommendTargetCellId),
    [effectiveDraftState, filters, recommendTargetCellId]
  );
  const recommendFingerprint = useMemo(() => JSON.stringify(recommendPayload), [recommendPayload]);
  const hasDraftOverrides = useMemo(
    () => localOverrideApplied(slotOverrides, banOverrides, localRoleOverride),
    [banOverrides, localRoleOverride, slotOverrides]
  );

  useEffect(() => {
    let cancelled = false;
    const timeoutId = window.setTimeout(() => {
      setRecommendLoading(true);
      void recommendDraft(recommendPayload)
        .then((bundle) => {
          if (!cancelled) {
            startTransition(() => {
              setRecommendations(bundle);
            });
          }
        })
        .catch((error: unknown) => {
          if (!cancelled) {
            const msg = error instanceof Error ? error.message : String(error);
            console.error("[recommend] failed:", msg, recommendPayload);
            setRecommendations(emptyRecommendations);
            setToastMessage({ text: `Recommendation failed: ${msg}`, tone: "error" });
          }
        })
        .finally(() => {
          if (!cancelled) {
            setRecommendLoading(false);
          }
        });
    }, 150);

    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [recommendFingerprint, recommendPayload]);

  // Rune recommendation: triggers when local player has locked a champion
  const localSlotForRunes = useMemo(() => {
    const local = findLocalPlayerSlot(effectiveDraftState);
    if (!local || local.champion_id <= 0) return null;
    return local;
  }, [effectiveDraftState]);

  const runeRequestFingerprint = useMemo(() => {
    if (!localSlotForRunes) return "";
    const enemies = effectiveDraftState.enemy_team_picks
      .filter((s) => s.champion_id > 0)
      .map((s) => ({ champion_id: s.champion_id, role: s.effective_role ?? s.assigned_role ?? "" }));
    return JSON.stringify({
      champion_id: localSlotForRunes.champion_id,
      role: localSlotForRunes.effective_role ?? localSlotForRunes.assigned_role ?? "",
      enemies,
      rank_tier: filters.rank_tier,
    });
  }, [localSlotForRunes, effectiveDraftState.enemy_team_picks, filters.rank_tier]);

  useEffect(() => {
    if (!localSlotForRunes || !runeRequestFingerprint) {
      setRuneRecommendations(null);
      return;
    }
    let cancelled = false;
    const tid = window.setTimeout(() => {
      setRuneLoading(true);
      const enemies = effectiveDraftState.enemy_team_picks
        .filter((s) => s.champion_id > 0)
        .map((s) => ({ champion_id: s.champion_id, role: s.effective_role ?? s.assigned_role ?? "" }));
      void recommendRunes({
        champion_id: localSlotForRunes.champion_id,
        role: localSlotForRunes.effective_role ?? localSlotForRunes.assigned_role ?? "",
        enemy_slots: enemies,
        rank_tier: filters.rank_tier,
      })
        .then((result) => { if (!cancelled) startTransition(() => setRuneRecommendations(result)); })
        .catch((err: unknown) => { if (!cancelled) console.error("[rune-recommend] failed:", err); })
        .finally(() => { if (!cancelled) setRuneLoading(false); });
    }, 300);
    return () => { cancelled = true; window.clearTimeout(tid); };
  }, [runeRequestFingerprint, localSlotForRunes, effectiveDraftState.enemy_team_picks]);

  // Build recommendation: triggers when game is in progress or when enemy team is fully drafted
  const inGame = gameflowPhase === "InProgress" || gameflowPhase === "GameStart";
  const buildRequestFingerprint = useMemo(() => {
    if (!localSlotForRunes) return "";
    const enemies = effectiveDraftState.enemy_team_picks
      .filter((s) => s.champion_id > 0)
      .map((s) => ({ champion_id: s.champion_id, role: s.effective_role ?? s.assigned_role ?? "" }));
    if (enemies.length === 0) return "";
    return JSON.stringify({
      champion_id: localSlotForRunes.champion_id,
      role: localSlotForRunes.effective_role ?? localSlotForRunes.assigned_role ?? "",
      keystone_id: playerRunes?.keystone_id ?? null,
      enemies,
      rank_tier: filters.rank_tier,
    });
  }, [localSlotForRunes, effectiveDraftState.enemy_team_picks, playerRunes?.keystone_id, filters.rank_tier]);

  useEffect(() => {
    if (!buildRequestFingerprint || !localSlotForRunes) {
      setBuildRecommendation(null);
      return;
    }
    let cancelled = false;
    const tid = window.setTimeout(() => {
      setBuildLoading(true);
      const enemies = effectiveDraftState.enemy_team_picks
        .filter((s) => s.champion_id > 0)
        .map((s) => ({ champion_id: s.champion_id, role: s.effective_role ?? s.assigned_role ?? "" }));
      void recommendBuild({
        champion_id: localSlotForRunes.champion_id,
        role: localSlotForRunes.effective_role ?? localSlotForRunes.assigned_role ?? "",
        keystone_id: playerRunes?.keystone_id ?? null,
        enemy_slots: enemies,
        rank_tier: filters.rank_tier,
      })
        .then((result) => { if (!cancelled) startTransition(() => setBuildRecommendation(result)); })
        .catch((err: unknown) => { if (!cancelled) console.error("[build-recommend] failed:", err); })
        .finally(() => { if (!cancelled) setBuildLoading(false); });
    }, 300);
    return () => { cancelled = true; window.clearTimeout(tid); };
  }, [buildRequestFingerprint, localSlotForRunes, effectiveDraftState.enemy_team_picks, playerRunes?.keystone_id]);

  // Apply runes via Tauri command
  const handleApplyRunes = async (keystoneId: number) => {
    if (!isTauriRuntime()) {
      setToastMessage({ text: "Rune apply requires Tauri runtime", tone: "error" });
      return;
    }
    if (!runeRecommendations) return;

    const runePage = buildFullRunePage(
      keystoneId,
      runeRecommendations.per_rune_stats,
      runeLookup,
      playerRunes?.selected_perk_ids,
    );

    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("apply_runes", { request: runePage });
      setToastMessage({ text: "Runes applied successfully!", tone: "success" });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setToastMessage({ text: `Failed to apply runes: ${msg}`, tone: "error" });
    }
  };

  const updateManualSlot = (team: "ally" | "enemy", cellId: number, updates: Partial<TeamSlot>) => {
    const field = team === "ally" ? "my_team_picks" : "enemy_team_picks";
    setManualDraftState((currentDraft) => ({
      ...currentDraft,
      [field]: currentDraft[field].map((slot) => (slot.cell_id === cellId ? { ...slot, ...updates } : slot)),
    }));
  };

  const handleSlotChampionChange = (team: "ally" | "enemy", cellId: number, championId: number) => {
    if (lcuState.connected && lcuDraftState) {
      const slotKey = `${team}:${cellId}`;
      setSlotOverrides((current) => ({
        ...current,
        [slotKey]: {
          ...current[slotKey],
          championId,
        },
      }));
      return;
    }

    updateManualSlot(team, cellId, {
      champion_id: championId,
      champion_name: null,
      champion_image_url: null,
    });
  };

  const handleSlotRoleChange = (team: "ally" | "enemy", cellId: number, role: string) => {
    const localSlot = findLocalPlayerSlot(effectiveDraftState);
    if (team === "ally" && localSlot && cellId === localSlot.cell_id) {
      setLocalRoleOverride(role || null);
      return;
    }

    const enemyRoleResolution =
      team === "enemy" ? resolveEnemyRoleSelection(effectiveDraftState, cellId, role) : null;
    const nextEnemyRoleLockOrder = role
      ? (() => {
          enemyRoleLockOrderRef.current += 1;
          return enemyRoleLockOrderRef.current;
        })()
      : null;

    if (team === "enemy") {
      setEnemyRoleLockOrder((current) => {
        const nextOrder = { ...current };
        if (nextEnemyRoleLockOrder != null) {
          nextOrder[cellId] = nextEnemyRoleLockOrder;
        } else {
          delete nextOrder[cellId];
        }
        if (enemyRoleResolution?.releasedCellId != null) {
          delete nextOrder[enemyRoleResolution.releasedCellId];
        }
        return nextOrder;
      });
    }

    if (lcuState.connected && lcuDraftState) {
      const slotKey = `${team}:${cellId}`;
      setSlotOverrides((current) => {
        const nextOverrides = { ...current };
        const currentOverride = nextOverrides[slotKey] ?? {};
        const nextOverride = {
          ...currentOverride,
          clearRole: false,
          role: role || null,
        };
        if (!nextOverride.clearRole && nextOverride.championId === undefined && nextOverride.role == null) {
          delete nextOverrides[slotKey];
        } else {
          nextOverrides[slotKey] = nextOverride;
        }

        if (team === "enemy" && enemyRoleResolution?.releasedCellId != null) {
          const releasedSlotKey = `enemy:${enemyRoleResolution.releasedCellId}`;
          const releasedOverride = nextOverrides[releasedSlotKey] ?? {};
          const nextReleasedOverride = {
            ...releasedOverride,
            clearRole: true,
            role: null,
          };
          if (!nextReleasedOverride.clearRole && nextReleasedOverride.championId === undefined && nextReleasedOverride.role == null) {
            delete nextOverrides[releasedSlotKey];
          } else {
            nextOverrides[releasedSlotKey] = nextReleasedOverride;
          }
        }

        return nextOverrides;
      });
      if (enemyRoleResolution?.toastText) {
        setToastMessage({ text: enemyRoleResolution.toastText, tone: "success" });
      }
      return;
    }

    if (team === "enemy") {
      setManualDraftState((currentDraft) => ({
        ...currentDraft,
        enemy_team_picks: currentDraft.enemy_team_picks.map((slot) => {
          if (slot.cell_id === cellId) {
            if (role) {
              return { ...slot, ...createRoleSnapshot(role) };
            }
            return { ...slot, ...createRoleSnapshot(null) };
          }

          if (enemyRoleResolution?.releasedCellId === slot.cell_id) {
            return { ...slot, ...createRoleSnapshot(null) };
          }

          return slot;
        }),
      }));
      if (enemyRoleResolution?.toastText) {
        setToastMessage({ text: enemyRoleResolution.toastText, tone: "success" });
      }
      return;
    }

    updateManualSlot(team, cellId, {
      assigned_role: role || null,
      effective_role: role || null,
      role_source: role ? "manual" : "unknown",
      role_confidence: role ? 1 : 0,
      role_candidates: role ? [{ role, confidence: 1 }] : [],
    });
  };

  const handleBanChange = (team: "ally" | "enemy", index: number, championId: number) => {
    if (lcuState.connected) {
      setBanOverrides((current) => ({
        ...current,
        [`${team}:${index}`]: championId,
      }));
      return;
    }

    const field = team === "ally" ? "my_bans" : "enemy_bans";
    setManualDraftState((currentDraft) => {
      const nextBans = [...currentDraft[field]];
      while (nextBans.length < 5) {
        nextBans.push(0);
      }
      nextBans[index] = championId;
      return {
        ...currentDraft,
        [field]: nextBans,
      };
    });
  };

  const showPhaseIndicator = lcuState.connected && effectiveDraftState.phase !== "IDLE";
  const defaultTab = effectiveDraftState.current_action_type?.toLowerCase() === "ban" ? "bans" : "picks";
  const scopeWarnings = recommendations.warnings.length > 0 ? recommendations.warnings : status?.recommendation_warnings ?? [];
  const localPlayerCellId =
    findLocalPlayerSlot(effectiveDraftState)?.cell_id ?? effectiveDraftState.local_player_cell_id ?? 1;

  if (loading) {
    return (
      <main className="mx-auto flex min-h-screen max-w-7xl flex-col items-center justify-center gap-4 px-4">
        <div className="loading-pulse" aria-hidden="true" />
        <span className="rounded bg-cyan-500/15 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-cyan-400">
          Booting
        </span>
        <h1 className="text-2xl font-semibold text-zinc-100">Preparing desktop draft flow</h1>
        <p className="text-sm text-zinc-500">Connecting to Hetzner, loading the champion catalog, and waiting for LCU state.</p>
      </main>
    );
  }

  return (
    <div className="min-h-screen">
      <main className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-5">
        <section className="rounded-[var(--radius-panel)] border border-zinc-800 bg-zinc-900/60 p-5">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.26em] text-cyan-400">LoL Draft Assistant</p>
              <h1 className="mt-2 text-3xl font-semibold tracking-tight text-zinc-100">Tauri desk client</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-zinc-400">
                LCU draft state flows into the board when League is open. If the client is unavailable, the same board stays fully manual and keeps hitting the Hetzner recommendation API.
              </p>
            </div>
            <div className="rounded-2xl border border-zinc-800 bg-zinc-950/80 px-4 py-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-zinc-500">Request mode</p>
              <p className="mt-1 text-sm font-medium text-zinc-100">{lcuState.connected ? "LCU auto + manual override" : "Manual draft tracking"}</p>
              <p className="mt-1 text-xs text-zinc-500">{recommendLoading ? "Refreshing recommendations..." : "Recommendations are live"}</p>
            </div>
          </div>
        </section>

        <ConnectionStatus apiBaseUrl={apiBaseUrl} status={status} lcu={lcuState} />

        {showPhaseIndicator ? <PhaseIndicator draftState={effectiveDraftState} /> : null}

        {scopeWarnings.length > 0 ? (
          <div className="rounded-[var(--radius-panel)] border border-amber-500/20 bg-amber-500/5 px-4 py-3">
            <p className="text-sm text-amber-300">{scopeWarnings.join(" ")}</p>
          </div>
        ) : null}

        <AnalysisFiltersPanel filters={filters} onChange={setFilters} />

        <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
          <DraftBoard
            champions={champions}
            draftState={effectiveDraftState}
            lcuConnected={lcuState.connected}
            targetCellId={recommendTargetCellId}
            localPlayerCellId={localPlayerCellId}
            hasOverrides={hasDraftOverrides}
            onSlotChampionChange={handleSlotChampionChange}
            onSlotRoleChange={handleSlotRoleChange}
            onTargetSlotChange={(cellId) => setTargetCellId(cellId === localPlayerCellId ? null : cellId)}
            onRecommendForMe={() => setTargetCellId(null)}
            onBanChange={handleBanChange}
            onResetOverrides={() => {
              setSlotOverrides({});
              setBanOverrides({});
              setLocalRoleOverride(null);
              setEnemyRoleLockOrder({});
              enemyRoleLockOrderRef.current = 0;
              setToastMessage({ text: "Local overrides cleared.", tone: "success" });
            }}
          />

          <section className="rounded-[var(--radius-panel)] border border-zinc-800 bg-zinc-900/55 p-4">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-zinc-500">Output</p>
                <h2 className="text-lg font-semibold text-zinc-100">Recommendation feed</h2>
              </div>
              <span className="rounded-full border border-zinc-800 bg-zinc-950/80 px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-zinc-400">
                {recommendLoading ? "Syncing" : "Ready"}
              </span>
            </div>

            <RecommendationPanel
              picks={recommendations.picks}
              bans={recommendations.bans}
              bundle={recommendations}
              defaultTab={defaultTab}
              runeData={runeRecommendations}
              buildData={buildRecommendation}
              runeLookup={runeLookup}
              itemLookup={itemLookup}
              runeLoading={runeLoading}
              buildLoading={buildLoading}
              lcuConnected={lcuState.connected}
              showRuneTab={localSlotForRunes != null}
              showBuildTab={localSlotForRunes != null && effectiveDraftState.enemy_team_picks.some((s) => s.champion_id > 0)}
              onApplyRunes={handleApplyRunes}
              championLookup={championLookup}
            />
          </section>
        </div>
      </main>

      {toastMessage ? <Toast message={toastMessage.text} tone={toastMessage.tone} onClose={() => setToastMessage(null)} /> : null}
    </div>
  );
}
