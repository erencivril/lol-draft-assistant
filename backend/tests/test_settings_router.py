from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.domain.settings import UserSettings
from app.routers import settings as settings_router
from app.services.session_registry import SessionRegistry


class _WsManagerStub:
    async def broadcast_session(self, _session) -> None:
        return None


@pytest.mark.asyncio
async def test_settings_are_isolated_per_session() -> None:
    app = FastAPI()
    app.include_router(settings_router.router)
    app.state.default_user_settings = UserSettings(region_override="TR", rank_override="silver", role_override="middle")
    app.state.session_registry = SessionRegistry()
    app.state.ws_manager = _WsManagerStub()

    async def recompute_session(_session, *, draft_state=None) -> None:
        return None

    app.state.recompute_session = recompute_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        initial_alpha = await client.get("/api/settings?session=alpha")
        update_alpha = await client.put(
            "/api/settings?session=alpha",
            json={
                "region_mode": "manual",
                "rank_mode": "manual",
                "role_mode": "manual",
                "region_override": "EUW",
                "rank_override": "gold",
                "role_override": "support",
                "auto_refresh": True,
                "top_n": 4,
                "weights": {
                    "counter": 0.35,
                    "synergy": 0.25,
                    "tier": 0.25,
                    "role_fit": 0.15,
                },
            },
        )
        final_alpha = await client.get("/api/settings?session=alpha")
        untouched_beta = await client.get("/api/settings?session=beta")

    assert initial_alpha.status_code == 200
    assert initial_alpha.json()["region_override"] == "TR"

    assert update_alpha.status_code == 200
    assert update_alpha.json()["region_override"] == "EUW"
    assert update_alpha.json()["role_override"] == "support"

    assert final_alpha.status_code == 200
    assert final_alpha.json()["rank_override"] == "gold"

    assert untouched_beta.status_code == 200
    assert untouched_beta.json()["region_override"] == "TR"
    assert untouched_beta.json()["role_override"] == "middle"
