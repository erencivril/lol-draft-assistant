from __future__ import annotations

import aiosqlite
import pytest
import pytest_asyncio

from app.db.repository import ChampionRecord, DatabaseRepository, MatchupRecord, SynergyRecord, TierStatRecord


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
async def test_status_snapshot_tracks_current_patch_only_and_purges_history(repository: DatabaseRepository) -> None:
    await repository.upsert_champions(
        [
            ChampionRecord(champion_id=1, key="Ahri", name="Ahri", image_url="", roles=["middle"], patch="16.6.1"),
        ]
    )

    await repository.replace_tier_stats(
        region="TR",
        rank_tier="silver",
        role="middle",
        patch="16.5.1",
        records=[
            TierStatRecord(
                champion_id=1,
                region="TR",
                rank_tier="silver",
                role="middle",
                win_rate=51.0,
                pick_rate=8.0,
                ban_rate=3.0,
                tier_grade="A",
                games=10000,
                patch="16.5.1",
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )
    await repository.replace_matchups(
        region="TR",
        rank_tier="silver",
        role="middle",
        patch="16.5.1",
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
                patch="16.5.1",
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )
    await repository.replace_synergies(
        region="TR",
        rank_tier="silver",
        role="middle",
        patch="16.5.1",
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
                patch="16.5.1",
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )

    snapshot = await repository.status_snapshot()
    assert snapshot["latest_patch"] == "16.6.1"
    assert snapshot["tier_stats_count"] == 0
    assert snapshot["historical_rows"] == 3
    assert snapshot["data_patches"] == ["16.5.1"]

    purged = await repository.purge_stale_data(patch="16.6.1")
    assert purged == {"tier_stats": 1, "matchups": 1, "synergies": 1}

    snapshot = await repository.status_snapshot()
    assert snapshot["historical_rows"] == 0
    assert snapshot["data_patches"] == []


@pytest.mark.asyncio
async def test_fail_stale_provider_runs_marks_old_running_rows(repository: DatabaseRepository) -> None:
    run_id = await repository.start_provider_run(
        provider_name="lolalytics",
        region="TR",
        rank_tier="silver",
        role="middle",
        patch="16.6.1",
        pages_total=10,
    )
    await repository.connection.execute(
        "UPDATE provider_runs SET started_at = ? WHERE id = ?",
        ("2026-03-08T00:00:00+00:00", run_id),
    )
    await repository.connection.commit()

    affected = await repository.fail_stale_provider_runs(started_before="2026-03-09T00:00:00+00:00")
    latest = await repository.latest_provider_run(
        provider_name="lolalytics",
        region="TR",
        rank_tier="silver",
        role="middle",
        patch="16.6.1",
    )

    assert affected == 1
    assert latest is not None
    assert latest["status"] == "failed"
    assert "Marked failed after stale running scrape" in latest["notes"]


@pytest.mark.asyncio
async def test_initialize_normalizes_legacy_champion_icon_urls() -> None:
    connection = await aiosqlite.connect(":memory:")
    connection.row_factory = aiosqlite.Row
    repository = DatabaseRepository(connection)
    await repository.initialize()
    await connection.execute(
        """
        INSERT INTO champions (id, key, name, image_url, roles_json, patch, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            "Ahri",
            "Ahri",
            "https://ddragon.leagueoflegends.com/cdn/16.5.1/img/champion/Ahri.png.png",
            "[]",
            "16.5.1",
            "2026-03-10T00:00:00+00:00",
        ),
    )
    await connection.commit()

    await repository.initialize()
    champion = (await repository.get_champion_lookup())[1]

    assert champion.image_url.endswith("Ahri.png")
    await connection.close()
