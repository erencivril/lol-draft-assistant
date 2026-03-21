from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ChampionCompositionProfile:
    champion_id: int
    damage_physical_pct: float  # 0-1
    damage_magic_pct: float     # 0-1
    damage_true_pct: float      # 0-1
    cc_hard_seconds: float
    cc_soft_seconds: float
    engage_score: float         # 0-1
    disengage_score: float      # 0-1
    frontline_score: float      # 0-1
    poke_score: float           # 0-1
    split_score: float          # 0-1
    teamfight_score: float      # 0-1
    protect_score: float        # 0-1
    scaling: float              # 0-1
    flex_roles: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
