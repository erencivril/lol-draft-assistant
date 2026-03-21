from __future__ import annotations

import pytest

from app.domain.draft import DraftState, TeamSlot
from app.services.draft_phase import DraftPhaseContext, resolve_draft_phase
from app.services.scoring import flex_pick_score


def _make_draft(
    my_picked: int = 0,
    enemy_picked: int = 0,
) -> DraftState:
    """Build a DraftState with the given number of picked champions per team."""
    my_slots = []
    for i in range(5):
        champ_id = (i + 1) * 100 if i < my_picked else 0
        my_slots.append(TeamSlot(cell_id=i, champion_id=champ_id))
    enemy_slots = []
    for i in range(5):
        champ_id = (i + 1) * 200 if i < enemy_picked else 0
        enemy_slots.append(TeamSlot(cell_id=i + 5, champion_id=champ_id))
    return DraftState(
        phase="PICK",
        my_team_picks=my_slots,
        enemy_team_picks=enemy_slots,
    )


class TestResolveDraftPhase:
    """Tests for resolve_draft_phase context computation."""

    def test_first_pick_blind(self):
        """Pick 1 with no enemies visible: early pick, low counter weight, high flex/safety."""
        ctx = resolve_draft_phase(_make_draft(my_picked=0, enemy_picked=0))
        assert ctx.pick_number == 1
        assert ctx.is_early_pick is True
        assert ctx.is_late_pick is False
        assert ctx.allies_visible == 0
        assert ctx.enemies_visible == 0
        assert ctx.counter_weight_scale == pytest.approx(0.4)
        assert ctx.flex_bonus == pytest.approx(1.30)
        assert ctx.safety_bonus == pytest.approx(1.20)

    def test_second_pick_one_enemy(self):
        """Pick 2 with 1 enemy visible."""
        ctx = resolve_draft_phase(_make_draft(my_picked=1, enemy_picked=1))
        assert ctx.pick_number == 2
        assert ctx.is_early_pick is True
        assert ctx.is_late_pick is False
        assert ctx.enemies_visible == 1
        assert ctx.allies_visible == 1
        assert ctx.counter_weight_scale == pytest.approx(0.55)
        assert ctx.flex_bonus == pytest.approx(1.15)
        assert ctx.safety_bonus == pytest.approx(1.10)

    def test_third_pick_mid_draft(self):
        """Pick 3 with 2 enemies: middle pick, no flex/safety bonus."""
        ctx = resolve_draft_phase(_make_draft(my_picked=2, enemy_picked=2))
        assert ctx.pick_number == 3
        assert ctx.is_early_pick is False
        assert ctx.is_late_pick is False
        assert ctx.enemies_visible == 2
        assert ctx.counter_weight_scale == pytest.approx(0.70)
        assert ctx.flex_bonus == pytest.approx(1.0)
        assert ctx.safety_bonus == pytest.approx(1.0)

    def test_fourth_pick_late(self):
        """Pick 4 with 3 enemies: late pick, high counter weight."""
        ctx = resolve_draft_phase(_make_draft(my_picked=3, enemy_picked=3))
        assert ctx.pick_number == 4
        assert ctx.is_early_pick is False
        assert ctx.is_late_pick is True
        assert ctx.enemies_visible == 3
        assert ctx.counter_weight_scale == pytest.approx(0.85)
        assert ctx.flex_bonus == pytest.approx(1.0)
        assert ctx.safety_bonus == pytest.approx(1.0)

    def test_fifth_pick_full_info(self):
        """Pick 5 with all 5 enemies: counter weight capped at 1.0."""
        ctx = resolve_draft_phase(_make_draft(my_picked=4, enemy_picked=5))
        assert ctx.pick_number == 5
        assert ctx.is_early_pick is False
        assert ctx.is_late_pick is True
        assert ctx.enemies_visible == 5
        assert ctx.counter_weight_scale == pytest.approx(1.0)
        assert ctx.flex_bonus == pytest.approx(1.0)
        assert ctx.safety_bonus == pytest.approx(1.0)

    def test_counter_weight_caps_at_one(self):
        """Counter weight scale should never exceed 1.0 even with many enemies."""
        ctx = resolve_draft_phase(_make_draft(my_picked=0, enemy_picked=5))
        assert ctx.counter_weight_scale == pytest.approx(1.0)

    def test_empty_draft_state(self):
        """Empty draft state should produce pick 1 defaults."""
        ctx = resolve_draft_phase(DraftState())
        assert ctx.pick_number == 1
        assert ctx.is_early_pick is True
        assert ctx.counter_weight_scale == pytest.approx(0.4)


class TestFlexPickScore:
    """Tests for flex_pick_score scoring function."""

    def test_single_role_returns_zero(self):
        assert flex_pick_score(1) == 0.0

    def test_zero_roles_returns_zero(self):
        assert flex_pick_score(0) == 0.0

    def test_two_roles_default_bonus(self):
        assert flex_pick_score(2) == pytest.approx(0.3)

    def test_three_roles_default_bonus(self):
        assert flex_pick_score(3) == pytest.approx(0.6)

    def test_four_roles_default_bonus(self):
        assert flex_pick_score(4) == pytest.approx(0.9)

    def test_five_roles_caps_at_one(self):
        # (5-1)*0.3 = 1.2, capped to 1.0
        assert flex_pick_score(5) == pytest.approx(1.0)

    def test_flex_bonus_amplifies(self):
        # 2 roles base=0.3, with 1.3 bonus -> 0.39
        assert flex_pick_score(2, 1.3) == pytest.approx(0.39)

    def test_flex_bonus_caps_at_one(self):
        # 4 roles base=0.9, with 1.3 bonus -> 1.17, capped to 1.0
        assert flex_pick_score(4, 1.3) == pytest.approx(1.0)
