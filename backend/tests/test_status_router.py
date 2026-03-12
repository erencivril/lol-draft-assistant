from __future__ import annotations

import aiosqlite
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.db.repository import BridgeSessionRecord
from app.domain.draft import DraftState
from app.domain.settings import ResolvedFilters
from app.domain.settings import UserSettings
from app.routers import status as status_router
from app.services.session_registry import DEFAULT_SESSION_ID, SessionRegistry, resolve_effective_session


class _CacheRepositoryStub:
    async def status_snapshot(self):
        raise aiosqlite.OperationalError("database is locked")


class _SessionRepositoryStub:
    def __init__(
        self,
        *,
        latest_bridge: BridgeSessionRecord | None = None,
        bridges: dict[str, BridgeSessionRecord] | None = None,
    ) -> None:
        self.latest_bridge = latest_bridge
        self.bridges = bridges or {}

    async def latest_bridge_session(self) -> BridgeSessionRecord | None:
        return self.latest_bridge

    async def get_bridge_session(self, *, device_id: str) -> BridgeSessionRecord | None:
        return self.bridges.get(device_id)


def _build_bridge_record(
    *,
    device_id: str,
    region: str = "TR",
    rank_tier: str = "gold",
    role: str = "middle",
) -> BridgeSessionRecord:
    draft_state = DraftState(
        phase="PLANNING",
        local_player_assigned_role=role,
        session_status="active",
    )
    return BridgeSessionRecord(
        device_id=device_id,
        label=device_id,
        token_hash="hash",
        connected=True,
        last_seen_at="2026-03-12T00:00:00+00:00",
        auto_region=region,
        auto_rank_tier=rank_tier,
        client_patch="16.5.1",
        queue_type="RANKED_SOLO_5X5",
        source="bridge",
        draft_state_json=draft_state.model_dump_json(),
        created_at="2026-03-12T00:00:00+00:00",
        updated_at="2026-03-12T00:00:00+00:00",
    )


def _configure_status_app(
    *,
    app: FastAPI,
    repository: _SessionRepositoryStub,
    session_registry: SessionRegistry,
) -> None:
    app.state.repository = repository
    app.state.default_user_settings = UserSettings()
    app.state.session_registry = session_registry
    app.state.status_snapshot_cache = {
        "champion_count": 0,
        "latest_patch": "16.5.1",
        "tier_stats_count": 0,
        "matchups_count": 0,
        "synergies_count": 0,
        "latest_data_fetch_at": None,
        "historical_rows": 0,
        "data_patches": [],
    }
    app.state.settings = type("SettingsStub", (), {"default_region": "TR", "default_rank_tier": "emerald"})()
    app.state.resolve_filters_for = lambda session: ResolvedFilters(
        region=session.runtime.auto_region or session.user_settings.region_override,
        rank_tier=session.runtime.auto_rank_tier or session.user_settings.rank_override,
        role=(
            session.runtime.draft_state.local_player_effective_role
            or session.runtime.draft_state.local_player_assigned_role
            or session.user_settings.role_override
        ),
    )

    async def resolve_session(requested_session: str | None):
        return await resolve_effective_session(
            requested_session=requested_session,
            registry=session_registry,
            default_settings=app.state.default_user_settings,
            repository=repository,
        )

    app.state.resolve_session = resolve_session


@pytest.mark.asyncio
async def test_status_route_uses_cached_snapshot_when_database_is_unavailable() -> None:
    app = FastAPI()
    app.include_router(status_router.router)
    app.state.repository = _CacheRepositoryStub()
    session_registry = SessionRegistry()
    user_session = session_registry.get_or_create(DEFAULT_SESSION_ID, UserSettings())
    app.state.session_registry = session_registry
    app.state.default_user_settings = UserSettings()
    app.state.status_snapshot_cache = {
        "champion_count": 172,
        "latest_patch": "16.5.1",
        "tier_stats_count": 100,
        "matchups_count": 200,
        "synergies_count": 300,
        "latest_data_fetch_at": "2026-03-11T00:00:00+00:00",
        "historical_rows": 0,
        "data_patches": [],
    }
    app.state.settings = type("SettingsStub", (), {"default_region": "TR", "default_rank_tier": "silver"})()

    def broken_filters(_session):
        raise aiosqlite.OperationalError("database is locked")

    user_session.runtime.bridge_connected = True
    app.state.resolve_filters_for = broken_filters

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        health_response = await client.get("/api/health")
        status_response = await client.get("/api/status")

    assert health_response.status_code == 200
    assert health_response.json()["status"] == "ok"

    assert status_response.status_code == 200
    payload = status_response.json()
    assert payload["effective_region"] == "TR"
    assert payload["effective_rank_tier"] == "silver"
    assert payload["storage"]["latest_patch"] == "16.5.1"
    assert payload["storage"]["champion_count"] == 172


@pytest.mark.asyncio
async def test_status_route_without_session_uses_latest_bridge_session() -> None:
    app = FastAPI()
    app.include_router(status_router.router)
    session_registry = SessionRegistry()
    repository = _SessionRepositoryStub(
        latest_bridge=_build_bridge_record(
            device_id="DESKTOP-CLMD3HB",
            region="TR",
            rank_tier="gold",
            role="middle",
        )
    )
    _configure_status_app(app=app, repository=repository, session_registry=session_registry)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["bridge_connected"] is True
    assert payload["source_device_id"] == "DESKTOP-CLMD3HB"
    assert payload["effective_region"] == "TR"
    assert payload["effective_rank_tier"] == "gold"
    assert payload["effective_role"] == "middle"


@pytest.mark.asyncio
async def test_status_route_prefers_explicit_session_over_latest_bridge() -> None:
    app = FastAPI()
    app.include_router(status_router.router)
    session_registry = SessionRegistry()
    repository = _SessionRepositoryStub(
        latest_bridge=_build_bridge_record(
            device_id="alpha",
            region="TR",
            rank_tier="gold",
            role="middle",
        )
    )
    _configure_status_app(app=app, repository=repository, session_registry=session_registry)
    beta_session = session_registry.get_or_create("beta", UserSettings())
    beta_session.runtime.bridge_connected = True
    beta_session.runtime.source_device_id = "beta"
    beta_session.runtime.auto_region = "EUW"
    beta_session.runtime.auto_rank_tier = "platinum"
    beta_session.runtime.draft_state = DraftState(
        phase="PLANNING",
        local_player_assigned_role="support",
        session_status="active",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/status?session=beta")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_device_id"] == "beta"
    assert payload["effective_region"] == "EUW"
    assert payload["effective_rank_tier"] == "platinum"
    assert payload["effective_role"] == "support"


@pytest.mark.asyncio
async def test_status_route_without_session_falls_back_to_local_session_when_no_bridge_exists() -> None:
    app = FastAPI()
    app.include_router(status_router.router)
    session_registry = SessionRegistry()
    repository = _SessionRepositoryStub()
    _configure_status_app(app=app, repository=repository, session_registry=session_registry)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["bridge_connected"] is False
    assert payload["source_device_id"] is None
    assert payload["effective_region"] == "TR"
    assert payload["effective_rank_tier"] == "emerald"
    assert payload["effective_role"] == "middle"
