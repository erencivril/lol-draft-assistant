"""Build recommendation service: aggregates per-matchup item data to suggest optimal build order."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

from app.db.repository import ChampionRecord
from app.providers.lolalytics_build_provider import (
    TIER_CASCADE,
    ItemBuildEntry,
    LolalyticsBuildsProvider,
    MatchupBuildData,
    SpellEntry,
    SkillEarlyLevel,
    SkillLevelPath,
    _normalize_tier,
)
from app.services.recommender_shared import (
    LANE_OPPONENT_WEIGHT, JUNGLE_WEIGHT, DEFAULT_WEIGHT,
    MIN_GAMES_PER_MATCHUP, position_weight,
)

logger = logging.getLogger("lda.services.build_recommender")

# Keystone coherence: items that appear in keystone-filtered builds get a small bonus
KEYSTONE_COHERENCE_BONUS = 1.15
MIN_MATCHUPS_FOR_AGGREGATION = 1
MIN_ITEM_GAMES = 10

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

# Consumable / ward IDs to exclude from starter slot recommendations
CONSUMABLE_IDS: frozenset[int] = frozenset({
    2003,   # Health Potion
    2010,   # Total Biscuit
    2031,   # Refillable Potion
    2051,   # Guardian's Horn (ARAM)
    2052,   # Poro-Snax (ARAM)
    3340,   # Stealth Ward
    3364,   # Oracle Lens
    3363,   # Farsight Alteration
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
class SpellRecommendation:
    """A recommended summoner spell combination."""
    spell1_id: int
    spell2_id: int
    weighted_score: float
    total_games: int
    avg_win_rate: float
    pick_rate: float


@dataclass(slots=True)
class SkillEarlyRecommendation:
    """Recommended ability for a specific early level."""
    level: int
    best_ability: str  # "Q", "W", "E"
    win_rate: float
    pick_rate: float
    games: int
    alternatives: list[dict]  # [{ability, wr, pr, games}]


@dataclass(slots=True)
class SkillPathRecommendation:
    """A recommended skill leveling path."""
    through_level: int  # 6 or 15
    sequence: str
    abilities: list[str]
    weighted_score: float
    total_games: int
    avg_win_rate: float


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
    summoner_spells: list[SpellRecommendation] = field(default_factory=list)
    skill_early: list[SkillEarlyRecommendation] = field(default_factory=list)
    skill_paths: list[SkillPathRecommendation] = field(default_factory=list)


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
        weight = position_weight(player_role, enemy_info.get("role", ""))
        opp_id = enemy_info.get("champion_id", 0)
        opponent_name = ""
        if opp_id and opp_id in champion_lookup:
            opponent_name = champion_lookup[opp_id].name

        items: list[ItemBuildEntry] = getattr(build_data, slot_attr, [])
        for item in items:
            iid = item.item_id
            if exclude_ids and iid in exclude_ids:
                continue
            if item.games < MIN_ITEM_GAMES:
                continue

            games_factor = min(1.0, item.games / 200)
            pr_factor = math.log1p(item.pick_rate) / math.log1p(100)
            score = item.win_rate * weight * games_factor * pr_factor

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
            agg["weight_sum"] += weight * games_factor * pr_factor
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


def _aggregate_spells(
    matchup_pairs: list[tuple[dict, MatchupBuildData]],
    player_role: str,
) -> list[SpellRecommendation]:
    """Aggregate summoner spell stats across matchups."""
    spell_scores: dict[tuple[int, int], dict] = {}

    for enemy_info, build_data in matchup_pairs:
        weight = position_weight(player_role, enemy_info.get("role", ""))
        for spell in build_data.spells:
            if spell.games < MIN_ITEM_GAMES:
                continue
            # Normalize pair order so (4,14) == (14,4)
            key = (min(spell.spell1_id, spell.spell2_id), max(spell.spell1_id, spell.spell2_id))
            games_factor = min(1.0, spell.games / 200)
            pr_factor = math.log1p(spell.pick_rate) / math.log1p(100)
            score = spell.win_rate * weight * games_factor * pr_factor

            if key not in spell_scores:
                spell_scores[key] = {"score": 0.0, "games": 0, "wr_sum": 0.0, "pr_sum": 0.0, "count": 0}
            agg = spell_scores[key]
            agg["score"] += score
            agg["games"] += spell.games
            agg["wr_sum"] += spell.win_rate * spell.games
            agg["pr_sum"] += spell.pick_rate
            agg["count"] += 1

    results: list[SpellRecommendation] = []
    for (s1, s2), agg in spell_scores.items():
        if agg["games"] <= 0:
            continue
        results.append(SpellRecommendation(
            spell1_id=s1,
            spell2_id=s2,
            weighted_score=agg["score"],
            total_games=agg["games"],
            avg_win_rate=round(agg["wr_sum"] / agg["games"], 2),
            pick_rate=round(agg["pr_sum"] / agg["count"], 2) if agg["count"] else 0.0,
        ))
    results.sort(key=lambda r: r.weighted_score, reverse=True)
    return results[:3]


ABILITY_NAMES = ["Q", "W", "E", "R"]


def _aggregate_skill_early(
    matchup_pairs: list[tuple[dict, MatchupBuildData]],
    player_role: str,
) -> list[SkillEarlyRecommendation]:
    """Aggregate skill-early data across matchups for levels 1-3."""
    # level -> ability_idx -> {weighted_wr, weight, games, pr_sum, count}
    level_data: dict[int, dict[int, dict]] = {}

    for enemy_info, build_data in matchup_pairs:
        weight = position_weight(player_role, enemy_info.get("role", ""))
        for sel in build_data.skill_early:
            if sel.level > 3:
                continue
            if sel.level not in level_data:
                level_data[sel.level] = {}
            for idx, (wr, pr, games) in enumerate(sel.abilities[:4]):
                if games <= 0:
                    continue
                if idx not in level_data[sel.level]:
                    level_data[sel.level][idx] = {"wr_sum": 0.0, "w_sum": 0.0, "games": 0, "pr_sum": 0.0, "count": 0}
                agg = level_data[sel.level][idx]
                agg["wr_sum"] += wr * weight * games
                agg["w_sum"] += weight * games
                agg["games"] += games
                agg["pr_sum"] += pr
                agg["count"] += 1

    results: list[SkillEarlyRecommendation] = []
    for level in sorted(level_data.keys()):
        abilities_ranked: list[dict] = []
        for idx, agg in level_data[level].items():
            if agg["w_sum"] <= 0 or idx >= 4:
                continue
            avg_wr = agg["wr_sum"] / agg["w_sum"]
            avg_pr = agg["pr_sum"] / agg["count"] if agg["count"] else 0.0
            abilities_ranked.append({
                "ability": ABILITY_NAMES[idx],
                "wr": round(avg_wr, 1),
                "pr": round(avg_pr, 1),
                "games": agg["games"],
            })
        abilities_ranked.sort(key=lambda a: a["wr"] * a["pr"], reverse=True)
        if abilities_ranked:
            best = abilities_ranked[0]
            results.append(SkillEarlyRecommendation(
                level=level,
                best_ability=best["ability"],
                win_rate=best["wr"],
                pick_rate=best["pr"],
                games=best["games"],
                alternatives=abilities_ranked[1:],
            ))
    return results


def _aggregate_skill_paths(
    matchup_pairs: list[tuple[dict, MatchupBuildData]],
    player_role: str,
    through_level: int,
) -> list[SkillPathRecommendation]:
    """Aggregate skill paths across matchups."""
    attr = "skill_paths_6" if through_level == 6 else "skill_paths_15"
    path_scores: dict[str, dict] = {}

    for enemy_info, build_data in matchup_pairs:
        weight = position_weight(player_role, enemy_info.get("role", ""))
        paths: list[SkillLevelPath] = getattr(build_data, attr, [])
        for path in paths:
            if path.games < MIN_ITEM_GAMES:
                continue
            games_factor = min(1.0, path.games / 200)
            pr_factor = math.log1p(path.pick_rate) / math.log1p(100)
            score = path.win_rate * weight * games_factor * pr_factor

            if path.sequence not in path_scores:
                path_scores[path.sequence] = {
                    "score": 0.0, "games": 0, "wr_sum": 0.0,
                    "abilities": path.abilities,
                }
            agg = path_scores[path.sequence]
            agg["score"] += score
            agg["games"] += path.games
            agg["wr_sum"] += path.win_rate * path.games

    results: list[SkillPathRecommendation] = []
    for seq, agg in path_scores.items():
        if agg["games"] <= 0:
            continue
        results.append(SkillPathRecommendation(
            through_level=through_level,
            sequence=seq,
            abilities=agg["abilities"],
            weighted_score=agg["score"],
            total_games=agg["games"],
            avg_win_rate=round(agg["wr_sum"] / agg["games"], 2),
        ))
    results.sort(key=lambda r: r.weighted_score, reverse=True)
    return results[:3]


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
    # Deduplicate roles: if multiple enemies share a role, clear the duplicate
    seen_roles: set[str] = set()
    for enemy in enemies:
        role_val = enemy.get("role", "")
        if role_val and role_val in seen_roles:
            enemy["role"] = ""
        if role_val:
            seen_roles.add(role_val)

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
    specific_count = 0
    for enemy, result in zip(enemies, matchup_results):
        if result is not None and result.total_games >= MIN_GAMES_PER_MATCHUP:
            matchup_pairs.append((enemy, result))
            specific_count += 1
        elif general_build is not None and enemy.get("champion_id", 0):
            # Use general build as positional fallback for low-data matchups
            matchup_pairs.append((enemy, general_build))

    fallback_used = specific_count < MIN_MATCHUPS_FOR_AGGREGATION
    if fallback_used and general_build is not None:
        matchup_pairs = [
            ({"slug": "", "champion_id": 0, "role": ""}, general_build)
        ]

    # Cascading fallback: if no data at all, try broader tiers
    if not matchup_pairs:
        normalized = _normalize_tier(tier)
        try:
            start_idx = TIER_CASCADE.index(normalized) + 1
        except ValueError:
            start_idx = 0
        for fallback_tier in TIER_CASCADE[start_idx:]:
            fb_general = await provider.fetch_general_build(
                champion_slug=champion_slug, champion_id=champion_id,
                role=role, tier=fallback_tier,
            )
            if fb_general and fb_general.total_games >= MIN_GAMES_PER_MATCHUP:
                logger.info("Build cascade: %s → %s for %s", tier, fallback_tier, champion_slug)
                matchup_pairs = [({"slug": "", "champion_id": 0, "role": ""}, fb_general)]
                general_build = fb_general
                break

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
        weight = position_weight(role, opp_role)
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
        already_picked | CONSUMABLE_IDS, keystone_item_set=keystone_item_set,
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

    # Aggregate summoner spells
    summoner_spells = _aggregate_spells(matchup_pairs, role)

    # Aggregate skill early levels and paths
    skill_early = _aggregate_skill_early(matchup_pairs, role)
    skill_paths_6 = _aggregate_skill_paths(matchup_pairs, role, through_level=6)
    skill_paths_15 = _aggregate_skill_paths(matchup_pairs, role, through_level=15)

    return BuildRecommendationResult(
        slots=slots,
        skill_order=skill_order,
        keystone_used=keystone_id if keystone_build else None,
        fallback_used=fallback_used,
        matchup_summaries=matchup_summaries,
        summoner_spells=summoner_spells,
        skill_early=skill_early,
        skill_paths=skill_paths_6 + skill_paths_15,
    )
