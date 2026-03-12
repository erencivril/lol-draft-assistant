from __future__ import annotations

import asyncio
import hashlib
import logging

import aiosqlite

from fastapi import APIRouter, Header, HTTPException, Request

from app.domain.bridge import (
    BridgeDraftStatePayload,
    BridgeHeartbeatPayload,
    BridgeRegisterPayload,
    BridgeRegisterResponse,
)
from app.services.session_registry import normalize_session_id

router = APIRouter(prefix="/api/bridge", tags=["bridge"])
logger = logging.getLogger("lda.routers.bridge")


def _authorize_bridge(request: Request, authorization: str | None) -> str:
    settings = request.app.state.settings
    tokens = settings.bridge_tokens
    if not tokens:
        raise HTTPException(status_code=503, detail="Bridge tokens are not configured.")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bridge bearer token.")
    token = authorization.split(" ", 1)[1].strip()
    if token not in tokens:
        raise HTTPException(status_code=403, detail="Invalid bridge token.")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _upsert_bridge_session_safe(request: Request, **kwargs) -> None:
    try:
        await asyncio.wait_for(request.app.state.repository.upsert_bridge_session(**kwargs), timeout=1.0)
    except asyncio.TimeoutError:
        logger.warning("Bridge session write skipped because the SQLite database did not respond in time")
    except aiosqlite.Error as exc:
        logger.warning("Bridge session write skipped because the SQLite database is unavailable: %s", exc)


async def _delete_bridge_session_safe(request: Request, *, device_id: str) -> None:
    try:
        await asyncio.wait_for(request.app.state.repository.delete_bridge_session(device_id=device_id), timeout=1.0)
    except asyncio.TimeoutError:
        logger.warning("Bridge session delete skipped because the SQLite database did not respond in time")
    except aiosqlite.Error as exc:
        logger.warning("Bridge session delete skipped because the SQLite database is unavailable: %s", exc)


def _get_session(request: Request, session_id: str):
    return request.app.state.session_registry.get_or_create(
        normalize_session_id(session_id),
        request.app.state.default_user_settings,
    )


@router.post("/register", response_model=BridgeRegisterResponse)
async def register_bridge(
    payload: BridgeRegisterPayload,
    request: Request,
    authorization: str | None = Header(default=None),
) -> BridgeRegisterResponse:
    token_hash = _authorize_bridge(request, authorization)
    await _upsert_bridge_session_safe(
        request,
        device_id=payload.device_id,
        label=payload.label,
        token_hash=token_hash,
        connected=True,
    )
    session = _get_session(request, payload.device_id)
    session.runtime.mark_bridge_seen(device_id=payload.device_id)
    return BridgeRegisterResponse(
        device_id=payload.device_id,
        heartbeat_interval_seconds=max(10, int(request.app.state.settings.bridge_session_timeout_seconds / 2)),
    )


@router.post("/heartbeat")
async def bridge_heartbeat(
    payload: BridgeHeartbeatPayload,
    request: Request,
    authorization: str | None = Header(default=None),
):
    token_hash = _authorize_bridge(request, authorization)
    await _upsert_bridge_session_safe(
        request,
        device_id=payload.device_id,
        label=payload.device_id,
        token_hash=token_hash,
        connected=True,
        auto_region=payload.auto_region,
        auto_rank_tier=payload.auto_rank_tier,
        client_patch=payload.client_patch,
        queue_type=payload.queue_type,
    )
    session = _get_session(request, payload.device_id)
    runtime = session.runtime
    runtime.lcu_connected = payload.lcu_connected
    runtime.auto_region = payload.auto_region or runtime.auto_region
    runtime.auto_rank_tier = payload.auto_rank_tier or runtime.auto_rank_tier
    runtime.mark_bridge_seen(device_id=payload.device_id)
    return {"status": "ok"}


@router.put("/draft-state")
async def update_bridge_draft_state(
    payload: BridgeDraftStatePayload,
    request: Request,
    authorization: str | None = Header(default=None),
):
    token_hash = _authorize_bridge(request, authorization)
    await _upsert_bridge_session_safe(
        request,
        device_id=payload.device_id,
        label=payload.device_id,
        token_hash=token_hash,
        connected=True,
        auto_region=payload.auto_region,
        auto_rank_tier=payload.auto_rank_tier,
        client_patch=payload.client_patch or payload.draft_state.patch,
        queue_type=payload.queue_type or payload.draft_state.queue_type,
        draft_state_json=payload.draft_state.model_dump_json(),
    )
    session = _get_session(request, payload.device_id)
    runtime = session.runtime
    runtime.lcu_connected = payload.lcu_connected
    runtime.auto_region = payload.auto_region
    runtime.auto_rank_tier = payload.auto_rank_tier
    runtime.mark_bridge_seen(device_id=payload.device_id)
    await request.app.state.recompute_session(session, draft_state=payload.draft_state)
    await request.app.state.ws_manager.broadcast_session(session)
    return request.app.state.ws_manager.build_payload(runtime)


@router.delete("/session/{device_id}")
async def delete_bridge_session(
    device_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    _authorize_bridge(request, authorization)
    await _delete_bridge_session_safe(request, device_id=device_id)
    await request.app.state.ws_manager.close_session_connections(device_id)
    request.app.state.session_registry.remove(device_id)
    return {"status": "disconnected"}
