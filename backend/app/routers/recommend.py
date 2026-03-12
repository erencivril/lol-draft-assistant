from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
from fastapi import APIRouter, Request

from app.domain.draft import DraftState, TeamSlot
from app.domain.recommendation import RecommendationBundle
from app.domain.roles import normalize_role_name
from app.domain.settings import ResolvedFilters

router = APIRouter(prefix="/api", tags=["recommend"])


class ChampionSlotInput(BaseModel):
    champion_id: int
    role: str | None = None

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role_value(cls, value: str | None) -> str | None:
        return normalize_role_name(value)


class RecommendRequest(BaseModel):
    region: str = "TR"
    rank_tier: str = "emerald"
    role: str = "middle"
    enemy_picks: list[ChampionSlotInput] = Field(default_factory=list)
    ally_picks: list[ChampionSlotInput] = Field(default_factory=list)
    bans: list[int] = Field(default_factory=list)

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role_value(cls, value: str | None) -> str:
        return normalize_role_name(value) or "middle"


class ChampionLookupItem(BaseModel):
    champion_id: int
    key: str
    name: str
    image_url: str
    roles: list[str]
    patch: str


def _build_slots(
    *,
    picks: list[ChampionSlotInput],
    start_cell_id: int,
) -> list[TeamSlot]:
    return [
        TeamSlot(
            cell_id=start_cell_id + index,
            champion_id=slot.champion_id,
            assigned_role=slot.role,
            effective_role=slot.role,
            role_source="manual" if slot.role else "unknown",
            role_confidence=1.0 if slot.role else 0.0,
        )
        for index, slot in enumerate(picks)
    ]


@router.post("/recommend", response_model=RecommendationBundle)
async def recommend(payload: RecommendRequest, request: Request) -> RecommendationBundle:
    filters = ResolvedFilters(
        region=payload.region,
        rank_tier=payload.rank_tier,
        role=payload.role,
    )
    draft_state = DraftState(
        local_player_cell_id=1,
        local_player_assigned_role=payload.role,
        local_player_effective_role=payload.role,
        current_actor_cell_id=1,
        current_action_type="pick",
        my_team_picks=[
            TeamSlot(
                cell_id=1,
                champion_id=0,
                assigned_role=payload.role,
                effective_role=payload.role,
                role_source="manual",
                role_confidence=1.0,
                is_local_player=True,
            ),
            *_build_slots(picks=payload.ally_picks, start_cell_id=2),
        ],
        enemy_team_picks=_build_slots(picks=payload.enemy_picks, start_cell_id=6),
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
            "role_override": filters.role or payload.role,
        }
    )
    snapshot = await request.app.state.recommendation_service.analyze(
        draft_state,
        filters,
        settings,
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
