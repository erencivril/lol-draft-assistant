from __future__ import annotations

from dataclasses import dataclass, field
from math import log2
from statistics import mean

from app.domain.champion_metadata import ChampionCompositionProfile


@dataclass(slots=True)
class TeamCompositionAnalysis:
    damage_balance_score: float  # Shannon entropy normalized [0-1], 1.0 = perfect balance
    cc_score: float  # Team CC adequacy [0-1]
    engage_score: float  # Team engage capacity [0-1]
    frontline_score: float  # Frontline presence [0-1]
    disengage_score: float  # Peel/disengage [0-1]
    archetype: str  # "teamfight"|"poke"|"engage"|"split"|"protect"|"balanced"
    coherence_score: float  # Archetype consistency [0-1]
    composition_total: float  # Weighted aggregate [0-1]
    warnings: list[str] = field(default_factory=list)


def analyze_composition(
    team_profiles: list[ChampionCompositionProfile],
    candidate_profile: ChampionCompositionProfile,
) -> TeamCompositionAnalysis:
    """Analyze how well a candidate champion fits with existing team profiles.

    Parameters
    ----------
    team_profiles:
        Composition profiles for already-picked allies.
    candidate_profile:
        Profile for the champion being evaluated.

    Returns
    -------
    TeamCompositionAnalysis with sub-scores, archetype label, and warnings.
    """
    all_profiles = [*team_profiles, candidate_profile]
    warnings: list[str] = []

    # 1. Damage balance -------------------------------------------------------
    damage_balance = _damage_balance(all_profiles, warnings)

    # 2. CC score -------------------------------------------------------------
    cc = _cc_score(all_profiles, warnings)

    # 3. Engage score ---------------------------------------------------------
    engage = _engage_score(all_profiles, warnings)

    # 4. Frontline score ------------------------------------------------------
    frontline = _frontline_score(all_profiles, warnings)

    # 5. Disengage score ------------------------------------------------------
    disengage = _disengage_score(all_profiles)

    # 6. Archetype detection & coherence --------------------------------------
    archetype, coherence = _archetype_coherence(all_profiles, engage)

    # 7. Composition total ----------------------------------------------------
    composition_total = (
        damage_balance * 0.35
        + cc * 0.15
        + engage * 0.15
        + frontline * 0.15
        + coherence * 0.10
        + disengage * 0.10
    )

    return TeamCompositionAnalysis(
        damage_balance_score=damage_balance,
        cc_score=cc,
        engage_score=engage,
        frontline_score=frontline,
        disengage_score=disengage,
        archetype=archetype,
        coherence_score=coherence,
        composition_total=composition_total,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ENTROPY_FLOOR = 0.01
_MAX_ENTROPY = log2(3)  # perfect 3-way split among physical/magic/true


def _damage_balance(
    profiles: list[ChampionCompositionProfile],
    warnings: list[str],
) -> float:
    avg_physical = mean(p.damage_physical_pct for p in profiles)
    avg_magic = mean(p.damage_magic_pct for p in profiles)
    avg_true = mean(p.damage_true_pct for p in profiles)

    parts = [avg_physical, avg_magic, avg_true]
    entropy = -sum(pct * log2(pct) for pct in parts if pct > _ENTROPY_FLOOR)
    score = entropy / _MAX_ENTROPY

    if avg_physical > 0.75:
        warnings.append(
            f"Takim %{avg_physical * 100:.0f} fiziksel hasar - dusmanlar zirh yigabilir"
        )
    if avg_magic > 0.75:
        warnings.append(
            f"Takim %{avg_magic * 100:.0f} buyu hasari - dusmanlar MR yigabilir"
        )

    return min(1.0, max(0.0, score))


def _cc_score(
    profiles: list[ChampionCompositionProfile],
    warnings: list[str],
) -> float:
    total_hard_cc = sum(p.cc_hard_seconds for p in profiles)
    score = min(1.0, total_hard_cc / 8.0)

    if total_hard_cc < 2.0:
        warnings.append("Takimda yeterli hard CC yok")

    return score


def _engage_score(
    profiles: list[ChampionCompositionProfile],
    warnings: list[str],
) -> float:
    max_engage = max(p.engage_score for p in profiles)
    avg_engage = mean(p.engage_score for p in profiles)
    score = 0.6 * max_engage + 0.4 * avg_engage

    if max_engage < 0.3:
        warnings.append("Takimda engage potansiyeli yok")

    return score


def _frontline_score(
    profiles: list[ChampionCompositionProfile],
    warnings: list[str],
) -> float:
    frontline_count = len([p for p in profiles if p.frontline_score > 0.6])
    score = min(1.0, frontline_count / 2.0)

    if frontline_count == 0:
        warnings.append("Takimda frontline/tank yok")

    return score


def _disengage_score(profiles: list[ChampionCompositionProfile]) -> float:
    max_disengage = max(p.disengage_score for p in profiles)
    avg_disengage = mean(p.disengage_score for p in profiles)
    return 0.6 * max_disengage + 0.4 * avg_disengage


def _archetype_coherence(
    profiles: list[ChampionCompositionProfile],
    engage_score: float,
) -> tuple[str, float]:
    archetype_scores = {
        "teamfight": mean(p.teamfight_score for p in profiles),
        "poke": mean(p.poke_score for p in profiles),
        "engage": engage_score,
        "split": mean(p.split_score for p in profiles),
        "protect": mean(p.protect_score for p in profiles),
    }

    sorted_archetypes = sorted(
        archetype_scores.items(), key=lambda item: item[1], reverse=True
    )
    top_name, top_val = sorted_archetypes[0]
    _, second_val = sorted_archetypes[1]

    if second_val > 0 and top_val > second_val * 1.3:
        return top_name, min(1.0, top_val)
    return "balanced", 0.5
