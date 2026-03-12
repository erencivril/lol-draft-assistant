from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import httpx

from app.config import Settings
from app.db.repository import ChampionRecord, DatabaseRepository

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
            SELECT champion_id, role, SUM(pick_rate) AS total_pick_rate
            FROM tier_stats
            WHERE patch = ?
            GROUP BY champion_id, role
            HAVING SUM(pick_rate) > 1.0
            """,
            (patch,),
        )
        rows = await cursor.fetchall()
        roles_by_champion: dict[int, list[str]] = {}
        for row in rows:
            champion_id = int(row["champion_id"])
            roles = roles_by_champion.setdefault(champion_id, [])
            roles.append(str(row["role"]))

        champion_lookup = await self.repository.get_champion_lookup()
        now = datetime.now(UTC).isoformat()
        for champion_id, champion in champion_lookup.items():
            derived_roles = sorted(set(roles_by_champion.get(champion_id, [])))
            await self.repository.connection.execute(
                """
                UPDATE champions
                SET roles_json = ?, updated_at = ?
                WHERE id = ? AND patch = ?
                """,
                (json.dumps(derived_roles), now, champion_id, patch),
            )
        await self.repository.connection.commit()
