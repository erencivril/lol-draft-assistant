import type {
  BuildRecommendResponse,
  ItemDefinition,
  RecommendationBundle,
  RuneDefinition,
  RuneRecommendResponse,
  StatusPayload,
} from "../types";

export type ChampionCatalogItem = {
  champion_id: number;
  key: string;
  name: string;
  image_url: string;
  roles: string[];
  patch: string;
  primary_role: string | null;
  role_hints: Array<{ role: string; weight: number; games: number }>;
};

export type RecommendSlotPayload = {
  cell_id: number;
  champion_id: number;
  role?: string | null;
  is_local_player?: boolean;
};

export type RecommendPayload = {
  region: string;
  rank_tier: string;
  target_cell_id: number;
  enemy_slots: RecommendSlotPayload[];
  ally_slots: RecommendSlotPayload[];
  bans: number[];
};

const DEFAULT_API_BASE_URL = "http://neco-vps:18080";

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

export function getApiBaseUrl(): string {
  const envBaseUrl =
    ((import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env?.VITE_API_BASE_URL ?? "");
  const storedBaseUrl =
    typeof window !== "undefined" ? window.localStorage.getItem("ourtbx.apiBaseUrl") ?? "" : "";
  return trimTrailingSlash(storedBaseUrl || envBaseUrl || DEFAULT_API_BASE_URL);
}

function toApiUrl(path: string): string {
  return `${getApiBaseUrl()}${path}`;
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(toApiUrl(path), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let detail = "";
    try {
      const body = await response.json();
      detail = typeof body?.detail === "string"
        ? body.detail
        : JSON.stringify(body?.detail ?? body);
    } catch {
      /* no parseable body */
    }
    throw new Error(
      detail
        ? `${response.status}: ${detail}`
        : `Request failed: ${response.status}`
    );
  }
  return response.json() as Promise<T>;
}

export function fetchStatus(): Promise<StatusPayload> {
  return fetchJson<StatusPayload>("/api/status");
}

export async function fetchChampions(): Promise<ChampionCatalogItem[]> {
  const payload = await fetchJson<Record<string, ChampionCatalogItem>>("/api/data/champions");
  return Object.values(payload).sort((left, right) => left.name.localeCompare(right.name));
}

export function recommendDraft(payload: RecommendPayload): Promise<RecommendationBundle> {
  return fetchJson<RecommendationBundle>("/api/recommend", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export type RuneRecommendPayload = {
  champion_id: number;
  role: string;
  enemy_slots: Array<{ champion_id: number; role: string }>;
  rank_tier?: string;
};

export type BuildRecommendPayload = {
  champion_id: number;
  role: string;
  keystone_id?: number | null;
  enemy_slots: Array<{ champion_id: number; role: string }>;
  rank_tier?: string;
};

export function recommendRunes(payload: RuneRecommendPayload): Promise<RuneRecommendResponse> {
  return fetchJson<RuneRecommendResponse>("/api/recommend/runes", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function recommendBuild(payload: BuildRecommendPayload): Promise<BuildRecommendResponse> {
  return fetchJson<BuildRecommendResponse>("/api/recommend/build", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchItems(): Promise<Record<string, ItemDefinition>> {
  return fetchJson<Record<string, ItemDefinition>>("/api/data/items");
}

export async function fetchRunes(): Promise<Record<string, RuneDefinition>> {
  return fetchJson<Record<string, RuneDefinition>>("/api/data/runes");
}
