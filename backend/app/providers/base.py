from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.db.repository import MatchupRecord, SynergyRecord, TierStatRecord


@dataclass(slots=True)
class ScrapeBundle:
    tier_stats: list[TierStatRecord]
    matchups: list[MatchupRecord]
    synergies: list[SynergyRecord]
    fallback_used: bool = False
    fallback_failures: int = 0
    http_ok: bool = True
    empty_scope: bool = False
    tier_signature: str = ""
    build_signature: str = ""
    parser_events: list[dict[str, Any]] = field(default_factory=list)


class StatsProvider:
    async def refresh(
        self,
        *,
        region: str,
        rank_tier: str,
        role: str,
        patch: str,
        browser: Any | None = None,
    ) -> ScrapeBundle:
        raise NotImplementedError
