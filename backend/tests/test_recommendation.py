from __future__ import annotations

import asyncio
from math import tanh

import aiosqlite
import pytest
import pytest_asyncio

from app.db.repository import ChampionRecord, DatabaseRepository, MatchupRecord, SynergyRecord, TierStatRecord
from app.domain.draft import DraftState, TeamSlot
from app.domain.settings import ResolvedFilters, UserSettings
from app.services.recommendation_service import RecommendationService


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
async def test_recommendation_prefers_exact_role_matchups_and_synergies(repository: DatabaseRepository) -> None:
    patch = "16.5.1"

    await repository.upsert_champions(
        [
            ChampionRecord(champion_id=1, key="Ahri", name="Ahri", image_url="", roles=["middle"], patch=patch),
            ChampionRecord(champion_id=2, key="Garen", name="Garen", image_url="", roles=["top"], patch=patch),
            ChampionRecord(champion_id=3, key="Syndra", name="Syndra", image_url="", roles=["middle"], patch=patch),
            ChampionRecord(champion_id=4, key="Thresh", name="Thresh", image_url="", roles=["support"], patch=patch),
        ]
    )

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
                games=30000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
            TierStatRecord(
                champion_id=3,
                region="TR",
                rank_tier="silver",
                role="middle",
                win_rate=54.0,
                pick_rate=7.0,
                ban_rate=3.0,
                tier_grade="S",
                games=30000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
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
                opponent_id=2,
                region="TR",
                rank_tier="silver",
                role="middle",
                opponent_role="top",
                win_rate=55.0,
                delta1=2.0,
                delta2=15.0,
                games=1000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
            MatchupRecord(
                champion_id=3,
                opponent_id=2,
                region="TR",
                rank_tier="silver",
                role="middle",
                opponent_role="top",
                win_rate=50.0,
                delta1=0.0,
                delta2=0.0,
                games=3000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
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
                teammate_id=4,
                region="TR",
                rank_tier="silver",
                role="middle",
                teammate_role="support",
                duo_win_rate=56.0,
                synergy_delta=2.5,
                normalised_delta=10.0,
                games=1200,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
            SynergyRecord(
                champion_id=3,
                teammate_id=4,
                region="TR",
                rank_tier="silver",
                role="middle",
                teammate_role="support",
                duo_win_rate=50.0,
                synergy_delta=0.0,
                normalised_delta=0.0,
                games=2500,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )

    service = RecommendationService(repository)
    await service.rebuild_indexes()

    bundle = await service.recommend(
        draft_state=DraftState(
            local_player_cell_id=1,
            local_player_assigned_role="middle",
            my_team_picks=[
                TeamSlot(cell_id=1, champion_id=0, assigned_role="middle", is_local_player=True),
                TeamSlot(cell_id=2, champion_id=4, assigned_role="support"),
            ],
            enemy_team_picks=[TeamSlot(cell_id=6, champion_id=2, assigned_role="top")],
            my_bans=[],
            enemy_bans=[],
            session_status="active",
        ),
        filters=ResolvedFilters(region="TR", rank_tier="silver"),
        settings=UserSettings(top_n=2),
    )

    assert bundle.exact_data_available is True
    assert bundle.picks[0].champion_id == 1
    # Lane proximity reduces cross-role matchup signals (mid vs top/support = 0.65)
    assert bundle.picks[0].counter_score > 0.45
    assert bundle.picks[0].synergy_score > 0.35
    assert bundle.picks[0].evidence_score == 1.0
    assert bundle.picks[0].explanation.summary
    assert bundle.picks[0].explanation.counters[0].champion_name == "Garen"
    assert bundle.picks[0].explanation.synergies[0].champion_name == "Thresh"
    assert bundle.picks[0].explanation.scoring


@pytest.mark.asyncio
async def test_recommendation_prefers_counter_profile_over_higher_tier_pick(repository: DatabaseRepository) -> None:
    patch = "16.5.1"

    await repository.upsert_champions(
        [
            ChampionRecord(champion_id=1, key="Ahri", name="Ahri", image_url="", roles=["middle"], patch=patch),
            ChampionRecord(champion_id=2, key="Syndra", name="Syndra", image_url="", roles=["middle"], patch=patch),
            ChampionRecord(champion_id=10, key="Garen", name="Garen", image_url="", roles=["top"], patch=patch),
            ChampionRecord(champion_id=11, key="JarvanIV", name="Jarvan IV", image_url="", roles=["jungle"], patch=patch),
            ChampionRecord(champion_id=12, key="Orianna", name="Orianna", image_url="", roles=["middle"], patch=patch),
            ChampionRecord(champion_id=13, key="Jinx", name="Jinx", image_url="", roles=["bottom"], patch=patch),
            ChampionRecord(champion_id=14, key="Thresh", name="Thresh", image_url="", roles=["support"], patch=patch),
        ]
    )

    await repository.replace_tier_stats(
        region="TR",
        rank_tier="emerald",
        role="middle",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=1,
                region="TR",
                rank_tier="emerald",
                role="middle",
                win_rate=51.5,
                pick_rate=7.4,
                ban_rate=3.0,
                tier_grade="A",
                games=28000,
                patch=patch,
                source="test",
                fetched_at="2026-03-12T00:00:00+00:00",
                tier_rank=8,
                pbi=18.0,
            ),
            TierStatRecord(
                champion_id=2,
                region="TR",
                rank_tier="emerald",
                role="middle",
                win_rate=52.1,
                pick_rate=7.6,
                ban_rate=4.1,
                tier_grade="S+",
                games=30000,
                patch=patch,
                source="test",
                fetched_at="2026-03-12T00:00:00+00:00",
                tier_rank=2,
                pbi=24.0,
            ),
        ],
    )

    await repository.replace_matchups(
        region="TR",
        rank_tier="emerald",
        role="middle",
        patch=patch,
        records=[
            MatchupRecord(
                champion_id=1,
                opponent_id=10,
                region="TR",
                rank_tier="emerald",
                role="middle",
                opponent_role="top",
                win_rate=55.0,
                delta1=2.0,
                delta2=15.0,
                games=1800,
                patch=patch,
                source="test",
                fetched_at="2026-03-12T00:00:00+00:00",
            ),
            MatchupRecord(
                champion_id=1,
                opponent_id=11,
                region="TR",
                rank_tier="emerald",
                role="middle",
                opponent_role="jungle",
                win_rate=54.6,
                delta1=1.8,
                delta2=14.0,
                games=1600,
                patch=patch,
                source="test",
                fetched_at="2026-03-12T00:00:00+00:00",
            ),
            MatchupRecord(
                champion_id=1,
                opponent_id=12,
                region="TR",
                rank_tier="emerald",
                role="middle",
                opponent_role="middle",
                win_rate=54.2,
                delta1=1.7,
                delta2=13.0,
                games=1500,
                patch=patch,
                source="test",
                fetched_at="2026-03-12T00:00:00+00:00",
            ),
            MatchupRecord(
                champion_id=1,
                opponent_id=13,
                region="TR",
                rank_tier="emerald",
                role="middle",
                opponent_role="bottom",
                win_rate=54.0,
                delta1=1.5,
                delta2=12.0,
                games=1400,
                patch=patch,
                source="test",
                fetched_at="2026-03-12T00:00:00+00:00",
            ),
            MatchupRecord(
                champion_id=1,
                opponent_id=14,
                region="TR",
                rank_tier="emerald",
                role="middle",
                opponent_role="support",
                win_rate=53.8,
                delta1=1.4,
                delta2=11.0,
                games=1350,
                patch=patch,
                source="test",
                fetched_at="2026-03-12T00:00:00+00:00",
            ),
            MatchupRecord(
                champion_id=2,
                opponent_id=10,
                region="TR",
                rank_tier="emerald",
                role="middle",
                opponent_role="top",
                win_rate=50.0,
                delta1=0.0,
                delta2=0.0,
                games=2200,
                patch=patch,
                source="test",
                fetched_at="2026-03-12T00:00:00+00:00",
            ),
            MatchupRecord(
                champion_id=2,
                opponent_id=11,
                region="TR",
                rank_tier="emerald",
                role="middle",
                opponent_role="jungle",
                win_rate=50.0,
                delta1=0.0,
                delta2=0.0,
                games=2200,
                patch=patch,
                source="test",
                fetched_at="2026-03-12T00:00:00+00:00",
            ),
            MatchupRecord(
                champion_id=2,
                opponent_id=12,
                region="TR",
                rank_tier="emerald",
                role="middle",
                opponent_role="middle",
                win_rate=50.0,
                delta1=0.0,
                delta2=0.0,
                games=2200,
                patch=patch,
                source="test",
                fetched_at="2026-03-12T00:00:00+00:00",
            ),
            MatchupRecord(
                champion_id=2,
                opponent_id=13,
                region="TR",
                rank_tier="emerald",
                role="middle",
                opponent_role="bottom",
                win_rate=50.0,
                delta1=0.0,
                delta2=0.0,
                games=2200,
                patch=patch,
                source="test",
                fetched_at="2026-03-12T00:00:00+00:00",
            ),
            MatchupRecord(
                champion_id=2,
                opponent_id=14,
                region="TR",
                rank_tier="emerald",
                role="middle",
                opponent_role="support",
                win_rate=50.0,
                delta1=0.0,
                delta2=0.0,
                games=2200,
                patch=patch,
                source="test",
                fetched_at="2026-03-12T00:00:00+00:00",
            ),
        ],
    )

    service = RecommendationService(repository)
    await service.rebuild_indexes()

    bundle = await service.recommend(
        draft_state=DraftState(
            local_player_cell_id=1,
            local_player_assigned_role="middle",
            my_team_picks=[TeamSlot(cell_id=1, champion_id=0, assigned_role="middle", is_local_player=True)],
            enemy_team_picks=[
                TeamSlot(cell_id=6, champion_id=10, assigned_role="top"),
                TeamSlot(cell_id=7, champion_id=11, assigned_role="jungle"),
                TeamSlot(cell_id=8, champion_id=12, assigned_role="middle"),
                TeamSlot(cell_id=9, champion_id=13, assigned_role="bottom"),
                TeamSlot(cell_id=10, champion_id=14, assigned_role="support"),
            ],
            my_bans=[],
            enemy_bans=[],
            session_status="active",
        ),
        filters=ResolvedFilters(region="TR", rank_tier="emerald", role="middle"),
        settings=UserSettings(top_n=2),
    )

    assert bundle.picks[0].champion_id == 1
    assert bundle.picks[0].champion_name == "Ahri"
    assert bundle.picks[0].counter_score > bundle.picks[1].counter_score
    assert bundle.picks[0].total_score > bundle.picks[1].total_score


@pytest.mark.asyncio
async def test_recommendation_does_not_fallback_to_nearby_rank(repository: DatabaseRepository) -> None:
    patch = "16.5.1"

    await repository.upsert_champions(
        [
            ChampionRecord(champion_id=1, key="Ahri", name="Ahri", image_url="", roles=["middle"], patch=patch),
            ChampionRecord(champion_id=2, key="Syndra", name="Syndra", image_url="", roles=["middle"], patch=patch),
        ]
    )

    await repository.replace_tier_stats(
        region="TR",
        rank_tier="emerald_plus",
        role="middle",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=1,
                region="TR",
                rank_tier="emerald_plus",
                role="middle",
                win_rate=53.0,
                pick_rate=7.0,
                ban_rate=4.0,
                tier_grade="S",
                games=25000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
            TierStatRecord(
                champion_id=2,
                region="TR",
                rank_tier="emerald_plus",
                role="middle",
                win_rate=51.0,
                pick_rate=6.0,
                ban_rate=3.0,
                tier_grade="A",
                games=25000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )

    service = RecommendationService(repository)
    await service.rebuild_indexes()

    bundle = await service.recommend(
        draft_state=DraftState(
            local_player_cell_id=1,
            local_player_assigned_role="middle",
            my_team_picks=[TeamSlot(cell_id=1, champion_id=0, assigned_role="middle", is_local_player=True)],
            enemy_team_picks=[],
            my_bans=[],
            enemy_bans=[],
            session_status="active",
        ),
        filters=ResolvedFilters(region="TR", rank_tier="emerald"),
        settings=UserSettings(top_n=2),
    )

    assert bundle.picks == []
    assert bundle.exact_data_available is False
    assert bundle.warnings


@pytest.mark.asyncio
async def test_recommendation_supports_explicit_aggregate_rank_filters(repository: DatabaseRepository) -> None:
    patch = "16.5.1"

    await repository.upsert_champions(
        [
            ChampionRecord(champion_id=1, key="Ahri", name="Ahri", image_url="", roles=["middle"], patch=patch),
            ChampionRecord(champion_id=2, key="Syndra", name="Syndra", image_url="", roles=["middle"], patch=patch),
        ]
    )

    await repository.replace_tier_stats(
        region="TR",
        rank_tier="emerald_plus",
        role="middle",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=1,
                region="TR",
                rank_tier="emerald_plus",
                role="middle",
                win_rate=53.0,
                pick_rate=7.0,
                ban_rate=4.0,
                tier_grade="S",
                games=25000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
            TierStatRecord(
                champion_id=2,
                region="TR",
                rank_tier="emerald_plus",
                role="middle",
                win_rate=51.0,
                pick_rate=6.0,
                ban_rate=3.0,
                tier_grade="A",
                games=25000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )

    service = RecommendationService(repository)
    await service.rebuild_indexes()

    bundle = await service.recommend(
        draft_state=DraftState(
            local_player_cell_id=1,
            local_player_assigned_role="middle",
            my_team_picks=[TeamSlot(cell_id=1, champion_id=0, assigned_role="middle", is_local_player=True)],
            enemy_team_picks=[],
            my_bans=[],
            enemy_bans=[],
            session_status="active",
        ),
        filters=ResolvedFilters(region="TR", rank_tier="emerald_plus"),
        settings=UserSettings(top_n=2),
    )

    assert [item.champion_id for item in bundle.picks] == [1, 2]
    assert bundle.exact_data_available is True


@pytest.mark.asyncio
async def test_recommendation_prefers_candidates_with_exact_relation_coverage(repository: DatabaseRepository) -> None:
    patch = "16.5.1"

    await repository.upsert_champions(
        [
            ChampionRecord(champion_id=2, key="Garen", name="Garen", image_url="", roles=["top"], patch=patch),
            ChampionRecord(champion_id=3, key="Thresh", name="Thresh", image_url="", roles=["support"], patch=patch),
            ChampionRecord(champion_id=10, key="Ahri", name="Ahri", image_url="", roles=["middle"], patch=patch),
            ChampionRecord(champion_id=11, key="Lux", name="Lux", image_url="", roles=["middle"], patch=patch),
        ]
    )

    await repository.replace_tier_stats(
        region="TR",
        rank_tier="silver",
        role="middle",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=10,
                region="TR",
                rank_tier="silver",
                role="middle",
                win_rate=52.0,
                pick_rate=7.0,
                ban_rate=3.0,
                tier_grade="A",
                games=20000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
            TierStatRecord(
                champion_id=11,
                region="TR",
                rank_tier="silver",
                role="middle",
                win_rate=55.0,
                pick_rate=7.0,
                ban_rate=3.0,
                tier_grade="S",
                games=20000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )

    await repository.replace_matchups(
        region="TR",
        rank_tier="silver",
        role="middle",
        patch=patch,
        records=[
            MatchupRecord(
                champion_id=10,
                opponent_id=2,
                region="TR",
                rank_tier="silver",
                role="middle",
                opponent_role="top",
                win_rate=56.0,
                delta1=2.0,
                delta2=15.0,
                games=1500,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )

    await repository.replace_synergies(
        region="TR",
        rank_tier="silver",
        role="middle",
        patch=patch,
        records=[
            SynergyRecord(
                champion_id=10,
                teammate_id=3,
                region="TR",
                rank_tier="silver",
                role="middle",
                teammate_role="support",
                duo_win_rate=55.0,
                synergy_delta=2.5,
                normalised_delta=10.0,
                games=1400,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )

    service = RecommendationService(repository)
    await service.rebuild_indexes()

    bundle = await service.recommend(
        draft_state=DraftState(
            local_player_cell_id=1,
            local_player_assigned_role="middle",
            my_team_picks=[
                TeamSlot(cell_id=1, champion_id=0, assigned_role="middle", is_local_player=True),
                TeamSlot(cell_id=2, champion_id=3, assigned_role="support"),
            ],
            enemy_team_picks=[TeamSlot(cell_id=6, champion_id=2, assigned_role="top")],
            my_bans=[],
            enemy_bans=[],
            session_status="active",
        ),
        filters=ResolvedFilters(region="TR", rank_tier="silver"),
        settings=UserSettings(top_n=2),
    )

    assert bundle.picks[0].champion_id == 10
    assert bundle.picks[0].evidence_score == 1.0
    assert bundle.picks[1].evidence_score < bundle.picks[0].evidence_score


@pytest.mark.asyncio
async def test_recommendation_infers_missing_visible_roles(repository: DatabaseRepository) -> None:
    patch = "16.5.1"

    await repository.upsert_champions(
        [
            ChampionRecord(champion_id=1, key="Ahri", name="Ahri", image_url="", roles=["middle"], patch=patch),
            ChampionRecord(champion_id=2, key="Garen", name="Garen", image_url="", roles=["top"], patch=patch),
            ChampionRecord(champion_id=3, key="Thresh", name="Thresh", image_url="", roles=["support"], patch=patch),
            ChampionRecord(champion_id=4, key="Syndra", name="Syndra", image_url="", roles=["middle"], patch=patch),
        ]
    )

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
                win_rate=53.0,
                pick_rate=8.0,
                ban_rate=4.0,
                tier_grade="S",
                games=30000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
            TierStatRecord(
                champion_id=4,
                region="TR",
                rank_tier="silver",
                role="middle",
                win_rate=51.0,
                pick_rate=7.0,
                ban_rate=3.0,
                tier_grade="A",
                games=30000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )
    await repository.replace_tier_stats(
        region="TR",
        rank_tier="silver",
        role="top",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=2,
                region="TR",
                rank_tier="silver",
                role="top",
                win_rate=50.0,
                pick_rate=10.0,
                ban_rate=2.0,
                tier_grade="B",
                games=30000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )
    await repository.replace_tier_stats(
        region="TR",
        rank_tier="silver",
        role="support",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=3,
                region="TR",
                rank_tier="silver",
                role="support",
                win_rate=51.0,
                pick_rate=9.0,
                ban_rate=2.0,
                tier_grade="A",
                games=30000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
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
                opponent_id=2,
                region="TR",
                rank_tier="silver",
                role="middle",
                opponent_role="top",
                win_rate=55.0,
                delta1=2.0,
                delta2=15.0,
                games=1000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
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
                teammate_id=3,
                region="TR",
                rank_tier="silver",
                role="middle",
                teammate_role="support",
                duo_win_rate=56.0,
                synergy_delta=2.5,
                normalised_delta=10.0,
                games=1200,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )

    service = RecommendationService(repository)
    await service.rebuild_indexes()

    bundle = await service.recommend(
        draft_state=DraftState(
            local_player_cell_id=1,
            local_player_assigned_role="middle",
            my_team_picks=[
                TeamSlot(cell_id=1, champion_id=0, assigned_role="middle", is_local_player=True),
                TeamSlot(cell_id=2, champion_id=3, assigned_role=None),
            ],
            enemy_team_picks=[TeamSlot(cell_id=6, champion_id=2, assigned_role=None)],
            my_bans=[],
            enemy_bans=[],
            session_status="active",
        ),
        filters=ResolvedFilters(region="TR", rank_tier="silver", role="middle"),
        settings=UserSettings(top_n=2),
    )

    assert bundle.picks[0].champion_id == 1
    # Lane proximity reduces cross-role matchup signals (mid vs top/support = 0.65)
    assert bundle.picks[0].counter_score > 0.45
    assert bundle.picks[0].synergy_score > 0.35
    assert any("Inferred 2 visible draft role" in warning for warning in bundle.warnings)
    assert bundle.picks[0].explanation.counters[0].role == "top"
    assert bundle.picks[0].explanation.synergies[0].role == "support"


@pytest.mark.asyncio
async def test_recommendation_uses_explicit_role_override_when_local_role_is_missing(repository: DatabaseRepository) -> None:
    patch = "16.5.1"

    await repository.upsert_champions(
        [
            ChampionRecord(champion_id=1, key="Garen", name="Garen", image_url="", roles=["top"], patch=patch),
            ChampionRecord(champion_id=2, key="Ahri", name="Ahri", image_url="", roles=["middle"], patch=patch),
        ]
    )

    await repository.replace_tier_stats(
        region="TR",
        rank_tier="silver",
        role="top",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=1,
                region="TR",
                rank_tier="silver",
                role="top",
                win_rate=52.0,
                pick_rate=8.0,
                ban_rate=4.0,
                tier_grade="S",
                games=30000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )
    await repository.replace_tier_stats(
        region="TR",
        rank_tier="silver",
        role="middle",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=2,
                region="TR",
                rank_tier="silver",
                role="middle",
                win_rate=51.0,
                pick_rate=8.0,
                ban_rate=4.0,
                tier_grade="A",
                games=30000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )

    service = RecommendationService(repository)
    await service.rebuild_indexes()

    bundle = await service.recommend(
        draft_state=DraftState(
            local_player_cell_id=1,
            local_player_assigned_role=None,
            my_team_picks=[TeamSlot(cell_id=1, champion_id=0, assigned_role=None, is_local_player=True)],
            enemy_team_picks=[],
            my_bans=[],
            enemy_bans=[],
            session_status="active",
        ),
        filters=ResolvedFilters(region="TR", rank_tier="silver", role="top"),
        settings=UserSettings(top_n=2, role_mode="manual", role_override="top"),
    )

    assert bundle.exact_data_available is True
    assert bundle.picks[0].champion_id == 1
    assert bundle.picks[0].suggested_role == "top"


@pytest.mark.asyncio
async def test_recommendation_warns_on_client_patch_mismatch(repository: DatabaseRepository) -> None:
    patch = "16.5.1"

    await repository.upsert_champions(
        [
            ChampionRecord(champion_id=1, key="Ahri", name="Ahri", image_url="", roles=["middle"], patch=patch),
        ]
    )

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
                games=30000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )

    service = RecommendationService(repository)
    await service.rebuild_indexes()

    bundle = await service.recommend(
        draft_state=DraftState(
            local_player_cell_id=1,
            local_player_assigned_role="middle",
            my_team_picks=[TeamSlot(cell_id=1, champion_id=0, assigned_role="middle", is_local_player=True)],
            enemy_team_picks=[],
            my_bans=[],
            enemy_bans=[],
            session_status="active",
            patch="16.6.3",
        ),
        filters=ResolvedFilters(region="TR", rank_tier="silver"),
        settings=UserSettings(top_n=2),
    )

    assert any("Client patch 16.6.3" in warning for warning in bundle.warnings)


@pytest.mark.asyncio
async def test_recommendation_applies_low_sample_relation_guard(repository: DatabaseRepository) -> None:
    patch = "16.5.1"

    await repository.upsert_champions(
        [
            ChampionRecord(champion_id=1, key="Ahri", name="Ahri", image_url="", roles=["middle"], patch=patch),
            ChampionRecord(champion_id=2, key="Garen", name="Garen", image_url="", roles=["top"], patch=patch),
        ]
    )

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
                games=30000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
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
                opponent_id=2,
                region="TR",
                rank_tier="silver",
                role="middle",
                opponent_role="top",
                win_rate=56.0,
                delta1=2.0,
                delta2=15.0,
                games=50,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )

    service = RecommendationService(repository)
    await service.rebuild_indexes()

    bundle = await service.recommend(
        draft_state=DraftState(
            local_player_cell_id=1,
            local_player_assigned_role="middle",
            my_team_picks=[TeamSlot(cell_id=1, champion_id=0, assigned_role="middle", is_local_player=True)],
            enemy_team_picks=[TeamSlot(cell_id=6, champion_id=2, assigned_role="top")],
            my_bans=[],
            enemy_bans=[],
            session_status="active",
        ),
        filters=ResolvedFilters(region="TR", rank_tier="silver", role="middle"),
        settings=UserSettings(top_n=2),
    )

    item = bundle.picks[0]
    # New formula: Bayesian shrinkage applied inside normalize_delta, RELATION_SHRINKAGE_PRIOR_GAMES=100,
    # and lane proximity (mid vs top = 0.65)
    # counter_score = tanh(15 * (50/250) / 7) * (50/150) * 0.65
    assert item.counter_score == pytest.approx(tanh(15 * (50 / 250) / 7) * (50 / 150) * 0.65, abs=0.02)
    assert item.sample_confidence == pytest.approx(50 / 150, abs=0.01)
    assert item.explanation.counters[0].sample_confidence == pytest.approx(50 / 150, abs=0.01)
    assert item.explanation.counters[0].shrinkage_weight == pytest.approx(50 / 150, abs=0.01)
    assert any("Reduced Garen (top)" in penalty for penalty in item.explanation.penalties)


@pytest.mark.asyncio
async def test_recommendation_prefers_manual_role_override_over_inference(repository: DatabaseRepository) -> None:
    patch = "16.5.1"

    await repository.upsert_champions(
        [
            ChampionRecord(champion_id=1, key="Ahri", name="Ahri", image_url="", roles=["middle"], patch=patch),
            ChampionRecord(champion_id=2, key="Poppy", name="Poppy", image_url="", roles=["top", "support"], patch=patch),
        ]
    )

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
                games=30000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )
    await repository.replace_tier_stats(
        region="TR",
        rank_tier="silver",
        role="top",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=2,
                region="TR",
                rank_tier="silver",
                role="top",
                win_rate=50.0,
                pick_rate=5.0,
                ban_rate=2.0,
                tier_grade="B",
                games=25000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )
    await repository.replace_tier_stats(
        region="TR",
        rank_tier="silver",
        role="support",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=2,
                region="TR",
                rank_tier="silver",
                role="support",
                win_rate=51.0,
                pick_rate=4.0,
                ban_rate=2.0,
                tier_grade="A",
                games=25000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
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
                opponent_id=2,
                region="TR",
                rank_tier="silver",
                role="middle",
                opponent_role="support",
                win_rate=56.0,
                delta1=2.0,
                delta2=15.0,
                games=1200,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )

    service = RecommendationService(repository)
    await service.rebuild_indexes()

    snapshot = await service.analyze(
        draft_state=DraftState(
            local_player_cell_id=1,
            local_player_assigned_role="middle",
            my_team_picks=[TeamSlot(cell_id=1, champion_id=0, assigned_role="middle", is_local_player=True)],
            enemy_team_picks=[TeamSlot(cell_id=6, champion_id=2, assigned_role=None)],
            my_bans=[],
            enemy_bans=[],
            session_status="active",
        ),
        filters=ResolvedFilters(region="TR", rank_tier="silver", role="middle"),
        settings=UserSettings(top_n=2),
        draft_role_overrides={("enemy", 6): "support"},
    )

    enemy_slot = snapshot.draft_state.enemy_team_picks[0]
    assert enemy_slot.effective_role == "support"
    assert enemy_slot.role_source == "manual"
    # Lane proximity reduces cross-role signal (mid vs support = 0.65)
    assert snapshot.recommendations.picks[0].counter_score > 0.45
    assert snapshot.recommendations.picks[0].explanation.counters[0].match_role_source == "manual"


@pytest.mark.asyncio
async def test_recommendation_uses_negative_language_for_negative_delta(repository: DatabaseRepository) -> None:
    patch = "16.5.1"

    await repository.upsert_champions(
        [
            ChampionRecord(champion_id=1, key="Ahri", name="Ahri", image_url="", roles=["middle"], patch=patch),
            ChampionRecord(champion_id=2, key="Fizz", name="Fizz", image_url="", roles=["middle"], patch=patch),
        ]
    )

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
                games=30000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
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
                opponent_id=2,
                region="TR",
                rank_tier="silver",
                role="middle",
                opponent_role="middle",
                win_rate=45.0,
                delta1=-3.0,
                delta2=-12.0,
                games=1200,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )

    service = RecommendationService(repository)
    await service.rebuild_indexes()

    bundle = await service.recommend(
        draft_state=DraftState(
            local_player_cell_id=1,
            local_player_assigned_role="middle",
            my_team_picks=[TeamSlot(cell_id=1, champion_id=0, assigned_role="middle", is_local_player=True)],
            enemy_team_picks=[TeamSlot(cell_id=6, champion_id=2, assigned_role="middle")],
            my_bans=[],
            enemy_bans=[],
            session_status="active",
        ),
        filters=ResolvedFilters(region="TR", rank_tier="silver", role="middle"),
        settings=UserSettings(top_n=2),
    )

    detail = bundle.picks[0].explanation.counters[0]
    assert bundle.picks[0].counter_score < 0
    assert detail.metric_value < 0
    assert "Struggles into" in detail.summary


@pytest.mark.asyncio
async def test_recommendation_warns_when_role_inference_is_ambiguous(repository: DatabaseRepository) -> None:
    patch = "16.5.1"

    await repository.upsert_champions(
        [
            ChampionRecord(champion_id=1, key="Ahri", name="Ahri", image_url="", roles=["middle"], patch=patch),
            ChampionRecord(champion_id=2, key="Sejuani", name="Sejuani", image_url="", roles=["top", "jungle"], patch=patch),
        ]
    )

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
                games=30000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )
    await repository.replace_tier_stats(
        region="TR",
        rank_tier="silver",
        role="top",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=2,
                region="TR",
                rank_tier="silver",
                role="top",
                win_rate=50.0,
                pick_rate=5.0,
                ban_rate=2.0,
                tier_grade="B",
                games=25000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )
    await repository.replace_tier_stats(
        region="TR",
        rank_tier="silver",
        role="jungle",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=2,
                region="TR",
                rank_tier="silver",
                role="jungle",
                win_rate=50.5,
                pick_rate=5.2,
                ban_rate=2.1,
                tier_grade="B+",
                games=25000,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
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
                opponent_id=2,
                region="TR",
                rank_tier="silver",
                role="middle",
                opponent_role="top",
                win_rate=55.0,
                delta1=2.0,
                delta2=15.0,
                games=1200,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
            MatchupRecord(
                champion_id=1,
                opponent_id=2,
                region="TR",
                rank_tier="silver",
                role="middle",
                opponent_role="jungle",
                win_rate=53.0,
                delta1=1.5,
                delta2=9.0,
                games=1200,
                patch=patch,
                source="test",
                fetched_at="2026-03-09T00:00:00+00:00",
            ),
        ],
    )

    service = RecommendationService(repository)
    await service.rebuild_indexes()

    snapshot = await service.analyze(
        draft_state=DraftState(
            local_player_cell_id=1,
            local_player_assigned_role="middle",
            my_team_picks=[TeamSlot(cell_id=1, champion_id=0, assigned_role="middle", is_local_player=True)],
            enemy_team_picks=[TeamSlot(cell_id=6, champion_id=2, assigned_role=None)],
            my_bans=[],
            enemy_bans=[],
            session_status="active",
        ),
        filters=ResolvedFilters(region="TR", rank_tier="silver", role="middle"),
        settings=UserSettings(top_n=2),
    )

    enemy_slot = snapshot.draft_state.enemy_team_picks[0]
    assert enemy_slot.role_source == "inferred"
    assert len(enemy_slot.role_candidates) >= 2
    assert any("ambiguous" in warning.lower() for warning in snapshot.recommendations.warnings)
    assert snapshot.recommendations.picks[0].counter_score > 0.0
    assert snapshot.recommendations.picks[0].counter_score < 1.0


@pytest.mark.asyncio
async def test_recommendation_uses_tier_rank_and_pbi_for_predraft_ordering(repository: DatabaseRepository) -> None:
    patch = "16.5.1"

    await repository.upsert_champions(
        [
            ChampionRecord(champion_id=11, key="XinZhao", name="Xin Zhao", image_url="", roles=["jungle"], patch=patch),
            ChampionRecord(champion_id=12, key="Kayn", name="Kayn", image_url="", roles=["jungle"], patch=patch),
            ChampionRecord(champion_id=13, key="Jax", name="Jax", image_url="", roles=["jungle"], patch=patch),
        ]
    )

    await repository.replace_tier_stats(
        region="TR",
        rank_tier="silver",
        role="jungle",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=11,
                region="TR",
                rank_tier="silver",
                role="jungle",
                tier_rank=1,
                win_rate=51.2,
                pick_rate=2.0,
                ban_rate=0.4,
                tier_grade="S",
                pbi=4.0,
                games=1200,
                patch=patch,
                source="test",
                fetched_at="2026-03-11T00:00:00+00:00",
            ),
            TierStatRecord(
                champion_id=12,
                region="TR",
                rank_tier="silver",
                role="jungle",
                tier_rank=15,
                win_rate=51.7,
                pick_rate=17.0,
                ban_rate=12.0,
                tier_grade="A",
                pbi=45.0,
                games=9000,
                patch=patch,
                source="test",
                fetched_at="2026-03-11T00:00:00+00:00",
            ),
            TierStatRecord(
                champion_id=13,
                region="TR",
                rank_tier="silver",
                role="jungle",
                tier_rank=7,
                win_rate=51.6,
                pick_rate=6.0,
                ban_rate=8.0,
                tier_grade="S-",
                pbi=16.0,
                games=3400,
                patch=patch,
                source="test",
                fetched_at="2026-03-11T00:00:00+00:00",
            ),
        ],
    )

    service = RecommendationService(repository)
    await service.rebuild_indexes()

    bundle = await service.recommend(
        draft_state=DraftState(
            local_player_cell_id=1,
            local_player_assigned_role="jungle",
            my_team_picks=[TeamSlot(cell_id=1, champion_id=0, assigned_role="jungle", is_local_player=True)],
            enemy_team_picks=[],
            my_bans=[],
            enemy_bans=[],
            session_status="active",
        ),
        filters=ResolvedFilters(region="TR", rank_tier="silver", role="jungle"),
        settings=UserSettings(top_n=3),
    )

    # PBI normalization /30 (was /50) makes Kayn (pbi=45 -> 1.0) outscore XinZhao (pbi=4 -> 0.13)
    # despite XinZhao's higher tier rank, so order is Kayn > XinZhao > Jax
    assert [item.champion_id for item in bundle.picks] == [12, 11, 13]
    assert bundle.picks[0].explanation.scoring[0].key == "tier_rank"


@pytest.mark.asyncio
async def test_recommendation_warns_when_selected_role_overlaps_teammate_assignment(
    repository: DatabaseRepository,
) -> None:
    patch = "16.5.1"

    await repository.upsert_champions(
        [
            ChampionRecord(champion_id=1, key="Thresh", name="Thresh", image_url="", roles=["support"], patch=patch),
            ChampionRecord(champion_id=2, key="Poppy", name="Poppy", image_url="", roles=["top", "support"], patch=patch),
            ChampionRecord(champion_id=3, key="Leona", name="Leona", image_url="", roles=["support"], patch=patch),
        ]
    )

    await repository.replace_tier_stats(
        region="TR",
        rank_tier="silver",
        role="support",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=1,
                region="TR",
                rank_tier="silver",
                role="support",
                win_rate=51.0,
                pick_rate=6.0,
                ban_rate=3.0,
                tier_grade="A",
                games=20000,
                patch=patch,
                source="test",
                fetched_at="2026-03-11T00:00:00+00:00",
            ),
            TierStatRecord(
                champion_id=3,
                region="TR",
                rank_tier="silver",
                role="support",
                win_rate=52.0,
                pick_rate=7.0,
                ban_rate=4.0,
                tier_grade="S",
                games=22000,
                patch=patch,
                source="test",
                fetched_at="2026-03-11T00:00:00+00:00",
            ),
        ],
    )
    await repository.replace_tier_stats(
        region="TR",
        rank_tier="silver",
        role="top",
        patch=patch,
        records=[
            TierStatRecord(
                champion_id=2,
                region="TR",
                rank_tier="silver",
                role="top",
                win_rate=50.0,
                pick_rate=5.0,
                ban_rate=2.0,
                tier_grade="B",
                games=18000,
                patch=patch,
                source="test",
                fetched_at="2026-03-11T00:00:00+00:00",
            ),
        ],
    )

    service = RecommendationService(repository)
    await service.rebuild_indexes()

    snapshot = await service.analyze(
        draft_state=DraftState(
            local_player_cell_id=1,
            local_player_assigned_role="middle",
            my_team_picks=[
                TeamSlot(cell_id=1, champion_id=0, assigned_role="middle", is_local_player=True),
                TeamSlot(cell_id=2, champion_id=2, assigned_role="support"),
            ],
            enemy_team_picks=[],
            my_bans=[],
            enemy_bans=[],
            session_status="active",
        ),
        filters=ResolvedFilters(region="TR", rank_tier="silver", role="support"),
        settings=UserSettings(role_mode="manual", role_override="support", top_n=2),
    )

    assert any("overlaps with Poppy's assigned position" in warning for warning in snapshot.recommendations.warnings)


@pytest.mark.asyncio
async def test_recommendation_returns_warming_bundle_while_indexes_build(repository: DatabaseRepository) -> None:
    patch = "16.5.1"
    await repository.upsert_champions(
        [
            ChampionRecord(champion_id=11, key="XinZhao", name="Xin Zhao", image_url="xin.png", roles=["jungle"], patch=patch),
        ]
    )
    service = RecommendationService(repository)
    release = asyncio.Event()

    async def fake_rebuild() -> None:
        await release.wait()
        service.patch = patch

    service._rebuild_task = asyncio.create_task(fake_rebuild())

    try:
        snapshot = await service.analyze(
            draft_state=DraftState(
                local_player_cell_id=1,
                local_player_assigned_role="middle",
                my_team_picks=[
                    TeamSlot(cell_id=1, champion_id=0, assigned_role="middle", is_local_player=True),
                    TeamSlot(cell_id=2, champion_id=11, assigned_role="jungle"),
                ],
                enemy_team_picks=[],
                my_bans=[],
                enemy_bans=[],
                session_status="active",
            ),
            filters=ResolvedFilters(region="TR", rank_tier="silver", role="middle"),
            settings=UserSettings(top_n=2),
        )
    finally:
        release.set()
        await service._rebuild_task

    bundle = snapshot.recommendations
    assert bundle.picks == []
    assert bundle.bans == []
    assert bundle.scope_ready is False
    assert bundle.scope_freshness == "warming"
    assert any("warming up" in warning.lower() for warning in bundle.warnings)
    assert snapshot.draft_state.my_team_picks[1].champion_name == "Xin Zhao"
    assert snapshot.draft_state.my_team_picks[1].champion_image_url == "xin.png"
