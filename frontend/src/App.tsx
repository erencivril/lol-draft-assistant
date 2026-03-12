import { startTransition, useEffect, useMemo, useState } from "react";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import {
  fetchChampions,
  fetchStatus,
  getApiBaseUrl,
  recommendDraft,
  type ChampionCatalogItem,
  type RecommendPayload,
} from "./api/client";
import { AnalysisFiltersPanel, type AnalysisFilters } from "./components/AnalysisFiltersPanel";
import { ConnectionStatus, type LcuConnectionState } from "./components/ConnectionStatus";
import { DraftBoard } from "./components/DraftBoard";
import { PhaseIndicator } from "./components/PhaseIndicator";
import { RecommendationPanel } from "./components/RecommendationPanel";
import { inferDraftRoles } from "./lib/draftRoleInference";
import { Toast } from "./components/Toast";
import { roleOptions } from "./constants/filters";
import type { DraftState, RecommendationBundle, StatusPayload, TeamSlot } from "./types";

type ToastState = {
  text: string;
  tone: "success" | "error";
};

type LcuDraftUpdatePayload = {
  connected: boolean;
  status?: string;
  draft_state?: DraftState | null;
};

type SlotOverride = {
  championId?: number;
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
    role: "middle",
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
    if (!parsed.region || !parsed.rank_tier || !parsed.role) {
      return defaultFilters();
    }
    return {
      region: parsed.region,
      rank_tier: parsed.rank_tier,
      role: parsed.role,
    };
  } catch {
    return defaultFilters();
  }
}

function createBaseSlot(cellId: number, role: string, isLocalPlayer = false): TeamSlot {
  return {
    cell_id: cellId,
    champion_id: 0,
    champion_name: null,
    champion_image_url: null,
    assigned_role: role,
    effective_role: role,
    role_source: "manual",
    role_confidence: 1,
    role_candidates: [{ role, confidence: 1 }],
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
    enemy_team_picks: roleOrder.map((role, index) => createBaseSlot(index + 6, role)),
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

function remapManualDraftState(currentDraft: DraftState, localRole: string): DraftState {
  const safeRole = roleOrder.includes(localRole) ? localRole : "middle";
  const allySlotsByRole = new Map(
    currentDraft.my_team_picks.map((slot) => [slot.assigned_role ?? slot.effective_role ?? `${slot.cell_id}`, slot])
  );
  const enemySlotsByRole = new Map(
    currentDraft.enemy_team_picks.map((slot) => [slot.assigned_role ?? slot.effective_role ?? `${slot.cell_id}`, slot])
  );
  const localPlayerCellId = roleOrder.indexOf(safeRole) + 1;

  return {
    ...currentDraft,
    phase: "MANUAL",
    local_player_cell_id: localPlayerCellId,
    local_player_assigned_role: safeRole,
    local_player_effective_role: safeRole,
    current_actor_cell_id: localPlayerCellId,
    current_action_type: "pick",
    session_status: "manual",
    is_local_players_turn: true,
    my_team_picks: roleOrder.map((role, index) => {
      const existing = allySlotsByRole.get(role);
      const nextSlot = {
        ...(existing ?? createBaseSlot(index + 1, role)),
        cell_id: index + 1,
        assigned_role: role,
        effective_role: role,
        is_local_player: role === safeRole,
        role_source: "manual" as const,
        role_confidence: 1,
        role_candidates: [{ role, confidence: 1 }],
      };
      return role === safeRole
        ? {
            ...nextSlot,
            champion_id: 0,
            champion_name: null,
            champion_image_url: null,
          }
        : nextSlot;
    }),
    enemy_team_picks: roleOrder.map((role, index) => {
      const existing = enemySlotsByRole.get(role);
      return {
        ...(existing ?? createBaseSlot(index + 6, role)),
        cell_id: index + 6,
        assigned_role: role,
        effective_role: role,
        is_local_player: false,
        role_source: "manual" as const,
        role_confidence: 1,
        role_candidates: [{ role, confidence: 1 }],
      };
    }),
    my_team_declared_roles: [safeRole],
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
      override.role === undefined ? slot.effective_role ?? slot.assigned_role ?? null : override.role;
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

function buildRecommendPayload(filters: AnalysisFilters, draftState: DraftState): RecommendPayload {
  return {
    region: filters.region,
    rank_tier: filters.rank_tier,
    role: filters.role,
    ally_picks: draftState.my_team_picks
      .filter((slot) => !slot.is_local_player && slot.champion_id > 0)
      .map((slot) => ({
        champion_id: slot.champion_id,
        role: slot.effective_role ?? slot.assigned_role ?? null,
      })),
    enemy_picks: draftState.enemy_team_picks
      .filter((slot) => slot.champion_id > 0)
      .map((slot) => ({
        champion_id: slot.champion_id,
        role: slot.effective_role ?? slot.assigned_role ?? null,
      })),
    bans: [...draftState.my_bans, ...draftState.enemy_bans].filter((championId) => championId > 0),
  };
}

export default function App() {
  const initialFilters = loadStoredFilters();
  const [filters, setFilters] = useState<AnalysisFilters>(initialFilters);
  const [status, setStatus] = useState<StatusPayload | null>(null);
  const [champions, setChampions] = useState<ChampionCatalogItem[]>([]);
  const [manualDraftState, setManualDraftState] = useState<DraftState>(() => createManualDraftState(initialFilters.role));
  const [lcuDraftState, setLcuDraftState] = useState<DraftState | null>(null);
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
    setManualDraftState((currentDraft) => remapManualDraftState(currentDraft, filters.role));
  }, [filters.role]);

  useEffect(() => {
    let cancelled = false;

    const loadBootstrap = async () => {
      try {
        const [nextStatus, nextChampions] = await Promise.all([fetchStatus(), fetchChampions()]);
        if (cancelled) {
          return;
        }
        startTransition(() => {
          setStatus(nextStatus);
          setChampions(nextChampions);
        });
      } catch {
        if (!cancelled) {
          setToastMessage({ text: "Failed to reach the Hetzner backend.", tone: "error" });
        }
      } finally {
        if (!cancelled) {
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
          const nextDraftState = event.payload.connected && event.payload.draft_state ? event.payload.draft_state : null;
          const nextRole =
            nextDraftState?.local_player_effective_role ?? nextDraftState?.local_player_assigned_role ?? null;
          startTransition(() => {
            setLcuState({
              connected: event.payload.connected,
              status:
                event.payload.status ??
                (event.payload.connected ? "Champ select session detected" : "Waiting for League Client"),
              lastUpdatedAt: new Date().toISOString(),
            });
            setLcuDraftState(nextDraftState);
            if (nextRole) {
              setFilters((current) => (current.role === nextRole ? current : { ...current, role: nextRole }));
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
    const baseDraft = lcuState.connected && lcuDraftState ? applyDraftOverrides(lcuDraftState, slotOverrides, banOverrides) : manualDraftState;
    const inferredDraft = inferDraftRoles(baseDraft, championLookup);
    return hydrateDraftState(inferredDraft, championLookup);
  }, [banOverrides, championLookup, lcuDraftState, lcuState.connected, manualDraftState, slotOverrides]);

  const recommendPayload = useMemo(
    () => buildRecommendPayload(filters, effectiveDraftState),
    [effectiveDraftState, filters]
  );
  const recommendFingerprint = useMemo(() => JSON.stringify(recommendPayload), [recommendPayload]);

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
        .catch(() => {
          if (!cancelled) {
            setRecommendations(emptyRecommendations);
            setToastMessage({ text: "Recommendation request failed.", tone: "error" });
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

  const updateManualSlot = (team: "ally" | "enemy", cellId: number, updates: Partial<TeamSlot>) => {
    const field = team === "ally" ? "my_team_picks" : "enemy_team_picks";
    setManualDraftState((currentDraft) => ({
      ...currentDraft,
      [field]: currentDraft[field].map((slot) => (slot.cell_id === cellId ? { ...slot, ...updates } : slot)),
    }));
  };

  const handleSlotChampionChange = (team: "ally" | "enemy", cellId: number, championId: number) => {
    if (lcuState.connected) {
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
    if (lcuState.connected) {
      const slotKey = `${team}:${cellId}`;
      setSlotOverrides((current) => {
        const nextOverrides = { ...current };
        const currentOverride = nextOverrides[slotKey] ?? {};
        const nextOverride = {
          ...currentOverride,
          role: role || null,
        };
        if (nextOverride.championId === undefined && nextOverride.role == null) {
          delete nextOverrides[slotKey];
        } else {
          nextOverrides[slotKey] = nextOverride;
        }
        return nextOverrides;
      });
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
            onSlotChampionChange={handleSlotChampionChange}
            onSlotRoleChange={handleSlotRoleChange}
            onBanChange={handleBanChange}
            onResetOverrides={() => {
              setSlotOverrides({});
              setBanOverrides({});
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
            />
          </section>
        </div>
      </main>

      {toastMessage ? <Toast message={toastMessage.text} tone={toastMessage.tone} onClose={() => setToastMessage(null)} /> : null}
    </div>
  );
}
