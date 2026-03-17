from __future__ import annotations

import aiosqlite
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.db.repository import ChampionRecord, DatabaseRepository
from app.domain.recommendation import RecommendationBundle
from app.domain.settings import UserSettings
from app.routers import recommend as recommend_router


@pytest_asyncio.fixture
async def repository() -> DatabaseRepository:
    connection = await aiosqlite.connect(":memory:")
    connection.row_factory = aiosqlite.Row
    repository = DatabaseRepository(connection)
    await repository.initialize()
    try:
        yield repository
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_champions_reads_fresh_repository_data_when_service_cache_is_stale(repository: DatabaseRepository) -> None:
    stale_champion = ChampionRecord(
        champion_id=350,
        key="Yuumi",
        name="Yuumi",
        image_url="https://example.test/Yuumi.png",
        roles=[],
        patch="16.5.1",
    )
    fresh_champion = ChampionRecord(
        champion_id=350,
        key="Yuumi",
        name="Yuumi",
        image_url="https://example.test/Yuumi.png",
        roles=["support"],
        patch="16.5.1",
    )
    await repository.upsert_champions([fresh_champion])

    class RecommendationServiceStub:
        def __init__(self) -> None:
            self.repository = repository
            self.champion_lookup = {350: stale_champion}
            self.patch = "16.5.1"

        async def ensure_champion_lookup_ready(self) -> None:
            self.champion_lookup = await self.repository.get_champion_lookup()

    app = FastAPI()
    app.include_router(recommend_router.router)
    app.state.recommendation_service = RecommendationServiceStub()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/data/champions")

    assert response.status_code == 200
    payload = response.json()["350"]
    assert payload["roles"] == ["support"]


@pytest.mark.asyncio
async def test_recommend_uses_local_player_role_when_targeting_another_ally_slot(repository: DatabaseRepository) -> None:
    captured: dict[str, object] = {}

    class RecommendationServiceStub:
        def __init__(self) -> None:
            self.repository = repository
            self.champion_lookup = {}
            self.patch = "16.5.1"

        async def analyze(self, draft_state, filters, settings, target_cell_id=None):
            captured["draft_state"] = draft_state
            captured["filters"] = filters
            captured["settings"] = settings
            captured["target_cell_id"] = target_cell_id
            return type("SnapshotStub", (), {"recommendations": RecommendationBundle()})()

    app = FastAPI()
    app.include_router(recommend_router.router)
    app.state.recommendation_service = RecommendationServiceStub()
    app.state.default_user_settings = UserSettings()

    payload = {
        "region": "TR",
        "rank_tier": "emerald",
        "target_cell_id": 4,
        "ally_slots": [
            {"cell_id": 3, "champion_id": 7, "role": "middle", "is_local_player": True},
            {"cell_id": 4, "champion_id": 222, "role": "bottom", "is_local_player": False},
        ],
        "enemy_slots": [],
        "bans": [],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/api/recommend", json=payload)

    assert response.status_code == 200
    draft_state = captured["draft_state"]
    filters = captured["filters"]
    settings = captured["settings"]

    assert captured["target_cell_id"] == 4
    # filter role comes from local player's slot role, not target slot
    assert filters.role == "middle"
    assert draft_state.local_player_cell_id == 3
    assert draft_state.local_player_effective_role == "middle"
    assert draft_state.current_actor_cell_id == 4
    assert any(slot.cell_id == 3 and slot.is_local_player for slot in draft_state.my_team_picks)
    assert any(slot.cell_id == 4 and slot.effective_role == "bottom" for slot in draft_state.my_team_picks)
    assert settings.role_override == "middle"


@pytest.mark.asyncio
async def test_recommend_uses_local_player_slot_when_it_is_the_target(repository: DatabaseRepository) -> None:
    captured: dict[str, object] = {}

    class RecommendationServiceStub:
        def __init__(self) -> None:
            self.repository = repository
            self.champion_lookup = {}
            self.patch = "16.5.1"

        async def analyze(self, draft_state, filters, settings, target_cell_id=None):
            captured["draft_state"] = draft_state
            captured["filters"] = filters
            captured["settings"] = settings
            captured["target_cell_id"] = target_cell_id
            return type("SnapshotStub", (), {"recommendations": RecommendationBundle()})()

    app = FastAPI()
    app.include_router(recommend_router.router)
    app.state.recommendation_service = RecommendationServiceStub()
    app.state.default_user_settings = UserSettings()

    payload = {
        "region": "TR",
        "rank_tier": "emerald",
        "target_cell_id": 1,
        "ally_slots": [
            {"cell_id": 1, "champion_id": 266, "role": "top", "is_local_player": True},
            {"cell_id": 2, "champion_id": 0, "role": "jungle", "is_local_player": False},
        ],
        "enemy_slots": [],
        "bans": [],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/api/recommend", json=payload)

    assert response.status_code == 200
    draft_state = captured["draft_state"]
    filters = captured["filters"]

    assert captured["target_cell_id"] == 1
    assert filters.role == "top"
    assert draft_state.local_player_cell_id == 1
    assert draft_state.local_player_effective_role == "top"
    assert draft_state.my_team_picks[0].is_local_player is True
    assert draft_state.my_team_picks[0].effective_role == "top"
