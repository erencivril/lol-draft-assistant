from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import Browser, BrowserContext, Page, async_playwright
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

TIER_ROW_SELECTOR = r"div.flex.h-\[52px\]"
CAROUSEL_SELECTOR = "div.cursor-grab"
COUNTER_TAB_TYPES = ["common_counter", "strong_counter", "weak_counter", "delta_counter"]
SYNERGY_TAB_TYPES = ["common_synergy", "good_synergy", "bad_synergy", "delta_synergy", "delta_synergy_normalised"]

TIER_ROW_EXTRACT_SCRIPT = """
(els) => els.map((el) => {
    const links = Array.from(el.querySelectorAll('a[href*="/build/"]'));
    if (!links.length) {
        return null;
    }
    const lines = (el.innerText || '')
        .split('\\n')
        .map((line) => line.trim())
        .filter(Boolean);
    if (lines.length < 10) {
        return null;
    }
    return {
        href: links[0].getAttribute('href'),
        name: (links[links.length - 1].innerText || '').trim(),
        lines,
    };
}).filter(Boolean)
"""

CAROUSEL_EXTRACT_SCRIPT = """
(els, expectedLabel) => els.map((el) => {
    const parent = el.parentElement;
    const labelNode = Array.from(parent?.children || []).find((child) => {
        return child.className && String(child.className).includes('w-[80px]');
    });
    const label = labelNode?.innerText?.split('\\n')[0]?.trim() || '';
    if (label !== expectedLabel) {
        return null;
    }
    const cards = Array.from(el.firstElementChild?.children || []);
    if (!cards.length) {
        return null;
    }
    const items = cards.map((card) => {
        const link = card.querySelector('a');
        const href = link?.getAttribute('href');
        if (!href) {
            return null;
        }
        const image = link.querySelector('img');
        const metrics = Array.from(card.children)
            .filter((child) => child.tagName === 'DIV')
            .map((child) => (child.textContent || '').trim());
        return {
            href,
            label: image?.getAttribute('alt') || '',
            metrics,
        };
    }).filter(Boolean);
    if (!items.length) {
        return null;
    }
    const roleParam = expectedLabel === 'Counter' ? 'vslane' : 'lane';
    const rowRole = new URL(items[0].href, window.location.origin).searchParams.get(roleParam);
    return { rowRole, items };
}).filter(Boolean)
""" 


@dataclass(slots=True)
class TierPageResult:
    rows: list[dict[str, object]]
    is_empty_scope: bool = False


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

    async def fetch_tier_rows(self, url: str) -> TierPageResult:
        async with self._semaphore:
            async def operation() -> TierPageResult:
                html = await self._fetch_html(url)
                return self._parse_tier_page(html)

            return await self._with_retry(operation, url)

    async def fetch_build_payload(self, url: str) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        async with self._semaphore:
            async def operation() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
                html = await self._fetch_html(url)
                return (
                    self._parse_build_counter_rows(html),
                    await self._fetch_build_synergy_rows(url),
                )

            return await self._with_retry(operation, url)

    async def _fetch_html(self, url: str) -> str:
        if self._client is None:
            raise RuntimeError("Lolalytics HTTP session is not initialized")
        response = await self._client.get(url)
        response.raise_for_status()
        return response.text

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

    def _parse_tier_rows(self, html: str) -> list[dict[str, object]]:
        soup = BeautifulSoup(html, "html.parser")
        rows: list[dict[str, object]] = []
        for element in soup.select(TIER_ROW_SELECTOR):
            links = element.select('a[href*="/build/"]')
            if not links:
                continue
            clone = BeautifulSoup(str(element), "html.parser").select_one(TIER_ROW_SELECTOR)
            if clone is None:
                continue
            for hidden in clone.select(r"q\:template,[hidden],[aria-hidden='true'],script,style"):
                hidden.decompose()
            lines = self._normalize_lines(list(clone.stripped_strings))
            if len(lines) < 10:
                continue
            rows.append(
                {
                    "href": links[0].get("href", ""),
                    "name": links[-1].get_text(strip=True),
                    "lines": lines,
                }
            )
        return rows

    def _parse_tier_page(self, html: str) -> TierPageResult:
        soup = BeautifulSoup(html, "html.parser")
        rows = self._parse_tier_rows(html)
        if rows:
            return TierPageResult(rows=rows)

        is_tier_document = (
            'q:route="lol/tierlist/"' in html
            or any("/lol/tierlist/" in (link.get("href") or "") for link in soup.select('link[rel="canonical"]'))
        )
        has_build_links = bool(soup.select('a[href*="/build/"]'))
        return TierPageResult(rows=[], is_empty_scope=is_tier_document and not has_build_links)

    def _parse_build_counter_rows(self, html: str) -> list[dict[str, object]]:
        payload = self._extract_qwik_payload(html)
        if payload is None:
            return []

        objs = payload.get("objs")
        if not isinstance(objs, list):
            return []

        cache: dict[int, object] = {}
        items: dict[tuple[str, int], dict[str, object]] = {}
        for obj in objs:
            if not isinstance(obj, dict) or "data" not in obj or "lane" not in obj:
                continue
            row_role = normalize_role_name(str(self._resolve_qwik_value(objs, obj.get("lane"), cache) or ""))
            compact_rows = self._resolve_qwik_value(objs, obj.get("data"), cache)
            if not row_role or not self._looks_like_compact_rows(compact_rows, row_length=6):
                continue
            for item in self._compact_rows_to_items(compact_rows, row_role=row_role):
                key = (row_role, int(item["champion_id"]))
                items[key] = item
        return list(items.values())

    async def _fetch_build_synergy_rows(self, build_url: str) -> list[dict[str, object]]:
        scope = self._build_scope_from_url(build_url)
        mega_url = (
            f"{LOLALYTICS_MEGA_URL}?ep=build-team"
            f"&v=1&patch={scope.patch}"
            f"&c={scope.champion_slug}"
            f"&lane={scope.lane}"
            f"&tier={scope.rank_tier}"
            f"&queue=ranked"
            f"&region={scope.region}"
        )
        payload = await self._fetch_json(mega_url, referer=build_url)
        return self._parse_team_payload(payload)

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
                    # Lolalytics compact rows expose pick rate in slot 4 instead of the browser-only adjusted delta.
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

    def _extract_qwik_payload(self, html: str) -> dict[str, object] | None:
        soup = BeautifulSoup(html, "html.parser")
        script = soup.find("script", {"type": "qwik/json"})
        if script is None:
            return None
        content = script.string or script.get_text()
        if not content:
            return None
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            logger.debug("Failed to decode qwik/json payload")
            return None
        return payload if isinstance(payload, dict) else None

    def _resolve_qwik_value(self, objs: list[object], value: object, cache: dict[int, object]) -> object:
        if isinstance(value, list):
            return [self._resolve_qwik_value(objs, item, cache) for item in value]
        if isinstance(value, dict):
            return {key: self._resolve_qwik_value(objs, item, cache) for key, item in value.items()}
        if not isinstance(value, str):
            return value
        if value == "":
            return value

        control_code = ord(value[0])
        if control_code == 1:
            return None
        if control_code == 5:
            return value[1:]
        if control_code == 18:
            return self._resolve_qwik_value(objs, value[1:], cache)

        ref_index = self._parse_base36_ref(value)
        if ref_index is None or not (0 <= ref_index < len(objs)):
            return value
        if ref_index in cache:
            return cache[ref_index]

        cache[ref_index] = None
        resolved = self._resolve_qwik_value(objs, objs[ref_index], cache)
        cache[ref_index] = resolved
        return resolved

    def _parse_base36_ref(self, value: str) -> int | None:
        digits: list[str] = []
        for char in value.lower():
            if char.isdigit() or "a" <= char <= "z":
                digits.append(char)
                continue
            break
        if not digits:
            return None
        return int("".join(digits), 36)

    def _looks_like_compact_rows(self, value: object, *, row_length: int) -> bool:
        return (
            isinstance(value, list)
            and bool(value)
            and isinstance(value[0], list)
            and len(value[0]) >= row_length
            and isinstance(value[0][0], int)
        )

    def _build_scope_from_url(self, build_url: str) -> BuildScope:
        parsed = urlparse(build_url)
        query = parse_qs(parsed.query)
        path_parts = [part for part in parsed.path.split("/") if part]
        champion_slug = path_parts[1] if len(path_parts) >= 2 else ""
        return BuildScope(
            champion_slug=champion_slug,
            lane=str(query.get("lane", [""])[0]),
            rank_tier=str(query.get("tier", [""])[0]),
            region=str(query.get("region", [""])[0]),
            patch=str(query.get("patch", [""])[0]),
        )

    def _normalize_lines(self, raw_lines: list[str]) -> list[str]:
        lines: list[str] = []
        index = 0
        while index < len(raw_lines):
            token = raw_lines[index].strip()
            if (
                token in {"+", "-"}
                and index + 1 < len(raw_lines)
                and self._looks_numeric(raw_lines[index + 1])
            ):
                lines.append(f"{token}{raw_lines[index + 1].strip()}")
                index += 2
                continue
            lines.append(token)
            index += 1
        return lines

    def _looks_numeric(self, value: str) -> bool:
        cleaned = value.replace("%", "").replace(",", "").replace(".", "").strip()
        return cleaned.isdigit()


class LolalyticsBrowserSession:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._semaphore = asyncio.Semaphore(settings.scrape_fallback_concurrency)

    async def __aenter__(self) -> LolalyticsBrowserSession:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context(
            locale="en-US",
            user_agent=LOLALYTICS_USER_AGENT,
            viewport={"width": 1600, "height": 900},
        )
        await self._context.route("**/*", self._handle_route)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._context is not None:
            await self._context.close()
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()

    async def fetch_tier_rows(self, url: str) -> list[dict[str, object]]:
        async with self._semaphore:
            async def operation() -> list[dict[str, object]]:
                page = await self._new_page()
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=int(self.settings.scrape_timeout_seconds * 1000))
                    await page.wait_for_selector(TIER_ROW_SELECTOR)
                    return await self._load_tier_rows(page)
                finally:
                    await page.close()

            return await self._with_retry(operation, url)

    async def fetch_build_payload(self, url: str) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        async with self._semaphore:
            async def operation() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
                page = await self._new_page()
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=int(self.settings.scrape_timeout_seconds * 1000))
                    try:
                        await page.wait_for_selector('div[data-type]', timeout=6000)
                    except Exception:
                        await page.wait_for_timeout(1200)
                        if await page.locator('div[data-type]').count() == 0:
                            return [], []
                    await page.wait_for_timeout(400)
                    counter_rows = await self._collect_tab_group(page, expected_label="Counter", tab_types=COUNTER_TAB_TYPES)
                    synergy_rows = await self._collect_tab_group(page, expected_label="Synergy", tab_types=SYNERGY_TAB_TYPES)
                    return counter_rows, synergy_rows
                finally:
                    await page.close()

            return await self._with_retry(operation, url)

    async def _with_retry(self, operation, url: str, max_retries: int = 3):
        for attempt in range(max_retries):
            try:
                return await operation()
            except Exception as exc:
                if attempt == max_retries - 1:
                    raise
                wait = 2**attempt
                logger.warning(
                    "Attempt %d/%d failed for %s: %s. Retry in %ds",
                    attempt + 1,
                    max_retries,
                    url,
                    exc,
                    wait,
                )
                await asyncio.sleep(wait)

    async def _new_page(self) -> Page:
        if self._context is None:
            raise RuntimeError("Lolalytics browser session is not initialized")
        page = await self._context.new_page()
        page.set_default_timeout(int(self.settings.scrape_timeout_seconds * 1000))
        return page

    async def _handle_route(self, route) -> None:
        if route.request.resource_type in {"image", "media", "font"}:
            await route.abort()
            return
        await route.continue_()

    async def _load_tier_rows(self, page: Page) -> list[dict[str, object]]:
        rows = page.locator(TIER_ROW_SELECTOR)
        previous_count = -1
        stable_passes = 0
        extracted: list[dict[str, object]] = []

        for _ in range(8):
            extracted = await rows.evaluate_all(TIER_ROW_EXTRACT_SCRIPT)
            current_count = len(extracted)
            if current_count == previous_count:
                stable_passes += 1
                if stable_passes >= 2:
                    break
            else:
                stable_passes = 0
                previous_count = current_count

            if current_count == 0:
                await page.wait_for_timeout(250)
                continue

            await rows.nth(current_count - 1).scroll_into_view_if_needed()
            await page.wait_for_timeout(350)

        return extracted

    async def _collect_tab_group(self, page: Page, *, expected_label: str, tab_types: list[str]) -> list[dict[str, object]]:
        collected: dict[tuple[str, str], dict[str, object]] = {}
        for tab_type in tab_types:
            tab = page.locator(f'div[data-type="{tab_type}"]').first
            if await tab.count() == 0:
                continue
            try:
                await tab.click(force=True, timeout=10_000)
            except Exception:
                await tab.evaluate("(el) => el.click()")
            await page.wait_for_timeout(300)
            rows = await page.locator(CAROUSEL_SELECTOR).evaluate_all(CAROUSEL_EXTRACT_SCRIPT, expected_label)
            for row in rows:
                row_role = normalize_role_name(str(row.get("rowRole") or ""))
                if not row_role:
                    continue
                for item in row.get("items", []):
                    href = str(item.get("href") or "")
                    key = (row_role, href)
                    collected[key] = {
                        "row_role": row_role,
                        "href": href,
                        "label": str(item.get("label") or ""),
                        "metrics": list(item.get("metrics") or []),
                    }
        return list(collected.values())


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
        browser: LolalyticsBrowserSession | None = None,
        include_builds: bool = True,
        champion_ids: set[int] | None = None,
    ) -> ScrapeBundle:
        async with LolalyticsHttpSession(self.settings) as http:
            return await self._do_refresh(
                browser=browser,
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
        browser: LolalyticsBrowserSession | None,
        http: LolalyticsHttpSession,
        region: str,
        rank_tier: str,
        role: str,
        patch: str,
        include_builds: bool,
        champion_ids: set[int] | None,
    ) -> ScrapeBundle:
        tier_stats, tier_meta = await self._fetch_tier_stats_with_meta(
            browser=browser,
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
                fallback_used=bool(tier_meta["fallback_used"]),
                fallback_failures=int(tier_meta["fallback_failures"]),
                http_ok=bool(tier_meta["http_ok"]),
                empty_scope=bool(tier_meta["empty_scope"]),
                parser_events=list(tier_meta["parser_events"]),
            )
        await asyncio.sleep(self.settings.scrape_delay_seconds)
        matchups: list[MatchupRecord] = []
        synergies: list[SynergyRecord] = []
        fallback_used = bool(tier_meta["fallback_used"])
        fallback_failures = int(tier_meta["fallback_failures"])
        http_ok = bool(tier_meta["http_ok"])
        parser_events = list(tier_meta["parser_events"])
        tasks = [
            self._fetch_build_records(
                browser=browser,
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
                http_ok = False
                continue
            matchup_rows, synergy_rows, build_meta = result
            matchups.extend(matchup_rows)
            synergies.extend(synergy_rows)
            fallback_used = fallback_used or bool(build_meta["fallback_used"])
            fallback_failures += int(build_meta["fallback_failures"])
            http_ok = http_ok and bool(build_meta["http_ok"])
            parser_events.extend(build_meta["parser_events"])

        return ScrapeBundle(
            tier_stats=tier_stats,
            matchups=matchups,
            synergies=synergies,
            fallback_used=fallback_used,
            fallback_failures=fallback_failures,
            http_ok=http_ok,
            empty_scope=bool(tier_meta["empty_scope"]),
            parser_events=parser_events,
        )

    async def _fetch_tier_stats(
        self,
        *,
        browser: LolalyticsBrowserSession | None,
        http: LolalyticsHttpSession,
        region: str,
        rank_tier: str,
        role: str,
        patch: str,
    ) -> list[TierStatRecord]:
        records, _ = await self._fetch_tier_stats_with_meta(
            browser=browser,
            http=http,
            region=region,
            rank_tier=rank_tier,
            role=role,
            patch=patch,
        )
        return records

    async def _fetch_tier_stats_with_meta(
        self,
        *,
        browser: LolalyticsBrowserSession | None,
        http: LolalyticsHttpSession,
        region: str,
        rank_tier: str,
        role: str,
        patch: str,
    ) -> tuple[list[TierStatRecord], dict[str, object]]:
        url = (
            f"{self.settings.lolalytics_base_url}/tierlist/"
            f"?lane={role}&tier={rank_tier}&region={region.lower()}&patch={self._lolalytics_patch(patch)}"
        )
        fetched_at = datetime.now(UTC).isoformat()
        meta: dict[str, object] = {
            "fallback_used": False,
            "fallback_failures": 0,
            "http_ok": True,
            "empty_scope": False,
            "parser_events": [],
        }
        tier_page = await http.fetch_tier_rows(url)
        rows = tier_page.rows
        if not rows and tier_page.is_empty_scope:
            logger.info("Tier scope has no rows for %s; treating it as a valid empty scope", url)
            meta["empty_scope"] = True
            meta["parser_events"] = [
                self._make_parser_event(
                    stage="tier",
                    event_type="empty_scope",
                    severity="info",
                    message=f"No tier rows for {region}/{rank_tier}/{role}",
                )
            ]
            return [], meta
        if not rows:
            logger.warning("HTTP tier parse returned no rows for %s, falling back to browser", url)
            meta["fallback_used"] = True
            meta["http_ok"] = False
            parser_events = list(meta["parser_events"])
            parser_events.append(
                self._make_parser_event(
                    stage="tier",
                    event_type="http_empty_browser_fallback",
                    severity="warning",
                    message=f"HTTP tier parse returned no rows for {url}",
                    used_fallback=True,
                )
            )
            meta["parser_events"] = parser_events
            if browser is not None:
                rows = await browser.fetch_tier_rows(url)
            else:
                async with LolalyticsBrowserSession(self.settings) as managed_browser:
                    rows = await managed_browser.fetch_tier_rows(url)
        records_by_champion: dict[int, TierStatRecord] = {}

        for row in rows:
            lines = list(row.get("lines") or [])
            if len(lines) < 10:
                continue
            champion = self._resolve_champion(name=str(row.get("name") or ""), href=str(row.get("href") or ""))
            if not champion:
                continue
            records_by_champion[champion.champion_id] = TierStatRecord(
                champion_id=champion.champion_id,
                region=region,
                rank_tier=rank_tier,
                role=role,
                tier_rank=self._parse_int(lines[0]),
                win_rate=self._parse_float(lines[4]),
                pick_rate=self._parse_float(lines[6]),
                ban_rate=self._parse_float(lines[7]),
                tier_grade=lines[2],
                pbi=self._parse_float(lines[8]),
                games=self._parse_int(lines[9]),
                scope_generation_id=patch,
                patch=patch,
                source="lolalytics",
                fetched_at=fetched_at,
            )

        return sorted(records_by_champion.values(), key=lambda item: item.tier_rank or 9999), meta

    async def _fetch_build_records(
        self,
        *,
        browser: LolalyticsBrowserSession | None,
        http: LolalyticsHttpSession,
        champion: ChampionRecord,
        region: str,
        rank_tier: str,
        role: str,
        patch: str,
    ) -> tuple[list[MatchupRecord], list[SynergyRecord], dict[str, object]]:
        url = (
            f"{self.settings.lolalytics_base_url}/{champion.key.lower()}/build/"
            f"?lane={role}&tier={rank_tier}&region={region.lower()}&patch={self._lolalytics_patch(patch)}"
        )
        fetched_at = datetime.now(UTC).isoformat()
        meta: dict[str, object] = {
            "fallback_used": False,
            "fallback_failures": 0,
            "http_ok": True,
            "parser_events": [],
        }
        counter_rows, synergy_rows = await http.fetch_build_payload(url)
        if not counter_rows and not synergy_rows:
            meta["fallback_used"] = True
            meta["http_ok"] = False
            meta["parser_events"] = [
                self._make_parser_event(
                    stage="build",
                    event_type="http_empty_browser_fallback",
                    severity="warning",
                    message=f"HTTP build parse returned no rows for {champion.name} {region}/{rank_tier}/{role}",
                    champion_id=champion.champion_id,
                    used_fallback=True,
                )
            ]
            try:
                if browser is not None:
                    counter_rows, synergy_rows = await browser.fetch_build_payload(url)
                else:
                    async with LolalyticsBrowserSession(self.settings) as managed_browser:
                        counter_rows, synergy_rows = await managed_browser.fetch_build_payload(url)
            except Exception as exc:
                meta["fallback_failures"] = 1
                meta["parser_events"].append(
                    self._make_parser_event(
                        stage="build",
                        event_type="browser_fallback_failed",
                        severity="error",
                        message=str(exc),
                        champion_id=champion.champion_id,
                        used_fallback=True,
                    )
                )
                raise
        return (
            self._build_matchup_records(
                champion=champion,
                region=region,
                rank_tier=rank_tier,
                role=role,
                patch=patch,
                fetched_at=fetched_at,
                items=counter_rows,
            ),
            self._build_synergy_records(
                champion=champion,
                region=region,
                rank_tier=rank_tier,
                role=role,
                patch=patch,
                fetched_at=fetched_at,
                items=synergy_rows,
            ),
            meta,
        )

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
            # Lolalytics exposes an extra adjusted delta value that we currently do not model downstream.
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
            # Lolalytics exposes an extra adjusted delta value that we currently do not model downstream.
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
