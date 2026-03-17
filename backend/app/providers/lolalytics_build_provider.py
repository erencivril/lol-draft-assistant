"""Fetch and parse item/rune build data from lolalytics q-data.json (Qwik SSR endpoint)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from app.config import Settings
from app.providers.lolalytics_provider import LOLALYTICS_USER_AGENT

logger = logging.getLogger("lda.providers.lolalytics_build")

LOLALYTICS_BUILD_BASE = "https://lolalytics.com/lol"
CACHE_TTL_SECONDS = 30 * 60  # 30 minutes

_TIER_MAP: dict[str, str] = {
    "iron": "all",
    "bronze": "all",
    "silver": "gold_plus",
    "gold": "gold_plus",
    "platinum": "platinum_plus",
    "emerald": "emerald_plus",
    "diamond": "diamond_plus",
    "master": "diamond_plus",
    "grandmaster": "grandmaster_plus",
    "challenger": "grandmaster_plus",
}


def _normalize_tier(tier: str) -> str:
    """Map single-rank tiers to nearest _plus aggregate tier for q-data.json URLs."""
    return _TIER_MAP.get(tier, tier)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ItemBuildEntry:
    """A single item option for a specific build slot."""
    item_id: int
    win_rate: float
    pick_rate: float
    games: int


@dataclass(slots=True)
class RuneStatEntry:
    """Stats for a single rune/keystone in a specific matchup context."""
    rune_id: int
    pick_rate: float
    win_rate: float
    games: int


@dataclass(slots=True)
class MatchupBuildData:
    """All build/rune data for a champion (optionally vs a specific opponent)."""
    champion_id: int
    champion_role: str
    opponent_id: int | None = None  # None = general build
    opponent_role: str | None = None
    # Items by slot position
    boots: list[ItemBuildEntry] = field(default_factory=list)
    start_items: list[ItemBuildEntry] = field(default_factory=list)
    item1: list[ItemBuildEntry] = field(default_factory=list)
    item2: list[ItemBuildEntry] = field(default_factory=list)
    item3: list[ItemBuildEntry] = field(default_factory=list)
    item4: list[ItemBuildEntry] = field(default_factory=list)
    item5: list[ItemBuildEntry] = field(default_factory=list)
    # Rune stats (keystones + individual runes + stat shards)
    rune_stats: list[RuneStatEntry] = field(default_factory=list)
    # Skill order
    skill_order: str | None = None
    # Overall matchup stats
    overall_win_rate: float = 0.0
    total_games: int = 0
    patch: str = ""
    fetched_at: str = ""


# ---------------------------------------------------------------------------
# Qwik JSON decoder
# ---------------------------------------------------------------------------

def _b36_decode(ref: str) -> int:
    """Decode a base-36 reference string to an integer index."""
    return int(ref, 36)


def _deep_resolve(objs: list, ref: object, depth: int = 0) -> object:
    """Recursively resolve Qwik base-36 references in _objs.

    After following a string reference to an _objs value, only recurse into
    containers (dict/list).  Scalar values (str, number) are returned as-is
    to avoid misinterpreting data strings like "16.5" as further references.
    """
    if depth > 8:
        return ref
    if isinstance(ref, str):
        if not ref.isalnum() or len(ref) == 0:
            return ref
        try:
            idx = _b36_decode(ref)
            if 0 <= idx < len(objs):
                val = objs[idx]
                if isinstance(val, dict):
                    return {k: _deep_resolve(objs, v, depth + 1) for k, v in val.items()}
                if isinstance(val, list):
                    return [_deep_resolve(objs, item, depth + 1) for item in val]
                # Scalar (str, int, float, bool, None) — return directly
                return val
        except ValueError:
            pass
        return ref
    if isinstance(ref, list):
        return [_deep_resolve(objs, item, depth + 1) for item in ref]
    if isinstance(ref, dict):
        return {k: _deep_resolve(objs, v, depth + 1) for k, v in ref.items()}
    return ref


def _find_build_loader(objs: list, entry_ref: str) -> dict | None:
    """Navigate _entry -> loaders -> find the loader that contains build data."""
    try:
        entry = objs[_b36_decode(entry_ref)]
    except (ValueError, IndexError):
        return None
    if not isinstance(entry, dict) or "loaders" not in entry:
        return None

    loaders_ref = entry["loaders"]
    try:
        loaders = objs[_b36_decode(loaders_ref)]
    except (ValueError, IndexError):
        return None
    if not isinstance(loaders, dict):
        return None

    # The build data loader has keys like 'header', 'item1', 'runes'
    for loader_key, loader_ref in loaders.items():
        if not isinstance(loader_ref, str):
            continue
        try:
            loader = objs[_b36_decode(loader_ref)]
        except (ValueError, IndexError):
            continue
        if isinstance(loader, dict) and "header" in loader and "item1" in loader:
            return loader

    return None


def _find_ref_data_loader(objs: list, entry_ref: str) -> dict | None:
    """Find the reference data loader (has 'patch', 'champions', 'items' keys)."""
    try:
        entry = objs[_b36_decode(entry_ref)]
    except (ValueError, IndexError):
        return None
    if not isinstance(entry, dict) or "loaders" not in entry:
        return None

    loaders_ref = entry["loaders"]
    try:
        loaders = objs[_b36_decode(loaders_ref)]
    except (ValueError, IndexError):
        return None
    if not isinstance(loaders, dict):
        return None

    for loader_ref in loaders.values():
        if not isinstance(loader_ref, str):
            continue
        try:
            loader = objs[_b36_decode(loader_ref)]
        except (ValueError, IndexError):
            continue
        if isinstance(loader, dict) and "patch" in loader and "items" in loader and "champions" in loader:
            return loader

    return None


def _parse_item_array(objs: list, build_loader: dict, key: str) -> list[ItemBuildEntry]:
    """Parse an item array (boots, item1, item2, etc.) from the build loader."""
    ref = build_loader.get(key)
    if not isinstance(ref, str):
        return []
    try:
        arr = objs[_b36_decode(ref)]
    except (ValueError, IndexError):
        return []
    if not isinstance(arr, list):
        return []

    entries: list[ItemBuildEntry] = []
    for item_ref in arr:
        if not isinstance(item_ref, str):
            continue
        resolved = _deep_resolve(objs, item_ref)
        if not isinstance(resolved, (list, dict)):
            continue
        # Items are either [itemId, wr, pr, games, time] or {"0": itemId, "1": wr, ...}
        if isinstance(resolved, list) and len(resolved) >= 4:
            row = resolved
        elif isinstance(resolved, dict):
            row = [resolved.get(str(i)) for i in range(5)]
        else:
            continue
        try:
            item_id = int(row[0])
            win_rate = float(row[1]) if row[1] is not None else 0.0
            pick_rate = float(row[2]) if row[2] is not None else 0.0
            games = int(row[3]) if row[3] is not None else 0
        except (TypeError, ValueError):
            continue
        if item_id > 0 and games > 0:
            entries.append(ItemBuildEntry(
                item_id=item_id,
                win_rate=win_rate,
                pick_rate=pick_rate,
                games=games,
            ))
    return entries


def _parse_rune_stats(objs: list, build_loader: dict) -> list[RuneStatEntry]:
    """Parse rune stats from the build loader's runes.stats object."""
    runes_ref = build_loader.get("runes")
    if not isinstance(runes_ref, str):
        return []
    try:
        runes_obj = objs[_b36_decode(runes_ref)]
    except (ValueError, IndexError):
        return []
    if not isinstance(runes_obj, dict) or "stats" not in runes_obj:
        return []

    stats_ref = runes_obj["stats"]
    if not isinstance(stats_ref, str):
        return []
    try:
        stats_obj = objs[_b36_decode(stats_ref)]
    except (ValueError, IndexError):
        return []
    if not isinstance(stats_obj, dict):
        return []

    entries: list[RuneStatEntry] = []
    for rune_id_str, entry_ref in stats_obj.items():
        try:
            rune_id = int(rune_id_str)
        except ValueError:
            continue

        resolved = _deep_resolve(objs, entry_ref)

        # Rune stats resolve to [[pickRate, winRate, games], ...]
        # (list of arrays, usually one entry per usage context)
        primary: list | None = None
        if isinstance(resolved, list) and len(resolved) > 0:
            first = resolved[0]
            if isinstance(first, list) and len(first) >= 3:
                primary = first
        elif isinstance(resolved, dict):
            # Fallback: some formats use {"0": [pickRate, winRate, games]}
            candidate = resolved.get("0") or resolved.get(0)
            if isinstance(candidate, list) and len(candidate) >= 3:
                primary = candidate

        if primary is None:
            continue

        try:
            pick_rate = float(primary[0])
            win_rate = float(primary[1])
            games = int(primary[2]) if isinstance(primary[2], (int, float)) else int(float(str(primary[2])))
        except (TypeError, ValueError):
            continue

        if games > 0:
            entries.append(RuneStatEntry(
                rune_id=rune_id,
                pick_rate=pick_rate,
                win_rate=win_rate,
                games=games,
            ))
    return entries


def _parse_header(objs: list, build_loader: dict) -> dict:
    """Extract header metadata from the build loader."""
    header_ref = build_loader.get("header")
    if not isinstance(header_ref, str):
        return {}
    resolved = _deep_resolve(objs, header_ref)
    if not isinstance(resolved, dict):
        return {}
    return resolved


def _parse_skill_order(objs: list, build_loader: dict) -> str | None:
    """Extract the most popular skill order (e.g. 'EQW', 'QEW')."""
    ref = build_loader.get("skillOrder")
    if not isinstance(ref, str):
        return None
    try:
        arr = objs[_b36_decode(ref)]
    except (ValueError, IndexError):
        return None
    if not isinstance(arr, list) or len(arr) == 0:
        return None

    # First entry is most popular: [label, winRate, pickRate, games]
    resolved = _deep_resolve(objs, arr[0])
    if isinstance(resolved, list) and len(resolved) > 0:
        label = resolved[0]
        if isinstance(label, str) and label.isalpha():
            return label
    if isinstance(resolved, dict):
        order = resolved.get("0") or resolved.get("order")
        if isinstance(order, str):
            return order
    return None


def parse_qdata_json(raw: dict, champion_id: int, role: str,
                     opponent_id: int | None = None,
                     opponent_role: str | None = None) -> MatchupBuildData | None:
    """Parse a q-data.json response into structured build data."""
    objs = raw.get("_objs")
    entry_ref = raw.get("_entry")
    if not isinstance(objs, list) or not isinstance(entry_ref, str):
        logger.warning("Invalid q-data.json format: missing _objs or _entry")
        return None

    build_loader = _find_build_loader(objs, entry_ref)
    if build_loader is None:
        logger.warning("Could not find build data loader in q-data.json")
        return None

    header = _parse_header(objs, build_loader)
    patch = str(header.get("patch", ""))
    overall_wr = float(header.get("wr", 0))
    total_n = int(header.get("n", 0)) if header.get("n") else 0

    # If this is a VS page, use header.vs for opponent confirmation
    if opponent_id is None and header.get("vs"):
        try:
            opponent_id = int(header["vs"])
        except (TypeError, ValueError):
            pass
    if opponent_role is None and header.get("vsLane"):
        opponent_role = str(header["vsLane"])

    return MatchupBuildData(
        champion_id=champion_id,
        champion_role=role,
        opponent_id=opponent_id,
        opponent_role=opponent_role,
        boots=_parse_item_array(objs, build_loader, "boots"),
        start_items=_parse_item_array(objs, build_loader, "startItem"),
        item1=_parse_item_array(objs, build_loader, "item1"),
        item2=_parse_item_array(objs, build_loader, "item2"),
        item3=_parse_item_array(objs, build_loader, "item3"),
        item4=_parse_item_array(objs, build_loader, "item4"),
        item5=_parse_item_array(objs, build_loader, "item5"),
        rune_stats=_parse_rune_stats(objs, build_loader),
        skill_order=_parse_skill_order(objs, build_loader),
        overall_win_rate=overall_wr,
        total_games=total_n,
        patch=patch,
        fetched_at=datetime.now(UTC).isoformat(),
    )


# ---------------------------------------------------------------------------
# HTTP fetcher with caching
# ---------------------------------------------------------------------------

@dataclass
class _CacheEntry:
    data: MatchupBuildData | None
    expires_at: float


class LolalyticsBuildsProvider:
    """Fetches and parses item/rune build data from lolalytics q-data.json."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._cache: dict[str, _CacheEntry] = {}
        self._semaphore = asyncio.Semaphore(settings.scrape_page_concurrency)

    def _cache_key(self, champion_slug: str, role: str,
                   opponent_slug: str | None, opponent_role: str | None,
                   keystone_id: int | None = None) -> str:
        ks = str(keystone_id) if keystone_id and not opponent_slug else ""
        return f"{champion_slug}:{role}:{opponent_slug or ''}:{opponent_role or ''}:{ks}"

    def _get_cached(self, key: str) -> MatchupBuildData | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        if time.monotonic() > entry.expires_at:
            del self._cache[key]
            return None
        return entry.data

    def _set_cached(self, key: str, data: MatchupBuildData | None) -> None:
        self._cache[key] = _CacheEntry(
            data=data,
            expires_at=time.monotonic() + CACHE_TTL_SECONDS,
        )

    async def fetch_build_data(
        self,
        *,
        champion_slug: str,
        champion_id: int,
        role: str,
        opponent_slug: str | None = None,
        opponent_id: int | None = None,
        opponent_role: str | None = None,
        keystone_id: int | None = None,
        tier: str = "emerald_plus",
    ) -> MatchupBuildData | None:
        """Fetch build/rune data for a champion, optionally vs a specific opponent.

        Returns cached data if available, otherwise fetches from lolalytics.
        keystone_id is only used for general build pages (vs pages don't support it).
        """
        cache_key = self._cache_key(champion_slug, role, opponent_slug, opponent_role, keystone_id)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        normalized_tier = _normalize_tier(tier)
        if opponent_slug and opponent_role:
            # VS page — keystone filter not supported
            url = (
                f"{LOLALYTICS_BUILD_BASE}/{champion_slug}/vs/{opponent_slug}"
                f"/build/q-data.json?lane={role}&vslane={opponent_role}&tier={normalized_tier}"
            )
            referer = (
                f"https://lolalytics.com/lol/{champion_slug}/vs/{opponent_slug}"
                f"/build/?lane={role}&vslane={opponent_role}&tier={normalized_tier}"
            )
        else:
            # General page — keystone filter supported
            keystone_param = f"&keystone={keystone_id}" if keystone_id else ""
            url = (
                f"{LOLALYTICS_BUILD_BASE}/{champion_slug}"
                f"/build/q-data.json?lane={role}&tier={normalized_tier}{keystone_param}"
            )
            referer = (
                f"https://lolalytics.com/lol/{champion_slug}"
                f"/build/?lane={role}&tier={normalized_tier}{keystone_param}"
            )

        async with self._semaphore:
            result = await self._fetch_and_parse(
                url=url,
                referer=referer,
                champion_id=champion_id,
                role=role,
                opponent_id=opponent_id,
                opponent_role=opponent_role,
            )

        self._set_cached(cache_key, result)
        return result

    async def fetch_matchup_builds(
        self,
        *,
        champion_slug: str,
        champion_id: int,
        role: str,
        enemies: list[dict],
        tier: str = "emerald_plus",
    ) -> list[MatchupBuildData | None]:
        """Fetch build data for a champion vs each enemy in parallel.

        Args:
            enemies: list of {"slug": str, "champion_id": int, "role": str}

        Returns list of MatchupBuildData (one per enemy, None if fetch failed).
        """
        tasks = [
            self.fetch_build_data(
                champion_slug=champion_slug,
                champion_id=champion_id,
                role=role,
                opponent_slug=enemy["slug"],
                opponent_id=enemy["champion_id"],
                opponent_role=enemy["role"],
                tier=tier,
            )
            for enemy in enemies
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        parsed: list[MatchupBuildData | None] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(
                    "Failed to fetch build data for %s vs %s: %s",
                    champion_slug, enemies[i].get("slug", "?"), result,
                )
                parsed.append(None)
            else:
                parsed.append(result)
        return parsed

    async def fetch_general_build(
        self,
        *,
        champion_slug: str,
        champion_id: int,
        role: str,
        keystone_id: int | None = None,
        tier: str = "emerald_plus",
    ) -> MatchupBuildData | None:
        """Fetch general (non-matchup) build data, optionally filtered by keystone."""
        return await self.fetch_build_data(
            champion_slug=champion_slug,
            champion_id=champion_id,
            role=role,
            keystone_id=keystone_id,
            tier=tier,
        )

    async def _fetch_and_parse(
        self,
        *,
        url: str,
        referer: str,
        champion_id: int,
        role: str,
        opponent_id: int | None,
        opponent_role: str | None,
    ) -> MatchupBuildData | None:
        try:
            async with httpx.AsyncClient(
                headers={
                    "User-Agent": LOLALYTICS_USER_AGENT,
                    "Accept-Language": "en-US,en;q=0.9",
                },
                follow_redirects=True,
                timeout=self.settings.scrape_timeout_seconds,
            ) as client:
                response = await client.get(
                    url,
                    headers={
                        "Accept": "application/json,text/plain,*/*",
                        "Referer": referer,
                    },
                )
                response.raise_for_status()
                raw = response.json()
        except Exception as exc:
            logger.warning("Failed to fetch q-data.json from %s: %s", url, exc)
            return None

        if not isinstance(raw, dict):
            logger.warning("q-data.json response is not a dict from %s", url)
            return None

        return parse_qdata_json(
            raw,
            champion_id=champion_id,
            role=role,
            opponent_id=opponent_id,
            opponent_role=opponent_role,
        )
