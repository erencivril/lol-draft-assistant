from __future__ import annotations

import pytest

from app.config import Settings
from app.db.repository import ChampionRecord
from app.domain.ranks import normalize_rank_tier, rank_display_name
from app.providers.lolalytics_provider import LolalyticsHttpSession, LolalyticsProvider, TierPageResult


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


def test_http_session_parses_build_counter_rows_from_qwik_state() -> None:
    session = LolalyticsHttpSession(Settings())
    rows = session._parse_build_counter_rows(
        """
        <html>
          <body>
            <script type="qwik/json">
              {
                "refs": {},
                "ctx": {},
                "objs": [
                  {"data": "3", "lane": "4"},
                  null,
                  null,
                  [[2, 53.1, 1.4, 7.5, 0.8, 1250]],
                  "top"
                ],
                "subs": []
              }
            </script>
          </body>
        </html>
        """
    )

    assert rows == [
        {
            "row_role": "top",
            "champion_id": 2,
            "label": "",
            "href": "",
            "metrics": ["53.1", "1.4", "7.5", "0.8", "1250"],
        }
    ]


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


def test_http_session_parses_tier_rows_from_ssr_html() -> None:
    session = LolalyticsHttpSession(Settings())
    rows = session._parse_tier_rows(
        """
        <div class="flex h-[52px] justify-between text-[13px] text-[#cccccc]">
          <div>1</div>
          <div><a href="/lol/ahri/build/?tier=emerald&amp;region=tr"><img alt="Ahri" /></a></div>
          <div><a href="/lol/ahri/build/?tier=emerald&amp;region=tr">Ahri</a></div>
          <div>S</div>
          <div>88.10</div>
          <div><span>52.71</span><br /><span>+</span><span>1.52</span></div>
          <div>11.66</div>
          <div>23.90</div>
          <div>17</div>
          <div>4,022</div>
          <q:template hidden aria-hidden="true"><div>Ahri tooltip</div></q:template>
        </div>
        """
    )

    assert rows == [
        {
            "href": "/lol/ahri/build/?tier=emerald&region=tr",
            "name": "Ahri",
            "lines": ["1", "Ahri", "S", "88.10", "52.71", "+1.52", "11.66", "23.90", "17", "4,022"],
        }
    ]


def test_http_session_marks_empty_tier_scope_without_build_links() -> None:
    session = LolalyticsHttpSession(Settings())
    page = session._parse_tier_page(
        """
        <html>
          <head>
            <title>LoL Tier List - LoLalytics LoL Tier List for Patch 16.5</title>
            <link rel="canonical" href="https://lolalytics.com/lol/tierlist/?lane=top&tier=grandmaster&region=br&patch=16.5" />
          </head>
          <body q:route="lol/tierlist/">
            <div class="filters">No ranked rows for this scope.</div>
          </body>
        </html>
        """
    )

    assert page.rows == []
    assert page.is_empty_scope is True


def test_normalize_rank_tier_maps_legacy_master_plus_alias() -> None:
    assert normalize_rank_tier("master_plus") == "grandmaster_plus"
    assert normalize_rank_tier("Master+") == "grandmaster_plus"
    assert rank_display_name("grandmaster_plus") == "Grandmaster+"


class _FakeBrowser:
    def __init__(self) -> None:
        self.called = False

    async def fetch_tier_rows(self, _url: str) -> list[dict[str, object]]:
        self.called = True
        return []


class _FakeHttpSession:
    async def fetch_tier_rows(self, _url: str) -> TierPageResult:
        return TierPageResult(rows=[], is_empty_scope=True)


@pytest.mark.asyncio
async def test_fetch_tier_stats_skips_browser_fallback_for_valid_empty_scope() -> None:
    provider = build_provider()
    browser = _FakeBrowser()
    http = _FakeHttpSession()

    records = await provider._fetch_tier_stats(
        browser=browser,
        http=http,
        region="BR",
        rank_tier="grandmaster",
        role="top",
        patch="16.5.1",
    )

    assert records == []
    assert browser.called is False


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
