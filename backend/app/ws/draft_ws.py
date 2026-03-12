from __future__ import annotations

from collections import defaultdict
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.session_registry import normalize_session_id

logger = logging.getLogger("lda.ws.draft_ws")


class DraftWebSocketManager:
    def __init__(self) -> None:
        self._session_connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._ws_to_session: dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, session_id: str) -> None:
        await websocket.accept()
        normalized_session_id = normalize_session_id(session_id)
        self.disconnect(websocket)
        self._session_connections[normalized_session_id].add(websocket)
        self._ws_to_session[websocket] = normalized_session_id
        logger.debug(
            "WS client connected for session=%s, total=%d",
            normalized_session_id,
            len(self._session_connections[normalized_session_id]),
        )

    def disconnect(self, websocket: WebSocket) -> None:
        session_id = self._ws_to_session.pop(websocket, None)
        if session_id is None:
            return
        connections = self._session_connections.get(session_id)
        if connections is not None:
            connections.discard(websocket)
            if not connections:
                self._session_connections.pop(session_id, None)
        logger.debug("WS client disconnected for session=%s", session_id)

    async def send_state_to(self, websocket: WebSocket, runtime) -> None:
        await websocket.send_json(self.build_payload(runtime))

    async def broadcast_session(self, session) -> None:
        session.touch()
        payload = self.build_payload(session.runtime)
        closed_connections: list[WebSocket] = []
        for connection in list(self._session_connections.get(session.session_id, set())):
            try:
                await connection.send_json(payload)
            except Exception:
                closed_connections.append(connection)
        for connection in closed_connections:
            self.disconnect(connection)

    async def close_session_connections(self, session_id: str) -> None:
        connections = list(self._session_connections.get(normalize_session_id(session_id), set()))
        for connection in connections:
            try:
                await connection.close()
            except Exception:
                logger.debug("Failed to close WS connection for session=%s", session_id, exc_info=True)
            finally:
                self.disconnect(connection)

    async def broadcast_state(self, runtime) -> None:
        payload = self.build_payload(runtime)
        closed_connections: list[WebSocket] = []
        for connection in list(self._ws_to_session):
            try:
                await connection.send_json(payload)
            except Exception:
                closed_connections.append(connection)
        for connection in closed_connections:
            self.disconnect(connection)

    def build_payload(self, runtime) -> dict[str, object]:
        return {
            "type": "state",
            "draft_state": runtime.draft_state.model_dump(mode="json"),
            "recommendations": runtime.recommendations.model_dump(mode="json"),
            "auto_region": runtime.auto_region,
            "auto_rank_tier": runtime.auto_rank_tier,
            "auto_role": runtime.draft_state.local_player_assigned_role,
            "lcu_connected": runtime.lcu_connected,
            "bridge_connected": runtime.bridge_connected,
            "source_device_id": runtime.source_device_id,
        }


router = APIRouter()


@router.websocket("/ws/draft")
async def draft_stream(websocket: WebSocket):
    manager: DraftWebSocketManager = websocket.app.state.ws_manager
    session_id = websocket.query_params.get("session")
    resolver = getattr(websocket.app.state, "resolve_session", None)
    if resolver is not None:
        session = await resolver(session_id)
    else:
        registry = websocket.app.state.session_registry
        fallback_session_id = session_id or "__local__"
        session = registry.get_or_create(fallback_session_id, websocket.app.state.default_user_settings)
    await manager.connect(websocket, session.session_id)
    await manager.send_state_to(websocket, session.runtime)
    try:
        while True:
            await websocket.receive_text()
            session.touch()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
