from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator
from fastapi import APIRouter, Request

from app.domain.draft import DraftState, TeamSlot
from app.domain.recommendation import RecommendationBundle
from app.domain.roles import normalize_role_name
from app.domain.settings import ResolvedFilters

router = APIRouter(prefix="/api", tags=["recommend"])


class TeamSlotInput(BaseModel):
    cell_id: int
    champion_id: int
    role: str | None = None
    is_local_player: bool = False

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role_value(cls, value: str | None) -> str | None:
        return normalize_role_name(value)


class RecommendRequest(BaseModel):
    region: str = "TR"
    rank_tier: str = "emerald"
    target_cell_id: int
    enemy_slots: list[TeamSlotInput] = Field(default_factory=list)
    ally_slots: list[TeamSlotInput] = Field(default_factory=list)
    bans: list[int] = Field(default_factory=list)

    @field_validator("target_cell_id")
    @classmethod
    def validate_target_cell_id(cls, value: int) -> int:
        if value < 1:
            raise ValueError("target_cell_id must be a positive cell id")
        return value

    @model_validator(mode="after")
    def validate_slots(self) -> "RecommendRequest":
        ally_cell_ids = {slot.cell_id for slot in self.ally_slots}
        if self.target_cell_id not in ally_cell_ids:
            raise ValueError("target_cell_id must reference an ally slot")
        local_slots = [slot for slot in self.ally_slots if slot.is_local_player]
        if len(local_slots) != 1:
            raise ValueError("ally_slots must include exactly one local player slot")
        return self


class ChampionLookupItem(BaseModel):
    champion_id: int
    key: str
    name: str
    image_url: str
    roles: list[str]
    patch: str


def _build_slots(
    *,
    picks: list[TeamSlotInput],
) -> list[TeamSlot]:
    return [
        TeamSlot(
            cell_id=slot.cell_id,
            champion_id=slot.champion_id,
            assigned_role=slot.role,
            effective_role=slot.role,
            role_source="manual" if slot.role else "unknown",
            role_confidence=1.0 if slot.role else 0.0,
            is_local_player=slot.is_local_player,
        )
        for slot in sorted(picks, key=lambda item: item.cell_id)
    ]


@router.post("/recommend", response_model=RecommendationBundle)
async def recommend(payload: RecommendRequest, request: Request) -> RecommendationBundle:
    local_slot = next(slot for slot in payload.ally_slots if slot.is_local_player)
    local_role = normalize_role_name(local_slot.role) or "middle"
    filters = ResolvedFilters(
        region=payload.region,
        rank_tier=payload.rank_tier,
        role=local_role,
    )
    draft_state = DraftState(
        local_player_cell_id=local_slot.cell_id,
        local_player_assigned_role=local_role,
        local_player_effective_role=local_role,
        current_actor_cell_id=payload.target_cell_id,
        current_action_type="pick",
        my_team_picks=_build_slots(picks=payload.ally_slots),
        enemy_team_picks=_build_slots(picks=payload.enemy_slots),
        my_bans=payload.bans,
        enemy_bans=[],
        session_status="active",
        phase="PICK",
        is_local_players_turn=True,
    )
    settings = request.app.state.default_user_settings.model_copy(
        update={
            "region_mode": "manual",
            "rank_mode": "manual",
            "role_mode": "manual",
            "region_override": filters.region,
            "rank_override": filters.rank_tier,
            "role_override": local_role,
        }
    )
    snapshot = await request.app.state.recommendation_service.analyze(
        draft_state,
        filters,
        settings,
        target_cell_id=payload.target_cell_id,
    )
    return snapshot.recommendations


@router.get("/data/champions", response_model=dict[int, ChampionLookupItem])
async def get_champions(request: Request) -> dict[int, ChampionLookupItem]:
    service = request.app.state.recommendation_service
    await service.ensure_champion_lookup_ready()
    return {
        champion_id: ChampionLookupItem(
            champion_id=champion.champion_id,
            key=champion.key,
            name=champion.name,
            image_url=champion.image_url,
            roles=champion.roles,
            patch=champion.patch,
        )
        for champion_id, champion in sorted(service.champion_lookup.items(), key=lambda item: item[1].name)
    }
