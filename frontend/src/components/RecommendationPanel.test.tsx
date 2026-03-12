import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RecommendationPanel } from "./RecommendationPanel";
import type { RecommendationBundle } from "../types";

const bundle: RecommendationBundle = {
  picks: [
    {
      champion_id: 24,
      champion_name: "Jax",
      suggested_role: "jungle",
      total_score: 61.9,
      display_band: "strong",
      counter_score: 0.66,
      synergy_score: 0.65,
      tier_score: 0.84,
      role_fit_score: 1,
      matchup_coverage: 0.8,
      synergy_coverage: 0.75,
      evidence_score: 0.78,
      role_certainty: 0.64,
      sample_confidence: 0.6,
      thin_evidence: true,
      confidence: 0.62,
      reasons: [],
      explanation: {
        summary: "Jax is a strong jungle pick.",
        scenario_summary: "Enemy roles were weighted across 3 scenario(s). Top scenario 48%: Ahri=middle, Smolder=bottom.",
        scoring: [
          { key: "counter", label: "Counter edge", value: 0.66, weight: 0.28, contribution: 0.18, note: "Exact enemy coverage 80%" },
        ],
        counters: [
          {
            kind: "counter",
            champion_id: 103,
            champion_name: "Ahri",
            role: "middle",
            normalized_score: 0.55,
            sample_confidence: 0.6,
            signed_edge: 0.54,
            shrinkage_weight: 0.6,
            net_contribution: 0.33,
            match_role_source: "inferred",
            metric_label: "Delta2",
            metric_value: 7.2,
            win_rate: 53.2,
            games: 120,
            summary: "Strong into Ahri (middle, inferred 72%)",
          },
        ],
        synergies: [],
        penalties: ["Reduced Ahri (middle) to 60% weight because it only has 120 exact games."],
      },
    },
  ],
  bans: [],
  region: "TR",
  rank_tier: "silver",
  patch: "16.5.1",
  exact_data_available: true,
  patch_trusted: false,
  scope_complete: false,
  warnings: [],
  generated_at: new Date().toISOString(),
};

describe("RecommendationPanel", () => {
  it("renders tabs with pick and ban counts", () => {
    render(<RecommendationPanel picks={bundle.picks} bans={bundle.bans} bundle={bundle} defaultTab="picks" />);

    expect(screen.getByText("Picks (1)")).toBeInTheDocument();
    expect(screen.getByText("Bans (0)")).toBeInTheDocument();
  });

  it("shows thin evidence badge and expandable details", async () => {
    const user = userEvent.setup();

    render(<RecommendationPanel picks={bundle.picks} bans={bundle.bans} bundle={bundle} defaultTab="picks" />);

    expect(screen.getByText("thin evidence")).toBeInTheDocument();

    await user.click(screen.getByText("Show details"));

    expect(screen.getByText(/Enemy roles were weighted across 3 scenario/)).toBeInTheDocument();
    expect(screen.getByText("Counter edge")).toBeInTheDocument();
    expect(screen.getByText("Strong")).toBeInTheDocument();
    expect(screen.getByText(/edge \+0.54/)).toBeInTheDocument();
  });
});
