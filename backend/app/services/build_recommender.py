"""Build recommendation service: aggregates per-matchup item data to suggest optimal build order."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.db.repository import ChampionRecord
from app.providers.lolalytics_build_provider import (
    ItemBuildEntry,
    LolalyticsBuildsProvider,
    MatchupBuildData,
)
logger = logging.getLogger("lda.services.build_recommender")

# Position weights for build decisions (lane opponent matters most)
LANE_OPPONENT_WEIGHT = 4.0
JUNGLE_WEIGHT = 2.0
DEFAULT_WEIGHT = 1.0

# Keystone coherence: items that appear in keystone-filtered builds get a small bonus
KEYSTONE_COHERENCE_BONUS = 1.15

MIN_GAMES_PER_MATCHUP = 20
MIN_MATCHUPS_FOR_AGGREGATION = 1

# Boot item IDs (tier 2 boots)
BOOT_IDS: frozenset[int] = frozenset({
    3005, 3006, 3009, 3010, 3013, 3020, 3047, 3111, 3117, 3158,
})

# Starter item IDs
STARTER_IDS: frozenset[int] = frozenset({
    1054, 1055, 1056, 1082, 1083, 1101, 1102, 1103,
    2003, 2010, 2031, 2033, 2051, 2052, 3070, 3112,
    3850, 3851, 3854, 3855, 3858, 3859, 3862, 3863,
    3865, 3866, 3867, 3869, 3870, 3871, 3876, 3877,
})


@dataclass(slots=True)
class ItemRecommendation:
    """A recommended item for a specific build slot."""
    item_id: int
    weighted_score: float
    total_games: int
    avg_win_rate: float
    matchup_contributions: list[ItemMatchupContribution] = field(default_factory=list)


@dataclass(slots=True)
class ItemMatchupContribution:
    opponent_name: str
    opponent_id: int
    opponent_role: str
    win_rate: float
    games: int
    position_weight: float


@dataclass(slots=True)
class MatchupSummary:
    """Top-level summary of a single enemy matchup used in this recommendation."""
    opponent_name: str
    opponent_id: int
    opponent_role: str
    overall_win_rate: float
    total_games: int
    position_weight: float


@dataclass(slots=True)
class BuildSlot:
    """A build slot with primary recommendation and alternatives."""
    slot_name: str  # "starter", "boots", "item1", "item2", ...
    primary: ItemRecommendation | None = None
    alternatives: list[ItemRecommendation] = field(default_factory=list)


@dataclass(slots=True)
class BuildRecommendationResult:
    slots: list[BuildSlot]
    skill_order: str | None
    keystone_used: int | None
    fallback_used: bool
    matchup_summaries: list[MatchupSummary] = field(default_factory=list)


def _position_weight(player_role: str, opponent_role: str) -> float:
    """Determine how much an opponent's matchup should weigh in build decisions."""
    if player_role == opponent_role:
        return LANE_OPPONENT_WEIGHT
    if opponent_role == "jungle":
        return JUNGLE_WEIGHT
    if player_role == "jungle":
        return JUNGLE_WEIGHT
    return DEFAULT_WEIGHT


def _aggregate_slot_items(
    matchup_pairs: list[tuple[dict, MatchupBuildData]],
    slot_attr: str,
    player_role: str,
    champion_lookup: dict[int, ChampionRecord],
    exclude_ids: frozenset[int] | None = None,
    keystone_item_set: frozenset[int] | None = None,
) -> list[ItemRecommendation]:
    """Aggregate item stats across matchups for a given build slot."""
    # item_id -> {score, weight_sum, games, contributions}
    item_scores: dict[int, dict] = {}

    for enemy_info, build_data in matchup_pairs:
        weight = _position_weight(player_role, enemy_info.get("role", ""))
        opp_id = enemy_info.get("champion_id", 0)
        opponent_name = ""
        if opp_id and opp_id in champion_lookup:
            opponent_name = champion_lookup[opp_id].name

        items: list[ItemBuildEntry] = getattr(build_data, slot_attr, [])
        for item in items:
            iid = item.item_id
            if exclude_ids and iid in exclude_ids:
                continue
            if item.games <= 0:
                continue

            games_factor = min(1.0, item.games / 100)
            score = item.win_rate * weight * games_factor * item.pick_rate

            # Keystone coherence bonus
            if keystone_item_set and iid in keystone_item_set:
                score *= KEYSTONE_COHERENCE_BONUS

            if iid not in item_scores:
                item_scores[iid] = {
                    "score": 0.0,
                    "weight_sum": 0.0,
                    "games": 0,
                    "wr_sum": 0.0,
                    "contributions": [],
                }
            agg = item_scores[iid]
            agg["score"] += score
            agg["weight_sum"] += weight * games_factor * item.pick_rate
            agg["games"] += item.games
            agg["wr_sum"] += item.win_rate * item.games
            if opp_id:
                agg["contributions"].append(ItemMatchupContribution(
                    opponent_name=opponent_name,
                    opponent_id=opp_id,
                    opponent_role=enemy_info.get("role", ""),
                    win_rate=item.win_rate,
                    games=item.games,
                    position_weight=weight,
                ))

    recommendations: list[ItemRecommendation] = []
    for iid, agg in item_scores.items():
        if agg["games"] <= 0:
            continue
        avg_wr = agg["wr_sum"] / agg["games"]
        recommendations.append(ItemRecommendation(
            item_id=iid,
            weighted_score=agg["score"],
            total_games=agg["games"],
            avg_win_rate=round(avg_wr, 2),
            matchup_contributions=agg["contributions"],
        ))

    recommendations.sort(key=lambda r: r.weighted_score, reverse=True)
    return recommendations


def _build_slot(
    name: str,
    matchup_pairs: list[tuple[dict, MatchupBuildData]],
    slot_attr: str,
    player_role: str,
    champion_lookup: dict[int, ChampionRecord],
    already_picked: set[int],
    max_alternatives: int = 3,
    keystone_item_set: frozenset[int] | None = None,
) -> BuildSlot:
    """Build a single slot recommendation, excluding already-picked items."""
    items = _aggregate_slot_items(
        matchup_pairs, slot_attr, player_role, champion_lookup,
        exclude_ids=frozenset(already_picked),
        keystone_item_set=keystone_item_set,
    )
    slot = BuildSlot(slot_name=name)
    for item in items:
        if slot.primary is None:
            slot.primary = item
        elif len(slot.alternatives) < max_alternatives:
            slot.alternatives.append(item)
        else:
            break
    return slot


async def recommend_build(
    *,
    provider: LolalyticsBuildsProvider,
    champion_slug: str,
    champion_id: int,
    role: str,
    keystone_id: int | None,
    enemies: list[dict],
    champion_lookup: dict[int, ChampionRecord],
    tier: str = "emerald_plus",
) -> BuildRecommendationResult:
    """Recommend item build based on enemy team composition.

    Args:
        keystone_id: If provided, prefer builds matching this keystone (future filtering).
        enemies: list of {"slug": str, "champion_id": int, "role": str}

    Returns build recommendation with per-slot items.
    """
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

    # Fetch keystone-filtered general build for coherence scoring
    keystone_build = None
    if keystone_id:
        keystone_build = await provider.fetch_general_build(
            champion_slug=champion_slug,
            champion_id=champion_id,
            role=role,
            keystone_id=keystone_id,
            tier=tier,
        )

    # Build keystone-coherent item set from keystone-filtered build
    keystone_item_set: frozenset[int] | None = None
    if keystone_build:
        ks_items: set[int] = set()
        for slot_attr in ("boots", "start_items", "item1", "item2", "item3", "item4", "item5"):
            items = getattr(keystone_build, slot_attr, [])
            for item in items[:5]:
                ks_items.add(item.item_id)
        if ks_items:
            keystone_item_set = frozenset(ks_items)

    matchup_pairs: list[tuple[dict, MatchupBuildData]] = []
    for enemy, result in zip(enemies, matchup_results):
        if result is not None and result.total_games >= MIN_GAMES_PER_MATCHUP:
            matchup_pairs.append((enemy, result))

    fallback_used = len(matchup_pairs) < MIN_MATCHUPS_FOR_AGGREGATION
    if fallback_used and general_build is not None:
        matchup_pairs = [
            ({"slug": "", "champion_id": 0, "role": ""}, general_build)
        ]

    if not matchup_pairs:
        return BuildRecommendationResult(
            slots=[], skill_order=None, keystone_used=None, fallback_used=True,
        )

    # Build matchup summaries for UI
    matchup_summaries: list[MatchupSummary] = []
    for enemy_info, build_data in matchup_pairs:
        opp_id = enemy_info.get("champion_id", 0)
        if not opp_id:
            continue
        opp_name = ""
        if opp_id in champion_lookup:
            opp_name = champion_lookup[opp_id].name
        opp_role = enemy_info.get("role", "")
        weight = _position_weight(role, opp_role)
        matchup_summaries.append(MatchupSummary(
            opponent_name=opp_name,
            opponent_id=opp_id,
            opponent_role=opp_role,
            overall_win_rate=build_data.overall_win_rate,
            total_games=build_data.total_games,
            position_weight=weight,
        ))

    # Build each slot, tracking picked items to avoid duplicates
    already_picked: set[int] = set()
    slots: list[BuildSlot] = []

    # Starter items
    starter_slot = _build_slot(
        "starter", matchup_pairs, "start_items", role, champion_lookup,
        already_picked, keystone_item_set=keystone_item_set,
    )
    slots.append(starter_slot)
    if starter_slot.primary:
        already_picked.add(starter_slot.primary.item_id)

    # Boots
    boots_slot = _build_slot(
        "boots", matchup_pairs, "boots", role, champion_lookup,
        already_picked, keystone_item_set=keystone_item_set,
    )
    slots.append(boots_slot)
    if boots_slot.primary:
        already_picked.add(boots_slot.primary.item_id)

    # Core items (item1 through item5)
    for i in range(1, 6):
        slot_attr = f"item{i}"
        item_slot = _build_slot(
            slot_attr, matchup_pairs, slot_attr, role, champion_lookup,
            already_picked, keystone_item_set=keystone_item_set,
        )
        slots.append(item_slot)
        if item_slot.primary:
            already_picked.add(item_slot.primary.item_id)

    # Determine most common skill order from matchup data
    skill_orders: dict[str, int] = {}
    for _, build_data in matchup_pairs:
        if build_data.skill_order:
            skill_orders[build_data.skill_order] = (
                skill_orders.get(build_data.skill_order, 0) + build_data.total_games
            )
    skill_order = max(skill_orders, key=skill_orders.get) if skill_orders else None

    return BuildRecommendationResult(
        slots=slots,
        skill_order=skill_order,
        keystone_used=keystone_id if keystone_build else None,
        fallback_used=fallback_used,
        matchup_summaries=matchup_summaries,
    )
