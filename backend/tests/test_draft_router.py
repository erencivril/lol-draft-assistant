from __future__ import annotations

import aiosqlite
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.db.repository import ChampionRecord, DatabaseRepository, MatchupRecord, TierStatRecord
from app.domain.draft import DraftState, TeamSlot
from app.domain.settings import ResolvedFilters, UserSettings
from app.routers import draft as draft_router
from app.services.recommendation_service import RecommendationService
from app.services.session_registry import DEFAULT_SESSION_ID, SessionRegistry
from app.ws.draft_ws import DraftWebSocketManager


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


def _build_test_app(
    *,
    repository: DatabaseRepository,
    recommendation_service: RecommendationService,
    draft_state: DraftState,
    settings: UserSettings,
) -> tuple[FastAPI, object]:
    session_registry = SessionRegistry()
    user_session = session_registry.get_or_create(DEFAULT_SESSION_ID, settings)
    user_session.runtime.draft_state = draft_state

    app = FastAPI()
    app.include_router(draft_router.router)
    app.state.repository = repository
    app.state.recommendation_service = recommendation_service
    app.state.ws_manager = DraftWebSocketManager()
    app.state.default_user_settings = settings
    app.state.session_registry = session_registry

    async def recompute_session(session, *, draft_state=None) -> None:
        if draft_state is not None:
            session.runtime.draft_state = draft_state
        snapshot = await recommendation_service.analyze(
            session.runtime.draft_state,
            ResolvedFilters(region="TR", rank_tier="silver", role="middle"),
            session.user_settings,
            session.runtime.draft_role_overrides,
        )
        session.runtime.draft_state = snapshot.draft_state
        session.runtime.recommendations = snapshot.recommendations

    app.state.recompute_session = recompute_session
    return app, user_session


@pytest.mark.asyncio
async def test_put_draft_overrides_recomputes_payload(repository: DatabaseRepository) -> None:
    patch = "16.5.1"

    await repository.upsert_champions(
        [
            ChampionRecord(champion_id=1, key="Ahri", name="Ahri", image_url="ahri.png", roles=["middle"], patch=patch),
            ChampionRecord(champion_id=2, key="Poppy", name="Poppy", image_url="poppy.png", roles=["top", "support"], patch=patch),
        ]
    )
    await repository.replace_tier_stats(
        region="TR",
        rank_tier="silver",
        role="middle",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=1,
                region="TR",
                rank_tier="silver",
                role="middle",
                win_rate=52.0,
                pick_rate=8.0,
                ban_rate=4.0,
                tier_grade="A",
                games=30000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )
    await repository.replace_tier_stats(
        region="TR",
        rank_tier="silver",
        role="top",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=2,
                region="TR",
                rank_tier="silver",
                role="top",
                win_rate=51.0,
                pick_rate=5.0,
                ban_rate=2.0,
                tier_grade="B",
                games=25000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )
    await repository.replace_tier_stats(
        region="TR",
        rank_tier="silver",
        role="support",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=2,
                region="TR",
                rank_tier="silver",
                role="support",
                win_rate=52.0,
                pick_rate=5.1,
                ban_rate=2.0,
                tier_grade="A",
                games=25000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )
    await repository.replace_matchups(
        region="TR",
        rank_tier="silver",
        role="middle",
        patch=patch,
        records=[
            MatchupRecord(
                champion_id=1,
                opponent_id=2,
                region="TR",
                rank_tier="silver",
                role="middle",
                opponent_role="support",
                win_rate=56.0,
                delta1=2.0,
                delta2=15.0,
                games=1200,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )

    recommendation_service = RecommendationService(repository)
    await recommendation_service.rebuild_indexes()
    app, user_session = _build_test_app(
        repository=repository,
        recommendation_service=recommendation_service,
        draft_state=DraftState(
            local_player_cell_id=1,
            local_player_assigned_role="middle",
            my_team_picks=[TeamSlot(cell_id=1, champion_id=0, assigned_role="middle", is_local_player=True)],
            enemy_team_picks=[TeamSlot(cell_id=6, champion_id=2, assigned_role=None)],
            my_bans=[],
            enemy_bans=[],
            session_status="active",
        ),
        settings=UserSettings(top_n=2),
    )

    await app.state.recompute_session(user_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.put(
            "/api/draft/overrides",
            json={"overrides": [{"team": "enemy", "cell_id": 6, "role": "support"}]},
        )

    assert response.status_code == 200
    payload = response.json()
    enemy_slot = payload["draft_state"]["enemy_team_picks"][0]
    assert enemy_slot["effective_role"] == "support"
    assert enemy_slot["role_source"] == "manual"
    assert payload["recommendations"]["picks"][0]["explanation"]["counters"][0]["match_role_source"] == "manual"


@pytest.mark.asyncio
async def test_post_draft_preview_returns_alternate_role_scope(repository: DatabaseRepository) -> None:
    patch = "16.5.1"

    await repository.upsert_champions(
        [
            ChampionRecord(champion_id=1, key="Ahri", name="Ahri", image_url="ahri.png", roles=["middle"], patch=patch),
            ChampionRecord(champion_id=2, key="Thresh", name="Thresh", image_url="thresh.png", roles=["support"], patch=patch),
            ChampionRecord(champion_id=3, key="Leona", name="Leona", image_url="leona.png", roles=["support"], patch=patch),
        ]
    )
    await repository.replace_tier_stats(
        region="TR",
        rank_tier="silver",
        role="middle",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=1,
                region="TR",
                rank_tier="silver",
                role="middle",
                win_rate=52.0,
                pick_rate=8.0,
                ban_rate=4.0,
                tier_grade="A",
                games=30000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )
    await repository.replace_tier_stats(
        region="TR",
        rank_tier="silver",
        role="support",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=2,
                region="TR",
                rank_tier="silver",
                role="support",
                win_rate=53.0,
                pick_rate=7.0,
                ban_rate=4.0,
                tier_grade="S",
                games=30000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
            TierStatRecord(
                champion_id=3,
                region="TR",
                rank_tier="silver",
                role="support",
                win_rate=51.0,
                pick_rate=7.0,
                ban_rate=3.0,
                tier_grade="A",
                games=30000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )

    recommendation_service = RecommendationService(repository)
    await recommendation_service.rebuild_indexes()
    app, _user_session = _build_test_app(
        repository=repository,
        recommendation_service=recommendation_service,
        draft_state=DraftState(
            local_player_cell_id=1,
            local_player_assigned_role="middle",
            my_team_picks=[TeamSlot(cell_id=1, champion_id=0, assigned_role="middle", is_local_player=True)],
            enemy_team_picks=[],
            my_bans=[],
            enemy_bans=[],
            session_status="active",
        ),
        settings=UserSettings(top_n=2),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/draft/preview",
            json={"region": "TR", "rank_tier": "silver", "role": "support"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["filters"] == {"region": "TR", "rank_tier": "silver", "role": "support"}
    assert payload["recommendations"]["picks"][0]["suggested_role"] == "support"
    assert payload["recommendations"]["picks"][0]["champion_name"] == "Thresh"
