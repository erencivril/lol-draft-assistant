import { render, screen, waitFor } from "@testing-library/react";
import App from "./App";

const {
  mockFetchChampions,
  mockFetchStatus,
  mockGetApiBaseUrl,
  mockRecommendDraft,
} = vi.hoisted(() => ({
  mockFetchChampions: vi.fn(),
  mockFetchStatus: vi.fn(),
  mockGetApiBaseUrl: vi.fn(),
  mockRecommendDraft: vi.fn(),
}));

vi.mock("./api/client", () => ({
  fetchChampions: mockFetchChampions,
  fetchStatus: mockFetchStatus,
  getApiBaseUrl: mockGetApiBaseUrl,
  recommendDraft: mockRecommendDraft,
}));

vi.mock("./components/AnalysisFiltersPanel", () => ({
  AnalysisFiltersPanel: () => <div data-testid="analysis-filters" />,
}));

vi.mock("./components/ConnectionStatus", () => ({
  ConnectionStatus: () => <div data-testid="connection-status" />,
}));

vi.mock("./components/DraftBoard", () => ({
  DraftBoard: () => <div data-testid="draft-board" />,
}));

vi.mock("./components/PhaseIndicator", () => ({
  PhaseIndicator: () => null,
}));

vi.mock("./components/RecommendationPanel", () => ({
  RecommendationPanel: () => <div data-testid="recommendation-panel" />,
}));

vi.mock("./components/Toast", () => ({
  Toast: () => null,
}));

describe("App bootstrap", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    mockGetApiBaseUrl.mockReturnValue("http://neco-vps:18080");
    mockFetchStatus.mockResolvedValue({
      lcu_connected: false,
      effective_region: "TR",
      effective_rank_tier: "emerald",
      effective_role: "middle",
      exact_data_available: true,
      patch_trusted: true,
      scope_complete: true,
      scope_ready: true,
      recommendation_warnings: [],
      draft_phase: "MANUAL",
      latest_patch: "16.5.1",
      storage: {
        champion_count: 3,
        tier_stats_count: 0,
        matchups_count: 0,
        synergies_count: 0,
        latest_patch: "16.5.1",
        data_patches: ["16.5.1"],
        historical_rows: 0,
        latest_data_fetch_at: null,
      },
    });
    mockFetchChampions.mockResolvedValue([
      {
        champion_id: 103,
        key: "Ahri",
        name: "Ahri",
        image_url: "https://example.com/ahri.png",
        roles: ["middle"],
        patch: "16.5.1",
      },
    ]);
    mockRecommendDraft.mockResolvedValue({
      picks: [],
      bans: [],
      exact_data_available: true,
      patch_trusted: true,
      scope_complete: true,
      scope_ready: true,
      scope_last_synced_at: null,
      scope_freshness: "fresh",
      fallback_used_recently: false,
      warnings: [],
      generated_at: new Date().toISOString(),
    });
  });

  it("loads Hetzner data and requests recommendations for the current draft state", async () => {
    render(<App />);

    await screen.findByText("Tauri desk client");

    await waitFor(() => {
      expect(mockRecommendDraft).toHaveBeenCalledWith({
        region: "TR",
        rank_tier: "emerald",
        role: "middle",
        ally_picks: [],
        enemy_picks: [],
        bans: [],
      });
    });

    expect(screen.getByTestId("connection-status")).toBeInTheDocument();
    expect(screen.getByTestId("draft-board")).toBeInTheDocument();
    expect(screen.getByTestId("recommendation-panel")).toBeInTheDocument();
  });
});
