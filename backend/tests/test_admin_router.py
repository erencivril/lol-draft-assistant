from __future__ import annotations

import aiosqlite
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.db.repository import DatabaseRepository
from app.routers import admin as admin_router


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
async def test_admin_routes_expose_patch_scope_and_bridge_health(repository: DatabaseRepository) -> None:
    await repository.upsert_patch_generation(patch="16.5.1", is_active=True, scope_total=80)
    await repository.upsert_scope_status(
        region="TR",
        rank_tier="silver",
        role="jungle",
        patch="16.5.1",
        status="ready",
        empty_scope=False,
        last_success_at="2026-03-11T00:00:00+00:00",
        last_error="",
        last_tier_refresh_at="2026-03-11T00:00:00+00:00",
        last_build_refresh_at="2026-03-11T00:05:00+00:00",
        next_tier_due_at="2026-03-11T01:00:00+00:00",
        next_build_due_at="2026-03-11T02:00:00+00:00",
        tier_rows=20,
        matchup_rows=400,
        synergy_rows=320,
        http_ok=True,
        fallback_used=False,
        fallback_failures=0,
        tier_signature="tier-sig",
        build_signature="build-sig",
        patch_generation_id="16.5.1",
    )
    await repository.refresh_patch_generation_metrics(patch="16.5.1")
    await repository.upsert_bridge_session(
        device_id="pc-1",
        label="Desktop",
        token_hash="hash",
        connected=True,
        auto_region="TR",
        auto_rank_tier="silver",
        client_patch="16.5.1",
        queue_type="RANKED_SOLO_5x5",
    )
    await repository.record_parser_event(
        region="TR",
        rank_tier="silver",
        role="jungle",
        patch="16.5.1",
        champion_id=None,
        stage="tier",
        event_type="http_parse_ok",
        severity="info",
        message="Tier page parsed cleanly.",
        used_fallback=False,
    )

    app = FastAPI()
    app.include_router(admin_router.router)
    app.state.repository = repository
    app.state.settings = type("SettingsStub", (), {"scheduled_regions": ["TR"], "scheduled_ranks": ["silver"], "scheduled_roles": ["jungle"], "hot_regions": ["TR"], "hot_ranks": ["silver"]})()
    app.state.orchestrator = type("OrchestratorStub", (), {"refresh_matrix": None, "refresh_due_scopes": None})()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        overview_response = await client.get("/api/admin/overview")
        scopes_response = await client.get("/api/admin/scopes")
        parsers_response = await client.get("/api/admin/parsers")

    assert overview_response.status_code == 200
    overview = overview_response.json()
    assert overview["active_generation"]["patch"] == "16.5.1"
    assert overview["bridge_sessions"][0]["device_id"] == "pc-1"

    assert scopes_response.status_code == 200
    scopes = scopes_response.json()["items"]
    assert scopes[0]["region"] == "TR"
    assert scopes[0]["status"] == "ready"

    assert parsers_response.status_code == 200
    parser_snapshot = parsers_response.json()
    assert parser_snapshot["total_events"] >= 1
