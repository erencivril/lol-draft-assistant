from __future__ import annotations

import pytest

from app.config import Settings
from app.db.repository import ChampionRecord
from app.domain.ranks import normalize_rank_tier, rank_display_name
from app.providers.lolalytics_provider import LolalyticsHttpSession, LolalyticsProvider, _compute_tier_grade


def build_provider() -> LolalyticsProvider:
    champion_lookup = {
        1: ChampionRecord(champion_id=1, key="Ahri", name="Ahri", image_url="", roles=["middle"], patch="16.5.1"),
        2: ChampionRecord(champion_id=2, key="Garen", name="Garen", image_url="", roles=["top"], patch="16.5.1"),
        3: ChampionRecord(champion_id=3, key="Thresh", name="Thresh", image_url="", roles=["support"], patch="16.5.1"),
        4: ChampionRecord(champion_id=4, key="Rakan", name="Rakan", image_url="", roles=["support"], patch="16.5.1"),
    }
    return LolalyticsProvider(Settings(), champion_lookup)


def test_build_matchup_records_keeps_best_record_per_role() -> None:
    provider = build_provider()
    champion = provider.champion_lookup[1]

    records = provider._build_matchup_records(
        champion=champion,
        region="TR",
        rank_tier="silver",
        role="middle",
        patch="16.5.1",
        fetched_at="2026-03-09T00:00:00+00:00",
        items=[
            {
                "row_role": "top",
                "href": "/lol/ahri/vs/garen/build/?lane=middle&vslane=top",
                "label": "Garen",
                "metrics": ["53.1%", "+1.4", "+7.5", "+0.8", "1,250"],
            },
            {
                "row_role": "top",
                "href": "/lol/ahri/vs/garen/build/?lane=middle&vslane=top",
                "label": "Garen",
                "metrics": ["54.0%", "+1.8", "+8.2", "+0.9", "2,500"],
            },
            {
                "row_role": "middle",
                "href": "/lol/ahri/vs/garen/build/?lane=middle&vslane=middle",
                "label": "Garen",
                "metrics": ["46.8%", "-1.2", "-5.0", "-0.6", "900"],
            },
        ],
    )

    assert len(records) == 2

    top_record = next(record for record in records if record.opponent_role == "top")
    middle_record = next(record for record in records if record.opponent_role == "middle")

    assert top_record.opponent_id == 2
    assert top_record.games == 2500
    assert top_record.delta2 == 8.2
    assert middle_record.games == 900


def test_build_synergy_records_keeps_normalised_delta() -> None:
    provider = build_provider()
    champion = provider.champion_lookup[1]

    records = provider._build_synergy_records(
        champion=champion,
        region="TR",
        rank_tier="silver",
        role="middle",
        patch="16.5.1",
        fetched_at="2026-03-09T00:00:00+00:00",
        items=[
            {
                "row_role": "support",
                "href": "/lol/ahri/build/?lane=middle&duo=rakan",
                "label": "Rakan",
                "metrics": ["55.4%", "+2.5", "+9.0", "+1.1", "1,400"],
            },
            {
                "row_role": "support",
                "href": "/lol/ahri/build/?lane=middle&duo=rakan",
                "label": "Rakan",
                "metrics": ["54.0%", "+2.0", "+7.0", "+0.8", "900"],
            },
        ],
    )

    assert len(records) == 1
    assert records[0].teammate_id == 4
    assert records[0].teammate_role == "support"
    assert records[0].synergy_delta == 2.5
    assert records[0].normalised_delta == 9.0
    assert records[0].games == 1400


def test_lolalytics_patch_trims_micro_version() -> None:
    provider = build_provider()

    assert provider._lolalytics_patch("16.5.1") == "16.5"
    assert provider._lolalytics_patch("16.5") == "16.5"


def test_http_session_parses_team_payload_into_synergy_items() -> None:
    session = LolalyticsHttpSession(Settings())
    rows = session._parse_team_payload(
        {
            "team_h": ["id", "wr", "d1", "d2", "pr", "n"],
            "team": {
                "support": [[4, 55.4, 2.5, 9.0, 1.1, 1400]],
                "middle": [[1, 52.1, 0.7, 1.3, 0.2, 200]],
            },
        }
    )

    assert rows == [
        {
            "row_role": "support",
            "champion_id": 4,
            "label": "",
            "href": "",
            "metrics": ["55.4", "2.5", "9.0", "1.1", "1400"],
        },
        {
            "row_role": "middle",
            "champion_id": 1,
            "label": "",
            "href": "",
            "metrics": ["52.1", "0.7", "1.3", "0.2", "200"],
        },
    ]


def test_normalize_rank_tier_maps_legacy_master_plus_alias() -> None:
    assert normalize_rank_tier("master_plus") == "grandmaster_plus"
    assert normalize_rank_tier("Master+") == "grandmaster_plus"
    assert rank_display_name("grandmaster_plus") == "Grandmaster+"


def test_build_records_accept_direct_champion_ids() -> None:
    provider = build_provider()
    champion = provider.champion_lookup[1]

    matchup_records = provider._build_matchup_records(
        champion=champion,
        region="TR",
        rank_tier="emerald",
        role="middle",
        patch="16.5.1",
        fetched_at="2026-03-10T00:00:00+00:00",
        items=[
            {
                "row_role": "top",
                "champion_id": 2,
                "metrics": ["53.1", "1.4", "7.5", "0.8", "1250"],
            }
        ],
    )
    synergy_records = provider._build_synergy_records(
        champion=champion,
        region="TR",
        rank_tier="emerald",
        role="middle",
        patch="16.5.1",
        fetched_at="2026-03-10T00:00:00+00:00",
        items=[
            {
                "row_role": "support",
                "champion_id": 4,
                "metrics": ["55.4", "2.5", "9.0", "1.1", "1400"],
            }
        ],
    )

    assert matchup_records[0].opponent_id == 2
    assert matchup_records[0].games == 1250
    assert synergy_records[0].teammate_id == 4
    assert synergy_records[0].games == 1400


def test_parse_counter_items_maps_json_api_response() -> None:
    provider = build_provider()
    items = provider._parse_counter_items(
        {
            "stats": {"cid": 1, "lane": "middle"},
            "counters": [
                {"cid": 2, "vsWr": 56.5, "n": 1250, "d1": 3.16, "d2": 1.92, "allWr": 53.3, "defaultLane": "top"},
                {"cid": 3, "vsWr": 48.1, "n": 800, "d1": -1.4, "d2": -5.0, "allWr": 49.5, "defaultLane": "support"},
            ],
        }
    )

    assert len(items) == 2
    assert items[0]["row_role"] == "top"
    assert items[0]["champion_id"] == 2
    assert items[0]["metrics"] == ["56.5", "3.16", "1.92", "0", "1250"]
    assert items[1]["row_role"] == "support"
    assert items[1]["champion_id"] == 3


def test_empty_counter_json_yields_empty_list() -> None:
    provider = build_provider()
    items = provider._parse_counter_items({"stats": {}, "counters": []})
    assert items == []

    items2 = provider._parse_counter_items({"stats": {}})
    assert items2 == []


def test_tier_grade_derivation() -> None:
    assert _compute_tier_grade(1, 70) == "S+"
    assert _compute_tier_grade(3, 70) == "S"
    assert _compute_tier_grade(8, 70) == "A"
    assert _compute_tier_grade(20, 70) == "B+"
    assert _compute_tier_grade(40, 70) == "B"
    assert _compute_tier_grade(55, 70) == "C"
    assert _compute_tier_grade(60, 70) == "D"
    assert _compute_tier_grade(1, 0) == "B"
