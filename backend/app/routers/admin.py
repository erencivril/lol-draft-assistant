from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Query, Request

router = APIRouter(tags=["admin"])


async def _admin_overview(request: Request):
    repository = request.app.state.repository
    storage = await repository.status_snapshot()
    active_generation = await repository.active_patch_generation()
    bridge_sessions = await repository.list_bridge_sessions()
    parser_health = await repository.parser_health_snapshot()
    return {
        "storage": storage,
        "active_generation": (
            {
                "patch": active_generation.patch,
                "scope_total": active_generation.scope_total,
                "ready_scopes": active_generation.ready_scopes,
                "partial_scopes": active_generation.partial_scopes,
                "stale_scopes": active_generation.stale_scopes,
                "failed_scopes": active_generation.failed_scopes,
                "ready_at": active_generation.ready_at,
            }
            if active_generation
            else None
        ),
        "bridge_sessions": [
            {
                "device_id": session.device_id,
                "label": session.label,
                "connected": session.connected,
                "last_seen_at": session.last_seen_at,
                "auto_region": session.auto_region,
                "auto_rank_tier": session.auto_rank_tier,
                "client_patch": session.client_patch,
                "queue_type": session.queue_type,
            }
            for session in bridge_sessions
        ],
        "parser_health": parser_health,
    }


@router.get("/api/admin/overview")
async def get_admin_overview(request: Request):
    return await _admin_overview(request)


@router.get("/api/admin/scopes")
async def get_admin_scopes(
    request: Request,
    region: str | None = Query(default=None),
    rank_tier: str | None = Query(default=None),
    role: str | None = Query(default=None),
):
    repository = request.app.state.repository
    active_generation = await repository.active_patch_generation()
    patch = active_generation.patch if active_generation else await repository.latest_patch()
    scopes = await repository.list_scope_status(patch=patch, region=region, rank_tier=rank_tier, role=role)
    return {
        "patch": patch,
        "items": [
            {
                "region": item.region,
                "rank_tier": item.rank_tier,
                "role": item.role,
                "status": item.status,
                "empty_scope": item.empty_scope,
                "last_success_at": item.last_success_at,
                "last_tier_refresh_at": item.last_tier_refresh_at,
                "last_build_refresh_at": item.last_build_refresh_at,
                "next_tier_due_at": item.next_tier_due_at,
                "next_build_due_at": item.next_build_due_at,
                "tier_rows": item.tier_rows,
                "matchup_rows": item.matchup_rows,
                "synergy_rows": item.synergy_rows,
                "http_ok": item.http_ok,
                "fallback_used": item.fallback_used,
                "fallback_used_recently": item.fallback_used_recently,
                "fallback_failures": item.fallback_failures,
                "last_error": item.last_error,
            }
            for item in scopes
        ],
    }


@router.get("/api/admin/jobs")
async def get_admin_jobs(request: Request):
    jobs = await request.app.state.repository.list_scope_refresh_jobs(limit=100)
    return {
        "items": [
            {
                "id": job.id,
                "region": job.region,
                "rank_tier": job.rank_tier,
                "role": job.role,
                "patch": job.patch,
                "mode": job.mode,
                "status": job.status,
                "priority": job.priority,
                "fallback_used": job.fallback_used,
                "notes": job.notes,
                "scheduled_at": job.scheduled_at,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
            }
            for job in jobs
        ]
    }


@router.get("/api/admin/parsers")
async def get_admin_parsers(request: Request):
    return await request.app.state.repository.parser_health_snapshot()


@router.post("/api/admin/refresh/scope")
async def refresh_admin_scope(
    request: Request,
    background_tasks: BackgroundTasks,
    region: str,
    rank_tier: str,
    role: str,
):
    background_tasks.add_task(
        request.app.state.orchestrator.refresh_matrix,
        regions=[region],
        ranks=[rank_tier],
        roles=[role],
        resume=False,
    )
    return {"status": "queued"}


@router.post("/api/admin/refresh/region")
async def refresh_admin_region(request: Request, background_tasks: BackgroundTasks, region: str):
    settings = request.app.state.settings
    background_tasks.add_task(
        request.app.state.orchestrator.refresh_matrix,
        regions=[region],
        ranks=settings.scheduled_ranks,
        roles=settings.scheduled_roles,
        resume=False,
    )
    return {"status": "queued"}


@router.post("/api/admin/refresh/hot")
async def refresh_admin_hot(request: Request, background_tasks: BackgroundTasks):
    settings = request.app.state.settings
    background_tasks.add_task(
        request.app.state.orchestrator.refresh_due_scopes,
        regions=settings.hot_regions,
        ranks=settings.hot_ranks,
        roles=settings.scheduled_roles,
        limit=len(settings.hot_regions) * len(settings.hot_ranks) * len(settings.scheduled_roles),
        mode="admin_hot",
    )
    return {"status": "queued"}


@router.post("/api/admin/rebuild-patch-generation")
async def rebuild_patch_generation(request: Request, background_tasks: BackgroundTasks):
    settings = request.app.state.settings
    background_tasks.add_task(
        request.app.state.orchestrator.refresh_due_scopes,
        regions=settings.scheduled_regions,
        ranks=settings.scheduled_ranks,
        roles=settings.scheduled_roles,
        limit=len(settings.scheduled_regions) * len(settings.scheduled_ranks) * len(settings.scheduled_roles),
        mode="rebuild_generation",
    )
    return {"status": "queued"}


@router.post("/api/admin/retry-failed")
async def retry_failed_scopes(request: Request, background_tasks: BackgroundTasks):
    settings = request.app.state.settings
    background_tasks.add_task(
        request.app.state.orchestrator.refresh_due_scopes,
        regions=settings.scheduled_regions,
        ranks=settings.scheduled_ranks,
        roles=settings.scheduled_roles,
        limit=len(settings.scheduled_regions) * len(settings.scheduled_ranks) * len(settings.scheduled_roles),
        mode="retry_failed",
    )
    return {"status": "queued"}


@router.get("/api/provider/runs")
async def get_runs(request: Request):
    snapshot = await request.app.state.repository.status_snapshot()
    return snapshot["latest_run"]


@router.get("/api/provider/status")
async def get_provider_status(request: Request):
    return await _admin_overview(request)


@router.post("/api/provider/full-refresh")
async def full_refresh(request: Request, background_tasks: BackgroundTasks):
    settings = request.app.state.settings
    background_tasks.add_task(
        request.app.state.orchestrator.refresh_matrix,
        regions=settings.scheduled_regions,
        ranks=settings.scheduled_ranks,
        roles=settings.scheduled_roles,
        resume=False,
    )
    return {"status": "queued"}


@router.post("/api/provider/refresh-current-patch")
async def refresh_current_patch(
    request: Request,
    background_tasks: BackgroundTasks,
    session: str | None = None,
):
    resolver = getattr(request.app.state, "resolve_session", None)
    if resolver is not None:
        user_session = await resolver(session)
    else:
        user_session = request.app.state.session_registry.get_or_create(
            session or "__local__",
            request.app.state.default_user_settings,
        )
    filters = request.app.state.resolve_filters_for(user_session)
    background_tasks.add_task(
        request.app.state.orchestrator.refresh_matrix,
        regions=[filters.region],
        ranks=[filters.rank_tier],
        roles=[filters.role] if filters.role else request.app.state.settings.scheduled_roles,
        resume=False,
    )
    return {"status": "queued"}
