from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import httpx
from slugify import slugify

from app.config import Settings
from app.db.repository import ChampionRecord, MatchupRecord, SynergyRecord, TierStatRecord
from app.domain.roles import normalize_role_name
from app.providers.base import ScrapeBundle, StatsProvider

logger = logging.getLogger("lda.providers.lolalytics")

LOLALYTICS_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
)
LOLALYTICS_MEGA_URL = "https://a1.lolalytics.com/mega/"


@dataclass(slots=True)
class BuildScope:
    champion_slug: str
    lane: str
    rank_tier: str
    region: str
    patch: str


class LolalyticsHttpSession:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(settings.scrape_page_concurrency)

    async def __aenter__(self) -> LolalyticsHttpSession:
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": LOLALYTICS_USER_AGENT,
                "Accept-Language": "en-US,en;q=0.9",
            },
            follow_redirects=True,
            timeout=self.settings.scrape_timeout_seconds,
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def fetch_tier_json(
        self,
        *,
        region: str,
        rank_tier: str,
        role: str,
        patch: str,
    ) -> dict[str, object]:
        """Fetch tier list data via the Mega JSON API (ep=tier)."""
        url = (
            f"{LOLALYTICS_MEGA_URL}?ep=tier"
            f"&v=1&patch={patch}"
            f"&lane={role}"
            f"&tier={rank_tier}"
            f"&queue=ranked"
            f"&region={region.lower()}"
        )
        referer = f"https://lolalytics.com/lol/tierlist/?lane={role}&tier={rank_tier}&region={region.lower()}"
        async with self._semaphore:
            return await self._with_retry(lambda: self._fetch_json(url, referer=referer), url)

    async def fetch_counter_json(
        self,
        *,
        champion_slug: str,
        region: str,
        rank_tier: str,
        role: str,
        patch: str,
    ) -> dict[str, object]:
        """Fetch matchup/counter data via the Mega JSON API (ep=counter)."""
        url = (
            f"{LOLALYTICS_MEGA_URL}?ep=counter"
            f"&v=1&patch={patch}"
            f"&c={champion_slug}"
            f"&lane={role}"
            f"&tier={rank_tier}"
            f"&queue=ranked"
            f"&region={region.lower()}"
        )
        referer = f"https://lolalytics.com/lol/{champion_slug}/build/?lane={role}&tier={rank_tier}&region={region.lower()}"
        async with self._semaphore:
            return await self._with_retry(lambda: self._fetch_json(url, referer=referer), url)

    async def fetch_build_synergy_rows(self, *, champion_slug: str, region: str, rank_tier: str, role: str, patch: str) -> list[dict[str, object]]:
        """Fetch synergy data via the Mega JSON API (ep=build-team)."""
        mega_url = (
            f"{LOLALYTICS_MEGA_URL}?ep=build-team"
            f"&v=1&patch={patch}"
            f"&c={champion_slug}"
            f"&lane={role}"
            f"&tier={rank_tier}"
            f"&queue=ranked"
            f"&region={region.lower()}"
        )
        referer = f"https://lolalytics.com/lol/{champion_slug}/build/?lane={role}&tier={rank_tier}&region={region.lower()}"
        async with self._semaphore:
            payload = await self._with_retry(lambda: self._fetch_json(mega_url, referer=referer), mega_url)
        return self._parse_team_payload(payload)

    async def _fetch_json(self, url: str, *, referer: str) -> dict[str, object]:
        if self._client is None:
            raise RuntimeError("Lolalytics HTTP session is not initialized")
        response = await self._client.get(
            url,
            headers={
                "Accept": "application/json,text/plain,*/*",
                "Referer": referer,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Expected JSON object from {url}")
        return payload

    async def _with_retry(self, operation, url: str, max_retries: int = 3):
        for attempt in range(max_retries):
            try:
                return await operation()
            except Exception as exc:
                if attempt == max_retries - 1:
                    raise
                wait = 2**attempt
                logger.warning(
                    "HTTP attempt %d/%d failed for %s: %s. Retry in %ds",
                    attempt + 1,
                    max_retries,
                    url,
                    exc,
                    wait,
                )
                await asyncio.sleep(wait)

    def _parse_team_payload(self, payload: dict[str, object]) -> list[dict[str, object]]:
        team = payload.get("team")
        if not isinstance(team, dict):
            return []

        items: dict[tuple[str, int], dict[str, object]] = {}
        for row_role, compact_rows in team.items():
            normalized_role = normalize_role_name(str(row_role))
            if not normalized_role or not self._looks_like_compact_rows(compact_rows, row_length=6):
                continue
            for item in self._compact_rows_to_items(compact_rows, row_role=normalized_role):
                key = (normalized_role, int(item["champion_id"]))
                items[key] = item
        return list(items.values())

    def _compact_rows_to_items(self, compact_rows: object, *, row_role: str) -> list[dict[str, object]]:
        if not isinstance(compact_rows, list):
            return []

        items: list[dict[str, object]] = []
        for row in compact_rows:
            if not isinstance(row, list) or len(row) < 6 or not isinstance(row[0], int):
                continue
            items.append(
                {
                    "row_role": row_role,
                    "champion_id": row[0],
                    "label": "",
                    "href": "",
                    "metrics": [
                        str(row[1]),
                        str(row[2]),
                        str(row[3]),
                        str(row[4]),
                        str(int(float(str(row[5])))),
                    ],
                }
            )
        return items

    def _looks_like_compact_rows(self, value: object, *, row_length: int) -> bool:
        if not isinstance(value, list) or len(value) == 0:
            return False
        sample = value[0]
        return isinstance(sample, list) and len(sample) >= row_length


class LolalyticsProvider(StatsProvider):
    def __init__(self, settings: Settings, champion_lookup: dict[int, ChampionRecord]) -> None:
        self.settings = settings
        self.champion_lookup = champion_lookup
        self.slug_lookup: dict[str, ChampionRecord] = {}
        for record in champion_lookup.values():
            self.slug_lookup[slugify(record.name).replace("-", "")] = record
            self.slug_lookup[record.key.lower()] = record

    async def refresh(
        self,
        *,
        region: str,
        rank_tier: str,
        role: str,
        patch: str,
        include_builds: bool = True,
        champion_ids: set[int] | None = None,
    ) -> ScrapeBundle:
        async with LolalyticsHttpSession(self.settings) as http:
            return await self._do_refresh(
                http=http,
                region=region,
                rank_tier=rank_tier,
                role=role,
                patch=patch,
                include_builds=include_builds,
                champion_ids=champion_ids,
            )

    async def _do_refresh(
        self,
        *,
        http: LolalyticsHttpSession,
        region: str,
        rank_tier: str,
        role: str,
        patch: str,
        include_builds: bool,
        champion_ids: set[int] | None,
    ) -> ScrapeBundle:
        tier_stats, tier_meta = await self._fetch_tier_stats_with_meta(
            http=http,
            region=region,
            rank_tier=rank_tier,
            role=role,
            patch=patch,
        )
        if not include_builds:
            return ScrapeBundle(
                tier_stats=tier_stats,
                matchups=[],
                synergies=[],
                empty_scope=bool(tier_meta["empty_scope"]),
                parser_events=list(tier_meta["parser_events"]),
            )
        await asyncio.sleep(self.settings.scrape_delay_seconds)
        matchups: list[MatchupRecord] = []
        synergies: list[SynergyRecord] = []
        parser_events = list(tier_meta["parser_events"])
        tasks = [
            self._fetch_build_records(
                http=http,
                champion=self.champion_lookup[record.champion_id],
                region=region,
                rank_tier=rank_tier,
                role=role,
                patch=patch,
            )
            for record in tier_stats
            if record.champion_id in self.champion_lookup
            and (champion_ids is None or record.champion_id in champion_ids)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Skipped a Lolalytics build page after scrape error: %s", result)
                parser_events.append(
                    self._make_parser_event(
                        stage="build",
                        event_type="build_refresh_failed",
                        severity="error",
                        message=str(result),
                    )
                )
                continue
            matchup_rows, synergy_rows, build_events = result
            matchups.extend(matchup_rows)
            synergies.extend(synergy_rows)
            parser_events.extend(build_events)

        return ScrapeBundle(
            tier_stats=tier_stats,
            matchups=matchups,
            synergies=synergies,
            empty_scope=bool(tier_meta["empty_scope"]),
            parser_events=parser_events,
        )

    async def _fetch_tier_stats_with_meta(
        self,
        *,
        http: LolalyticsHttpSession,
        region: str,
        rank_tier: str,
        role: str,
        patch: str,
    ) -> tuple[list[TierStatRecord], dict[str, object]]:
        fetched_at = datetime.now(UTC).isoformat()
        meta: dict[str, object] = {
            "empty_scope": False,
            "parser_events": [],
        }
        api_patch = self._lolalytics_patch(patch)
        payload = await http.fetch_tier_json(
            region=region,
            rank_tier=rank_tier,
            role=role,
            patch=api_patch,
        )
        tier_data = payload.get("tier")
        if not isinstance(tier_data, dict) or not tier_data:
            logger.info("Tier JSON has no data for %s/%s/%s; treating as empty scope", region, rank_tier, role)
            meta["empty_scope"] = True
            meta["parser_events"] = [
                self._make_parser_event(
                    stage="tier",
                    event_type="empty_scope",
                    severity="info",
                    message=f"No tier data for {region}/{rank_tier}/{role}",
                )
            ]
            return [], meta

        records_by_champion: dict[int, TierStatRecord] = {}
        for _bucket, bucket_data in tier_data.items():
            if not isinstance(bucket_data, dict):
                continue
            lane_data = bucket_data.get("lane") if isinstance(bucket_data.get("lane"), dict) else bucket_data
            if not isinstance(lane_data, dict):
                continue
            for lane_name, lane_content in lane_data.items():
                normalized_lane = normalize_role_name(lane_name)
                if normalized_lane and normalized_lane != role:
                    continue
                cid_data = lane_content.get("cid") if isinstance(lane_content, dict) else None
                if not isinstance(cid_data, dict):
                    continue
                for cid_str, stats in cid_data.items():
                    if not isinstance(stats, dict):
                        continue
                    try:
                        champion_id = int(cid_str)
                    except (ValueError, TypeError):
                        continue
                    if champion_id not in self.champion_lookup:
                        continue
                    records_by_champion[champion_id] = TierStatRecord(
                        champion_id=champion_id,
                        region=region,
                        rank_tier=rank_tier,
                        role=role,
                        tier_rank=int(stats.get("rank", 0)),
                        win_rate=float(stats.get("wr", 0)),
                        pick_rate=float(stats.get("pr", 0)),
                        ban_rate=float(stats.get("br", 0)),
                        tier_grade="B",
                        pbi=float(stats.get("pr", 0)) + float(stats.get("br", 0)),
                        lane_rate=float(stats.get("pctLane", 0)),
                        games=int(stats.get("games", 0)),
                        scope_generation_id=patch,
                        patch=patch,
                        source="lolalytics",
                        fetched_at=fetched_at,
                    )

        total = len(records_by_champion)
        for record in records_by_champion.values():
            record.tier_grade = _compute_tier_grade(record.tier_rank, total)

        return sorted(records_by_champion.values(), key=lambda item: item.tier_rank or 9999), meta

    async def _fetch_build_records(
        self,
        *,
        http: LolalyticsHttpSession,
        champion: ChampionRecord,
        region: str,
        rank_tier: str,
        role: str,
        patch: str,
    ) -> tuple[list[MatchupRecord], list[SynergyRecord], list[dict[str, object]]]:
        fetched_at = datetime.now(UTC).isoformat()
        api_patch = self._lolalytics_patch(patch)
        parser_events: list[dict[str, object]] = []

        counter_payload = await http.fetch_counter_json(
            champion_slug=champion.key.lower(),
            region=region,
            rank_tier=rank_tier,
            role=role,
            patch=api_patch,
        )
        counter_items = self._parse_counter_items(counter_payload)

        synergy_items = await http.fetch_build_synergy_rows(
            champion_slug=champion.key.lower(),
            region=region,
            rank_tier=rank_tier,
            role=role,
            patch=api_patch,
        )

        return (
            self._build_matchup_records(
                champion=champion,
                region=region,
                rank_tier=rank_tier,
                role=role,
                patch=patch,
                fetched_at=fetched_at,
                items=counter_items,
            ),
            self._build_synergy_records(
                champion=champion,
                region=region,
                rank_tier=rank_tier,
                role=role,
                patch=patch,
                fetched_at=fetched_at,
                items=synergy_items,
            ),
            parser_events,
        )

    def _parse_counter_items(self, payload: dict[str, object]) -> list[dict[str, object]]:
        """Convert ep=counter JSON response into item dicts compatible with _build_matchup_records."""
        counters = payload.get("counters")
        if not isinstance(counters, list):
            return []

        items: list[dict[str, object]] = []
        for counter in counters:
            if not isinstance(counter, dict):
                continue
            cid = counter.get("cid")
            if cid is None:
                continue
            opponent_role = normalize_role_name(str(counter.get("defaultLane", "")))
            if not opponent_role:
                continue
            items.append(
                {
                    "row_role": opponent_role,
                    "champion_id": int(cid),
                    "label": "",
                    "href": "",
                    "metrics": [
                        str(counter.get("vsWr", 0)),
                        str(counter.get("d1", 0)),
                        str(counter.get("d2", 0)),
                        "0",
                        str(int(float(str(counter.get("n", 0))))),
                    ],
                }
            )
        return items

    def _make_parser_event(
        self,
        *,
        stage: str,
        event_type: str,
        severity: str,
        message: str,
        champion_id: int | None = None,
        used_fallback: bool = False,
    ) -> dict[str, object]:
        return {
            "stage": stage,
            "event_type": event_type,
            "severity": severity,
            "message": message,
            "champion_id": champion_id,
            "used_fallback": used_fallback,
        }

    def _build_matchup_records(
        self,
        *,
        champion: ChampionRecord,
        region: str,
        rank_tier: str,
        role: str,
        patch: str,
        fetched_at: str,
        items: list[dict[str, object]],
    ) -> list[MatchupRecord]:
        records: dict[tuple[int, str], MatchupRecord] = {}
        for item in items:
            opponent_role = normalize_role_name(str(item.get("row_role") or ""))
            opponent = self._resolve_item_champion(item)
            metrics = self._parse_metric_series(list(item.get("metrics") or []))
            if not opponent_role or not opponent or metrics is None:
                continue
            win_rate, delta1, delta2, _unused_adjusted_delta, games = metrics
            record = MatchupRecord(
                champion_id=champion.champion_id,
                opponent_id=opponent.champion_id,
                region=region,
                rank_tier=rank_tier,
                role=role,
                opponent_role=opponent_role,
                win_rate=win_rate,
                delta1=delta1,
                delta2=delta2,
                games=games,
                patch=patch,
                source="lolalytics",
                fetched_at=fetched_at,
            )
            key = (record.opponent_id, record.opponent_role)
            if key not in records or records[key].games < record.games:
                records[key] = record
        return list(records.values())

    def _build_synergy_records(
        self,
        *,
        champion: ChampionRecord,
        region: str,
        rank_tier: str,
        role: str,
        patch: str,
        fetched_at: str,
        items: list[dict[str, object]],
    ) -> list[SynergyRecord]:
        records: dict[tuple[int, str], SynergyRecord] = {}
        for item in items:
            teammate_role = normalize_role_name(str(item.get("row_role") or ""))
            teammate = self._resolve_item_champion(item)
            metrics = self._parse_metric_series(list(item.get("metrics") or []))
            if not teammate_role or not teammate or metrics is None:
                continue
            duo_win_rate, synergy_delta, normalised_delta, _unused_adjusted_delta, games = metrics
            record = SynergyRecord(
                champion_id=champion.champion_id,
                teammate_id=teammate.champion_id,
                region=region,
                rank_tier=rank_tier,
                role=role,
                teammate_role=teammate_role,
                duo_win_rate=duo_win_rate,
                synergy_delta=synergy_delta,
                normalised_delta=normalised_delta,
                games=games,
                patch=patch,
                source="lolalytics",
                fetched_at=fetched_at,
            )
            key = (record.teammate_id, record.teammate_role)
            if key not in records or records[key].games < record.games:
                records[key] = record
        return list(records.values())

    def _resolve_item_champion(self, item: dict[str, object]) -> ChampionRecord | None:
        champion_id = item.get("champion_id")
        try:
            if champion_id is not None:
                direct_match = self.champion_lookup.get(int(champion_id))
                if direct_match is not None:
                    return direct_match
        except (TypeError, ValueError):
            logger.debug("Could not parse direct champion id from %r", champion_id)
        return self._resolve_champion(name=str(item.get("label") or ""), href=str(item.get("href") or ""))

    def _resolve_champion(self, *, name: str, href: str) -> ChampionRecord | None:
        slug = self._slug_from_href(href)
        candidates = [slugify(name).replace("-", ""), name.strip().lower().replace(" ", "").replace("'", ""), slug]
        for candidate in candidates:
            if not candidate:
                continue
            champion = self.slug_lookup.get(candidate.replace("-", ""))
            if champion:
                return champion
        logger.debug("Could not resolve champion name=%r href=%r", name, href)
        return None

    def _slug_from_href(self, href: str) -> str:
        path_parts = [part for part in urlparse(href).path.strip("/").split("/") if part]
        if "vs" in path_parts:
            vs_index = path_parts.index("vs")
            if vs_index + 1 < len(path_parts):
                return path_parts[vs_index + 1].replace("-", "")
        if len(path_parts) >= 2 and path_parts[0] == "lol":
            return path_parts[1].replace("-", "")
        return ""

    def _parse_metric_series(self, metrics: list[object]) -> tuple[float, float, float, float, int] | None:
        if len(metrics) < 5:
            return None
        cleaned = [str(value).strip() for value in metrics[:5]]
        return (
            self._parse_float(cleaned[0]),
            self._parse_float(cleaned[1]),
            self._parse_float(cleaned[2]),
            self._parse_float(cleaned[3]),
            self._parse_int(cleaned[4]),
        )

    def _parse_float(self, value: str) -> float:
        cleaned = value.replace("%", "").replace(",", "").strip()
        if cleaned.startswith("+"):
            cleaned = cleaned[1:]
        try:
            return float(cleaned)
        except ValueError:
            logger.debug("Failed to parse float from %r", value)
            return 0.0

    def _parse_int(self, value: str) -> int:
        cleaned = value.replace(",", "").strip()
        try:
            return int(float(cleaned))
        except ValueError:
            logger.debug("Failed to parse int from %r", value)
            return 0

    def _lolalytics_patch(self, patch: str) -> str:
        parts = patch.split(".")
        return ".".join(parts[:2]) if len(parts) >= 2 else patch


def _compute_tier_grade(rank: int, total: int) -> str:
    if total == 0:
        return "B"
    pct = rank / total
    if pct <= 0.02:
        return "S+"
    if pct <= 0.07:
        return "S"
    if pct <= 0.15:
        return "A"
    if pct <= 0.35:
        return "B+"
    if pct <= 0.60:
        return "B"
    if pct <= 0.80:
        return "C"
    return "D"
