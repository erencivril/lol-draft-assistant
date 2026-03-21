from __future__ import annotations

from dataclasses import dataclass

from app.domain.ranks import normalize_rank_tier


@dataclass(slots=True)
class RankWeightProfile:
    """Per-rank scoring weight profile.

    Controls how different scoring dimensions are weighted
    at different elos. Higher elo → more counter/comp emphasis.
    """
    # Pre-draft weights (must sum to ~1.0)
    tier_rank_weight: float
    tier_weight: float
    pbi_weight: float
    role_fit_weight: float

    # In-draft counter band window (wider = counter matters less)
    counter_band_window: float

    # In-draft hierarchy weights
    worst_enemy_weight: float
    board_counter_weight: float
    tier_secondary_weight: float
    synergy_weight: float
    composition_weight: float

    # Scaling factors
    counter_importance: float      # 0-1, scales counter_score
    composition_importance: float  # 0-1, scales composition_weight
    flex_importance: float         # 0-1, scales flex bonus

    # Ban weights
    ban_tier_weight: float
    ban_counter_weight: float


# Default emerald profile matches current hardcoded constants exactly
_EMERALD = RankWeightProfile(
    tier_rank_weight=0.45,
    tier_weight=0.25,
    pbi_weight=0.15,
    role_fit_weight=0.15,
    counter_band_window=0.03,
    worst_enemy_weight=0.50,
    board_counter_weight=0.25,
    tier_secondary_weight=0.125,
    synergy_weight=0.0625,
    composition_weight=0.0625,
    counter_importance=0.85,
    composition_importance=0.70,
    flex_importance=0.70,
    ban_tier_weight=0.34,
    ban_counter_weight=0.38,
)

RANK_PROFILES: dict[str, RankWeightProfile] = {
    # Low elo: tier/meta matters most, counter knowledge underutilized
    "iron": RankWeightProfile(
        tier_rank_weight=0.50, tier_weight=0.30, pbi_weight=0.10, role_fit_weight=0.10,
        counter_band_window=0.06,
        worst_enemy_weight=0.30, board_counter_weight=0.20,
        tier_secondary_weight=0.25, synergy_weight=0.10, composition_weight=0.10,
        counter_importance=0.50, composition_importance=0.40, flex_importance=0.30,
        ban_tier_weight=0.50, ban_counter_weight=0.20,
    ),
    "bronze": RankWeightProfile(
        tier_rank_weight=0.50, tier_weight=0.28, pbi_weight=0.12, role_fit_weight=0.10,
        counter_band_window=0.055,
        worst_enemy_weight=0.32, board_counter_weight=0.22,
        tier_secondary_weight=0.23, synergy_weight=0.10, composition_weight=0.10,
        counter_importance=0.55, composition_importance=0.42, flex_importance=0.35,
        ban_tier_weight=0.48, ban_counter_weight=0.22,
    ),
    "silver": RankWeightProfile(
        tier_rank_weight=0.48, tier_weight=0.27, pbi_weight=0.13, role_fit_weight=0.12,
        counter_band_window=0.05,
        worst_enemy_weight=0.35, board_counter_weight=0.22,
        tier_secondary_weight=0.22, synergy_weight=0.10, composition_weight=0.10,
        counter_importance=0.60, composition_importance=0.45, flex_importance=0.40,
        ban_tier_weight=0.45, ban_counter_weight=0.25,
    ),
    "gold": RankWeightProfile(
        tier_rank_weight=0.45, tier_weight=0.25, pbi_weight=0.15, role_fit_weight=0.15,
        counter_band_window=0.04,
        worst_enemy_weight=0.40, board_counter_weight=0.25,
        tier_secondary_weight=0.18, synergy_weight=0.08, composition_weight=0.08,
        counter_importance=0.70, composition_importance=0.50, flex_importance=0.50,
        ban_tier_weight=0.40, ban_counter_weight=0.30,
    ),
    "platinum": RankWeightProfile(
        tier_rank_weight=0.45, tier_weight=0.25, pbi_weight=0.15, role_fit_weight=0.15,
        counter_band_window=0.035,
        worst_enemy_weight=0.45, board_counter_weight=0.25,
        tier_secondary_weight=0.15, synergy_weight=0.07, composition_weight=0.07,
        counter_importance=0.80, composition_importance=0.60, flex_importance=0.60,
        ban_tier_weight=0.38, ban_counter_weight=0.34,
    ),
    "emerald": _EMERALD,
    "diamond": RankWeightProfile(
        tier_rank_weight=0.40, tier_weight=0.20, pbi_weight=0.15, role_fit_weight=0.15,
        counter_band_window=0.025,
        worst_enemy_weight=0.55, board_counter_weight=0.25,
        tier_secondary_weight=0.10, synergy_weight=0.06, composition_weight=0.06,
        counter_importance=1.0, composition_importance=0.85, flex_importance=0.85,
        ban_tier_weight=0.28, ban_counter_weight=0.42,
    ),
    "master": RankWeightProfile(
        tier_rank_weight=0.38, tier_weight=0.18, pbi_weight=0.15, role_fit_weight=0.12,
        counter_band_window=0.022,
        worst_enemy_weight=0.58, board_counter_weight=0.25,
        tier_secondary_weight=0.09, synergy_weight=0.05, composition_weight=0.05,
        counter_importance=1.0, composition_importance=0.90, flex_importance=0.90,
        ban_tier_weight=0.26, ban_counter_weight=0.44,
    ),
    "grandmaster": RankWeightProfile(
        tier_rank_weight=0.36, tier_weight=0.16, pbi_weight=0.15, role_fit_weight=0.12,
        counter_band_window=0.02,
        worst_enemy_weight=0.58, board_counter_weight=0.25,
        tier_secondary_weight=0.08, synergy_weight=0.05, composition_weight=0.05,
        counter_importance=1.0, composition_importance=0.95, flex_importance=0.95,
        ban_tier_weight=0.25, ban_counter_weight=0.45,
    ),
    "challenger": RankWeightProfile(
        tier_rank_weight=0.35, tier_weight=0.15, pbi_weight=0.15, role_fit_weight=0.10,
        counter_band_window=0.02,
        worst_enemy_weight=0.60, board_counter_weight=0.25,
        tier_secondary_weight=0.08, synergy_weight=0.05, composition_weight=0.05,
        counter_importance=1.0, composition_importance=1.0, flex_importance=1.0,
        ban_tier_weight=0.25, ban_counter_weight=0.45,
    ),
    # Aggregate tiers: use reasonable defaults
    "all": _EMERALD,
    "gold_plus": _EMERALD,
    "platinum_plus": _EMERALD,
    "emerald_plus": _EMERALD,
    "diamond_plus": RankWeightProfile(
        tier_rank_weight=0.40, tier_weight=0.20, pbi_weight=0.15, role_fit_weight=0.15,
        counter_band_window=0.025,
        worst_enemy_weight=0.55, board_counter_weight=0.25,
        tier_secondary_weight=0.10, synergy_weight=0.06, composition_weight=0.06,
        counter_importance=1.0, composition_importance=0.85, flex_importance=0.85,
        ban_tier_weight=0.28, ban_counter_weight=0.42,
    ),
    "grandmaster_plus": RankWeightProfile(
        tier_rank_weight=0.36, tier_weight=0.16, pbi_weight=0.15, role_fit_weight=0.12,
        counter_band_window=0.02,
        worst_enemy_weight=0.58, board_counter_weight=0.25,
        tier_secondary_weight=0.08, synergy_weight=0.05, composition_weight=0.05,
        counter_importance=1.0, composition_importance=0.95, flex_importance=0.95,
        ban_tier_weight=0.25, ban_counter_weight=0.45,
    ),
}


def get_rank_profile(rank_tier: str) -> RankWeightProfile:
    """Look up rank profile, falling back to emerald as default."""
    normalized = normalize_rank_tier(rank_tier)
    if normalized and normalized in RANK_PROFILES:
        return RANK_PROFILES[normalized]
    return _EMERALD
