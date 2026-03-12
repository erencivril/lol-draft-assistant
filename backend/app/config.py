from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import os
import platform
import sys

from app.domain.ranks import SUPPORTED_RANKS
from app.domain.ranks import OPTIONAL_AGGREGATE_RANKS
from app.domain.regions import SUPPORTED_REGIONS
from app.domain.roles import ROLE_ORDER
from pydantic import Field
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_lockfile_path() -> Path:
    if sys.platform == "linux":
        try:
            if "microsoft" in platform.uname().release.lower():
                return Path("/mnt/c/Riot Games/League of Legends/lockfile")
        except Exception:
            pass
        return Path.home() / ".local" / "share" / "leagueoflegends" / "lockfile"
    if sys.platform == "darwin":
        return Path("/Applications/League of Legends.app/Contents/LoL/lockfile")
    candidates = [
        Path(r"C:\Riot Games\League of Legends\lockfile"),
        Path(r"D:\Riot Games\League of Legends\lockfile"),
        Path(os.environ.get("ProgramData", r"C:\ProgramData"))
        / "Riot Games"
        / "Metadata"
        / "league_of_legends.live"
        / "league_of_legends.live.lockfile",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LDA_", env_file=".env", extra="ignore")

    app_name: str = "LoL Draft Assistant"
    app_env: str = "development"
    debug: bool = True
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    project_root: Path = Path(__file__).resolve().parents[2]
    data_dir: Path = Path(__file__).resolve().parents[2] / "backend" / "data"
    logs_dir: Path = Path(__file__).resolve().parents[2] / "backend" / "logs"
    database_path: Path = Path(__file__).resolve().parents[2] / "backend" / "data" / "lol_draft_assistant.db"
    frontend_dist: Path = Path(__file__).resolve().parents[2] / "frontend" / "dist"

    ddragon_versions_url: str = "https://ddragon.leagueoflegends.com/api/versions.json"
    ddragon_champions_url: str = "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json"
    ddragon_icon_url: str = "https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/{name}.png"

    lolalytics_base_url: str = "https://lolalytics.com/lol"
    default_region: str = "TR"
    default_rank_tier: str = "emerald"
    poll_interval_seconds: float = 2.0
    scrape_page_concurrency: int = 6
    scrape_fallback_concurrency: int = 1
    scrape_timeout_seconds: float = 45.0
    scrape_delay_seconds: float = 0.5
    scrape_stale_run_minutes: int = 30
    patch_probe_minutes: int = 10
    refresh_loop_minutes: int = 10
    refresh_batch_limit: int = 18
    tier_refresh_interval_hours: int = 1
    hot_build_refresh_interval_hours: int = 2
    cold_build_refresh_interval_hours: int = 6
    aggregate_build_refresh_interval_hours: int = 12
    scheduled_regions: list[str] = Field(default_factory=lambda: SUPPORTED_REGIONS.copy())
    scheduled_ranks: list[str] = Field(default_factory=lambda: SUPPORTED_RANKS.copy())
    scheduled_roles: list[str] = Field(default_factory=lambda: ROLE_ORDER.copy())
    scheduled_resume: bool = True
    hot_regions: list[str] = Field(default_factory=lambda: ["TR", "EUW", "NA", "KR"])
    hot_ranks: list[str] = Field(default_factory=lambda: ["silver", "gold", "platinum", "emerald", "diamond", "all", "gold_plus", "emerald_plus", "diamond_plus"])
    aggregate_ranks: list[str] = Field(default_factory=lambda: OPTIONAL_AGGREGATE_RANKS.copy())
    enable_local_lcu: bool = True
    enable_refresh_scheduler: bool = True
    enable_bridge_housekeeping: bool = True
    enable_startup_index_warmup: bool = False
    bridge_tokens: list[str] = Field(default_factory=list)
    bridge_session_timeout_seconds: int = 30
    admin_enabled: bool = True

    lcu_lockfile_path: Path = Field(default_factory=_default_lockfile_path)

    @field_validator("bridge_tokens", mode="before")
    @classmethod
    def parse_bridge_tokens(cls, value):
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [token.strip() for token in value.split(",") if token.strip()]
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    return settings
