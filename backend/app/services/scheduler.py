from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import Settings
from app.services.scraper_orchestrator import ScraperOrchestrator

logger = logging.getLogger("lda.services.scheduler")


class SchedulerService:
    def __init__(self, settings: Settings, orchestrator: ScraperOrchestrator, bridge_housekeeping=None) -> None:
        self.settings = settings
        self.orchestrator = orchestrator
        self.bridge_housekeeping = bridge_housekeeping
        self.scheduler = AsyncIOScheduler(timezone="UTC")

    def start(self) -> None:
        has_jobs = False
        if self.settings.enable_refresh_scheduler:
            self.scheduler.add_job(
                self._rolling_refresh,
                IntervalTrigger(minutes=self.settings.refresh_loop_minutes),
                max_instances=1,
                coalesce=True,
            )
            self.scheduler.add_job(
                self._integrity_refresh,
                "cron",
                hour=3,
                minute=0,
                max_instances=1,
                coalesce=True,
            )
            has_jobs = True
        if self.bridge_housekeeping is not None and self.settings.enable_bridge_housekeeping:
            self.scheduler.add_job(
                self.bridge_housekeeping,
                IntervalTrigger(seconds=max(10, int(self.settings.bridge_session_timeout_seconds / 2))),
                max_instances=1,
                coalesce=True,
            )
            has_jobs = True
        if not has_jobs:
            logger.info("Scheduler disabled by configuration")
            return
        self.scheduler.start()
        if self.settings.enable_refresh_scheduler and self.bridge_housekeeping is not None and self.settings.enable_bridge_housekeeping:
            logger.info(
                "Scheduler started: rolling refresh every %d min, daily integrity sweep at 03:00 UTC, bridge housekeeping enabled",
                self.settings.refresh_loop_minutes,
            )
        elif self.settings.enable_refresh_scheduler:
            logger.info(
                "Scheduler started: rolling refresh every %d min, daily integrity sweep at 03:00 UTC",
                self.settings.refresh_loop_minutes,
            )
        else:
            logger.info("Scheduler started: bridge housekeeping enabled")

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    async def _rolling_refresh(self) -> None:
        try:
            await self.orchestrator.refresh_due_scopes(
                regions=self.settings.scheduled_regions,
                ranks=self.settings.scheduled_ranks,
                roles=self.settings.scheduled_roles,
            )
        except Exception:
            logger.exception("Rolling refresh failed")

    async def _integrity_refresh(self) -> None:
        try:
            await self.orchestrator.refresh_due_scopes(
                regions=self.settings.scheduled_regions,
                ranks=self.settings.scheduled_ranks,
                roles=self.settings.scheduled_roles,
                limit=len(self.settings.scheduled_regions) * len(self.settings.scheduled_ranks) * len(self.settings.scheduled_roles),
                mode="integrity",
            )
        except Exception:
            logger.exception("Integrity refresh failed")
