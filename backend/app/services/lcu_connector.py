from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import aiohttp

from app.config import Settings
from app.domain.draft import DraftState
from app.services.draft_state_builder import DraftStateBuilder

logger = logging.getLogger("lda.services.lcu_connector")


@dataclass(slots=True)
class LcuSnapshot:
    draft_state: DraftState
    auto_region: str | None
    auto_rank_tier: str | None
    connected: bool


class LcuConnector:
    def __init__(self, settings: Settings, draft_state_builder: DraftStateBuilder) -> None:
        self.settings = settings
        self.draft_state_builder = draft_state_builder
        self._task: asyncio.Task | None = None
        self.latest_snapshot = LcuSnapshot(draft_state=DraftState(), auto_region=None, auto_rank_tier=None, connected=False)

    async def start(self, on_update) -> None:
        self._task = asyncio.create_task(self._run(on_update))

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self, on_update) -> None:
        while True:
            lockfile = self._resolve_lcu_credentials()
            if not lockfile:
                self.latest_snapshot = LcuSnapshot(draft_state=DraftState(), auto_region=None, auto_rank_tier=None, connected=False)
                await on_update(self.latest_snapshot)
                await asyncio.sleep(self.settings.poll_interval_seconds)
                continue

            auth_header = self._build_auth_header(lockfile["password"])
            base_url = f"https://127.0.0.1:{lockfile['port']}"

            try:
                async with aiohttp.ClientSession(headers={"Authorization": auth_header, "Accept": "application/json"}) as session:
                    draft_payload = await self._safe_json(session, f"{base_url}/lol-champ-select/v1/session")
                    rank_payload = await self._safe_json(session, f"{base_url}/lol-ranked/v1/current-ranked-stats")
                    region_payload = await self._safe_json(session, f"{base_url}/riotclient/region-locale")
                    patch_payload = await self._safe_json(session, f"{base_url}/lol-patch/v1/game-version")
                    draft_state = self.draft_state_builder.build(
                        session=draft_payload if isinstance(draft_payload, dict) else None,
                        patch=patch_payload if isinstance(patch_payload, str) else None,
                        queue_type=(draft_payload or {}).get("gameType") if isinstance(draft_payload, dict) else None,
                    )
                    snapshot = LcuSnapshot(
                        draft_state=draft_state,
                        auto_region=(region_payload or {}).get("region") if isinstance(region_payload, dict) else None,
                        auto_rank_tier=self._resolve_rank(rank_payload),
                        connected=True,
                    )
                    self.latest_snapshot = snapshot
                    await on_update(snapshot)
            except aiohttp.ClientError as exc:
                logger.debug("LCU connection failed, retrying", exc_info=exc)
                self.latest_snapshot = LcuSnapshot(draft_state=DraftState(), auto_region=None, auto_rank_tier=None, connected=False)
                await on_update(self.latest_snapshot)

            await asyncio.sleep(self.settings.poll_interval_seconds)

    def _read_lockfile(self, path: Path) -> dict[str, str] | None:
        if not path.exists():
            logger.debug("LCU lockfile not found at %s", path)
            return None
        try:
            parts = path.read_text(encoding="utf-8").strip().split(":")
            return {
                "process_name": parts[0],
                "pid": parts[1],
                "port": parts[2],
                "password": parts[3],
                "protocol": parts[4],
            }
        except (OSError, IndexError):
            return None

    def _resolve_lcu_credentials(self) -> dict[str, str] | None:
        if credentials := self._read_lockfile(self.settings.lcu_lockfile_path):
            return credentials
        return self._discover_from_process()

    def _discover_from_process(self) -> dict[str, str] | None:
        if self._is_wsl():
            return self._discover_from_wsl()
        if sys.platform == "win32":
            return self._discover_from_powershell()
        return None

    def _is_wsl(self) -> bool:
        if sys.platform != "linux":
            return False
        try:
            return "microsoft" in platform.uname().release.lower()
        except Exception:
            return False

    def _discover_from_wsl(self) -> dict[str, str] | None:
        return self._discover_with_shell("powershell.exe")

    def _discover_from_powershell(self) -> dict[str, str] | None:
        return self._discover_with_shell("powershell")

    def _discover_with_shell(self, executable: str) -> dict[str, str] | None:
        command = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -eq 'LeagueClientUx.exe' } | "
            "Select-Object -ExpandProperty CommandLine"
        )
        try:
            result = subprocess.run(
                [executable, "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return self._parse_process_output(result.stdout)

    def _parse_process_output(self, output: str) -> dict[str, str] | None:
        if not output.strip():
            return None

        port = self._extract_arg(output, "app-port")
        password = self._extract_arg(output, "remoting-auth-token")
        install_directory = self._extract_arg(output, "install-directory")
        if not port or not password:
            return None
        return {
            "process_name": "LeagueClientUx",
            "pid": "0",
            "port": port,
            "password": password,
            "protocol": "https",
            "install_directory": install_directory or "",
        }

    def _extract_arg(self, command_line: str, name: str) -> str | None:
        patterns = [
            rf'"--{re.escape(name)}=([^"]+)"',
            rf'--{re.escape(name)}=([^\s"]+)',
        ]
        for pattern in patterns:
            if match := re.search(pattern, command_line):
                return match.group(1)
        return None

    def _build_auth_header(self, password: str) -> str:
        token = base64.b64encode(f"riot:{password}".encode("utf-8")).decode("utf-8")
        return f"Basic {token}"

    async def _safe_json(self, session: aiohttp.ClientSession, url: str):
        async with session.get(url, ssl=False) as response:
            if response.status >= 400:
                return None
            if "application/json" in response.headers.get("Content-Type", ""):
                return await response.json()
            return await response.text()

    def _resolve_rank(self, payload: dict | None) -> str | None:
        if not isinstance(payload, dict):
            return None
        queue_map = payload.get("queues") or payload.get("queueMap") or {}
        solo = queue_map.get("RANKED_SOLO_5x5") if isinstance(queue_map, dict) else None
        if isinstance(solo, dict) and isinstance(solo.get("tier"), str):
            return solo["tier"].lower()
        highest_entry = payload.get("highestRankedEntrySR") or payload.get("highestRankedEntry")
        if isinstance(highest_entry, dict) and isinstance(highest_entry.get("tier"), str):
            return highest_entry["tier"].lower()
        return None
