from __future__ import annotations

import hashlib
import inspect
import logging
from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.db.repository import DatabaseRepository, ScopeStatusRecord
from app.domain.ranks import SUPPORTED_RANKS
from app.domain.regions import SUPPORTED_REGIONS
from app.providers.lolalytics_provider import LolalyticsProvider
from app.services.champion_sync import ChampionSyncService
from app.services.recommendation_service import RecommendationService
from app.services.scoring_constants import SUPPORTED_ROLES

logger = logging.getLogger("lda.services.scraper_orchestrator")


class ScraperOrchestrator:
    def __init__(
        self,
        settings: Settings,
        repository: DatabaseRepository,
        champion_sync_service: ChampionSyncService,
        recommendation_service: RecommendationService,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.champion_sync_service = champion_sync_service
        self.recommendation_service = recommendation_service

    async def bootstrap(self, *, region: str | None = None) -> dict[str, str]:
        target_region = region or self.settings.default_region
        return await self.refresh_matrix(regions=[target_region], ranks=SUPPORTED_RANKS, roles=SUPPORTED_ROLES)

    async def refresh_matrix(
        self,
        *,
        regions: list[str],
        ranks: list[str],
        roles: list[str],
        resume: bool = False,
    ) -> dict[str, str]:
        patch = await self._prepare_patch_generation(regions=regions, ranks=ranks, roles=roles)
        provider = LolalyticsProvider(self.settings, await self.repository.get_champion_lookup())
        for region in regions:
            for rank_tier in ranks:
                for role in roles:
                    existing = await self.repository.get_scope_status(region=region, rank_tier=rank_tier, role=role, patch=patch)
                    if resume and existing and existing.status == "ready" and (existing.tier_rows > 0 or existing.empty_scope):
                        logger.info("Skipping ready scope region=%s rank=%s role=%s patch=%s", region, rank_tier, role, patch)
                        continue
                    await self.refresh_exact_scope(
                        provider=provider,
                        patch=patch,
                        region=region,
                        rank_tier=rank_tier,
                        role=role,
                        mode="manual_full",
                        force_build=True,
                    )
        await self._finalize_refresh(patch=patch)
        return {"patch": patch, "region": ",".join(regions)}

    async def refresh_due_scopes(
        self,
        *,
        regions: list[str] | None = None,
        ranks: list[str] | None = None,
        roles: list[str] | None = None,
        limit: int | None = None,
        mode: str = "rolling",
    ) -> dict[str, object]:
        target_regions = regions or self.settings.scheduled_regions
        target_ranks = ranks or self.settings.scheduled_ranks
        target_roles = roles or self.settings.scheduled_roles
        patch = await self._prepare_patch_generation(regions=target_regions, ranks=target_ranks, roles=target_roles)
        provider = LolalyticsProvider(self.settings, await self.repository.get_champion_lookup())
        due_scopes = await self._select_due_scopes(
            patch=patch,
            regions=target_regions,
            ranks=target_ranks,
            roles=target_roles,
            limit=limit or self.settings.refresh_batch_limit,
        )
        logger.info("Refreshing %d due scope(s) for patch=%s", len(due_scopes), patch)
        for candidate in due_scopes:
            await self.refresh_exact_scope(
                provider=provider,
                patch=patch,
                region=candidate["region"],
                rank_tier=candidate["rank_tier"],
                role=candidate["role"],
                mode=mode,
                force_build=False,
            )
        await self._finalize_refresh(patch=patch)
        return {"patch": patch, "count": len(due_scopes)}

    async def refresh_scope(
        self,
        *,
        provider: LolalyticsProvider,
        patch: str,
        region: str,
        ranks: list[str],
        roles: list[str],
        resume: bool = False,
        finalize: bool = True,
    ) -> dict[str, str]:
        for rank_tier in ranks:
            for role in roles:
                existing = await self.repository.get_scope_status(region=region, rank_tier=rank_tier, role=role, patch=patch)
                if resume:
                    if existing and existing.status == "ready" and (existing.tier_rows > 0 or existing.empty_scope):
                        continue
                    if existing is None:
                        latest_run = await self.repository.latest_provider_run(
                            provider_name="lolalytics",
                            region=region,
                            rank_tier=rank_tier,
                            role=role,
                            patch=patch,
                        )
                        counts = await self.repository.scope_counts(region=region, rank_tier=rank_tier, role=role, patch=patch)
                        if (
                            latest_run
                            and latest_run["status"] == "completed"
                            and counts["tier_stats"] > 0
                            and counts["matchups"] > 0
                            and counts["synergies"] > 0
                        ):
                            continue
                await self.refresh_exact_scope(
                    provider=provider,
                    patch=patch,
                    region=region,
                    rank_tier=rank_tier,
                    role=role,
                    mode="manual_scope",
                    force_build=True,
                )
        if finalize:
            await self._finalize_refresh(patch=patch)
        return {"patch": patch, "region": region}

    async def refresh_exact_scope(
        self,
        *,
        provider: LolalyticsProvider,
        patch: str,
        region: str,
        rank_tier: str,
        role: str,
        mode: str,
        force_build: bool,
    ) -> dict[str, object]:
        now = datetime.now(UTC)
        current_status = await self.repository.get_scope_status(region=region, rank_tier=rank_tier, role=role, patch=patch)
        priority = self._scope_priority(region=region, rank_tier=rank_tier, existing=current_status, now=now)
        job_id = await self.repository.start_scope_refresh_job(
            region=region,
            rank_tier=rank_tier,
            role=role,
            patch=patch,
            mode=mode,
            priority=priority,
        )
        provider_run_id = await self.repository.start_provider_run(
            provider_name="lolalytics",
            region=region,
            rank_tier=rank_tier,
            role=role,
            patch=patch,
            pages_total=len(provider.champion_lookup) + 1,
        )
        logger.info("Refreshing region=%s rank=%s role=%s mode=%s", region, rank_tier, role, mode)
        try:
            provider_supports_incremental = self._provider_supports_incremental(provider)
            tier_bundle = await self._provider_refresh(
                provider=provider,
                region=region,
                rank_tier=rank_tier,
                role=role,
                patch=patch,
                include_builds=False,
            )
            await self.repository.replace_tier_stats(region=region, rank_tier=rank_tier, role=role, patch=patch, records=tier_bundle.tier_stats)
            tier_signature = self._tier_signature(tier_bundle.tier_stats)
            build_refresh_needed = force_build or self._should_refresh_builds(
                existing=current_status,
                patch=patch,
                now=now,
                tier_signature=tier_signature,
            )

            build_matchups = current_status.matchup_rows if current_status else 0
            build_synergies = current_status.synergy_rows if current_status else 0
            build_signature = current_status.build_signature if current_status else ""
            last_build_refresh_at = current_status.last_build_refresh_at if current_status else None
            fallback_used = tier_bundle.fallback_used
            fallback_failures = tier_bundle.fallback_failures
            http_ok = tier_bundle.http_ok
            parser_events = list(tier_bundle.parser_events)
            bundle = tier_bundle

            if build_refresh_needed and not tier_bundle.empty_scope:
                if provider_supports_incremental:
                    bundle = await self._provider_refresh(
                        provider=provider,
                        region=region,
                        rank_tier=rank_tier,
                        role=role,
                        patch=patch,
                        include_builds=True,
                    )
                else:
                    bundle = tier_bundle
                await self.repository.replace_matchups(region=region, rank_tier=rank_tier, role=role, patch=patch, records=bundle.matchups)
                await self.repository.replace_synergies(region=region, rank_tier=rank_tier, role=role, patch=patch, records=bundle.synergies)
                build_matchups = len(bundle.matchups)
                build_synergies = len(bundle.synergies)
                build_signature = self._build_signature(bundle.matchups, bundle.synergies)
                last_build_refresh_at = now.isoformat()
                fallback_used = bundle.fallback_used
                fallback_failures = bundle.fallback_failures
                http_ok = bundle.http_ok
                parser_events = list(bundle.parser_events)

            for event in parser_events:
                await self.repository.record_parser_event(
                    region=region,
                    rank_tier=rank_tier,
                    role=role,
                    patch=patch,
                    champion_id=event.get("champion_id"),
                    stage=str(event["stage"]),
                    event_type=str(event["event_type"]),
                    severity=str(event["severity"]),
                    message=str(event["message"]),
                    used_fallback=bool(event.get("used_fallback")),
                )

            next_tier_due_at = (now + timedelta(hours=self.settings.tier_refresh_interval_hours)).isoformat()
            next_build_due_at = (now + self._build_refresh_interval(region=region, rank_tier=rank_tier)).isoformat()
            status = self._scope_status_name(
                empty_scope=tier_bundle.empty_scope,
                tier_rows=len(tier_bundle.tier_stats),
                matchup_rows=build_matchups,
                synergy_rows=build_synergies,
                built=build_refresh_needed,
            )
            await self.repository.upsert_scope_status(
                region=region,
                rank_tier=rank_tier,
                role=role,
                patch=patch,
                status=status,
                empty_scope=tier_bundle.empty_scope,
                last_success_at=now.isoformat(),
                last_error="",
                last_tier_refresh_at=now.isoformat(),
                last_build_refresh_at=last_build_refresh_at,
                next_tier_due_at=next_tier_due_at,
                next_build_due_at=next_build_due_at,
                tier_rows=len(tier_bundle.tier_stats),
                matchup_rows=build_matchups,
                synergy_rows=build_synergies,
                http_ok=http_ok,
                fallback_used=fallback_used,
                fallback_failures=fallback_failures,
                tier_signature=tier_signature,
                build_signature=build_signature,
                patch_generation_id=patch,
            )
            await self.repository.complete_scope_refresh_job(job_id, status="completed", fallback_used=fallback_used)
            await self.repository.complete_provider_run(provider_run_id, status="completed", pages_done=len(provider.champion_lookup) + 1)
            return {
                "region": region,
                "rank_tier": rank_tier,
                "role": role,
                "status": status,
                "patch": patch,
            }
        except Exception as exc:
            await self.repository.upsert_scope_status(
                region=region,
                rank_tier=rank_tier,
                role=role,
                patch=patch,
                status="failed",
                empty_scope=False,
                last_success_at=current_status.last_success_at if current_status else None,
                last_error=str(exc),
                last_tier_refresh_at=current_status.last_tier_refresh_at if current_status else None,
                last_build_refresh_at=current_status.last_build_refresh_at if current_status else None,
                next_tier_due_at=(now + timedelta(minutes=30)).isoformat(),
                next_build_due_at=(now + timedelta(minutes=30)).isoformat(),
                tier_rows=current_status.tier_rows if current_status else 0,
                matchup_rows=current_status.matchup_rows if current_status else 0,
                synergy_rows=current_status.synergy_rows if current_status else 0,
                http_ok=False,
                fallback_used=current_status.fallback_used if current_status else False,
                fallback_failures=(current_status.fallback_failures if current_status else 0) + 1,
                tier_signature=current_status.tier_signature if current_status else "",
                build_signature=current_status.build_signature if current_status else "",
                patch_generation_id=patch,
            )
            await self.repository.record_parser_event(
                region=region,
                rank_tier=rank_tier,
                role=role,
                patch=patch,
                stage="scope",
                event_type="scope_refresh_failed",
                severity="error",
                message=str(exc),
            )
            await self.repository.complete_scope_refresh_job(job_id, status="failed", fallback_used=False, notes=str(exc))
            await self.repository.complete_provider_run(provider_run_id, status="failed", pages_done=0, notes=str(exc))
            raise

    async def _prepare_patch_generation(self, *, regions: list[str], ranks: list[str], roles: list[str]) -> str:
        stale_before = (datetime.now(UTC) - timedelta(minutes=self.settings.scrape_stale_run_minutes)).isoformat()
        stale_runs = await self.repository.fail_stale_provider_runs(started_before=stale_before)
        if stale_runs:
            logger.warning("Marked %d stale provider runs as failed before refresh", stale_runs)

        patch = await self.champion_sync_service.sync()
        await self.repository.upsert_patch_generation(
            patch=patch,
            is_active=True,
            scope_total=len(regions) * len(ranks) * len(roles),
        )
        await self.repository.purge_stale_data(patch=patch)
        return patch

    async def _finalize_refresh(self, *, patch: str) -> None:
        await self.repository.refresh_patch_generation_metrics(patch=patch)
        await self.recommendation_service.rebuild_indexes()
        await self.champion_sync_service.update_roles_from_tier_stats(patch)

    async def _select_due_scopes(
        self,
        *,
        patch: str,
        regions: list[str],
        ranks: list[str],
        roles: list[str],
        limit: int,
    ) -> list[dict[str, str]]:
        current_statuses = await self.repository.list_scope_status(patch=patch)
        status_index = {
            (status.region, status.rank_tier, status.role): status
            for status in current_statuses
        }
        now = datetime.now(UTC)
        candidates: list[tuple[int, dict[str, str]]] = []
        for region in regions:
            for rank_tier in ranks:
                for role in roles:
                    existing = status_index.get((region, rank_tier, role))
                    due_reason = self._due_reason(existing=existing, patch=patch, now=now)
                    if due_reason is None:
                        continue
                    priority = self._scope_priority(region=region, rank_tier=rank_tier, existing=existing, now=now)
                    candidates.append(
                        (
                            priority,
                            {
                                "region": region,
                                "rank_tier": rank_tier,
                                "role": role,
                                "reason": due_reason,
                            },
                        )
                    )
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in candidates[:limit]]

    def _due_reason(self, *, existing: ScopeStatusRecord | None, patch: str, now: datetime) -> str | None:
        if existing is None:
            return "missing_scope"
        if existing.patch != patch:
            return "patch_changed"
        if existing.status in {"failed", "partial"}:
            return existing.status
        if self._is_due(existing.next_tier_due_at, now):
            return "tier_due"
        if self._is_due(existing.next_build_due_at, now):
            return "build_due"
        return None

    def _scope_priority(
        self,
        *,
        region: str,
        rank_tier: str,
        existing: ScopeStatusRecord | None,
        now: datetime,
    ) -> int:
        score = 0
        if region in self.settings.hot_regions and rank_tier in self.settings.hot_ranks:
            score += 20
        if region not in self.settings.hot_regions or rank_tier in self.settings.aggregate_ranks:
            score -= 5
        if existing is None:
            return score + 50
        if existing.status == "failed":
            score += 45
        elif existing.status == "partial":
            score += 35
        if self._is_due(existing.next_build_due_at, now):
            score += 20
        if self._is_due(existing.next_tier_due_at, now):
            score += 10
        return score

    def _should_refresh_builds(
        self,
        *,
        existing: ScopeStatusRecord | None,
        patch: str,
        now: datetime,
        tier_signature: str,
    ) -> bool:
        if existing is None:
            return True
        if existing.patch != patch:
            return True
        if existing.status in {"failed", "partial"}:
            return True
        if existing.empty_scope:
            return False
        if existing.matchup_rows == 0 or existing.synergy_rows == 0:
            return True
        if existing.tier_signature != tier_signature:
            return True
        return self._is_due(existing.next_build_due_at, now)

    def _scope_status_name(
        self,
        *,
        empty_scope: bool,
        tier_rows: int,
        matchup_rows: int,
        synergy_rows: int,
        built: bool,
    ) -> str:
        if empty_scope:
            return "ready"
        if tier_rows == 0:
            return "failed"
        if not built:
            return "ready" if matchup_rows > 0 and synergy_rows > 0 else "partial"
        if matchup_rows > 0 and synergy_rows > 0:
            return "ready"
        return "partial"

    def _tier_signature(self, records) -> str:
        digest = hashlib.sha256()
        for record in sorted(records, key=lambda item: item.tier_rank or 9999):
            digest.update(
                f"{record.champion_id}:{record.tier_rank}:{record.tier_grade}:{record.win_rate:.2f}:{record.pick_rate:.2f}:{record.ban_rate:.2f}:{record.pbi:.2f}".encode("utf-8")
            )
        return digest.hexdigest()

    def _build_signature(self, matchups, synergies) -> str:
        digest = hashlib.sha256()
        digest.update(str(len(matchups)).encode("utf-8"))
        digest.update(str(len(synergies)).encode("utf-8"))
        if matchups:
            top_matchups = sorted(matchups, key=lambda item: item.games, reverse=True)[:10]
            for record in top_matchups:
                digest.update(f"{record.champion_id}:{record.opponent_id}:{record.opponent_role}:{record.games}".encode("utf-8"))
        if synergies:
            top_synergies = sorted(synergies, key=lambda item: item.games, reverse=True)[:10]
            for record in top_synergies:
                digest.update(f"{record.champion_id}:{record.teammate_id}:{record.teammate_role}:{record.games}".encode("utf-8"))
        return digest.hexdigest()

    def _build_refresh_interval(self, *, region: str, rank_tier: str) -> timedelta:
        if region not in self.settings.hot_regions or rank_tier in self.settings.aggregate_ranks:
            return timedelta(hours=self.settings.aggregate_build_refresh_interval_hours)
        if rank_tier in self.settings.hot_ranks:
            return timedelta(hours=self.settings.hot_build_refresh_interval_hours)
        return timedelta(hours=self.settings.cold_build_refresh_interval_hours)

    def _is_due(self, value: str | None, now: datetime) -> bool:
        if not value:
            return True
        try:
            return datetime.fromisoformat(value) <= now
        except ValueError:
            return True

    def _provider_supports_incremental(self, provider) -> bool:
        try:
            signature = inspect.signature(provider.refresh)
        except (TypeError, ValueError):
            return False
        return "include_builds" in signature.parameters

    async def _provider_refresh(
        self,
        *,
        provider,
        region: str,
        rank_tier: str,
        role: str,
        patch: str,
        include_builds: bool,
    ):
        try:
            return await provider.refresh(
                region=region,
                rank_tier=rank_tier,
                role=role,
                patch=patch,
                include_builds=include_builds,
            )
        except TypeError:
            return await provider.refresh(
                region=region,
                rank_tier=rank_tier,
                role=role,
                patch=patch,
            )
