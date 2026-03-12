from __future__ import annotations

import asyncio

import aiohttp
import pytest

from app.domain.draft import DraftState
from app.services.lcu_connector import LcuSnapshot
from bridge.bridge_client import BridgeClient


class _FakeResponse:
    def __init__(self, *, status: int = 200) -> None:
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.status < 400:
            return
        raise aiohttp.ClientResponseError(
            request_info=None,
            history=(),
            status=self.status,
            message="error",
            headers=None,
        )


class _FakeSession:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, url: str, **_: object):
        self.calls.append((method, url))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            return _FakeErrorContext(outcome)
        return outcome

    def delete(self, *_args: object, **_kwargs: object):
        return _FakeResponse()

    async def close(self) -> None:
        return None


class _FakeErrorContext:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def __aenter__(self):
        raise self.exc

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeConnector:
    def __init__(self) -> None:
        self.started = False

    async def start(self, _callback) -> None:
        self.started = True

    async def stop(self) -> None:
        return None


@pytest.mark.asyncio
async def test_bridge_start_retries_until_register_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession(
        [
            asyncio.TimeoutError(),
            asyncio.TimeoutError(),
            _FakeResponse(),
        ]
    )
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr("bridge.bridge_client.aiohttp.ClientSession", lambda *args, **kwargs: session)
    monkeypatch.setattr("bridge.bridge_client.asyncio.sleep", fake_sleep)

    client = BridgeClient(
        server_base_url="http://example.test",
        token="token",
        device_id="device",
        label="label",
    )
    client.connector = _FakeConnector()

    await client.start()

    assert client._registered is True
    assert client.connector.started is True
    assert session.calls == [
        ("POST", "http://example.test/api/bridge/register"),
        ("POST", "http://example.test/api/bridge/register"),
        ("POST", "http://example.test/api/bridge/register"),
    ]
    assert 5 in waits


@pytest.mark.asyncio
async def test_bridge_on_update_uses_put_for_draft_state() -> None:
    calls: list[tuple[str, str, dict]] = []
    client = BridgeClient(
        server_base_url="http://example.test",
        token="token",
        device_id="device",
        label="label",
    )
    client._session = object()  # mark session as available
    client._registered = True

    async def fake_post(path: str, payload: dict, *, attempts: int = 6) -> None:
        calls.append(("POST", path, payload))

    async def fake_request(method: str, path: str, payload: dict, *, attempts: int = 6) -> None:
        calls.append((method, path, payload))

    client._post = fake_post  # type: ignore[method-assign]
    client._request = fake_request  # type: ignore[method-assign]

    await client._on_update(
        LcuSnapshot(
            draft_state=DraftState(),
            auto_region="TR",
            auto_rank_tier="gold",
            connected=True,
        )
    )

    assert calls == [
        ("POST", "/api/bridge/heartbeat", {
            "device_id": "device",
            "lcu_connected": True,
            "auto_region": "TR",
            "auto_rank_tier": "gold",
            "client_patch": None,
            "queue_type": None,
        }),
        ("PUT", "/api/bridge/draft-state", {
            "device_id": "device",
            "lcu_connected": True,
            "auto_region": "TR",
            "auto_rank_tier": "gold",
            "client_patch": None,
            "queue_type": None,
            "draft_state": DraftState().model_dump(mode="json"),
        }),
    ]
