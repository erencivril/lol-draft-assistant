from __future__ import annotations

import pytest

from app.services.rank_weights import (
    RANK_PROFILES,
    RankWeightProfile,
    get_rank_profile,
)


class TestGetRankProfile:
    """Tests for get_rank_profile lookup and fallback logic."""

    def test_exact_rank_returns_profile(self):
        """Known exact ranks return their specific profile."""
        profile = get_rank_profile("iron")
        assert profile.counter_importance == 0.50
        assert profile.composition_importance == 0.40

    def test_emerald_default_values(self):
        """Emerald profile matches the hardcoded constants it replaces."""
        profile = get_rank_profile("emerald")
        assert profile.tier_rank_weight == 0.45
        assert profile.tier_weight == 0.25
        assert profile.pbi_weight == 0.15
        assert profile.role_fit_weight == 0.15
        assert profile.counter_band_window == 0.03
        assert profile.worst_enemy_weight == 0.50
        assert profile.board_counter_weight == 0.25
        assert profile.counter_importance == 0.85
        assert profile.composition_importance == 0.70
        assert profile.flex_importance == 0.70

    def test_challenger_max_importance(self):
        """Challenger has all importance factors at 1.0."""
        profile = get_rank_profile("challenger")
        assert profile.counter_importance == 1.0
        assert profile.composition_importance == 1.0
        assert profile.flex_importance == 1.0

    def test_aggregate_rank_resolves(self):
        """Aggregate rank tiers like 'diamond_plus' resolve to a profile."""
        profile = get_rank_profile("diamond_plus")
        assert profile.counter_importance == 1.0
        assert profile.composition_importance == 0.85

    def test_unknown_rank_falls_back_to_emerald(self):
        """Unknown rank tier returns the emerald default."""
        profile = get_rank_profile("unknown_rank")
        emerald = get_rank_profile("emerald")
        assert profile is emerald

    def test_empty_string_falls_back_to_emerald(self):
        """Empty string falls back to emerald."""
        profile = get_rank_profile("")
        emerald = get_rank_profile("emerald")
        assert profile is emerald

    def test_case_insensitive_lookup(self):
        """Rank lookup should be case-insensitive via normalize_rank_tier."""
        profile = get_rank_profile("Diamond")
        assert profile.counter_importance == 1.0

    def test_plus_alias_resolves(self):
        """Plus-suffix syntax like 'grandmaster+' resolves correctly."""
        profile = get_rank_profile("grandmaster+")
        assert profile.counter_importance == 1.0
        assert profile.composition_importance == 0.95

    def test_counter_importance_increases_with_rank(self):
        """Counter importance should generally increase from low to high elo."""
        ordered_ranks = ["iron", "bronze", "silver", "gold", "platinum", "emerald", "diamond"]
        importances = [get_rank_profile(r).counter_importance for r in ordered_ranks]
        for i in range(1, len(importances)):
            assert importances[i] >= importances[i - 1], (
                f"{ordered_ranks[i]} counter_importance ({importances[i]}) "
                f"should be >= {ordered_ranks[i-1]} ({importances[i-1]})"
            )

    def test_all_profiles_are_rank_weight_profile(self):
        """All entries in RANK_PROFILES are RankWeightProfile instances."""
        for key, profile in RANK_PROFILES.items():
            assert isinstance(profile, RankWeightProfile), f"{key} is not a RankWeightProfile"

    def test_all_exact_ranks_have_profiles(self):
        """Every exact rank from the domain has a corresponding profile."""
        from app.domain.ranks import EXACT_RANKS
        for rank in EXACT_RANKS:
            assert rank in RANK_PROFILES, f"Missing profile for exact rank '{rank}'"
