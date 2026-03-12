from __future__ import annotations

from app.domain.draft import DraftAction, DraftState, TeamSlot
from app.domain.roles import normalize_role_name


class DraftStateBuilder:
    def build(self, *, session: dict | None, patch: str | None, queue_type: str | None) -> DraftState:
        if not session:
            return DraftState(session_status="idle", patch=patch, queue_type=queue_type)

        local_player_cell_id = session.get("localPlayerCellId")
        current_action = self._find_current_action(session.get("actions", []))
        picked_champions = self._build_pick_lookup(session.get("actions", []))
        my_team = [
            TeamSlot(
                cell_id=item["cellId"],
                champion_id=self._resolve_slot_champion_id(item, picked_champions),
                assigned_role=normalize_role_name(item.get("assignedPosition")),
                summoner_id=item.get("summonerId"),
                is_local_player=item["cellId"] == local_player_cell_id,
            )
            for item in session.get("myTeam", [])
        ]
        enemy_team = [
            TeamSlot(
                cell_id=item["cellId"],
                champion_id=self._resolve_slot_champion_id(item, picked_champions),
                assigned_role=normalize_role_name(item.get("assignedPosition")),
                summoner_id=item.get("summonerId"),
            )
            for item in session.get("theirTeam", [])
        ]

        timer = session.get("timer", {})
        bans = session.get("bans", {})
        local_role = next((slot.assigned_role for slot in my_team if slot.is_local_player), None)

        return DraftState(
            phase=timer.get("phase", "IDLE"),
            timer_seconds_left=max(int(timer.get("adjustedTimeLeftInPhase", 0) / 1000), 0),
            local_player_cell_id=local_player_cell_id,
            local_player_assigned_role=local_role,
            local_player_effective_role=local_role,
            current_actor_cell_id=current_action.actor_cell_id if current_action else None,
            current_action_type=current_action.action_type if current_action else None,
            my_team_picks=my_team,
            enemy_team_picks=enemy_team,
            my_team_declared_roles=[slot.assigned_role or "" for slot in my_team],
            enemy_team_declared_roles=[slot.assigned_role or "" for slot in enemy_team],
            my_bans=bans.get("myTeamBans", []),
            enemy_bans=bans.get("theirTeamBans", []),
            current_action=current_action,
            session_status="active",
            patch=patch,
            queue_type=queue_type,
            is_local_players_turn=(current_action.actor_cell_id == local_player_cell_id) if current_action else False,
        )

    def _find_current_action(self, action_groups: list[list[dict]]) -> DraftAction | None:
        fallback_action: DraftAction | None = None
        for group in action_groups:
            for action in group:
                if action.get("completed"):
                    continue
                draft_action = DraftAction(
                    action_id=action.get("id"),
                    actor_cell_id=action.get("actorCellId"),
                    champion_id=action.get("championId", 0),
                    action_type=action.get("type", "unknown"),
                    completed=bool(action.get("completed", False)),
                    is_in_progress=bool(action.get("isInProgress", False)),
                )
                if draft_action.is_in_progress:
                    return draft_action
                if fallback_action is None:
                    fallback_action = draft_action
        return fallback_action

    def _build_pick_lookup(self, action_groups: list[list[dict]]) -> dict[int, int]:
        picked_champions: dict[int, int] = {}
        for group in action_groups:
            for action in group:
                if action.get("type") != "pick":
                    continue
                champion_id = int(action.get("championId") or 0)
                actor_cell_id = action.get("actorCellId")
                if champion_id <= 0 or actor_cell_id is None:
                    continue
                picked_champions[int(actor_cell_id)] = champion_id
        return picked_champions

    def _resolve_slot_champion_id(self, slot: dict, picked_champions: dict[int, int]) -> int:
        champion_id = int(slot.get("championId") or 0)
        if champion_id > 0:
            return champion_id
        pick_intent = int(slot.get("championPickIntent") or 0)
        if pick_intent > 0:
            return pick_intent
        return picked_champions.get(int(slot["cellId"]), 0)
