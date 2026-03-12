from __future__ import annotations

import asyncio
import signal
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from app.config import get_settings
from app.db.connection import create_connection
from app.db.repository import DatabaseRepository
from app.logging_config import setup_logging
from app.services.champion_sync import ChampionSyncService
from app.services.recommendation_service import RecommendationService
from app.services.scheduler import SchedulerService
from app.services.scraper_orchestrator import ScraperOrchestrator


async def run_worker() -> None:
    settings = get_settings()
    setup_logging(settings.logs_dir, debug=settings.debug)
    connection = await create_connection(str(settings.database_path))
    repository = DatabaseRepository(connection)
    await repository.initialize()
    recommendation_service = RecommendationService(repository)
    champion_sync_service = ChampionSyncService(settings, repository)
    orchestrator = ScraperOrchestrator(settings, repository, champion_sync_service, recommendation_service)

    async def cleanup_bridge_sessions() -> None:
        await repository.expire_bridge_sessions(
            stale_before=(datetime.now(UTC) - timedelta(seconds=settings.bridge_session_timeout_seconds)).isoformat()
        )

    scheduler = SchedulerService(settings, orchestrator, cleanup_bridge_sessions)
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for signal_name in ("SIGINT", "SIGTERM"):
        signal_value = getattr(signal, signal_name, None)
        if signal_value is None:
            continue
        with suppress(NotImplementedError):
            loop.add_signal_handler(signal_value, stop_event.set)

    try:
        await recommendation_service.rebuild_indexes()
        scheduler.start()
        await stop_event.wait()
    finally:
        scheduler.shutdown()
        await connection.close()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
