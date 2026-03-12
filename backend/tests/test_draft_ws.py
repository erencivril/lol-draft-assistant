from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.repository import BridgeSessionRecord
from app.domain.draft import DraftState
from app.domain.settings import UserSettings
from app.services.session_registry import SessionRegistry, resolve_effective_session
from app.ws.draft_ws import DraftWebSocketManager, router as draft_ws_router


class _RepositoryStub:
    def __init__(self, *, latest_bridge: BridgeSessionRecord | None = None) -> None:
        self.latest_bridge = latest_bridge

    async def latest_bridge_session(self) -> BridgeSessionRecord | None:
        return self.latest_bridge

    async def get_bridge_session(self, *, device_id: str) -> BridgeSessionRecord | None:
        if self.latest_bridge and self.latest_bridge.device_id == device_id:
            return self.latest_bridge
        return None


def _build_bridge_record(device_id: str) -> BridgeSessionRecord:
    return BridgeSessionRecord(
        device_id=device_id,
        label=device_id,
        token_hash="hash",
        connected=True,
        last_seen_at="2026-03-12T00:00:00+00:00",
        auto_region="TR",
        auto_rank_tier="gold",
        client_patch="16.5.1",
        queue_type="RANKED_SOLO_5X5",
        source="bridge",
        draft_state_json=DraftState(
            phase="BAN_PICK",
            local_player_assigned_role="middle",
            session_status="active",
        ).model_dump_json(),
        created_at="2026-03-12T00:00:00+00:00",
        updated_at="2026-03-12T00:00:00+00:00",
    )


def test_draft_websocket_without_session_uses_latest_bridge_session() -> None:
    app = FastAPI()
    app.include_router(draft_ws_router)
    app.state.ws_manager = DraftWebSocketManager()
    app.state.default_user_settings = UserSettings()
    app.state.session_registry = SessionRegistry()
    repository = _RepositoryStub(latest_bridge=_build_bridge_record("DESKTOP-CLMD3HB"))

    async def resolve_session(requested_session: str | None):
        return await resolve_effective_session(
            requested_session=requested_session,
            registry=app.state.session_registry,
            default_settings=app.state.default_user_settings,
            repository=repository,
        )

    app.state.resolve_session = resolve_session

    with TestClient(app) as client:
        with client.websocket_connect("/ws/draft") as websocket:
            payload = websocket.receive_json()

    assert payload["type"] == "state"
    assert payload["bridge_connected"] is True
    assert payload["source_device_id"] == "DESKTOP-CLMD3HB"
    assert payload["auto_region"] == "TR"
    assert payload["auto_rank_tier"] == "gold"
    assert payload["draft_state"]["local_player_assigned_role"] == "middle"
