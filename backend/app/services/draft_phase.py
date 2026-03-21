from __future__ import annotations

from dataclasses import dataclass

from app.domain.draft import DraftState


@dataclass(slots=True)
class DraftPhaseContext:
    pick_number: int              # 1-5 (which pick for our team)
    is_early_pick: bool           # picks 1-2
    is_late_pick: bool            # picks 4-5
    enemies_visible: int          # how many enemy champions are visible
    allies_visible: int           # how many ally champions are visible
    counter_weight_scale: float   # 0.4-1.0 (low for early blind picks, high for late counter picks)
    flex_bonus: float             # 1.0-1.3 (higher = early picks value flex more)
    safety_bonus: float           # 1.0-1.2 (higher = early picks value safety more)


def resolve_draft_phase(draft_state: DraftState) -> DraftPhaseContext:
    """Determine draft phase context from draft state.

    Computes pick number (1-5 for our team), and scales counter weight,
    flex bonus, and safety bonus accordingly.
    """
    my_picked = [s for s in draft_state.my_team_picks if s.champion_id]
    enemy_picked = [s for s in draft_state.enemy_team_picks if s.champion_id]

    pick_number = len(my_picked) + 1  # next pick number
    allies_visible = len(my_picked)
    enemies_visible = len(enemy_picked)

    is_early = pick_number <= 2
    is_late = pick_number >= 4

    # Counter weight scales up with enemies visible and pick number
    # Early blind picks: counter matters less (0.4 base)
    # Late picks with many enemies: counter matters most (1.0)
    counter_weight_scale = min(1.0, 0.4 + 0.15 * enemies_visible)

    # Flex bonus: early picks benefit from multi-role flexibility
    # Pick 1: 1.30, Pick 2: 1.15, Pick 3+: 1.0
    flex_bonus = 1.0 + max(0.0, 0.15 * (3 - pick_number))

    # Safety bonus: early picks should prefer safe champions
    # Pick 1: 1.20, Pick 2: 1.10, Pick 3+: 1.0
    safety_bonus = 1.0 + max(0.0, 0.10 * (3 - pick_number))

    return DraftPhaseContext(
        pick_number=pick_number,
        is_early_pick=is_early,
        is_late_pick=is_late,
        enemies_visible=enemies_visible,
        allies_visible=allies_visible,
        counter_weight_scale=counter_weight_scale,
        flex_bonus=flex_bonus,
        safety_bonus=safety_bonus,
    )
