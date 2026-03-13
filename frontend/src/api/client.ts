import type { RecommendationBundle, StatusPayload } from "../types";

export type ChampionCatalogItem = {
  champion_id: number;
  key: string;
  name: string;
  image_url: string;
  roles: string[];
  patch: string;
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
    throw new Error(`Request failed: ${response.status}`);
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
