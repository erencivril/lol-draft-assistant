import type { RuneDefinition, RunePagePayload, RuneStatOut } from "../types";

const DEFAULT_STAT_SHARDS = [5008, 5008, 5001];

function pickStatShards(
  perRuneStats: RuneStatOut[],
  runeLookup: Record<string, RuneDefinition>,
  currentPerkIds?: number[],
): number[] {
  const shardRows = [4, 5, 6];
  const result: number[] = [];

  for (const targetRow of shardRows) {
    const validIds = new Set<number>();
    for (const [key, def] of Object.entries(runeLookup)) {
      if (def.row === targetRow) validIds.add(Number(key));
    }

    let bestId = 0;
    let bestWr = -1;
    for (const stat of perRuneStats) {
      if (validIds.has(stat.rune_id) && stat.weighted_win_rate > bestWr) {
        bestWr = stat.weighted_win_rate;
        bestId = stat.rune_id;
      }
    }

    if (bestId > 0) {
      result.push(bestId);
    } else if (currentPerkIds && currentPerkIds.length >= 9) {
      result.push(currentPerkIds[6 + result.length]);
    } else {
      result.push(DEFAULT_STAT_SHARDS[result.length]);
    }
  }
  return result;
}

/**
 * Build a complete 9-perk rune page from a keystone selection and per-rune stats.
 *
 * Layout: [keystone, primary_row1, primary_row2, primary_row3, sec1, sec2, stat1, stat2, stat3]
 */
export function buildFullRunePage(
  keystoneId: number,
  perRuneStats: RuneStatOut[],
  runeLookup: Record<string, RuneDefinition>,
  currentPerkIds?: number[],
): RunePagePayload {
  const keystoneDef = runeLookup[String(keystoneId)];
  const primaryTreeId = keystoneDef?.tree_id ?? 0;

  // Build a map from rune_id to its stat for quick lookup
  const statByRuneId = new Map<number, RuneStatOut>();
  for (const stat of perRuneStats) {
    statByRuneId.set(stat.rune_id, stat);
  }

  // Group runes by tree, then by row
  const byTree = new Map<number, Map<number, RuneStatOut[]>>();
  for (const stat of perRuneStats) {
    const def = runeLookup[String(stat.rune_id)];
    if (!def) continue;
    if (!byTree.has(def.tree_id)) byTree.set(def.tree_id, new Map<number, RuneStatOut[]>());
    const byRow = byTree.get(def.tree_id)!;
    if (!byRow.has(def.row)) byRow.set(def.row, []);
    byRow.get(def.row)!.push(stat);
  }

  // Pick best rune per row (by weighted_win_rate), with fallback to any valid rune
  function bestPerRow(
    byRow: Map<number, RuneStatOut[]>,
    rows: number[],
    treeId: number,
  ): number[] {
    return rows.map((row) => {
      const candidates = byRow.get(row) ?? [];
      if (candidates.length > 0) {
        return candidates.reduce((best, curr) =>
          curr.weighted_win_rate > best.weighted_win_rate ? curr : best
        ).rune_id;
      }
      // Fallback: pick any valid rune from runeLookup for this tree+row
      for (const [key, def] of Object.entries(runeLookup)) {
        if (def.tree_id === treeId && def.row === row) {
          return Number(key);
        }
      }
      return 0;
    });
  }

  // Primary tree: rows 1, 2, 3 (non-keystone rows)
  const primaryByRow = byTree.get(primaryTreeId) ?? new Map<number, RuneStatOut[]>();
  const primaryRunes = bestPerRow(primaryByRow, [1, 2, 3], primaryTreeId);

  // Secondary tree: highest total score among non-primary trees
  let secondaryTreeId = 0;
  let bestScore = -1;
  for (const [treeId, byRow] of byTree) {
    if (treeId === primaryTreeId) continue;
    let score = 0;
    for (const runes of byRow.values()) {
      for (const r of runes) score += r.weighted_win_rate * r.total_games;
    }
    if (score > bestScore) {
      bestScore = score;
      secondaryTreeId = treeId;
    }
  }

  // Fallback: if no secondary tree found in stats, pick most common non-primary tree
  if (secondaryTreeId === 0 && primaryTreeId > 0) {
    const treeCounts = new Map<number, number>();
    for (const def of Object.values(runeLookup)) {
      if (def.tree_id !== primaryTreeId && def.row > 0) {
        treeCounts.set(def.tree_id, (treeCounts.get(def.tree_id) ?? 0) + 1);
      }
    }
    let maxCount = 0;
    for (const [tid, count] of treeCounts) {
      if (count > maxCount) { maxCount = count; secondaryTreeId = tid; }
    }
  }

  // Pick top 2 secondary runes from different rows
  const secondaryRunes: number[] = [];
  if (secondaryTreeId > 0) {
    const secByRow = byTree.get(secondaryTreeId) ?? new Map<number, RuneStatOut[]>();
    // Collect all candidates with their best rune per row
    const rowCandidates: Array<{ row: number; rune_id: number; score: number }> = [];
    for (const [row, runes] of secByRow) {
      if (row < 1 || row > 3) continue; // Only non-keystone rows valid for secondary
      const best = runes.reduce((a, b) => (b.weighted_win_rate > a.weighted_win_rate ? b : a));
      rowCandidates.push({ row, rune_id: best.rune_id, score: best.weighted_win_rate });
    }
    rowCandidates.sort((a, b) => b.score - a.score);
    const usedRows = new Set<number>();
    for (const candidate of rowCandidates) {
      if (secondaryRunes.length >= 2) break;
      if (!usedRows.has(candidate.row)) {
        secondaryRunes.push(candidate.rune_id);
        usedRows.add(candidate.row);
      }
    }
  }
  // Pad secondary runes with valid runes from the secondary tree if needed
  if (secondaryRunes.length < 2 && secondaryTreeId > 0) {
    const usedRows = new Set<number>();
    for (const rid of secondaryRunes) {
      const def = runeLookup[String(rid)];
      if (def) usedRows.add(def.row);
    }
    for (const [key, def] of Object.entries(runeLookup)) {
      if (secondaryRunes.length >= 2) break;
      if (def.tree_id === secondaryTreeId && def.row > 0 && !usedRows.has(def.row)) {
        secondaryRunes.push(Number(key));
        usedRows.add(def.row);
      }
    }
  }
  while (secondaryRunes.length < 2) secondaryRunes.push(0);

  // Stat shards: pick best per row (4, 5, 6) from per_rune_stats data
  const statShards = pickStatShards(perRuneStats, runeLookup, currentPerkIds);

  const selectedPerkIds = [
    keystoneId,
    ...primaryRunes,
    ...secondaryRunes,
    ...statShards,
  ];

  // Final validation: reject pages with any zero perk ID (LCU will reject them)
  const hasZeroPerk = selectedPerkIds.some((id) => id === 0);

  return {
    keystone_id: keystoneId,
    primary_style_id: primaryTreeId,
    sub_style_id: secondaryTreeId,
    selected_perk_ids: selectedPerkIds,
    _invalid: hasZeroPerk,
  };
}
