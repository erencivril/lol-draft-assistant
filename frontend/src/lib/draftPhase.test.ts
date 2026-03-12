import { getRecommendationPanelOrder } from "./draftPhase";

describe("getRecommendationPanelOrder", () => {
  it("prioritizes bans during ban phases", () => {
    expect(getRecommendationPanelOrder("ban")).toEqual({ primary: "bans", secondary: "picks" });
  });

  it("defaults to picks for unknown or pick actions", () => {
    expect(getRecommendationPanelOrder("pick")).toEqual({ primary: "picks", secondary: "bans" });
    expect(getRecommendationPanelOrder(null)).toEqual({ primary: "picks", secondary: "bans" });
  });

  it("falls back to the populated panel when the phase-primary list is empty", () => {
    expect(getRecommendationPanelOrder("ban", { picks: 4, bans: 0 })).toEqual({ primary: "picks", secondary: "bans" });
    expect(getRecommendationPanelOrder("pick", { picks: 0, bans: 3 })).toEqual({ primary: "bans", secondary: "picks" });
  });
});
