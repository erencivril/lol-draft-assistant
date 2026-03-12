from __future__ import annotations

import asyncio
import argparse
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import get_settings
from app.db.connection import create_connection
from app.db.repository import DatabaseRepository
from app.domain.ranks import DEFAULT_SCRAPE_RANKS, SUPPORTED_RANKS
from app.domain.regions import SUPPORTED_REGIONS
from app.domain.roles import ROLE_ORDER
from app.providers.lolalytics_provider import LolalyticsProvider
from app.services.champion_sync import ChampionSyncService
from app.services.recommendation_service import RecommendationService
from app.services.scraper_orchestrator import ScraperOrchestrator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", action="append")
    parser.add_argument("--rank", action="append", choices=SUPPORTED_RANKS)
    parser.add_argument("--role", action="append", choices=ROLE_ORDER)
    parser.add_argument("--all-regions", action="store_true")
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    settings = get_settings()
    connection = await create_connection(str(settings.database_path))
    repository = DatabaseRepository(connection)
    await repository.initialize()

    champion_sync = ChampionSyncService(settings, repository)
    recommendation_service = RecommendationService(repository)
    orchestrator = ScraperOrchestrator(settings, repository, champion_sync, recommendation_service)
    patch = await champion_sync.sync()
    actual_provider = LolalyticsProvider(
        settings,
        await repository.get_champion_lookup(),
    )
    ranks = args.rank or DEFAULT_SCRAPE_RANKS
    roles = args.role or ROLE_ORDER
    regions = SUPPORTED_REGIONS if args.all_regions else (args.region or [settings.default_region])

    for region in regions:
        print(f"Starting bootstrap for region={region}, ranks={','.join(ranks)}, roles={','.join(roles)}")
        result = await orchestrator.refresh_scope(
            provider=actual_provider,
            patch=patch,
            region=region,
            ranks=ranks,
            roles=roles,
            resume=args.resume,
        )
        print(f"Bootstrap completed for region={result['region']} patch={result['patch']}")
    await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
