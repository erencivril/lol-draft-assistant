export function getRecommendationPanelOrder(
  actionType?: string | null,
  counts?: {
    picks: number;
    bans: number;
  }
): {
  primary: "picks" | "bans";
  secondary: "picks" | "bans";
} {
  const normalized = actionType?.toLowerCase();
  if (normalized === "ban") {
    if ((counts?.bans ?? 0) === 0 && (counts?.picks ?? 0) > 0) {
      return { primary: "picks", secondary: "bans" };
    }
    return { primary: "bans", secondary: "picks" };
  }
  if ((counts?.picks ?? 0) === 0 && (counts?.bans ?? 0) > 0) {
    return { primary: "bans", secondary: "picks" };
  }
  return { primary: "picks", secondary: "bans" };
}
