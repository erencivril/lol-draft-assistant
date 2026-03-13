from __future__ import annotations

from dataclasses import dataclass, field
from math import log1p, tanh
from typing import Callable

from app.db.repository import MatchupRecord, SynergyRecord, TierStatRecord
from app.domain.draft import TeamSlot
from app.domain.recommendation import RecommendationScoreComponent
from app.domain.roles import normalize_role_name

from .scoring_constants import (
    BAN_WEIGHT_BAN_RATE,
    BAN_WEIGHT_COUNTER,
    BAN_WEIGHT_PICK_RATE,
    BAN_WEIGHT_ROLE_LIKELIHOOD,
    BAN_WEIGHT_SYNERGY,
    BAN_WEIGHT_TIER,
    COUNTER_EDGE_SCALE,
    DISPLAY_BAND_ELITE,
    DISPLAY_BAND_SITUATIONAL,
    DISPLAY_BAND_STRONG,
    LANE_PROXIMITY,
    MATCHUP_SHRINKAGE_PRIOR,
    PBI_NORMALIZATION_SCALE,
    PICK_COUNTER_BAND_WINDOW,
    PICK_COUNTER_MISSING_COVERAGE_PENALTY,
    PICK_HIERARCHY_BOARD_COUNTER_WEIGHT,
    PICK_HIERARCHY_CONFIDENCE_WEIGHT,
    PICK_HIERARCHY_SYNERGY_WEIGHT,
    PICK_HIERARCHY_TIER_WEIGHT,
    PICK_HIERARCHY_WORST_ENEMY_WEIGHT,
    PREDRAFT_WEIGHT_PBI,
    PREDRAFT_WEIGHT_ROLE_FIT,
    PREDRAFT_WEIGHT_TIER,
    PREDRAFT_WEIGHT_TIER_RANK,
    RELATION_SHRINKAGE_PRIOR_GAMES,
    ROLE_FIT_HIGH_PICK_RATE,
    ROLE_FIT_MEDIUM_PICK_RATE,
    SAMPLE_THRESHOLD_IGNORE,
    SYNERGY_EDGE_SCALE,
    SYNERGY_SHRINKAGE_PRIOR,
    TIER_GAMES_HIGH,
    TIER_GAMES_MEDIUM,
    TIER_PENALTY_LOW,
    TIER_PENALTY_MEDIUM,
    TIER_SCORES,
)


@dataclass(slots=True)
class TierCandidate:
    champion_id: int
    role: str
    record: TierStatRecord
    role_prior: float = 1.0


@dataclass(slots=True)
class RelationInsight:
    kind: str
    champion_id: int
    champion_name: str
    role: str | None
    normalized_score: float
    sample_confidence: float
    signed_edge: float
    shrinkage_weight: float
    net_contribution: float
    match_role_source: str
    metric_label: str
    metric_value: float
    win_rate: float
    games: int
    summary: str


@dataclass(slots=True)
class RelationSummary:
    score: float
    raw_score: float
    worst_score: float
    coverage: float
    coverage_penalty: float
    sample_confidence: float
    details: list[str]
    insights: list[RelationInsight]
    thin_evidence_notes: list[str] = field(default_factory=list)
    top_games: int | None = None


@dataclass(slots=True)
class ScorePart:
    key: str
    label: str
    value: float
    weight: float
    note: str | None = None


@dataclass(slots=True)
class ScoreComposition:
    total: float
    base_score: float
    evidence_multiplier: float
    penalty: float
    components: list[RecommendationScoreComponent]


def normalize_delta(record: MatchupRecord | None) -> float:
    if record is None:
        return 0.0
    # Bayesian shrinkage: low-sample matchups are pulled toward 0
    shrinkage = record.games / (record.games + MATCHUP_SHRINKAGE_PRIOR)
    return tanh(record.delta2 * shrinkage / COUNTER_EDGE_SCALE)


def normalize_synergy(record: SynergyRecord | None) -> float:
    if record is None:
        return 0.0
    # Bayesian shrinkage: low-sample synergies are pulled toward 0
    shrinkage = record.games / (record.games + SYNERGY_SHRINKAGE_PRIOR)
    return tanh(record.normalised_delta * shrinkage / SYNERGY_EDGE_SCALE)


def clamp_relation_score(value: float) -> float:
    return max(-1.0, min(1.0, value))


def sample_confidence(games: int) -> float:
    if games < SAMPLE_THRESHOLD_IGNORE:
        return 0.0
    return games / (games + RELATION_SHRINKAGE_PRIOR_GAMES)


def tier_score(record: TierStatRecord) -> float:
    grade_component = TIER_SCORES.get(record.tier_grade.upper(), 0.58)
    # Center win rate around 50% with ±7% range for realistic LoL win rates (43-57%)
    wr_centered = (record.win_rate - 50.0) / 7.0
    wr_component = max(0.0, min(1.0, 0.5 + wr_centered * 0.5))
    return (grade_component * 0.6) + (wr_component * 0.4)


def role_fit_score(record: TierStatRecord) -> float:
    pick_rate = record.pick_rate
    if pick_rate <= 0:
        return 0.1
    # Smooth logarithmic curve: PR=1% -> 0.25, PR=5% -> 0.66, PR=10% -> 0.82, PR=15% -> 1.0
    return max(0.1, min(1.0, log1p(pick_rate) / log1p(15.0)))


def low_sample_penalty(record: TierStatRecord) -> float:
    games = record.games
    if games >= TIER_GAMES_HIGH:
        return 0.0
    # Smooth continuous curve instead of cliffs: 1000 games -> 0.08, 2500 -> 0.05, 4000 -> 0.02
    return TIER_PENALTY_LOW * (1.0 - min(games / float(TIER_GAMES_HIGH), 1.0))


def tier_rank_score(record: TierStatRecord) -> float:
    if record.tier_rank <= 0:
        return 0.4
    return max(0.0, min(1.0, 1.0 - ((record.tier_rank - 1) / 30.0)))


def pbi_score(record: TierStatRecord) -> float:
    if record.pbi <= 0:
        return 0.0
    # PBI values rarely exceed 30 in practice; normalizing to 50 left most values compressed
    return max(0.0, min(1.0, record.pbi / PBI_NORMALIZATION_SCALE))


def display_band(score: float) -> str:
    if score >= DISPLAY_BAND_ELITE:
        return "elite"
    if score >= DISPLAY_BAND_STRONG:
        return "strong"
    if score >= DISPLAY_BAND_SITUATIONAL:
        return "situational"
    return "risky"


def combine_coverages(matchup_coverage: float, synergy_coverage: float) -> float:
    values = [value for value in [matchup_coverage, synergy_coverage] if value > 0]
    return sum(values) / len(values) if values else 0.0


def combine_metric(
    first_value: float,
    second_value: float,
    first_slots: list[TeamSlot],
    second_slots: list[TeamSlot],
) -> float:
    values: list[float] = []
    if first_slots:
        values.append(first_value)
    if second_slots:
        values.append(second_value)
    return sum(values) / len(values) if values else 1.0


def evidence_score(
    matchup_coverage: float,
    synergy_coverage: float,
    matchup_slots: list[TeamSlot],
    synergy_slots: list[TeamSlot],
) -> float:
    if not matchup_slots and not synergy_slots:
        return 1.0
    total_slots = len(matchup_slots) + len(synergy_slots)
    matched_slots = (matchup_coverage * len(matchup_slots)) + (synergy_coverage * len(synergy_slots))
    return matched_slots / total_slots if total_slots else 1.0


def has_thin_evidence(counter_summary: RelationSummary, synergy_summary: RelationSummary) -> bool:
    return bool(
        counter_summary.top_games is not None
        and counter_summary.top_games < 100
        and synergy_summary.top_games is not None
        and synergy_summary.top_games < 100
    )


def summarize_relations(
    *,
    slots: list[TeamSlot],
    role_probabilities: dict[int, dict[str, float]],
    certainty_multiplier: float,
    loader: Callable[[TeamSlot, str], MatchupRecord | SynergyRecord | None],
    normalizer: Callable[[MatchupRecord | SynergyRecord | None], float],
    detail_builder: Callable[[TeamSlot, str, MatchupRecord | SynergyRecord, float, float, float], RelationInsight],
    sample_penalty_note_fn: Callable[[TeamSlot, str, int, float], str],
    candidate_role: str | None = None,
    missing_penalty_scale: float = 0.0,
) -> RelationSummary:
    if not slots:
        return RelationSummary(
            score=0.0,
            raw_score=0.0,
            worst_score=0.0,
            coverage=0.0,
            coverage_penalty=0.0,
            sample_confidence=1.0,
            details=[],
            insights=[],
        )

    raw_slot_scores: list[float] = []
    slot_scores: list[float] = []
    coverage_total = 0.0
    coverage_penalty_total = 0.0
    sample_total = 0.0
    details: list[str] = []
    insights: list[RelationInsight] = []
    thin_evidence_notes: list[str] = []

    for slot in slots:
        probabilities = role_probabilities.get(slot.cell_id)
        if not probabilities:
            role = normalize_role_name(slot.effective_role) or normalize_role_name(slot.assigned_role)
            probabilities = {role: 1.0} if role else {}
        slot_score = 0.0
        slot_coverage = 0.0
        slot_sample = 0.0
        best_insight: RelationInsight | None = None
        for matched_role, role_probability in probabilities.items():
            if role_probability <= 0:
                continue
            record = loader(slot, matched_role)
            if record is None:
                continue
            base_score = normalizer(record)
            sc = sample_confidence(record.games)
            proximity = LANE_PROXIMITY.get((candidate_role, matched_role), 0.7) if candidate_role else 1.0
            slot_coverage += role_probability
            slot_sample += role_probability * sc
            contribution = role_probability * base_score * sc * proximity
            slot_score += contribution
            insight = detail_builder(slot, matched_role, record, base_score, contribution, sc)
            if best_insight is None or abs(contribution) > abs(best_insight.net_contribution):
                best_insight = insight
            if sc < 1.0:
                thin_evidence_notes.append(
                    sample_penalty_note_fn(slot, matched_role, record.games, sc)
                )
        raw_slot_scores.append(clamp_relation_score(slot_score))
        slot_penalty = max(0.0, 1.0 - slot_coverage) * missing_penalty_scale
        coverage_penalty_total += slot_penalty
        slot_scores.append(clamp_relation_score(slot_score - slot_penalty))
        coverage_total += slot_coverage
        sample_total += slot_sample
        if best_insight:
            insights.append(best_insight)
            details.append(best_insight.summary)

    coverage = coverage_total / len(slots) if slots else 1.0
    coverage_penalty = coverage_penalty_total / len(slots) if slots else 0.0
    sc_result = sample_total / coverage_total if coverage_total else 0.0
    raw_score = ((sum(raw_slot_scores) / len(slots)) if slots else 0.0) * certainty_multiplier
    score = ((sum(slot_scores) / len(slots)) if slots else 0.0) * certainty_multiplier
    worst_score = (min(raw_slot_scores) if raw_slot_scores else 0.0) * certainty_multiplier
    sorted_insights = sorted(insights, key=lambda item: abs(item.net_contribution), reverse=True)
    top_games = sorted_insights[0].games if sorted_insights else None
    return RelationSummary(
        score=clamp_relation_score(score),
        raw_score=clamp_relation_score(raw_score),
        worst_score=clamp_relation_score(worst_score),
        coverage=coverage,
        coverage_penalty=coverage_penalty,
        sample_confidence=sc_result,
        details=details,
        insights=sorted_insights,
        thin_evidence_notes=unique_notes(thin_evidence_notes),
        top_games=top_games,
    )


def compose_pick_score(
    *,
    record: TierStatRecord,
    counter_score: float,
    worst_enemy_score: float,
    counter_coverage_penalty: float,
    tier_secondary_score: float,
    synergy_score: float,
    enemy_count: int,
    ally_count: int,
    low_sample_penalty_val: float,
) -> ScoreComposition:
    if enemy_count <= 0:
        synergy_weight = 0.12 if ally_count > 0 else 0.0
        base_weight = max(0.0, 1.0 - synergy_weight)
        parts = [
            ScorePart(key="tier_rank", label="Tier base", value=tier_rank_score(record), weight=PREDRAFT_WEIGHT_TIER_RANK * base_weight),
            ScorePart(key="tier", label="Tier strength", value=tier_score(record), weight=PREDRAFT_WEIGHT_TIER * base_weight),
            ScorePart(key="pbi", label="PBI", value=pbi_score(record), weight=PREDRAFT_WEIGHT_PBI * base_weight),
            ScorePart(key="role_fit", label="Role fit", value=role_fit_score(record), weight=PREDRAFT_WEIGHT_ROLE_FIT * base_weight),
        ]
        if ally_count > 0:
            parts.append(
                ScorePart(
                    key="synergy",
                    label="Team synergy",
                    value=synergy_score,
                    weight=synergy_weight,
                    note="Signed normalized synergy expectation over visible allies",
                )
            )
        raw_total = sum(part.weight * part.value for part in parts) - low_sample_penalty_val
        clamped_total = max(0.0, min(1.0, raw_total))
        components = [
            RecommendationScoreComponent(
                key=part.key,
                label=part.label,
                value=round(part.value, 4),
                weight=round(part.weight, 4),
                contribution=round(part.weight * part.value, 4),
                note=part.note,
            )
            for part in parts
        ]
        if low_sample_penalty_val > 0:
            components.append(
                RecommendationScoreComponent(
                    key="penalty",
                    label="Penalty",
                    value=round(-low_sample_penalty_val, 4),
                    weight=1.0,
                    contribution=round(-low_sample_penalty_val, 4),
                    note="Tier low-sample penalty",
                )
            )
        return ScoreComposition(
            total=clamped_total,
            base_score=sum(part.weight * part.value for part in parts),
            evidence_multiplier=1.0,
            penalty=low_sample_penalty_val,
            components=components,
        )

    counter_band = pick_counter_band(counter_score)
    hierarchy_total = pick_hierarchy_score(
        counter_band=counter_band,
        worst_enemy_score=worst_enemy_score,
        board_counter_score=counter_score,
        tier_secondary_score=tier_secondary_score,
        synergy_secondary_score=synergy_score,
        confidence=0.0,
    )
    components = [
        RecommendationScoreComponent(
            key="counter_band",
            label="Counter band",
            value=round(float(counter_band), 4),
            weight=1.0,
            contribution=round(counter_band / max(pick_counter_band(1.0), 1), 4),
            note=f"Primary ranking band over visible enemy delta2 profile (window {PICK_COUNTER_BAND_WINDOW:.2f})",
        ),
        RecommendationScoreComponent(
            key="worst_enemy",
            label="Worst visible matchup",
            value=round(worst_enemy_score, 4),
            weight=round(PICK_HIERARCHY_WORST_ENEMY_WEIGHT, 4),
            contribution=round(PICK_HIERARCHY_WORST_ENEMY_WEIGHT * relation_to_unit_interval(worst_enemy_score), 4),
            note="Secondary key so one hard-losing enemy cannot hide inside a good overall board average",
        ),
        RecommendationScoreComponent(
            key="counter",
            label="Board counter profile",
            value=round(counter_score, 4),
            weight=round(PICK_HIERARCHY_BOARD_COUNTER_WEIGHT, 4),
            contribution=round(PICK_HIERARCHY_BOARD_COUNTER_WEIGHT * relation_to_unit_interval(counter_score), 4),
            note="Average signed Delta2 expectation over all visible enemies after coverage penalties",
        ),
        RecommendationScoreComponent(
            key="tier_secondary",
            label="Tier secondary",
            value=round(tier_secondary_score, 4),
            weight=round(PICK_HIERARCHY_TIER_WEIGHT, 4),
            contribution=round(PICK_HIERARCHY_TIER_WEIGHT * tier_secondary_score, 4),
            note="Second-priority tiebreak once the counter profile is close enough",
        ),
        RecommendationScoreComponent(
            key="synergy",
            label="Synergy bonus",
            value=round(synergy_score, 4),
            weight=round(PICK_HIERARCHY_SYNERGY_WEIGHT, 4),
            contribution=round(PICK_HIERARCHY_SYNERGY_WEIGHT * relation_to_unit_interval(synergy_score), 4),
            note="Lightest tiebreak using normalized synergy delta",
        ),
    ]
    if counter_coverage_penalty > 0:
        components.append(
            RecommendationScoreComponent(
                key="counter_coverage_penalty",
                label="Counter coverage penalty",
                value=round(-counter_coverage_penalty, 4),
                weight=1.0,
                contribution=round(-counter_coverage_penalty, 4),
                note="Visible enemy-role matchups without exact data were treated as a penalty instead of neutral",
            )
        )
    if low_sample_penalty_val > 0:
        components.append(
            RecommendationScoreComponent(
                key="penalty",
                label="Penalty",
                value=round(-low_sample_penalty_val, 4),
                weight=1.0,
                contribution=round(-low_sample_penalty_val, 4),
                note="Tier low-sample penalty",
            )
        )
    return ScoreComposition(
        total=max(0.0, min(1.0, hierarchy_total - low_sample_penalty_val)),
        base_score=hierarchy_total,
        evidence_multiplier=1.0,
        penalty=low_sample_penalty_val,
        components=components,
    )


def compose_predraft_pick_score(record: TierStatRecord) -> ScoreComposition:
    parts = [
        ScorePart(key="tier_rank", label="Tier base", value=tier_rank_score(record), weight=PREDRAFT_WEIGHT_TIER_RANK),
        ScorePart(key="tier", label="Tier strength", value=tier_score(record), weight=PREDRAFT_WEIGHT_TIER),
        ScorePart(key="pbi", label="PBI", value=pbi_score(record), weight=PREDRAFT_WEIGHT_PBI),
        ScorePart(key="role_fit", label="Role fit", value=role_fit_score(record), weight=PREDRAFT_WEIGHT_ROLE_FIT),
    ]
    base = sum(part.weight * part.value for part in parts)
    penalty = low_sample_penalty(record) * 0.5
    components = [
        RecommendationScoreComponent(
            key=part.key,
            label=part.label,
            value=round(part.value, 4),
            weight=round(part.weight, 4),
            contribution=round(part.weight * part.value, 4),
            note=None,
        )
        for part in parts
    ]
    if penalty > 0:
        components.append(
            RecommendationScoreComponent(
                key="penalty",
                label="Penalty",
                value=round(-penalty, 4),
                weight=1.0,
                contribution=round(-penalty, 4),
                note="Tier low-sample penalty",
            )
        )
    return ScoreComposition(
        total=max(0.0, min(1.0, base - penalty)),
        base_score=base,
        evidence_multiplier=1.0,
        penalty=penalty,
        components=components,
    )


def compose_ban_score(
    *,
    tier_threat: float,
    pick_rate_score: float,
    ban_rate_score: float,
    counter_threat: float,
    synergy_threat: float,
    matchup_slots_present: bool,
    synergy_slots_present: bool,
    role_likelihood_score: float,
) -> ScoreComposition:
    relation_budget = (BAN_WEIGHT_COUNTER if matchup_slots_present else 0.0) + (BAN_WEIGHT_SYNERGY if synergy_slots_present else 0.0)
    base_weight = max(0.0, 1.0 - relation_budget)
    parts = [
        ScorePart(key="tier", label="Tier base", value=tier_threat, weight=BAN_WEIGHT_TIER * base_weight),
        ScorePart(key="role_likelihood", label="Open-role likelihood", value=role_likelihood_score, weight=BAN_WEIGHT_ROLE_LIKELIHOOD * base_weight),
        ScorePart(key="pick_rate", label="Pick rate pressure", value=pick_rate_score, weight=BAN_WEIGHT_PICK_RATE * base_weight),
        ScorePart(key="ban_rate", label="Ban rate pressure", value=ban_rate_score, weight=BAN_WEIGHT_BAN_RATE * base_weight),
    ]
    if matchup_slots_present:
        parts.append(
            ScorePart(
                key="counter",
                label="Threat into allies",
                value=counter_threat,
                weight=BAN_WEIGHT_COUNTER,
                note="Signed Delta2 expectation over visible allies",
            )
        )
    if synergy_slots_present:
        parts.append(
            ScorePart(
                key="synergy",
                label="Enemy combo value",
                value=synergy_threat,
                weight=BAN_WEIGHT_SYNERGY,
                note="Signed normalized synergy expectation over visible enemies",
            )
        )
    components = [
        RecommendationScoreComponent(
            key=part.key,
            label=part.label,
            value=round(part.value, 4),
            weight=round(part.weight, 4),
            contribution=round(part.weight * part.value, 4),
            note=part.note,
        )
        for part in parts
    ]
    base = sum(part.weight * part.value for part in parts)
    return ScoreComposition(total=max(0.0, min(1.0, base)), base_score=base, evidence_multiplier=1.0, penalty=0.0, components=components)


def relation_to_unit_interval(value: float) -> float:
    return (clamp_relation_score(value) + 1.0) / 2.0


def pick_counter_band(counter_score: float) -> int:
    max_band = int(2.0 / PICK_COUNTER_BAND_WINDOW)
    clamped = clamp_relation_score(counter_score)
    band = int((clamped + 1.0) / PICK_COUNTER_BAND_WINDOW)
    return max(0, min(max_band, band))


def pick_hierarchy_score(
    *,
    counter_band: int,
    worst_enemy_score: float,
    board_counter_score: float,
    tier_secondary_score: float,
    synergy_secondary_score: float,
    confidence: float,
) -> float:
    max_band = max(pick_counter_band(1.0), 1)
    within_band = (
        relation_to_unit_interval(worst_enemy_score) * PICK_HIERARCHY_WORST_ENEMY_WEIGHT
        + relation_to_unit_interval(board_counter_score) * PICK_HIERARCHY_BOARD_COUNTER_WEIGHT
        + tier_secondary_score * PICK_HIERARCHY_TIER_WEIGHT
        + relation_to_unit_interval(synergy_secondary_score) * PICK_HIERARCHY_SYNERGY_WEIGHT
        + confidence * PICK_HIERARCHY_CONFIDENCE_WEIGHT
    )
    return max(0.0, min(1.0, (counter_band + within_band) / (max_band + 1)))


def unique_notes(notes: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for note in notes:
        if note in seen:
            continue
        seen.add(note)
        result.append(note)
    return result
