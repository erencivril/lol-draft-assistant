"""Rune recommendation service: aggregates per-matchup rune data to suggest optimal rune pages."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.db.repository import ChampionRecord
from app.providers.lolalytics_build_provider import (
    LolalyticsBuildsProvider,
    MatchupBuildData,
    RuneStatEntry,
)

logger = logging.getLogger("lda.services.rune_recommender")

# Keystones (row 0 in each rune tree)
KEYSTONE_IDS: frozenset[int] = frozenset({
    # Precision
    8005, 8008, 8010, 8021,
    # Domination
    8112, 8124, 8128,
    # Sorcery
    8214, 8229, 8230,
    # Resolve
    8437, 8439, 8465,
    # Inspiration
    8351, 8360, 8369,
})

# Position weights: how much each enemy position matters for rune choice
LANE_OPPONENT_WEIGHT = 3.0
JUNGLE_WEIGHT = 1.5
DEFAULT_WEIGHT = 1.0

MIN_GAMES_PER_MATCHUP = 30


@dataclass(slots=True)
class MatchupRuneDetail:
    opponent_name: str
    opponent_id: int
    opponent_role: str
    win_rate: float
    games: int


@dataclass(slots=True)
class RunePageRecommendation:
    keystone_id: int
    weighted_score: float
    total_games: int
    avg_win_rate: float
    matchup_details: list[MatchupRuneDetail] = field(default_factory=list)


@dataclass(slots=True)
class RuneRecommendationResult:
    rune_pages: list[RunePageRecommendation]
    per_rune_stats: list[RuneStatAggregated]
    fallback_used: bool


@dataclass(slots=True)
class RuneStatAggregated:
    """Aggregated stats for a single rune across all matchups."""
    rune_id: int
    weighted_win_rate: float
    total_games: int
    pick_rate: float


def _position_weight(player_role: str, opponent_role: str) -> float:
    """Determine how much an opponent's matchup should weigh in rune decisions."""
    if player_role == opponent_role:
        return LANE_OPPONENT_WEIGHT
    if opponent_role == "jungle":
        return JUNGLE_WEIGHT
    if player_role == "jungle":
        # Junglers face everyone — weight all equally
        return JUNGLE_WEIGHT
    return DEFAULT_WEIGHT


async def recommend_runes(
    *,
    provider: LolalyticsBuildsProvider,
    champion_slug: str,
    champion_id: int,
    role: str,
    enemies: list[dict],
    champion_lookup: dict[int, ChampionRecord],
    tier: str = "emerald_plus",
) -> RuneRecommendationResult:
    """Recommend rune pages based on enemy team composition.

    Args:
        enemies: list of {"slug": str, "champion_id": int, "role": str}

    Returns top 3 rune page recommendations sorted by weighted score.
    """
    # Fetch vs data for each enemy + general build as fallback
    matchup_results = await provider.fetch_matchup_builds(
        champion_slug=champion_slug,
        champion_id=champion_id,
        role=role,
        enemies=enemies,
        tier=tier,
    )
    general_build = await provider.fetch_general_build(
        champion_slug=champion_slug,
        champion_id=champion_id,
        role=role,
        tier=tier,
    )

    # Pair each result with its enemy info
    matchup_pairs: list[tuple[dict, MatchupBuildData]] = []
    for enemy, result in zip(enemies, matchup_results):
        if result is not None and result.total_games >= MIN_GAMES_PER_MATCHUP:
            matchup_pairs.append((enemy, result))

    fallback_used = len(matchup_pairs) == 0
    if fallback_used and general_build is not None:
        # Use general build as the sole data source
        matchup_pairs = [({"slug": "", "champion_id": 0, "role": ""}, general_build)]

    if not matchup_pairs:
        return RuneRecommendationResult(rune_pages=[], per_rune_stats=[], fallback_used=True)

    # Aggregate keystone scores across matchups
    keystone_scores: dict[int, dict] = {}  # keystone_id -> {score, games, details}
    rune_aggregated: dict[int, dict] = {}  # rune_id -> {weighted_wr_sum, weight_sum, games}

    for enemy_info, build_data in matchup_pairs:
        weight = _position_weight(role, enemy_info.get("role", ""))
        opponent_name = ""
        opp_id = enemy_info.get("champion_id", 0)
        if opp_id and opp_id in champion_lookup:
            opponent_name = champion_lookup[opp_id].name

        for rune_stat in build_data.rune_stats:
            rid = rune_stat.rune_id
            if rune_stat.games <= 0:
                continue

            # Aggregate per-rune stats
            if rid not in rune_aggregated:
                rune_aggregated[rid] = {"weighted_wr_sum": 0.0, "weight_sum": 0.0, "games": 0, "pr_sum": 0.0, "count": 0}
            agg = rune_aggregated[rid]
            agg["weighted_wr_sum"] += rune_stat.win_rate * weight * rune_stat.games
            agg["weight_sum"] += weight * rune_stat.games
            agg["games"] += rune_stat.games
            agg["pr_sum"] += rune_stat.pick_rate
            agg["count"] += 1

            # Aggregate keystone scores
            if rid in KEYSTONE_IDS:
                if rid not in keystone_scores:
                    keystone_scores[rid] = {"score": 0.0, "weight_sum": 0.0, "games": 0, "details": []}
                ks = keystone_scores[rid]
                ks["score"] += rune_stat.win_rate * weight * rune_stat.games
                ks["weight_sum"] += weight * rune_stat.games
                ks["games"] += rune_stat.games
                if opp_id:
                    ks["details"].append(MatchupRuneDetail(
                        opponent_name=opponent_name,
                        opponent_id=opp_id,
                        opponent_role=enemy_info.get("role", ""),
                        win_rate=rune_stat.win_rate,
                        games=rune_stat.games,
                    ))

    # Build keystone recommendations
    rune_pages: list[RunePageRecommendation] = []
    for ks_id, ks_data in keystone_scores.items():
        if ks_data["weight_sum"] <= 0:
            continue
        avg_wr = ks_data["score"] / ks_data["weight_sum"]
        rune_pages.append(RunePageRecommendation(
            keystone_id=ks_id,
            weighted_score=ks_data["score"],
            total_games=ks_data["games"],
            avg_win_rate=round(avg_wr, 2),
            matchup_details=ks_data["details"],
        ))

    rune_pages.sort(key=lambda p: p.weighted_score, reverse=True)

    # Build per-rune aggregated stats
    per_rune: list[RuneStatAggregated] = []
    for rid, agg in rune_aggregated.items():
        if agg["weight_sum"] <= 0:
            continue
        per_rune.append(RuneStatAggregated(
            rune_id=rid,
            weighted_win_rate=round(agg["weighted_wr_sum"] / agg["weight_sum"], 2),
            total_games=agg["games"],
            pick_rate=round(agg["pr_sum"] / agg["count"], 2) if agg["count"] > 0 else 0.0,
        ))

    return RuneRecommendationResult(
        rune_pages=rune_pages[:3],
        per_rune_stats=per_rune,
        fallback_used=fallback_used,
    )
