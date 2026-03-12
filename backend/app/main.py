from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.db.connection import create_connection
from app.db.repository import DatabaseRepository
from app.domain.draft import DraftState
from app.domain.settings import ResolvedFilters
from app.logging_config import setup_logging
from app.routers import admin, bridge, data, draft, recommend, settings as settings_router, status
from app.services.champion_sync import ChampionSyncService
from app.services.draft_state_builder import DraftStateBuilder
from app.services.lcu_connector import LcuConnector
from app.services.recommendation_service import RecommendationService
from app.services.scheduler import SchedulerService
from app.services.scraper_orchestrator import ScraperOrchestrator
from app.services.session_registry import (
    DEFAULT_SESSION_ID,
    SessionRegistry,
    UserSession,
    resolve_effective_session,
)
from app.ws.draft_ws import DraftWebSocketManager, router as draft_ws_router

logger = logging.getLogger("lda.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.logs_dir, debug=settings.debug)
    logger.info("App startup: opening database connection")
    connection = await create_connection(
        str(settings.database_path),
        timeout_seconds=5.0,
        busy_timeout_ms=750,
    )
    repository = DatabaseRepository(connection)
    logger.info("App startup: initializing repository")
    await repository.initialize()
    default_user_settings = await repository.get_settings()
    logger.info("App startup: opening recommendation read connection")
    recommendation_connection = await create_connection(
        str(settings.database_path),
        timeout_seconds=5.0,
        busy_timeout_ms=2000,
    )
    recommendation_repository = DatabaseRepository(recommendation_connection)
    await recommendation_repository.initialize()
    logger.info("App startup: building runtime services")

    session_registry = SessionRegistry()
    session_registry.get_or_create(DEFAULT_SESSION_ID, default_user_settings)
    ws_manager = DraftWebSocketManager()
    recommendation_service = RecommendationService(recommendation_repository)
    champion_sync_service = ChampionSyncService(settings, repository)
    orchestrator = ScraperOrchestrator(settings, repository, champion_sync_service, recommendation_service)
    draft_builder = DraftStateBuilder()
    lcu_connector = LcuConnector(settings, draft_builder)
    warm_indexes_task = None

    def get_session(session_id: str | None = DEFAULT_SESSION_ID) -> UserSession:
        return session_registry.get_or_create(session_id or DEFAULT_SESSION_ID, app.state.default_user_settings)

    async def resolve_session(requested_session: str | None) -> UserSession:
        return await resolve_effective_session(
            requested_session=requested_session,
            registry=session_registry,
            default_settings=app.state.default_user_settings,
            repository=repository,
        )

    def resolve_filters_for(session: UserSession) -> ResolvedFilters:
        runtime = session.runtime
        user_settings = session.user_settings
        region = runtime.auto_region if user_settings.region_mode == "auto" else user_settings.region_override
        rank = runtime.auto_rank_tier if user_settings.rank_mode == "auto" else user_settings.rank_override
        detected_role = runtime.draft_state.local_player_effective_role or runtime.draft_state.local_player_assigned_role
        if user_settings.role_mode == "auto":
            role = detected_role or user_settings.role_override
        else:
            role = user_settings.role_override
        return ResolvedFilters(
            region=region or settings.default_region,
            rank_tier=rank or settings.default_rank_tier,
            role=role,
        )

    async def recompute_session(session: UserSession, *, draft_state=None) -> None:
        session.touch()
        runtime = session.runtime
        if draft_state is not None:
            runtime.draft_state = draft_state
        runtime.clear_draft_role_overrides_if_inactive()
        snapshot = await recommendation_service.analyze(
            runtime.draft_state,
            resolve_filters_for(session),
            session.user_settings,
            runtime.draft_role_overrides,
        )
        runtime.draft_state = snapshot.draft_state
        runtime.recommendations = snapshot.recommendations

    async def cleanup_bridge_sessions() -> None:
        expired = await repository.expire_bridge_sessions(
            stale_before=(datetime.now(UTC) - timedelta(seconds=settings.bridge_session_timeout_seconds)).isoformat()
        )
        expired_session_ids = {session.device_id for session in expired}
        expired_session_ids.update(session_registry.expire_stale(timeout_seconds=300))
        if not expired_session_ids:
            return
        for session_id in expired_session_ids:
            await ws_manager.close_session_connections(session_id)
            session_registry.remove(session_id)

    scheduler = SchedulerService(settings, orchestrator, cleanup_bridge_sessions)

    app.state.settings = settings
    app.state.repository = repository
    app.state.default_user_settings = default_user_settings
    app.state.status_snapshot_cache = {
        "champion_count": 0,
        "latest_patch": None,
        "tier_stats_count": 0,
        "matchups_count": 0,
        "synergies_count": 0,
        "latest_data_fetch_at": None,
        "historical_rows": 0,
        "data_patches": [],
    }
    try:
        app.state.status_snapshot_cache = await repository.status_snapshot()
    except Exception:
        logger.exception("App startup: failed to prime status snapshot cache")
    app.state.session_registry = session_registry
    app.state.get_session = get_session
    app.state.resolve_session = resolve_session
    app.state.ws_manager = ws_manager
    app.state.recommendation_service = recommendation_service
    app.state.orchestrator = orchestrator
    app.state.lcu_connector = lcu_connector
    app.state.resolve_filters_for = resolve_filters_for

    async def resolve_filters() -> ResolvedFilters:
        return resolve_filters_for(await resolve_session(None))

    app.state.resolve_filters = resolve_filters
    app.state.recompute_session = recompute_session

    async def on_lcu_update(snapshot):
        session = get_session(DEFAULT_SESSION_ID)
        session.runtime.lcu_connected = snapshot.connected
        session.runtime.auto_region = snapshot.auto_region
        session.runtime.auto_rank_tier = snapshot.auto_rank_tier
        await recompute_session(session, draft_state=snapshot.draft_state)
        await ws_manager.broadcast_session(session)

    if settings.enable_startup_index_warmup:
        logger.info("App startup: scheduling background recommendation warmup")
        warm_indexes_task = recommendation_service.warm_indexes_in_background()
    else:
        logger.info("App startup: skipping background recommendation warmup")
    if settings.enable_local_lcu:
        logger.info("App startup: starting local LCU connector")
        await lcu_connector.start(on_lcu_update)
    logger.info("App startup: starting scheduler")
    scheduler.start()
    logger.info("App startup complete")

    try:
        yield
    finally:
        logger.info("App shutdown: stopping services")
        if warm_indexes_task and not warm_indexes_task.done():
            warm_indexes_task.cancel()
        scheduler.shutdown()
        if settings.enable_local_lcu:
            await lcu_connector.stop()
        await recommendation_connection.close()
        await connection.close()
        logger.info("App shutdown complete")


app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
allow_origins = list(
    dict.fromkeys(
        [
            *get_settings().cors_origins,
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
        ]
    )
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(status.router)
app.include_router(settings_router.router)
app.include_router(draft.router)
app.include_router(bridge.router)
app.include_router(data.router)
app.include_router(recommend.router)
app.include_router(admin.router)
app.include_router(draft_ws_router)

frontend_dist = get_settings().frontend_dist
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
