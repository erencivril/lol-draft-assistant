from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from app.config import Settings

logger = logging.getLogger("lda.services.item_rune_sync")

DDRAGON_ITEM_URL = "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/item.json"
DDRAGON_RUNES_URL = "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/runesReforged.json"
DDRAGON_ITEM_IMAGE_URL = "https://ddragon.leagueoflegends.com/cdn/{version}/img/item/{item_id}.png"
DDRAGON_RUNE_IMAGE_BASE = "https://ddragon.leagueoflegends.com/cdn/img/"


@dataclass(slots=True)
class ItemDefinition:
    item_id: int
    name: str
    image_url: str
    gold: int
    tags: list[str] = field(default_factory=list)
    is_boot: bool = False


@dataclass(slots=True)
class RuneDefinition:
    rune_id: int
    name: str
    image_url: str
    tree_name: str
    tree_id: int
    row: int
    is_keystone: bool


class ItemRuneSyncService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.items: dict[int, ItemDefinition] = {}
        self.runes: dict[int, RuneDefinition] = {}
        self._version: str | None = None

    async def sync(self) -> str:
        """Fetch latest version, then pull item and rune data from DDragon."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            versions_response = await client.get(self.settings.ddragon_versions_url)
            versions_response.raise_for_status()
            version = versions_response.json()[0]
            self._version = version

            # Fetch items
            items_response = await client.get(DDRAGON_ITEM_URL.format(version=version))
            items_response.raise_for_status()
            items_payload: dict = items_response.json()["data"]

            # Fetch runes
            runes_response = await client.get(DDRAGON_RUNES_URL.format(version=version))
            runes_response.raise_for_status()
            runes_payload: list[dict] = runes_response.json()

        self._parse_items(items_payload, version)
        self._parse_runes(runes_payload, version)

        logger.info(
            "Synced %d items and %d runes for patch %s",
            len(self.items),
            len(self.runes),
            version,
        )
        return version

    def _parse_items(self, payload: dict, version: str) -> None:
        items: dict[int, ItemDefinition] = {}
        for item_id_str, data in payload.items():
            # Filter out items not available on Summoner's Rift (map 11)
            maps = data.get("maps", {})
            if not maps.get("11", False):
                continue

            item_id = int(item_id_str)
            tags: list[str] = data.get("tags", [])
            items[item_id] = ItemDefinition(
                item_id=item_id,
                name=data["name"],
                image_url=DDRAGON_ITEM_IMAGE_URL.format(version=version, item_id=item_id_str),
                gold=data.get("gold", {}).get("total", 0),
                tags=tags,
                is_boot="Boots" in tags,
            )
        self.items = items

    def _parse_runes(self, payload: list[dict], version: str) -> None:
        runes: dict[int, RuneDefinition] = {}
        for tree in payload:
            tree_id = tree["id"]
            tree_name = tree["name"]
            for slot_index, slot in enumerate(tree["slots"]):
                for rune_data in slot["runes"]:
                    rune_id = rune_data["id"]
                    icon_path = rune_data["icon"]
                    runes[rune_id] = RuneDefinition(
                        rune_id=rune_id,
                        name=rune_data["name"],
                        image_url=DDRAGON_RUNE_IMAGE_BASE + icon_path,
                        tree_name=tree_name,
                        tree_id=tree_id,
                        row=slot_index,
                        is_keystone=slot_index == 0,
                    )
        self.runes = runes

    def get_item(self, item_id: int) -> ItemDefinition | None:
        return self.items.get(item_id)

    def get_rune(self, rune_id: int) -> RuneDefinition | None:
        return self.runes.get(rune_id)
