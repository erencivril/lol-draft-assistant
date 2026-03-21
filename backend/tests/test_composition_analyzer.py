from __future__ import annotations

import pytest

from app.domain.champion_metadata import ChampionCompositionProfile
from app.services.composition_analyzer import TeamCompositionAnalysis, analyze_composition


def _make_profile(
    champion_id: int = 1,
    *,
    damage_physical_pct: float = 0.33,
    damage_magic_pct: float = 0.33,
    damage_true_pct: float = 0.34,
    cc_hard_seconds: float = 1.5,
    cc_soft_seconds: float = 1.0,
    engage_score: float = 0.5,
    disengage_score: float = 0.5,
    frontline_score: float = 0.5,
    poke_score: float = 0.3,
    split_score: float = 0.3,
    teamfight_score: float = 0.5,
    protect_score: float = 0.3,
    scaling: float = 0.5,
    flex_roles: list[str] | None = None,
    tags: list[str] | None = None,
) -> ChampionCompositionProfile:
    return ChampionCompositionProfile(
        champion_id=champion_id,
        damage_physical_pct=damage_physical_pct,
        damage_magic_pct=damage_magic_pct,
        damage_true_pct=damage_true_pct,
        cc_hard_seconds=cc_hard_seconds,
        cc_soft_seconds=cc_soft_seconds,
        engage_score=engage_score,
        disengage_score=disengage_score,
        frontline_score=frontline_score,
        poke_score=poke_score,
        split_score=split_score,
        teamfight_score=teamfight_score,
        protect_score=protect_score,
        scaling=scaling,
        flex_roles=flex_roles or [],
        tags=tags or [],
    )


class TestDamageBalance:
    """Tests for damage balance scoring and warnings."""

    def test_full_ad_team_low_score_with_warning(self) -> None:
        """A team of all-physical-damage champions should score low and warn."""
        ad_profile = _make_profile(
            damage_physical_pct=0.90,
            damage_magic_pct=0.05,
            damage_true_pct=0.05,
        )
        team = [_make_profile(i, damage_physical_pct=0.90, damage_magic_pct=0.05, damage_true_pct=0.05) for i in range(2, 5)]
        result = analyze_composition(team, ad_profile)

        assert result.damage_balance_score < 0.5
        assert any("fiziksel hasar" in w for w in result.warnings)

    def test_full_ap_team_low_score_with_warning(self) -> None:
        """A team of all-magic-damage champions should score low and warn."""
        ap_profile = _make_profile(
            damage_physical_pct=0.05,
            damage_magic_pct=0.90,
            damage_true_pct=0.05,
        )
        team = [_make_profile(i, damage_physical_pct=0.05, damage_magic_pct=0.90, damage_true_pct=0.05) for i in range(2, 5)]
        result = analyze_composition(team, ap_profile)

        assert result.damage_balance_score < 0.5
        assert any("buyu hasari" in w for w in result.warnings)

    def test_balanced_team_high_score(self) -> None:
        """A team with even damage split should score near 1.0."""
        balanced = _make_profile(
            damage_physical_pct=0.34,
            damage_magic_pct=0.33,
            damage_true_pct=0.33,
        )
        team = [_make_profile(i, damage_physical_pct=0.34, damage_magic_pct=0.33, damage_true_pct=0.33) for i in range(2, 5)]
        result = analyze_composition(team, balanced)

        assert result.damage_balance_score > 0.95
        assert not any("fiziksel hasar" in w for w in result.warnings)
        assert not any("buyu hasari" in w for w in result.warnings)

    def test_no_damage_warning_when_below_threshold(self) -> None:
        """A team with 70% physical should NOT trigger the warning (threshold is 75%)."""
        profile = _make_profile(
            damage_physical_pct=0.70,
            damage_magic_pct=0.20,
            damage_true_pct=0.10,
        )
        team = [_make_profile(i, damage_physical_pct=0.70, damage_magic_pct=0.20, damage_true_pct=0.10) for i in range(2, 5)]
        result = analyze_composition(team, profile)

        assert not any("fiziksel hasar" in w for w in result.warnings)


class TestCCScore:
    """Tests for CC adequacy scoring."""

    def test_high_cc_team(self) -> None:
        """A team with plenty of hard CC should score near 1.0."""
        profile = _make_profile(cc_hard_seconds=2.5)
        team = [_make_profile(i, cc_hard_seconds=2.5) for i in range(2, 5)]
        result = analyze_composition(team, profile)

        # 4 * 2.5 = 10s total, min(1.0, 10/8) = 1.0
        assert result.cc_score == 1.0
        assert not any("hard CC" in w for w in result.warnings)

    def test_low_cc_team_warns(self) -> None:
        """A team with almost no hard CC should warn."""
        profile = _make_profile(cc_hard_seconds=0.3)
        team = [_make_profile(i, cc_hard_seconds=0.3) for i in range(2, 5)]
        result = analyze_composition(team, profile)

        # 4 * 0.3 = 1.2s total < 2.0
        assert result.cc_score < 0.25
        assert any("hard CC" in w for w in result.warnings)


class TestEngageScore:
    """Tests for engage capacity scoring."""

    def test_no_engage_team_warns(self) -> None:
        """A team where nobody has engage should warn."""
        profile = _make_profile(engage_score=0.1)
        team = [_make_profile(i, engage_score=0.1) for i in range(2, 5)]
        result = analyze_composition(team, profile)

        assert result.engage_score < 0.2
        assert any("engage" in w for w in result.warnings)

    def test_one_strong_engager(self) -> None:
        """Even one strong engager should prevent the warning."""
        team = [_make_profile(i, engage_score=0.1) for i in range(2, 5)]
        engager = _make_profile(engage_score=0.9)
        result = analyze_composition(team, engager)

        # max=0.9, avg=(0.1+0.1+0.1+0.9)/4=0.3 -> 0.6*0.9 + 0.4*0.3 = 0.66
        assert result.engage_score > 0.5
        assert not any("engage" in w for w in result.warnings)


class TestFrontlineScore:
    """Tests for frontline presence scoring."""

    def test_no_frontline_warns(self) -> None:
        """A team of squishies (frontline_score <= 0.6) should warn."""
        profile = _make_profile(frontline_score=0.2)
        team = [_make_profile(i, frontline_score=0.2) for i in range(2, 5)]
        result = analyze_composition(team, profile)

        assert result.frontline_score == 0.0
        assert any("frontline" in w for w in result.warnings)

    def test_two_frontliners_max_score(self) -> None:
        """Two frontliners should cap the score at 1.0."""
        team = [
            _make_profile(2, frontline_score=0.8),
            _make_profile(3, frontline_score=0.9),
            _make_profile(4, frontline_score=0.2),
        ]
        candidate = _make_profile(frontline_score=0.2)
        result = analyze_composition(team, candidate)

        assert result.frontline_score == 1.0
        assert not any("frontline" in w for w in result.warnings)


class TestDisengageScore:
    """Tests for disengage scoring."""

    def test_disengage_blended(self) -> None:
        """Disengage should blend max and average (60/40)."""
        team = [
            _make_profile(2, disengage_score=0.2),
            _make_profile(3, disengage_score=0.2),
            _make_profile(4, disengage_score=0.2),
        ]
        candidate = _make_profile(disengage_score=0.8)
        result = analyze_composition(team, candidate)

        # max=0.8, avg=(0.2+0.2+0.2+0.8)/4=0.35 -> 0.6*0.8 + 0.4*0.35 = 0.62
        assert abs(result.disengage_score - 0.62) < 0.01


class TestArchetypeDetection:
    """Tests for archetype detection and coherence."""

    def test_teamfight_comp_detected(self) -> None:
        """A team with high teamfight scores should be detected as teamfight."""
        tf_profile = _make_profile(
            teamfight_score=0.9,
            poke_score=0.1,
            split_score=0.1,
            protect_score=0.1,
            engage_score=0.3,
        )
        team = [
            _make_profile(
                i,
                teamfight_score=0.9,
                poke_score=0.1,
                split_score=0.1,
                protect_score=0.1,
                engage_score=0.3,
            )
            for i in range(2, 5)
        ]
        result = analyze_composition(team, tf_profile)

        assert result.archetype == "teamfight"
        assert result.coherence_score > 0.5

    def test_split_comp_detected(self) -> None:
        """A team with high split scores should be detected as split."""
        split_profile = _make_profile(
            split_score=0.85,
            teamfight_score=0.1,
            poke_score=0.1,
            protect_score=0.1,
            engage_score=0.1,
        )
        team = [
            _make_profile(
                i,
                split_score=0.85,
                teamfight_score=0.1,
                poke_score=0.1,
                protect_score=0.1,
                engage_score=0.1,
            )
            for i in range(2, 5)
        ]
        result = analyze_composition(team, split_profile)

        assert result.archetype == "split"
        assert result.coherence_score > 0.5

    def test_balanced_when_no_dominant_archetype(self) -> None:
        """When archetype scores are close, the team should be classified as balanced."""
        even_profile = _make_profile(
            teamfight_score=0.5,
            poke_score=0.5,
            split_score=0.5,
            protect_score=0.5,
            engage_score=0.5,
        )
        team = [
            _make_profile(
                i,
                teamfight_score=0.5,
                poke_score=0.5,
                split_score=0.5,
                protect_score=0.5,
                engage_score=0.5,
            )
            for i in range(2, 5)
        ]
        result = analyze_composition(team, even_profile)

        assert result.archetype == "balanced"
        assert result.coherence_score == 0.5


class TestCompositionTotal:
    """Tests for the weighted aggregate score."""

    def test_total_is_weighted_sum(self) -> None:
        """composition_total must equal the documented weight formula."""
        profile = _make_profile()
        team = [_make_profile(i) for i in range(2, 5)]
        result = analyze_composition(team, profile)

        expected = (
            result.damage_balance_score * 0.35
            + result.cc_score * 0.15
            + result.engage_score * 0.15
            + result.frontline_score * 0.15
            + result.coherence_score * 0.10
            + result.disengage_score * 0.10
        )
        assert abs(result.composition_total - expected) < 1e-9

    def test_total_bounded_zero_one(self) -> None:
        """composition_total must always fall between 0 and 1."""
        # Worst-case team: all zeros
        awful = _make_profile(
            damage_physical_pct=0.98,
            damage_magic_pct=0.01,
            damage_true_pct=0.01,
            cc_hard_seconds=0.0,
            engage_score=0.0,
            disengage_score=0.0,
            frontline_score=0.0,
            teamfight_score=0.0,
            poke_score=0.0,
            split_score=0.0,
            protect_score=0.0,
        )
        team = [
            _make_profile(
                i,
                damage_physical_pct=0.98,
                damage_magic_pct=0.01,
                damage_true_pct=0.01,
                cc_hard_seconds=0.0,
                engage_score=0.0,
                disengage_score=0.0,
                frontline_score=0.0,
                teamfight_score=0.0,
                poke_score=0.0,
                split_score=0.0,
                protect_score=0.0,
            )
            for i in range(2, 5)
        ]
        result = analyze_composition(team, awful)

        assert 0.0 <= result.composition_total <= 1.0


class TestMinimalTeam:
    """Edge cases with a single-member team."""

    def test_single_candidate_no_team(self) -> None:
        """Works with empty team_profiles (just the candidate)."""
        candidate = _make_profile(
            cc_hard_seconds=3.0,
            engage_score=0.8,
            frontline_score=0.7,
        )
        result = analyze_composition([], candidate)

        assert isinstance(result, TeamCompositionAnalysis)
        assert 0.0 <= result.composition_total <= 1.0
