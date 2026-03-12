from __future__ import annotations

from app.services.draft_state_builder import DraftStateBuilder


def test_build_normalizes_lcu_roles() -> None:
    builder = DraftStateBuilder()
    draft_state = builder.build(
        session={
            "localPlayerCellId": 1,
            "timer": {"phase": "PLANNING", "adjustedTimeLeftInPhase": 30000},
            "actions": [[{"id": 11, "actorCellId": 1, "championId": 0, "type": "pick", "completed": False}]],
            "bans": {"myTeamBans": [], "theirTeamBans": []},
            "myTeam": [
                {"cellId": 1, "assignedPosition": "UTILITY", "championId": 0, "summonerId": 1001},
                {"cellId": 2, "assignedPosition": "JUNGLE", "championId": 0, "summonerId": 1002},
            ],
            "theirTeam": [
                {"cellId": 6, "assignedPosition": "BOTTOM", "championId": 0, "summonerId": 2001},
            ],
        },
        patch="16.5.1",
        queue_type="RANKED_SOLO_5x5",
    )

    assert draft_state.local_player_assigned_role == "support"
    assert draft_state.local_player_effective_role == "support"
    assert draft_state.my_team_picks[0].assigned_role == "support"
    assert draft_state.my_team_picks[1].assigned_role == "jungle"
    assert draft_state.enemy_team_picks[0].assigned_role == "bottom"
    assert draft_state.is_local_players_turn is True


def test_build_prefers_in_progress_action_over_first_incomplete_action() -> None:
    builder = DraftStateBuilder()

    draft_state = builder.build(
        session={
            "localPlayerCellId": 1,
            "timer": {"phase": "BAN_PICK", "adjustedTimeLeftInPhase": 12000},
            "actions": [
                [
                    {
                        "id": 10,
                        "actorCellId": 6,
                        "championId": 0,
                        "type": "ban",
                        "completed": False,
                        "isInProgress": False,
                    }
                ],
                [
                    {
                        "id": 22,
                        "actorCellId": 7,
                        "championId": 0,
                        "type": "pick",
                        "completed": False,
                        "isInProgress": True,
                    }
                ],
            ],
            "bans": {"myTeamBans": [], "theirTeamBans": []},
            "myTeam": [
                {"cellId": 1, "assignedPosition": "JUNGLE", "championId": 0, "summonerId": 1001},
            ],
            "theirTeam": [
                {"cellId": 6, "assignedPosition": "TOP", "championId": 0, "summonerId": 2001},
                {"cellId": 7, "assignedPosition": "MIDDLE", "championId": 0, "summonerId": 2002},
            ],
        },
        patch="16.5.1",
        queue_type="RANKED_SOLO_5x5",
    )

    assert draft_state.current_actor_cell_id == 7
    assert draft_state.current_action_type == "pick"
    assert draft_state.is_local_players_turn is False


def test_build_uses_pick_actions_when_team_slots_have_zero_champion_ids() -> None:
    builder = DraftStateBuilder()

    draft_state = builder.build(
        session={
            "localPlayerCellId": 0,
            "timer": {"phase": "BAN_PICK", "adjustedTimeLeftInPhase": 12000},
            "actions": [
                [
                    {
                        "id": 1,
                        "actorCellId": 0,
                        "championId": 104,
                        "type": "pick",
                        "completed": True,
                    },
                    {
                        "id": 2,
                        "actorCellId": 6,
                        "championId": 117,
                        "type": "pick",
                        "completed": True,
                    },
                ]
            ],
            "bans": {"myTeamBans": [], "theirTeamBans": []},
            "myTeam": [
                {"cellId": 0, "assignedPosition": "JUNGLE", "championId": 0, "summonerId": 1001},
            ],
            "theirTeam": [
                {"cellId": 6, "assignedPosition": "UTILITY", "championId": 0, "summonerId": 2001},
            ],
        },
        patch="16.5.1",
        queue_type="RANKED_SOLO_5x5",
    )

    assert draft_state.my_team_picks[0].champion_id == 104
    assert draft_state.enemy_team_picks[0].champion_id == 117


def test_build_prefers_pick_intent_when_champion_id_is_zero() -> None:
    builder = DraftStateBuilder()

    draft_state = builder.build(
        session={
            "localPlayerCellId": 3,
            "timer": {"phase": "BAN_PICK", "adjustedTimeLeftInPhase": 12000},
            "actions": [],
            "bans": {"myTeamBans": [], "theirTeamBans": []},
            "myTeam": [
                {
                    "cellId": 3,
                    "assignedPosition": "TOP",
                    "championId": 0,
                    "championPickIntent": 86,
                    "summonerId": 1003,
                },
            ],
            "theirTeam": [],
        },
        patch="16.5.1",
        queue_type="RANKED_SOLO_5x5",
    )

    assert draft_state.my_team_picks[0].champion_id == 86
