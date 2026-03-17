from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import httpx

from app.config import Settings
from app.db.repository import ChampionRecord, DatabaseRepository, RoleHint

logger = logging.getLogger("lda.services.champion_sync")


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

        records: list[ChampionRecord] = []
        for data in champions_payload.values():
            image_name = str(data["image"]["full"])
            if image_name.lower().endswith(".png"):
                image_name = image_name[:-4]
            records.append(
                ChampionRecord(
                    champion_id=int(data["key"]),
                    key=data["id"],
                    name=data["name"],
                    image_url=self.settings.ddragon_icon_url.format(version=patch, name=image_name),
                    roles=[],
                    patch=patch,
                )
            )

        logger.info("Synced %d champions for patch %s", len(records), patch)
        await self.repository.upsert_champions(records)
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
