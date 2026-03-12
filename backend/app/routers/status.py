from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from app.domain.settings import ResolvedFilters

router = APIRouter(prefix="/api", tags=["status"])
logger = logging.getLogger("lda.routers.status")


async def _get_session(request: Request, session_id: str | None):
    resolver = getattr(request.app.state, "resolve_session", None)
    if resolver is not None:
        return await resolver(session_id)
    return request.app.state.session_registry.get_or_create(
        session_id or "__local__",
        request.app.state.default_user_settings,
    )


def _fallback_filters(request: Request, user_session) -> ResolvedFilters:
    runtime = user_session.runtime
    user_settings = user_session.user_settings
    settings = request.app.state.settings
    region = runtime.auto_region if user_settings.region_mode == "auto" else user_settings.region_override
    rank_tier = runtime.auto_rank_tier if user_settings.rank_mode == "auto" else user_settings.rank_override
    if user_settings.role_mode == "auto":
        role = runtime.draft_state.local_player_effective_role or runtime.draft_state.local_player_assigned_role or user_settings.role_override
    else:
        role = user_settings.role_override
    return ResolvedFilters(
        region=region or settings.default_region,
        rank_tier=rank_tier or settings.default_rank_tier,
        role=role or "middle",
    )


@router.get("/health")
async def get_health(request: Request, session: str | None = None):
    runtime = (await _get_session(request, session)).runtime
    return {
        "status": "ok",
        "bridge_connected": runtime.bridge_connected,
        "lcu_connected": runtime.lcu_connected,
    }


@router.get("/status")
async def get_status(request: Request, session: str | None = None):
    user_session = await _get_session(request, session)
    runtime = user_session.runtime
    snapshot = request.app.state.status_snapshot_cache
    try:
        effective_filters = request.app.state.resolve_filters_for(user_session)
    except Exception as exc:
        logger.warning("Effective filter fallback triggered: %s", exc)
        effective_filters = _fallback_filters(request, user_session)

    return {
        "lcu_connected": runtime.lcu_connected,
        "bridge_connected": runtime.bridge_connected,
        "source_device_id": runtime.source_device_id,
        "auto_region": runtime.auto_region,
        "auto_rank_tier": runtime.auto_rank_tier,
        "auto_role": runtime.draft_state.local_player_assigned_role,
        "client_patch": runtime.draft_state.patch,
        "effective_region": effective_filters.region,
        "effective_rank_tier": effective_filters.rank_tier,
        "effective_role": effective_filters.role,
        "exact_data_available": runtime.recommendations.exact_data_available,
        "patch_trusted": runtime.recommendations.patch_trusted,
        "scope_complete": runtime.recommendations.scope_complete,
        "scope_ready": runtime.recommendations.scope_ready,
        "scope_last_synced_at": runtime.recommendations.scope_last_synced_at,
        "scope_freshness": runtime.recommendations.scope_freshness,
        "fallback_used_recently": runtime.recommendations.fallback_used_recently,
        "active_patch_generation": runtime.recommendations.active_patch_generation,
        "recommendation_warnings": runtime.recommendations.warnings,
        "draft_phase": runtime.draft_state.phase,
        "latest_patch": snapshot["latest_patch"],
        "storage": snapshot,
    }
