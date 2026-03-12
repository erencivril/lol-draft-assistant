from __future__ import annotations

import pytest

from app.config import Settings
from app.providers.lolalytics_provider import LolalyticsBrowserSession


@pytest.mark.asyncio
async def test_with_retry_succeeds_on_second_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    session = LolalyticsBrowserSession(Settings())
    attempts = 0
    waits: list[int] = []

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary failure")
        return "ok"

    async def fake_sleep(seconds: int) -> None:
        waits.append(seconds)

    monkeypatch.setattr("app.providers.lolalytics_provider.asyncio.sleep", fake_sleep)

    result = await session._with_retry(operation, "https://example.test/tier")

    assert result == "ok"
    assert attempts == 2
    assert waits == [1]


@pytest.mark.asyncio
async def test_with_retry_raises_after_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    session = LolalyticsBrowserSession(Settings())
    attempts = 0

    async def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("still failing")

    async def fake_sleep(_: int) -> None:
        return None

    monkeypatch.setattr("app.providers.lolalytics_provider.asyncio.sleep", fake_sleep)

    with pytest.raises(RuntimeError, match="still failing"):
        await session._with_retry(operation, "https://example.test/build", max_retries=2)

    assert attempts == 2
