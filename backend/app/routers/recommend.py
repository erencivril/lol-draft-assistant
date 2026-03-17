from __future__ import annotations

import logging

from pydantic import BaseModel, Field, field_validator, model_validator
from fastapi import APIRouter, Request

from app.domain.draft import DraftState, TeamSlot
from app.domain.recommendation import RecommendationBundle
from app.domain.roles import normalize_role_name
from app.domain.settings import ResolvedFilters
from app.providers.lolalytics_build_provider import LolalyticsBuildsProvider
from app.services.rune_recommender import recommend_runes
from app.services.build_recommender import recommend_build

logger = logging.getLogger("lda.routers.recommend")

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
        if value < 0:
            raise ValueError("target_cell_id must be a non-negative cell id")
        return value

    @model_validator(mode="after")
    def validate_slots(self) -> "RecommendRequest":
        ally_cell_ids = {slot.cell_id for slot in self.ally_slots}
        if self.target_cell_id not in ally_cell_ids and self.ally_slots:
            self.target_cell_id = self.ally_slots[0].cell_id
        local_slots = [s for s in self.ally_slots if s.is_local_player]
        if len(local_slots) == 0 and self.ally_slots:
            self.ally_slots[0].is_local_player = True
        elif len(local_slots) > 1:
            for s in local_slots[1:]:
                s.is_local_player = False
        return self


class RoleHintItem(BaseModel):
    role: str
    weight: float
    games: int


class ChampionLookupItem(BaseModel):
    champion_id: int
    key: str
    name: str
    image_url: str
    roles: list[str]
    patch: str
    primary_role: str | None = None
    role_hints: list[RoleHintItem] = Field(default_factory=list)


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
            primary_role=champion.primary_role,
            role_hints=[
                RoleHintItem(role=h.role, weight=h.weight, games=h.games)
                for h in champion.role_hints
            ],
        )
        for champion_id, champion in sorted(service.champion_lookup.items(), key=lambda item: item[1].name)
    }


# ---------------------------------------------------------------------------
# Rune & Build recommendation endpoints
# ---------------------------------------------------------------------------

class EnemySlotInput(BaseModel):
    champion_id: int
    role: str

    @field_validator("role", mode="before")
    @classmethod
    def normalize(cls, v: str) -> str:
        return normalize_role_name(v) or v


class RuneRecommendRequest(BaseModel):
    champion_id: int
    role: str
    enemy_slots: list[EnemySlotInput] = Field(default_factory=list)
    rank_tier: str = "emerald_plus"

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, v: str) -> str:
        return normalize_role_name(v) or v


class RuneMatchupDetail(BaseModel):
    opponent_name: str
    opponent_id: int
    opponent_role: str
    win_rate: float
    games: int


class RunePageOut(BaseModel):
    keystone_id: int
    weighted_score: float
    total_games: int
    avg_win_rate: float
    matchup_details: list[RuneMatchupDetail]


class RuneStatOut(BaseModel):
    rune_id: int
    weighted_win_rate: float
    total_games: int
    pick_rate: float


class RuneRecommendResponse(BaseModel):
    rune_pages: list[RunePageOut]
    per_rune_stats: list[RuneStatOut]
    fallback_used: bool


class BuildRecommendRequest(BaseModel):
    champion_id: int
    role: str
    keystone_id: int | None = None
    enemy_slots: list[EnemySlotInput] = Field(default_factory=list)
    rank_tier: str = "emerald_plus"

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, v: str) -> str:
        return normalize_role_name(v) or v


class ItemMatchupOut(BaseModel):
    opponent_name: str
    opponent_id: int
    opponent_role: str
    win_rate: float
    games: int


class ItemOut(BaseModel):
    item_id: int
    weighted_score: float
    total_games: int
    avg_win_rate: float
    matchup_contributions: list[ItemMatchupOut]


class BuildSlotOut(BaseModel):
    slot_name: str
    primary: ItemOut | None = None
    alternatives: list[ItemOut]


class BuildRecommendResponse(BaseModel):
    slots: list[BuildSlotOut]
    skill_order: str | None = None
    keystone_filtered: bool
    fallback_used: bool


async def _prepare_enemies(
    enemy_slots: list[EnemySlotInput],
    champion_lookup: dict,
) -> list[dict]:
    """Convert enemy slot inputs to the dict format expected by providers."""
    enemies: list[dict] = []
    for slot in enemy_slots:
        champ = champion_lookup.get(slot.champion_id)
        if champ is None:
            logger.warning("Unknown champion_id %d in enemy slots", slot.champion_id)
            continue
        enemies.append({
            "slug": champ.key.lower(),
            "champion_id": slot.champion_id,
            "role": slot.role,
        })
    return enemies


@router.post("/recommend/runes", response_model=RuneRecommendResponse)
async def recommend_runes_endpoint(
    payload: RuneRecommendRequest,
    request: Request,
) -> RuneRecommendResponse:
    provider: LolalyticsBuildsProvider = request.app.state.builds_provider
    champion_lookup = await request.app.state.repository.get_champion_lookup()

    champ = champion_lookup.get(payload.champion_id)
    if champ is None:
        return RuneRecommendResponse(rune_pages=[], per_rune_stats=[], fallback_used=True)

    enemies = await _prepare_enemies(payload.enemy_slots, champion_lookup)

    result = await recommend_runes(
        provider=provider,
        champion_slug=champ.key.lower(),
        champion_id=payload.champion_id,
        role=payload.role,
        enemies=enemies,
        champion_lookup=champion_lookup,
        tier=payload.rank_tier,
    )

    return RuneRecommendResponse(
        rune_pages=[
            RunePageOut(
                keystone_id=p.keystone_id,
                weighted_score=p.weighted_score,
                total_games=p.total_games,
                avg_win_rate=p.avg_win_rate,
                matchup_details=[
                    RuneMatchupDetail(
                        opponent_name=d.opponent_name,
                        opponent_id=d.opponent_id,
                        opponent_role=d.opponent_role,
                        win_rate=d.win_rate,
                        games=d.games,
                    )
                    for d in p.matchup_details
                ],
            )
            for p in result.rune_pages
        ],
        per_rune_stats=[
            RuneStatOut(
                rune_id=s.rune_id,
                weighted_win_rate=s.weighted_win_rate,
                total_games=s.total_games,
                pick_rate=s.pick_rate,
            )
            for s in result.per_rune_stats
        ],
        fallback_used=result.fallback_used,
    )


@router.post("/recommend/build", response_model=BuildRecommendResponse)
async def recommend_build_endpoint(
    payload: BuildRecommendRequest,
    request: Request,
) -> BuildRecommendResponse:
    provider: LolalyticsBuildsProvider = request.app.state.builds_provider
    champion_lookup = await request.app.state.repository.get_champion_lookup()

    champ = champion_lookup.get(payload.champion_id)
    if champ is None:
        return BuildRecommendResponse(
            slots=[], skill_order=None, keystone_filtered=False, fallback_used=True,
        )

    enemies = await _prepare_enemies(payload.enemy_slots, champion_lookup)

    result = await recommend_build(
        provider=provider,
        champion_slug=champ.key.lower(),
        champion_id=payload.champion_id,
        role=payload.role,
        keystone_id=payload.keystone_id,
        enemies=enemies,
        champion_lookup=champion_lookup,
        tier=payload.rank_tier,
    )

    return BuildRecommendResponse(
        slots=[
            BuildSlotOut(
                slot_name=s.slot_name,
                primary=ItemOut(
                    item_id=s.primary.item_id,
                    weighted_score=s.primary.weighted_score,
                    total_games=s.primary.total_games,
                    avg_win_rate=s.primary.avg_win_rate,
                    matchup_contributions=[
                        ItemMatchupOut(
                            opponent_name=c.opponent_name,
                            opponent_id=c.opponent_id,
                            opponent_role=c.opponent_role,
                            win_rate=c.win_rate,
                            games=c.games,
                        )
                        for c in s.primary.matchup_contributions
                    ],
                ) if s.primary else None,
                alternatives=[
                    ItemOut(
                        item_id=a.item_id,
                        weighted_score=a.weighted_score,
                        total_games=a.total_games,
                        avg_win_rate=a.avg_win_rate,
                        matchup_contributions=[
                            ItemMatchupOut(
                                opponent_name=c.opponent_name,
                                opponent_id=c.opponent_id,
                                opponent_role=c.opponent_role,
                                win_rate=c.win_rate,
                                games=c.games,
                            )
                            for c in a.matchup_contributions
                        ],
                    )
                    for a in s.alternatives
                ],
            )
            for s in result.slots
        ],
        skill_order=result.skill_order,
        keystone_filtered=result.keystone_filtered,
        fallback_used=result.fallback_used,
    )
