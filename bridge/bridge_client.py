from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import socket

import aiohttp

from app.config import get_settings
from app.domain.bridge import BridgeDraftStatePayload, BridgeHeartbeatPayload, BridgeRegisterPayload
from app.services.draft_state_builder import DraftStateBuilder
from app.services.lcu_connector import LcuConnector

logger = logging.getLogger("lda.bridge_client")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Relay local LCU champ select state to a remote LoL Draft Assistant server.")
    parser.add_argument("--server-base-url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--device-id", default=socket.gethostname().lower())
    parser.add_argument("--label", default=socket.gethostname())
    return parser.parse_args()


class BridgeClient:
    def __init__(self, *, server_base_url: str, token: str, device_id: str, label: str) -> None:
        self.server_base_url = server_base_url.rstrip("/")
        self.token = token
        self.device_id = device_id
        self.label = label
        self.settings = get_settings()
        self.connector = LcuConnector(self.settings, DraftStateBuilder())
        self._session: aiohttp.ClientSession | None = None
        self._registered = False

    async def start(self) -> None:
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_connect=10, sock_read=30)
        self._session = aiohttp.ClientSession(headers=headers, timeout=timeout)
        try:
            await self._wait_until_registered()
            await self.connector.start(self._on_update)
        except Exception:
            await self.stop()
            raise

    async def stop(self) -> None:
        await self.connector.stop()
        if self._session is not None:
            with contextlib.suppress(Exception):
                async with self._session.delete(f"{self.server_base_url}/api/bridge/session/{self.device_id}", ssl=False):
                    pass
            await self._session.close()
        self._registered = False

    async def _on_update(self, snapshot) -> None:
        if self._session is None:
            return
        if not await self._try_register_once():
            return
        heartbeat = BridgeHeartbeatPayload(
            device_id=self.device_id,
            lcu_connected=snapshot.connected,
            auto_region=snapshot.auto_region,
            auto_rank_tier=snapshot.auto_rank_tier,
            client_patch=snapshot.draft_state.patch,
            queue_type=snapshot.draft_state.queue_type,
        )
        try:
            await self._post("/api/bridge/heartbeat", heartbeat.model_dump(mode="json"), attempts=2)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            self._registered = False
            logger.warning("Bridge heartbeat failed, will retry on next poll: %s", exc)
            return
        payload = BridgeDraftStatePayload(
            device_id=self.device_id,
            lcu_connected=snapshot.connected,
            auto_region=snapshot.auto_region,
            auto_rank_tier=snapshot.auto_rank_tier,
            client_patch=snapshot.draft_state.patch,
            queue_type=snapshot.draft_state.queue_type,
            draft_state=snapshot.draft_state,
        )
        try:
            await self._request("PUT", "/api/bridge/draft-state", payload.model_dump(mode="json"), attempts=2)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning("Bridge draft relay failed, will retry on next poll: %s", exc)

    async def _wait_until_registered(self) -> None:
        while not await self._try_register_once():
            logger.warning("Cloud bridge is unreachable. Retrying registration in 5 seconds.")
            await asyncio.sleep(5)

    async def _try_register_once(self) -> bool:
        if self._registered:
            return True
        try:
            await self._post(
                "/api/bridge/register",
                BridgeRegisterPayload(device_id=self.device_id, label=self.label).model_dump(mode="json"),
                attempts=2,
            )
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning("Bridge register failed: %s", exc)
            return False
        self._registered = True
        logger.info("Cloud bridge connected to %s", self.server_base_url)
        return True

    async def _post(self, path: str, payload: dict, *, attempts: int = 6) -> None:
        await self._request("POST", path, payload, attempts=attempts)

    async def _request(self, method: str, path: str, payload: dict, *, attempts: int = 6) -> None:
        if self._session is None:
            return
        for attempt in range(1, attempts + 1):
            try:
                async with self._session.request(method, f"{self.server_base_url}{path}", json=payload, ssl=False) as response:
                    response.raise_for_status()
                    return
            except aiohttp.ClientResponseError as exc:
                if exc.status < 500 or attempt == attempts:
                    raise
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt == attempts:
                    raise
            await asyncio.sleep(min(5.0, 0.5 * attempt))


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    args = parse_args()
    client = BridgeClient(
        server_base_url=args.server_base_url,
        token=args.token,
        device_id=args.device_id,
        label=args.label,
    )
    await client.start()
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
