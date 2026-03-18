from __future__ import annotations

import asyncio
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import get_settings
from app.db.connection import create_connection
from app.db.repository import DatabaseRepository
from app.services.champion_sync import ChampionSyncService


async def _run() -> int:
    settings = get_settings()
    connection = await create_connection(str(settings.database_path), timeout_seconds=5.0, busy_timeout_ms=2000)
    repository = DatabaseRepository(connection)
    await repository.initialize()

    try:
        patch = sys.argv[1] if len(sys.argv) > 1 else await repository.latest_patch()
        if not patch:
            print("No active patch found.")
            return 1

        champion_sync = ChampionSyncService(settings, repository)
        await champion_sync.update_roles_from_tier_stats(patch)
        champion_lookup = await repository.get_champion_lookup()
        populated_count = sum(1 for champion in champion_lookup.values() if champion.patch == patch and champion.role_hints)

        print(f"Backfilled role hints for {populated_count} champions on patch {patch}.")
        return 0
    finally:
        await connection.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
