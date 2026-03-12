from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from math import exp

from app.db.repository import ChampionRecord, TierStatRecord
from app.domain.draft import RoleCandidate, TeamSlot
from app.domain.roles import ROLE_ORDER, normalize_role_name

from .scoring_constants import (
    ROLE_AMBIGUITY_GAP_THRESHOLD,
    ROLE_AMBIGUITY_PENALTY,
    ROLE_AMBIGUITY_TOP_THRESHOLD,
    ROLE_SCENARIO_LIMIT,
    ROLE_SCENARIO_TEMPERATURE,
    SUPPORTED_ROLES,
)


@dataclass(slots=True)
class TeamScenario:
    assignments: dict[int, str]
    raw_score: float
    probability: float
    remaining_roles: tuple[str, ...]
    summary: str


@dataclass(slots=True)
class ResolvedTeamContext:
    team: str
    slots: list[TeamSlot]
    role_probabilities: dict[int, dict[str, float]]
    scenarios: list[TeamScenario]
    certainty_multiplier: float
    warning: str | None
    inferred_count: int
    open_role_weights: dict[str, float]
    scenario_summary: str
    role_certainty: float


def resolve_team_context(
    *,
    team: str,
    slots: list[TeamSlot],
    region: str,
    rank_tier: str,
    reserved_roles: set[str],
    overrides: dict[tuple[str, int], str],
    champion_lookup: dict[int, ChampionRecord],
    tier_index: dict[tuple[str, str, str, int], TierStatRecord],
    champion_name_fn: callable,
) -> ResolvedTeamContext:
    fixed_roles: dict[int, str] = {}
    fixed_sources: dict[int, str] = {}
    picked_unknown: list[tuple[int, TeamSlot]] = []
    role_scores: dict[int, dict[str, float]] = {}

    reserved = {normalize_role_name(role) for role in reserved_roles}
    reserved = {role for role in reserved if role}

    for slot_index, slot in enumerate(slots):
        manual_role = normalize_role_name(overrides.get((team, slot.cell_id)))
        lcu_role = normalize_role_name(slot.assigned_role)
        fixed_role = manual_role or lcu_role
        fixed_source = "manual" if manual_role else "lcu" if lcu_role else None
        if fixed_role:
            fixed_roles[slot.cell_id] = fixed_role
            fixed_sources[slot.cell_id] = fixed_source or "unknown"
        elif slot.champion_id:
            picked_unknown.append((slot_index, slot))
            role_scores[slot.cell_id] = candidate_role_scores(
                slot=slot,
                slot_index=slot_index,
                region=region,
                rank_tier=rank_tier,
                champion_lookup=champion_lookup,
                tier_index=tier_index,
            )

    scenarios = build_team_scenarios(
        picked_unknown=picked_unknown,
        role_scores=role_scores,
        fixed_roles=fixed_roles,
        reserved_roles=reserved,
        champion_name_fn=champion_name_fn,
    )
    scenario_probabilities = softmax_scenarios(scenarios)
    role_probabilities: dict[int, dict[str, float]] = {}
    for cell_id, role in fixed_roles.items():
        role_probabilities[cell_id] = {role: 1.0}
    for scenario in scenario_probabilities:
        for cell_id, role in scenario.assignments.items():
            role_probabilities.setdefault(cell_id, {})
            role_probabilities[cell_id][role] = role_probabilities[cell_id].get(role, 0.0) + scenario.probability

    decorated_slots: list[TeamSlot] = []
    inferred_count = 0
    role_confidences: list[float] = []
    for slot in slots:
        if slot.cell_id in fixed_roles:
            resolved = slot.model_copy(
                update={
                    "effective_role": fixed_roles[slot.cell_id],
                    "role_source": fixed_sources[slot.cell_id],
                    "role_confidence": 1.0,
                    "role_candidates": [RoleCandidate(role=fixed_roles[slot.cell_id], confidence=1.0)],
                }
            )
        elif slot.champion_id and slot.cell_id in role_probabilities:
            sorted_roles = sorted(role_probabilities[slot.cell_id].items(), key=lambda item: item[1], reverse=True)
            effective_role, confidence = sorted_roles[0]
            resolved = slot.model_copy(
                update={
                    "effective_role": effective_role,
                    "role_source": "inferred",
                    "role_confidence": round(confidence, 4),
                    "role_candidates": [
                        RoleCandidate(role=role, confidence=round(probability, 4))
                        for role, probability in sorted_roles[:3]
                    ],
                }
            )
            inferred_count += 1
        else:
            resolved = slot.model_copy(
                update={
                    "effective_role": normalize_role_name(slot.assigned_role),
                    "role_source": slot.role_source,
                    "role_confidence": slot.role_confidence,
                    "role_candidates": slot.role_candidates,
                }
            )
        if resolved.champion_id and resolved.role_confidence > 0:
            role_confidences.append(resolved.role_confidence)
        decorated_slots.append(resolved)

    open_role_weights: dict[str, float] = {}
    unknown_open_slots = [slot for slot in slots if not slot.champion_id and slot.cell_id not in fixed_roles]
    for slot in slots:
        if slot.champion_id or slot.cell_id not in fixed_roles:
            continue
        open_role_weights[fixed_roles[slot.cell_id]] = 1.0
    if unknown_open_slots:
        for scenario in scenario_probabilities:
            for role in scenario.remaining_roles:
                open_role_weights[role] = open_role_weights.get(role, 0.0) + scenario.probability
    if not open_role_weights and any(not slot.champion_id for slot in slots):
        open_role_weights = {role: 1.0 for role in SUPPORTED_ROLES}

    top_probability = scenario_probabilities[0].probability if scenario_probabilities else 1.0
    second_probability = scenario_probabilities[1].probability if len(scenario_probabilities) > 1 else 0.0
    certainty_multiplier = 1.0
    warning = None
    if picked_unknown and (top_probability < ROLE_AMBIGUITY_TOP_THRESHOLD or (top_probability - second_probability) < ROLE_AMBIGUITY_GAP_THRESHOLD):
        certainty_multiplier = ROLE_AMBIGUITY_PENALTY
        warning = (
            f"{team.title()} role inference is ambiguous: top scenario {top_probability:.0%}, "
            f"next {second_probability:.0%}. Exact relation contributions were reduced."
        )

    summary = scenario_summary(team=team, scenarios=scenario_probabilities)
    role_certainty = sum(role_confidences) / len(role_confidences) if role_confidences else 1.0
    return ResolvedTeamContext(
        team=team,
        slots=decorated_slots,
        role_probabilities=role_probabilities,
        scenarios=scenario_probabilities,
        certainty_multiplier=certainty_multiplier,
        warning=warning,
        inferred_count=inferred_count,
        open_role_weights=open_role_weights,
        scenario_summary=summary,
        role_certainty=role_certainty,
    )


def candidate_role_scores(
    *,
    slot: TeamSlot,
    slot_index: int,
    region: str,
    rank_tier: str,
    champion_lookup: dict[int, ChampionRecord],
    tier_index: dict[tuple[str, str, str, int], TierStatRecord],
) -> dict[str, float]:
    champion = champion_lookup.get(slot.champion_id)
    derived_roles = set(champion.roles if champion else [])
    scores: dict[str, float] = {}
    for role in SUPPORTED_ROLES:
        score = 0.0
        if record := tier_index.get((region, rank_tier, role, slot.champion_id)):
            score += 10.0
            score += min(record.pick_rate / 2.0, 5.0)
            score += min(record.games / 5000.0, 4.0)
        elif derived_roles and role in derived_roles:
            score += 2.5
        if champion and role in derived_roles:
            score += 1.2
        if role == ROLE_ORDER[min(slot_index, len(ROLE_ORDER) - 1)]:
            score += 0.3
        scores[role] = score
    return scores


def build_team_scenarios(
    *,
    picked_unknown: list[tuple[int, TeamSlot]],
    role_scores: dict[int, dict[str, float]],
    fixed_roles: dict[int, str],
    reserved_roles: set[str],
    champion_name_fn: callable,
) -> list[TeamScenario]:
    occupied_roles = {role for role in fixed_roles.values()} | reserved_roles
    available_roles = [role for role in SUPPORTED_ROLES if role not in occupied_roles]
    if not picked_unknown:
        return [
            TeamScenario(
                assignments={},
                raw_score=1.0,
                probability=1.0,
                remaining_roles=tuple(sorted(role for role in SUPPORTED_ROLES if role not in occupied_roles)),
                summary="Roles came directly from the client or manual overrides.",
            )
        ]

    if len(available_roles) < len(picked_unknown):
        available_roles = SUPPORTED_ROLES.copy()

    scenarios: list[TeamScenario] = []
    for role_combo in permutations(available_roles, len(picked_unknown)):
        used_roles = set(occupied_roles)
        raw_score = 0.0
        assignments: dict[int, str] = {}
        valid = True
        for (_, slot), role in zip(picked_unknown, role_combo, strict=False):
            if role in used_roles:
                valid = False
                break
            used_roles.add(role)
            assignments[slot.cell_id] = role
            raw_score += role_scores[slot.cell_id][role]
        if not valid:
            continue

        summary = ", ".join(
            f"{champion_name_fn(slot.champion_id)}={assignments[slot.cell_id]}"
            for _, slot in picked_unknown
        )
        scenarios.append(
            TeamScenario(
                assignments=assignments,
                raw_score=raw_score,
                probability=0.0,
                remaining_roles=tuple(sorted(role for role in SUPPORTED_ROLES if role not in used_roles)),
                summary=summary,
            )
        )

    if not scenarios:
        return [
            TeamScenario(
                assignments={},
                raw_score=1.0,
                probability=1.0,
                remaining_roles=tuple(sorted(role for role in SUPPORTED_ROLES if role not in occupied_roles)),
                summary="No valid unique-role scenario was available.",
            )
        ]
    return sorted(scenarios, key=lambda item: item.raw_score, reverse=True)[:ROLE_SCENARIO_LIMIT]


def softmax_scenarios(scenarios: list[TeamScenario]) -> list[TeamScenario]:
    if not scenarios:
        return []
    if len(scenarios) == 1:
        only = scenarios[0]
        return [
            TeamScenario(
                assignments=only.assignments,
                raw_score=only.raw_score,
                probability=1.0,
                remaining_roles=only.remaining_roles,
                summary=only.summary,
            )
        ]

    max_score = max(scenario.raw_score for scenario in scenarios)
    weights = [exp((scenario.raw_score - max_score) / ROLE_SCENARIO_TEMPERATURE) for scenario in scenarios]
    total = sum(weights) or 1.0
    weighted = [
        TeamScenario(
            assignments=scenario.assignments,
            raw_score=scenario.raw_score,
            probability=weight / total,
            remaining_roles=scenario.remaining_roles,
            summary=scenario.summary,
        )
        for scenario, weight in zip(scenarios, weights, strict=False)
    ]
    return sorted(weighted, key=lambda item: item.probability, reverse=True)


def scenario_summary(*, team: str, scenarios: list[TeamScenario]) -> str:
    if not scenarios:
        return ""
    top = scenarios[0]
    if len(scenarios) == 1 and top.probability >= 0.999:
        return f"{team.title()} roles are fixed from the client or manual overrides."
    return (
        f"{team.title()} roles were weighted across {len(scenarios)} scenario(s). "
        f"Top scenario {top.probability:.0%}: {top.summary or 'No visible picked champions yet.'}"
    )
