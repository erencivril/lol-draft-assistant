from __future__ import annotations

import aiosqlite
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.db.repository import ChampionRecord, DatabaseRepository, TierStatRecord
from app.routers import recommend as recommend_router
from app.services.champion_sync import ChampionSyncService
from app.services.recommendation_service import RecommendationService


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
async def test_update_roles_from_tier_stats_builds_role_hints_and_primary_role(
    repository: DatabaseRepository,
) -> None:
    patch = "16.5.1"
    await repository.upsert_champions(
        [
            ChampionRecord(champion_id=1, key="Yuumi", name="Yuumi", image_url="yuumi.png", roles=[], patch=patch),
            ChampionRecord(champion_id=2, key="NoData", name="No Data", image_url="nodata.png", roles=[], patch=patch),
        ]
    )
    await repository.replace_tier_stats(
        region="TR",
        rank_tier="emerald",
        role="support",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=1,
                region="TR",
                rank_tier="emerald",
                role="support",
                win_rate=51.0,
                pick_rate=11.8,
                ban_rate=2.0,
                tier_grade="A",
                games=42000,
                patch=patch,
                source="test",
                fetched_at="2026-03-14T00:00:00+00:00",
            ),
        ],
    )
    await repository.replace_tier_stats(
        region="TR",
        rank_tier="emerald",
        role="bottom",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=1,
                region="TR",
                rank_tier="emerald",
                role="bottom",
                win_rate=48.5,
                pick_rate=0.9,
                ban_rate=0.2,
                tier_grade="C",
                games=1200,
                patch=patch,
                source="test",
                fetched_at="2026-03-14T00:00:00+00:00",
            ),
        ],
    )

    service = ChampionSyncService(Settings(), repository)
    await service.update_roles_from_tier_stats(patch)

    champion_lookup = await repository.get_champion_lookup()
    yuumi = champion_lookup[1]
    no_data = champion_lookup[2]

    assert yuumi.primary_role == "support"
    assert yuumi.roles == ["support", "bottom"]
    assert [(hint.role, hint.games) for hint in yuumi.role_hints] == [("support", 42000), ("bottom", 1200)]
    assert yuumi.role_hints[0].weight == pytest.approx(1.0)
    assert yuumi.role_hints[1].weight == pytest.approx(round(0.9 / 11.8, 4))

    assert no_data.primary_role is None
    assert no_data.roles == []
    assert no_data.role_hints == []


@pytest.mark.asyncio
async def test_data_champions_endpoint_returns_role_hints(repository: DatabaseRepository) -> None:
    patch = "16.5.1"
    await repository.upsert_champions(
        [ChampionRecord(champion_id=1, key="Yuumi", name="Yuumi", image_url="yuumi.png", roles=[], patch=patch)]
    )
    await repository.replace_tier_stats(
        region="TR",
        rank_tier="emerald",
        role="support",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=1,
                region="TR",
                rank_tier="emerald",
                role="support",
                win_rate=51.0,
                pick_rate=11.8,
                ban_rate=2.0,
                tier_grade="A",
                games=42000,
                patch=patch,
                source="test",
                fetched_at="2026-03-14T00:00:00+00:00",
            ),
        ],
    )

    sync_service = ChampionSyncService(Settings(), repository)
    await sync_service.update_roles_from_tier_stats(patch)

    recommendation_service = RecommendationService(repository)
    await recommendation_service.rebuild_indexes()

    app = FastAPI()
    app.include_router(recommend_router.router)
    app.state.recommendation_service = recommendation_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/data/champions")

    assert response.status_code == 200
    payload = response.json()

    assert payload["1"]["primary_role"] == "support"
    assert payload["1"]["roles"] == ["support"]
    assert payload["1"]["role_hints"] == [{"role": "support", "weight": 1.0, "games": 42000}]


@pytest.mark.asyncio
async def test_sync_preserves_existing_role_metadata(repository: DatabaseRepository, monkeypatch: pytest.MonkeyPatch) -> None:
    patch = "16.5.1"
    await repository.upsert_champions(
        [
            ChampionRecord(
                champion_id=1,
                key="Yuumi",
                name="Yuumi",
                image_url="https://example.com/yuumi.png",
                roles=["support"],
                patch=patch,
                primary_role="support",
            )
        ]
    )
    await repository.connection.execute(
        "UPDATE champions SET role_hints_json = ? WHERE id = ?",
        ('[{"role":"support","weight":1.0,"games":42000}]', 1),
    )
    await repository.connection.commit()

    class _Response:
        def __init__(self, payload) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._payload

    class _AsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            del exc_type, exc, tb
            return None

        async def get(self, url: str):
            if url == Settings().ddragon_versions_url:
                return _Response([patch])
            if url == Settings().ddragon_champions_url.format(version=patch):
                return _Response(
                    {
                        "data": {
                            "Yuumi": {
                                "key": "1",
                                "id": "Yuumi",
                                "name": "Yuumi",
                                "image": {"full": "Yuumi.png"},
                            }
                        }
                    }
                )
            raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("app.services.champion_sync.httpx.AsyncClient", _AsyncClient)

    service = ChampionSyncService(Settings(), repository)
    synced_patch = await service.sync()
    champion_lookup = await repository.get_champion_lookup()

    assert synced_patch == patch
    assert champion_lookup[1].roles == ["support"]
    assert champion_lookup[1].primary_role == "support"
    assert [(hint.role, hint.games) for hint in champion_lookup[1].role_hints] == [("support", 42000)]
