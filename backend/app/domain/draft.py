from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.domain.roles import normalize_role_name


class RoleCandidate(BaseModel):
    role: str
    confidence: float

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role_value(cls, value: str | None) -> str:
        return normalize_role_name(value) or "middle"


class TeamSlot(BaseModel):
    cell_id: int
    champion_id: int = 0
    champion_name: str | None = None
    champion_image_url: str | None = None
    assigned_role: str | None = None
    effective_role: str | None = None
    role_source: Literal["lcu", "manual", "inferred", "unknown"] = "unknown"
    role_confidence: float = 0.0
    role_candidates: list[RoleCandidate] = Field(default_factory=list)
    summoner_id: int | None = None
    is_local_player: bool = False


class DraftAction(BaseModel):
    action_id: int | None = None
    actor_cell_id: int | None = None
    champion_id: int | None = None
    action_type: Literal["pick", "ban", "unknown"] = "unknown"
    completed: bool = False
    is_in_progress: bool = False


class DraftState(BaseModel):
    phase: str = "IDLE"
    timer_seconds_left: int | None = None
    local_player_cell_id: int | None = None
    local_player_assigned_role: str | None = None
    local_player_effective_role: str | None = None
    current_actor_cell_id: int | None = None
    current_action_type: str | None = None
    my_team_picks: list[TeamSlot] = Field(default_factory=list)
    enemy_team_picks: list[TeamSlot] = Field(default_factory=list)
    my_team_declared_roles: list[str] = Field(default_factory=list)
    enemy_team_declared_roles: list[str] = Field(default_factory=list)
    my_bans: list[int] = Field(default_factory=list)
    enemy_bans: list[int] = Field(default_factory=list)
    current_action: DraftAction | None = None
    session_status: str = "disconnected"
    patch: str | None = None
    queue_type: str | None = None
    is_local_players_turn: bool = False


class DraftRoleOverride(BaseModel):
    team: Literal["ally", "enemy"]
    cell_id: int
    role: str | None = None

    @field_validator("role", mode="before")
    @classmethod
    def normalize_override_role(cls, value: str | None) -> str | None:
        return normalize_role_name(value)


class DraftRoleOverridePayload(BaseModel):
    overrides: list[DraftRoleOverride] = Field(default_factory=list)
