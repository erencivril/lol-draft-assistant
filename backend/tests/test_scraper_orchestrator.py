from __future__ import annotations

import aiosqlite
import pytest
import pytest_asyncio

from app.config import Settings
from app.db.repository import ChampionRecord, DatabaseRepository, MatchupRecord, SynergyRecord, TierStatRecord
from app.providers.base import ScrapeBundle
from app.services.champion_sync import ChampionSyncService
from app.services.recommendation_service import RecommendationService
from app.services.scraper_orchestrator import ScraperOrchestrator


class FakeProvider:
    def __init__(self, champion_lookup: dict[int, ChampionRecord], bundle: ScrapeBundle) -> None:
        self.champion_lookup = champion_lookup
        self.bundle = bundle
        self.calls = 0

    async def refresh(self, *, region: str, rank_tier: str, role: str, patch: str, browser=None) -> ScrapeBundle:
        self.calls += 1
        return self.bundle


@pytest_asyncio.fixture
async def repository() -> DatabaseRepository:
    connection = await aiosqlite.connect(":memory:")
    connection.row_factory = aiosqlite.Row
    repository = DatabaseRepository(connection)
    await repository.initialize()
    try:
        yield repository
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_refresh_scope_resume_skips_existing_scope(
    repository: DatabaseRepository,
) -> None:
    patch = "16.5.1"

    champion = ChampionRecord(champion_id=1, key="Ahri", name="Ahri", image_url="", roles=["middle"], patch=patch)
    await repository.upsert_champions([champion])

    await repository.replace_tier_stats(
        region="TR",
        rank_tier="silver",
        role="middle",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=1,
                region="TR",
                rank_tier="silver",
                role="middle",
                win_rate=52.0,
                pick_rate=8.0,
                ban_rate=4.0,
                tier_grade="A",
                games=20000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            )
        ],
    )
    await repository.replace_matchups(
        region="TR",
        rank_tier="silver",
        role="middle",
        patch=patch,
        records=[
            MatchupRecord(
                champion_id=1,
                opponent_id=1,
                region="TR",
                rank_tier="silver",
                role="middle",
                opponent_role="middle",
                win_rate=50.0,
                delta1=0.0,
                delta2=0.0,
                games=100,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            )
        ],
    )
    await repository.replace_synergies(
        region="TR",
        rank_tier="silver",
        role="middle",
        patch=patch,
        records=[
            SynergyRecord(
                champion_id=1,
                teammate_id=1,
                region="TR",
                rank_tier="silver",
                role="middle",
                teammate_role="middle",
                duo_win_rate=50.0,
                synergy_delta=0.0,
                normalised_delta=0.0,
                games=100,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            )
        ],
    )
    run_id = await repository.start_provider_run(
        provider_name="lolalytics",
        region="TR",
        rank_tier="silver",
        role="middle",
        patch=patch,
        pages_total=2,
    )
    await repository.complete_provider_run(run_id, status="completed", pages_done=2)

    recommendation_service = RecommendationService(repository)
    orchestrator = ScraperOrchestrator(
        Settings(),
        repository,
        ChampionSyncService(Settings(), repository),
        recommendation_service,
    )
    provider = FakeProvider(
        champion_lookup={1: champion},
        bundle=ScrapeBundle(tier_stats=[], matchups=[], synergies=[]),
    )

    result = await orchestrator.refresh_scope(
        provider=provider,
        patch=patch,
        region="TR",
        ranks=["silver"],
        roles=["middle"],
        resume=True,
    )

    assert provider.calls == 0
    assert result == {"patch": patch, "region": "TR"}


@pytest.mark.asyncio
async def test_refresh_scope_resume_does_not_trust_partial_counts_without_completed_run(
    repository: DatabaseRepository,
) -> None:
    patch = "16.5.1"

    champion = ChampionRecord(champion_id=1, key="Ahri", name="Ahri", image_url="", roles=["middle"], patch=patch)
    await repository.upsert_champions([champion])

    await repository.replace_tier_stats(
        region="TR",
        rank_tier="silver",
        role="middle",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=1,
                region="TR",
                rank_tier="silver",
                role="middle",
                win_rate=52.0,
                pick_rate=8.0,
                ban_rate=4.0,
                tier_grade="A",
                games=20000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            )
        ],
    )
    await repository.replace_matchups(
        region="TR",
        rank_tier="silver",
        role="middle",
        patch=patch,
        records=[
            MatchupRecord(
                champion_id=1,
                opponent_id=1,
                region="TR",
                rank_tier="silver",
                role="middle",
                opponent_role="middle",
                win_rate=50.0,
                delta1=0.0,
                delta2=0.0,
                games=100,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            )
        ],
    )
    await repository.replace_synergies(
        region="TR",
        rank_tier="silver",
        role="middle",
        patch=patch,
        records=[
            SynergyRecord(
                champion_id=1,
                teammate_id=1,
                region="TR",
                rank_tier="silver",
                role="middle",
                teammate_role="middle",
                duo_win_rate=50.0,
                synergy_delta=0.0,
                normalised_delta=0.0,
                games=100,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            )
        ],
    )

    recommendation_service = RecommendationService(repository)
    orchestrator = ScraperOrchestrator(
        Settings(),
        repository,
        ChampionSyncService(Settings(), repository),
        recommendation_service,
    )
    provider = FakeProvider(
        champion_lookup={1: champion},
        bundle=ScrapeBundle(tier_stats=[], matchups=[], synergies=[]),
    )

    await orchestrator.refresh_scope(
        provider=provider,
        patch=patch,
        region="TR",
        ranks=["silver"],
        roles=["middle"],
        resume=True,
    )

    assert provider.calls == 1


@pytest.mark.asyncio
async def test_refresh_matrix_purges_old_patch_data(
    repository: DatabaseRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_patch = "16.5.1"
    new_patch = "16.6.1"
    champion = ChampionRecord(champion_id=1, key="Ahri", name="Ahri", image_url="", roles=["middle"], patch=old_patch)
    await repository.upsert_champions([champion])

    await repository.replace_tier_stats(
        region="TR",
        rank_tier="silver",
        role="middle",
        patch=old_patch,
        records=[
            TierStatRecord(
                champion_id=1,
                region="TR",
                rank_tier="silver",
                role="middle",
                win_rate=52.0,
                pick_rate=8.0,
                ban_rate=4.0,
                tier_grade="A",
                games=20000,
                patch=old_patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            )
        ],
    )

    recommendation_service = RecommendationService(repository)
    champion_sync_service = ChampionSyncService(Settings(), repository)

    async def fake_sync() -> str:
        await repository.upsert_champions(
            [ChampionRecord(champion_id=1, key="Ahri", name="Ahri", image_url="", roles=["middle"], patch=new_patch)]
        )
        return new_patch

    monkeypatch.setattr(champion_sync_service, "sync", fake_sync)
    monkeypatch.setattr(
        "app.services.scraper_orchestrator.LolalyticsProvider",
        lambda *_args, **_kwargs: FakeProvider(
            champion_lookup={1: ChampionRecord(champion_id=1, key="Ahri", name="Ahri", image_url="", roles=["middle"], patch=new_patch)},
            bundle=ScrapeBundle(tier_stats=[], matchups=[], synergies=[]),
        ),
    )

    orchestrator = ScraperOrchestrator(
        Settings(),
        repository,
        champion_sync_service,
        recommendation_service,
    )

    await orchestrator.refresh_matrix(regions=["TR"], ranks=["silver"], roles=["middle"])

    snapshot = await repository.status_snapshot()
    assert snapshot["latest_patch"] == new_patch
    assert snapshot["historical_rows"] == 0
