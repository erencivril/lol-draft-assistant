from __future__ import annotations

from app.db.repository import MatchupRecord, SynergyRecord
from app.domain.draft import TeamSlot
from app.domain.recommendation import (
    RecommendationExplanation,
    RecommendationRelationDetail,
)
from app.domain.settings import ResolvedFilters

from .role_inference import ResolvedTeamContext
from .scoring import (
    RelationInsight,
    RelationSummary,
    ScoreComposition,
    TierCandidate,
)


def build_pick_explanation(
    *,
    champion_name: str,
    candidate: TierCandidate,
    filters: ResolvedFilters,
    composition: ScoreComposition,
    counter_summary: RelationSummary,
    synergy_summary: RelationSummary,
    scenario_summary: str,
    thin_evidence: bool,
) -> RecommendationExplanation:
    penalties = explanation_penalties(
        record=candidate.record,
        composition=composition,
        counter_summary=counter_summary,
        synergy_summary=synergy_summary,
        thin_evidence=thin_evidence,
    )
    top_counter = counter_summary.insights[0].summary if counter_summary.insights else "No exact enemy matchup data matched the visible draft yet."
    top_synergy = synergy_summary.insights[0].summary if synergy_summary.insights else "No exact ally synergy data matched the visible draft yet."
    summary = (
        f"{champion_name} is a {candidate.record.tier_grade} {candidate.role} pick in "
        f"{filters.region} / {filters.rank_tier} with {candidate.record.win_rate:.1f}% WR over "
        f"{candidate.record.games:,} games. {top_counter} {top_synergy}"
    )
    return RecommendationExplanation(
        summary=summary,
        scenario_summary=scenario_summary,
        scoring=composition.components,
        counters=[relation_detail(item) for item in counter_summary.insights[:5]],
        synergies=[relation_detail(item) for item in synergy_summary.insights[:5]],
        penalties=penalties,
    )


def build_ban_explanation(
    *,
    champion_name: str,
    candidate: TierCandidate,
    filters: ResolvedFilters,
    composition: ScoreComposition,
    counter_summary: RelationSummary,
    synergy_summary: RelationSummary,
    scenario_summary: str,
    thin_evidence: bool,
) -> RecommendationExplanation:
    penalties = explanation_penalties(
        record=candidate.record,
        composition=composition,
        counter_summary=counter_summary,
        synergy_summary=synergy_summary,
        thin_evidence=thin_evidence,
    )
    top_counter = counter_summary.insights[0].summary if counter_summary.insights else "No exact threat data matched your current allies yet."
    top_synergy = synergy_summary.insights[0].summary if synergy_summary.insights else "No exact enemy combo data matched the visible opponents yet."
    summary = (
        f"{champion_name} is a high-threat {candidate.role} ban in {filters.region} / {filters.rank_tier}: "
        f"{candidate.record.tier_grade} tier, {candidate.record.pick_rate:.1f}% pick rate, {candidate.record.games:,} games. "
        f"{top_counter} {top_synergy}"
    )
    return RecommendationExplanation(
        summary=summary,
        scenario_summary=scenario_summary,
        scoring=composition.components,
        counters=[relation_detail(item) for item in counter_summary.insights[:5]],
        synergies=[relation_detail(item) for item in synergy_summary.insights[:5]],
        penalties=penalties,
    )


def combined_scenario_summary(enemy_context: ResolvedTeamContext, ally_context: ResolvedTeamContext) -> str:
    parts = [part for part in [enemy_context.scenario_summary, ally_context.scenario_summary] if part]
    return " ".join(parts)


def explanation_penalties(
    *,
    record,
    composition: ScoreComposition,
    counter_summary: RelationSummary,
    synergy_summary: RelationSummary,
    thin_evidence: bool,
) -> list[str]:
    penalties: list[str] = []
    if composition.penalty > 0:
        penalties.append(
            f"Low-sample tier penalty applied because this tier row has {record.games:,} games on patch {record.patch}."
        )
    if composition.evidence_multiplier < 1.0:
        penalties.append(
            f"Score was reduced by draft coverage to {composition.evidence_multiplier:.2f}x because "
            f"exact matchup coverage is {counter_summary.coverage:.0%} and exact synergy coverage is {synergy_summary.coverage:.0%}."
        )
    if counter_summary.coverage_penalty > 0:
        penalties.append(
            f"Counter coverage penalty applied because exact matchup data only covered {counter_summary.coverage:.0%} of visible enemy roles."
        )
    penalties.extend(counter_summary.thin_evidence_notes[:3])
    penalties.extend(note for note in synergy_summary.thin_evidence_notes[:3] if note not in penalties)
    if thin_evidence:
        penalties.append("Both the strongest counter and synergy edges are under 100 games, so the final score was reduced by 10%.")
    return penalties


def sample_penalty_note(*, slot: TeamSlot, matched_role: str, games: int, sample_confidence: float, champion_name: str) -> str:
    if sample_confidence == 0:
        return f"Ignored {champion_name} ({matched_role}) in score because it only has {games:,} exact games."
    return (
        f"Reduced {champion_name} ({matched_role}) to {sample_confidence:.0%} weight "
        f"because it only has {games:,} exact games."
    )


def matchup_insight(
    *,
    kind: str,
    slot: TeamSlot,
    matched_role: str,
    record: MatchupRecord | SynergyRecord,
    signed_edge: float,
    net_contribution: float,
    sample_confidence: float,
    champion_name: str,
) -> RelationInsight:
    assert isinstance(record, MatchupRecord)
    rn = role_note(slot=slot, matched_role=matched_role)
    summary_prefix = matchup_summary_prefix(kind=kind, metric_value=record.delta2)
    return RelationInsight(
        kind=kind,
        champion_id=slot.champion_id,
        champion_name=champion_name,
        role=matched_role,
        normalized_score=net_contribution,
        sample_confidence=sample_confidence,
        signed_edge=signed_edge,
        shrinkage_weight=sample_confidence,
        net_contribution=net_contribution,
        match_role_source=slot.role_source,
        metric_label="Delta2",
        metric_value=record.delta2,
        win_rate=record.win_rate,
        games=record.games,
        summary=(
            f"{summary_prefix} {champion_name} "
            f"({matched_role}{rn}) (delta {record.delta2:+.1f}, WR {record.win_rate:.1f}%, {record.games:,} games)"
        ),
    )


def synergy_insight(
    *,
    kind: str,
    slot: TeamSlot,
    matched_role: str,
    record: MatchupRecord | SynergyRecord,
    signed_edge: float,
    net_contribution: float,
    sample_confidence: float,
    champion_name: str,
) -> RelationInsight:
    assert isinstance(record, SynergyRecord)
    rn = role_note(slot=slot, matched_role=matched_role)
    summary_prefix = synergy_summary_prefix(kind=kind, metric_value=record.normalised_delta)
    return RelationInsight(
        kind=kind,
        champion_id=slot.champion_id,
        champion_name=champion_name,
        role=matched_role,
        normalized_score=net_contribution,
        sample_confidence=sample_confidence,
        signed_edge=signed_edge,
        shrinkage_weight=sample_confidence,
        net_contribution=net_contribution,
        match_role_source=slot.role_source,
        metric_label="Normalized delta",
        metric_value=record.normalised_delta,
        win_rate=record.duo_win_rate,
        games=record.games,
        summary=(
            f"{summary_prefix} {champion_name} "
            f"({matched_role}{rn}) (delta {record.normalised_delta:+.1f}, WR {record.duo_win_rate:.1f}%, {record.games:,} games)"
        ),
    )


def role_note(*, slot: TeamSlot, matched_role: str) -> str:
    if slot.role_source == "inferred":
        confidence = next((candidate.confidence for candidate in slot.role_candidates if candidate.role == matched_role), slot.role_confidence)
        return f", inferred {confidence:.0%}"
    if slot.role_source == "manual":
        return ", manual"
    if slot.role_source == "lcu":
        return ", lcu"
    return ""


def relation_detail(insight: RelationInsight) -> RecommendationRelationDetail:
    return RecommendationRelationDetail(
        kind=insight.kind,  # type: ignore[arg-type]
        champion_id=insight.champion_id,
        champion_name=insight.champion_name,
        role=insight.role,
        normalized_score=round(insight.normalized_score, 4),
        sample_confidence=round(insight.sample_confidence, 4),
        signed_edge=round(insight.signed_edge, 4),
        shrinkage_weight=round(insight.shrinkage_weight, 4),
        net_contribution=round(insight.net_contribution, 4),
        match_role_source=insight.match_role_source,  # type: ignore[arg-type]
        metric_label=insight.metric_label,
        metric_value=round(insight.metric_value, 4),
        win_rate=round(insight.win_rate, 4),
        games=insight.games,
        summary=insight.summary,
    )


def matchup_summary_prefix(*, kind: str, metric_value: float) -> str:
    if kind == "threat":
        return "Threatens" if metric_value >= 0 else "Less threatening into"
    return "Strong into" if metric_value >= 0 else "Struggles into"


def synergy_summary_prefix(*, kind: str, metric_value: float) -> str:
    if kind == "enemy_synergy":
        return "Combines well with" if metric_value >= 0 else "Has weak combo with"
    return "Pairs well with" if metric_value >= 0 else "Clashes with"
