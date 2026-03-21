from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.config import Settings
from app.db.repository import ChampionRecord, DatabaseRepository, RoleHint
from app.domain.champion_metadata import ChampionCompositionProfile

logger = logging.getLogger("lda.services.champion_sync")

_OVERRIDES_PATH = Path(__file__).resolve().parent.parent / "data" / "champion_overrides.json"

# DDragon tag -> partial composition scores
_TAG_SCORE_MAP: dict[str, dict[str, float]] = {
    "Tank": {"frontline_score": 0.8, "teamfight_score": 0.7, "engage_score": 0.5},
    "Fighter": {"frontline_score": 0.5, "split_score": 0.5, "teamfight_score": 0.5},
    "Assassin": {"split_score": 0.7, "engage_score": 0.3, "frontline_score": 0.1},
    "Mage": {"poke_score": 0.6, "teamfight_score": 0.6, "frontline_score": 0.1},
    "Marksman": {"scaling": 0.7, "teamfight_score": 0.6, "frontline_score": 0.1},
    "Support": {"protect_score": 0.7, "disengage_score": 0.5, "teamfight_score": 0.6},
}

_SCORE_FIELDS = [
    "engage_score", "disengage_score", "frontline_score", "poke_score",
    "split_score", "teamfight_score", "protect_score", "scaling",
]


def _load_overrides() -> dict[str, dict[str, object]]:
    if _OVERRIDES_PATH.exists():
        with open(_OVERRIDES_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def _derive_metadata(
    champion_id: int,
    champion_key: str,
    info: dict[str, int],
    tags: list[str],
    overrides: dict[str, dict[str, object]],
) -> ChampionCompositionProfile:
    """Build a ChampionCompositionProfile from DDragon info + tags, then apply overrides."""
    attack = info.get("attack", 5)
    magic = info.get("magic", 5)
    total = max(attack + magic, 1)
    damage_physical_pct = round(attack / total, 3)
    damage_magic_pct = round(magic / total, 3)
    damage_true_pct = round(1.0 - damage_physical_pct - damage_magic_pct, 3)
    if damage_true_pct < 0:
        damage_true_pct = 0.0

    # Start with moderate defaults
    scores: dict[str, float] = {f: 0.3 for f in _SCORE_FIELDS}
    scores["scaling"] = 0.5

    # Apply tag-derived scores (use max across all tags for each field)
    for tag in tags:
        mapping = _TAG_SCORE_MAP.get(tag, {})
        for field_name, value in mapping.items():
            scores[field_name] = max(scores[field_name], value)

    profile = ChampionCompositionProfile(
        champion_id=champion_id,
        damage_physical_pct=damage_physical_pct,
        damage_magic_pct=damage_magic_pct,
        damage_true_pct=damage_true_pct,
        cc_hard_seconds=0.0,
        cc_soft_seconds=0.0,
        engage_score=scores["engage_score"],
        disengage_score=scores["disengage_score"],
        frontline_score=scores["frontline_score"],
        poke_score=scores["poke_score"],
        split_score=scores["split_score"],
        teamfight_score=scores["teamfight_score"],
        protect_score=scores["protect_score"],
        scaling=scores["scaling"],
        flex_roles=[],
        tags=tags,
    )

    # Apply overrides on top
    champ_overrides = overrides.get(champion_key, {})
    for field_name, value in champ_overrides.items():
        if hasattr(profile, field_name):
            setattr(profile, field_name, value)

    return profile


class ChampionSyncService:
    def __init__(self, settings: Settings, repository: DatabaseRepository) -> None:
        self.settings = settings
        self.repository = repository

    async def sync(self) -> str:
        async with httpx.AsyncClient(timeout=30.0) as client:
            versions_response = await client.get(self.settings.ddragon_versions_url)
            versions_response.raise_for_status()
            patch = versions_response.json()[0]

            champions_response = await client.get(self.settings.ddragon_champions_url.format(version=patch))
            champions_response.raise_for_status()
            champions_payload = champions_response.json()["data"]

        overrides = _load_overrides()

        records: list[ChampionRecord] = []
        profiles: list[ChampionCompositionProfile] = []

        for data in champions_payload.values():
            champion_id = int(data["key"])
            champion_key = data["id"]
            image_name = str(data["image"]["full"])
            if image_name.lower().endswith(".png"):
                image_name = image_name[:-4]

            records.append(
                ChampionRecord(
                    champion_id=champion_id,
                    key=champion_key,
                    name=data["name"],
                    image_url=self.settings.ddragon_icon_url.format(version=patch, name=image_name),
                    roles=[],
                    patch=patch,
                )
            )

            info = data.get("info", {})
            tags = data.get("tags", [])
            profiles.append(_derive_metadata(champion_id, champion_key, info, tags, overrides))

        logger.info("Synced %d champions for patch %s", len(records), patch)
        await self.repository.upsert_champions(records)

        logger.info("Upserting %d champion metadata profiles", len(profiles))
        await self.repository.upsert_champion_metadata(profiles, patch)

        return patch

    async def update_roles_from_tier_stats(self, patch: str) -> None:
        cursor = await self.repository.connection.execute(
            """
            SELECT champion_id, role, SUM(pick_rate) AS total_pick_rate, SUM(games) AS total_games
            FROM tier_stats
            WHERE patch = ?
            GROUP BY champion_id, role
            HAVING SUM(pick_rate) > 0
            """,
            (patch,),
        )
        rows = await cursor.fetchall()

        # Build per-champion data: {champion_id: [(role, pick_rate, games), ...]} sorted by pick_rate desc
        role_data_by_champion: dict[int, list[tuple[str, float, int]]] = {}
        for row in rows:
            champion_id = int(row["champion_id"])
            entries = role_data_by_champion.setdefault(champion_id, [])
            entries.append((str(row["role"]), float(row["total_pick_rate"]), int(row["total_games"])))

        champion_lookup = await self.repository.get_champion_lookup()
        now = datetime.now(UTC).isoformat()
        for champion_id, champion in champion_lookup.items():
            entries = sorted(role_data_by_champion.get(champion_id, []), key=lambda e: e[1], reverse=True)
            if not entries:
                derived_roles: list[str] = []
                primary_role = None
                role_hints: list[RoleHint] = []
            else:
                max_pick_rate = entries[0][1]
                derived_roles = [e[0] for e in entries]
                primary_role = entries[0][0]
                role_hints = [
                    RoleHint(
                        role=e[0],
                        weight=round(e[1] / max_pick_rate, 4),
                        games=e[2],
                    )
                    for e in entries
                ]

            await self.repository.connection.execute(
                """
                UPDATE champions
                SET roles_json = ?, primary_role = ?, role_hints_json = ?, updated_at = ?
                WHERE id = ? AND patch = ?
                """,
                (
                    json.dumps(derived_roles),
                    primary_role,
                    json.dumps([{"role": h.role, "weight": h.weight, "games": h.games} for h in role_hints]),
                    now,
                    champion_id,
                    patch,
                ),
            )
        await self.repository.connection.commit()
