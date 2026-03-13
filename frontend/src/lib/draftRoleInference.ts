import type { ChampionCatalogItem } from "../api/client";
import { roleOptions } from "../constants/filters";
import type { DraftState, RoleCandidate, TeamSlot } from "../types";

const supportedRoles = roleOptions.map((option) => option.value);
const roleScoreByRank = [9, 6, 4, 2, 1];
const inferenceTemperature = 1.35;
const maxRoleCandidates = 3;

type RoleScenario = {
  assignments: Record<number, string>;
  probability: number;
  rawScore: number;
};

type InferableSlot = {
  championRoles: string[];
  slot: TeamSlot;
};

type ExplicitRoleCandidate = {
  cellId: number;
  order: number;
  role: string;
  source: "lcu" | "manual";
};

type TeamInferenceOptions = {
  manualLockOrderByCellId?: Record<number, number>;
};

type DraftInferenceOptions = {
  enemyManualLockOrderByCellId?: Record<number, number>;
};

export function inferDraftRoles(
  draftState: DraftState,
  championLookup: Map<number, ChampionCatalogItem>,
  options: DraftInferenceOptions = {}
): DraftState {
  const myTeamPicks = inferTeamRoles(draftState.my_team_picks, championLookup);
  const enemyTeamPicks = inferTeamRoles(draftState.enemy_team_picks, championLookup, {
    manualLockOrderByCellId: options.enemyManualLockOrderByCellId,
  });
  const localPlayerSlot = myTeamPicks.find(
    (slot) => slot.is_local_player || slot.cell_id === draftState.local_player_cell_id
  );

  return {
    ...draftState,
    my_team_picks: myTeamPicks,
    enemy_team_picks: enemyTeamPicks,
    my_team_declared_roles: collectDeclaredRoles(myTeamPicks),
    enemy_team_declared_roles: collectDeclaredRoles(enemyTeamPicks),
    local_player_assigned_role:
      localPlayerSlot?.assigned_role ?? draftState.local_player_assigned_role ?? null,
    local_player_effective_role:
      localPlayerSlot?.effective_role ?? draftState.local_player_effective_role ?? null,
  };
}

function inferTeamRoles(
  slots: TeamSlot[],
  championLookup: Map<number, ChampionCatalogItem>,
  options: TeamInferenceOptions = {}
): TeamSlot[] {
  const normalizedSlots = slots.map(normalizeSlotRoles);
  const { fixedRoles, fixedSources, releasedCellIds } = resolveFixedRoles(
    normalizedSlots,
    options.manualLockOrderByCellId ?? {}
  );
  const inferableSlots: InferableSlot[] = [];

  for (const slot of normalizedSlots) {
    if (fixedRoles.has(slot.cell_id)) {
      continue;
    }

    if (slot.champion_id <= 0) {
      continue;
    }

    const championRoles = normalizeRoleList(championLookup.get(slot.champion_id)?.roles ?? []);
    if (championRoles.length === 0) {
      continue;
    }

    inferableSlots.push({ slot, championRoles });
  }

  const scenarios = inferableSlots.length > 0 ? buildRoleScenarios(inferableSlots, fixedRoles) : [];
  const roleProbabilities = aggregateRoleProbabilities(scenarios);

  const resolvedSlots: TeamSlot[] = normalizedSlots.map((slot): TeamSlot => {
    const explicitRole = fixedRoles.get(slot.cell_id);
    if (explicitRole) {
      const roleSource = fixedSources.get(slot.cell_id) ?? "manual";
      return {
        ...slot,
        assigned_role: explicitRole,
        effective_role: explicitRole,
        role_source: roleSource,
        role_confidence: 1,
        role_candidates: [{ role: explicitRole, confidence: 1 }],
      };
    }

    const probabilities = roleProbabilities.get(slot.cell_id);
    if (probabilities) {
      const sortedRoles = [...probabilities.entries()].sort((left, right) => right[1] - left[1]);
      const [effectiveRole, confidence] = sortedRoles[0];
      const roleCandidates: RoleCandidate[] = sortedRoles.slice(0, maxRoleCandidates).map(([role, value]) => ({
        role,
        confidence: roundConfidence(value),
      }));

      return {
        ...slot,
        assigned_role: effectiveRole,
        effective_role: effectiveRole,
        role_source: "inferred",
        role_confidence: roundConfidence(confidence),
        role_candidates: roleCandidates,
      };
    }

    if (releasedCellIds.has(slot.cell_id)) {
      return clearRole(slot);
    }

    return slot;
  });

  return assignForcedOpenRole(resolvedSlots);
}

function resolveFixedRoles(
  slots: TeamSlot[],
  manualLockOrderByCellId: Record<number, number>
): {
  fixedRoles: Map<number, string>;
  fixedSources: Map<number, "lcu" | "manual">;
  releasedCellIds: Set<number>;
} {
  const winnersByRole = new Map<string, ExplicitRoleCandidate>();
  const releasedCellIds = new Set<number>();

  for (const slot of slots) {
    const explicitRole = getExplicitRole(slot);
    if (!explicitRole) {
      continue;
    }

    const candidate: ExplicitRoleCandidate = {
      cellId: slot.cell_id,
      role: explicitRole,
      source: slot.role_source === "lcu" ? "lcu" : "manual",
      order: manualLockOrderByCellId[slot.cell_id] ?? 0,
    };
    const existing = winnersByRole.get(candidate.role);

    if (!existing || shouldReplaceExplicitRole(existing, candidate)) {
      if (existing) {
        releasedCellIds.add(existing.cellId);
      }
      winnersByRole.set(candidate.role, candidate);
    } else {
      releasedCellIds.add(candidate.cellId);
    }
  }

  const fixedRoles = new Map<number, string>();
  const fixedSources = new Map<number, "lcu" | "manual">();

  for (const candidate of winnersByRole.values()) {
    fixedRoles.set(candidate.cellId, candidate.role);
    fixedSources.set(candidate.cellId, candidate.source);
  }

  return {
    fixedRoles,
    fixedSources,
    releasedCellIds,
  };
}

function shouldReplaceExplicitRole(
  current: ExplicitRoleCandidate,
  next: ExplicitRoleCandidate
): boolean {
  if (current.source !== next.source) {
    return next.source === "manual";
  }

  if (next.source === "manual") {
    if (next.order !== current.order) {
      return next.order > current.order;
    }
    return next.cellId > current.cellId;
  }

  return false;
}

function assignForcedOpenRole(slots: TeamSlot[]): TeamSlot[] {
  const unresolvedSlots = slots.filter(
    (slot) => slot.champion_id <= 0 && !normalizeRole(slot.effective_role ?? slot.assigned_role)
  );
  if (unresolvedSlots.length !== 1) {
    return slots;
  }

  const occupiedRoles = new Set(
    slots
      .map((slot) => normalizeRole(slot.effective_role ?? slot.assigned_role))
      .filter((role): role is string => Boolean(role))
  );
  const remainingRoles = supportedRoles.filter((role) => !occupiedRoles.has(role));
  if (remainingRoles.length !== 1) {
    return slots;
  }

  const forcedRole = remainingRoles[0];
  const unresolvedCellId = unresolvedSlots[0].cell_id;

  return slots.map((slot) =>
    slot.cell_id === unresolvedCellId
      ? {
          ...slot,
          assigned_role: forcedRole,
          effective_role: forcedRole,
          role_source: "inferred" as const,
          role_confidence: 1,
          role_candidates: [{ role: forcedRole, confidence: 1 }],
        }
      : slot
  );
}

function clearRole(slot: TeamSlot): TeamSlot {
  return {
    ...slot,
    assigned_role: null,
    effective_role: null,
    role_source: "unknown",
    role_confidence: 0,
    role_candidates: [],
  };
}

function buildRoleScenarios(
  inferableSlots: InferableSlot[],
  fixedRoles: Map<number, string>
): RoleScenario[] {
  const occupiedRoles = new Set(fixedRoles.values());
  const availableRoles = supportedRoles.filter((role) => !occupiedRoles.has(role));
  const scenarioRoles =
    availableRoles.length >= inferableSlots.length ? availableRoles : supportedRoles;
  const scenarios: RoleScenario[] = [];

  for (const roleCombo of permutations(scenarioRoles, inferableSlots.length)) {
    const usedRoles = new Set(occupiedRoles);
    let rawScore = 0;
    const assignments: Record<number, string> = {};
    let valid = true;

    for (let index = 0; index < inferableSlots.length; index += 1) {
      const role = roleCombo[index];
      if (usedRoles.has(role)) {
        valid = false;
        break;
      }

      const inferableSlot = inferableSlots[index];
      assignments[inferableSlot.slot.cell_id] = role;
      usedRoles.add(role);
      rawScore += scoreRoleForSlot(inferableSlot.championRoles, role);
    }

    if (!valid) {
      continue;
    }

    scenarios.push({
      assignments,
      probability: 0,
      rawScore,
    });
  }

  if (scenarios.length === 0) {
    return [
      {
        assignments: {},
        probability: 1,
        rawScore: 1,
      },
    ];
  }

  const maxScore = Math.max(...scenarios.map((scenario) => scenario.rawScore));
  const weights = scenarios.map((scenario) =>
    Math.exp((scenario.rawScore - maxScore) / inferenceTemperature)
  );
  const totalWeight = weights.reduce((sum, value) => sum + value, 0) || 1;

  return scenarios
    .map((scenario, index) => ({
      ...scenario,
      probability: weights[index] / totalWeight,
    }))
    .sort((left, right) => right.probability - left.probability);
}

function aggregateRoleProbabilities(
  scenarios: RoleScenario[]
): Map<number, Map<string, number>> {
  const probabilities = new Map<number, Map<string, number>>();

  for (const scenario of scenarios) {
    for (const [cellIdRaw, role] of Object.entries(scenario.assignments)) {
      const cellId = Number(cellIdRaw);
      const slotProbabilities = probabilities.get(cellId) ?? new Map<string, number>();
      slotProbabilities.set(role, (slotProbabilities.get(role) ?? 0) + scenario.probability);
      probabilities.set(cellId, slotProbabilities);
    }
  }

  return probabilities;
}

function scoreRoleForSlot(championRoles: string[], role: string): number {
  const roleIndex = championRoles.indexOf(role);
  if (roleIndex === -1) {
    return 0.15;
  }
  return roleScoreByRank[roleIndex] ?? 1;
}

function getExplicitRole(slot: TeamSlot): string | null {
  if (slot.role_source !== "manual" && slot.role_source !== "lcu") {
    return null;
  }

  return normalizeRole(slot.effective_role) ?? normalizeRole(slot.assigned_role);
}

function normalizeSlotRoles(slot: TeamSlot): TeamSlot {
  const assignedRole = normalizeRole(slot.assigned_role);
  const effectiveRole = normalizeRole(slot.effective_role) ?? assignedRole;
  const roleCandidates = normalizeRoleCandidates(slot.role_candidates);

  return {
    ...slot,
    assigned_role: assignedRole,
    effective_role: effectiveRole,
    role_candidates: roleCandidates,
  };
}

function normalizeRoleCandidates(candidates: RoleCandidate[]): RoleCandidate[] {
  const deduped = new Map<string, number>();
  for (const candidate of candidates) {
    const role = normalizeRole(candidate.role);
    if (!role) {
      continue;
    }
    deduped.set(role, Math.max(deduped.get(role) ?? 0, candidate.confidence));
  }

  return [...deduped.entries()].map(([role, confidence]) => ({
    role,
    confidence: roundConfidence(confidence),
  }));
}

function collectDeclaredRoles(slots: TeamSlot[]): string[] {
  return slots
    .map((slot) => normalizeRole(slot.effective_role) ?? normalizeRole(slot.assigned_role))
    .filter((role): role is string => Boolean(role));
}

function normalizeRoleList(roles: string[]): string[] {
  const normalized = roles
    .map((role) => normalizeRole(role))
    .filter((role): role is string => Boolean(role));

  return [...new Set(normalized)];
}

function normalizeRole(value?: string | null): string | null {
  switch ((value ?? "").trim().toLowerCase()) {
    case "top":
      return "top";
    case "jungle":
      return "jungle";
    case "middle":
    case "mid":
      return "middle";
    case "bottom":
    case "bot":
    case "adc":
      return "bottom";
    case "support":
    case "utility":
      return "support";
    default:
      return null;
  }
}

function permutations(values: string[], count: number): string[][] {
  if (count === 0) {
    return [[]];
  }

  const result: string[][] = [];
  for (let index = 0; index < values.length; index += 1) {
    const value = values[index];
    const remaining = values.filter((_, candidateIndex) => candidateIndex !== index);
    for (const tail of permutations(remaining, count - 1)) {
      result.push([value, ...tail]);
    }
  }
  return result;
}

function roundConfidence(value: number): number {
  return Math.round(value * 10000) / 10000;
}
