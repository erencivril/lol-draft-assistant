from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from app.domain.draft import DraftState
from app.domain.settings import UserSettings

from .runtime_state import RuntimeState

DEFAULT_SESSION_ID = "__local__"


def normalize_session_id(session_id: str | None) -> str:
    value = (session_id or "").strip()
    return value or DEFAULT_SESSION_ID


@dataclass(slots=True)
class UserSession:
    session_id: str
    runtime: RuntimeState = field(default_factory=RuntimeState)
    user_settings: UserSettings = field(default_factory=UserSettings)
    last_active_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def touch(self) -> None:
        self.last_active_at = datetime.now(UTC)


class SessionRegistry:
    def __init__(self) -> None:
        self.sessions: dict[str, UserSession] = {}

    def get_or_create(self, session_id: str, default_settings: UserSettings) -> UserSession:
        normalized_session_id = normalize_session_id(session_id)
        session = self.sessions.get(normalized_session_id)
        if session is None:
            session = UserSession(
                session_id=normalized_session_id,
                user_settings=default_settings.model_copy(deep=True),
            )
            self.sessions[normalized_session_id] = session
        session.touch()
        return session

    def get(self, session_id: str) -> UserSession | None:
        return self.sessions.get(normalize_session_id(session_id))

    def expire_stale(self, timeout_seconds: int) -> list[str]:
        cutoff = datetime.now(UTC) - timedelta(seconds=timeout_seconds)
        expired = [
            session_id
            for session_id, session in self.sessions.items()
            if session.last_active_at < cutoff
        ]
        for session_id in expired:
            self.sessions.pop(session_id, None)
        return expired

    def remove(self, session_id: str) -> None:
        self.sessions.pop(normalize_session_id(session_id), None)


def hydrate_session_from_bridge_record(session: UserSession, bridge_record) -> UserSession:
    runtime = session.runtime
    runtime.bridge_connected = bridge_record.connected
    runtime.source_device_id = bridge_record.device_id
    runtime.bridge_last_seen_at = bridge_record.last_seen_at or runtime.bridge_last_seen_at
    runtime.auto_region = bridge_record.auto_region or runtime.auto_region
    runtime.auto_rank_tier = bridge_record.auto_rank_tier or runtime.auto_rank_tier
    if bridge_record.draft_state_json:
        try:
            runtime.draft_state = DraftState.model_validate_json(bridge_record.draft_state_json)
        except (ValidationError, ValueError):
            pass
    session.touch()
    return session


async def resolve_effective_session(
    *,
    requested_session: str | None,
    registry: SessionRegistry,
    default_settings: UserSettings,
    repository,
) -> UserSession:
    explicit_session = requested_session is not None and requested_session.strip() != ""
    normalized_requested = normalize_session_id(requested_session)

    if explicit_session:
        session = registry.get_or_create(normalized_requested, default_settings)
        if normalized_requested != DEFAULT_SESSION_ID and not (session.runtime.bridge_connected or session.runtime.lcu_connected):
            bridge_record = await repository.get_bridge_session(device_id=normalized_requested)
            if bridge_record is not None:
                hydrate_session_from_bridge_record(session, bridge_record)
        return session

    local_session = registry.get_or_create(DEFAULT_SESSION_ID, default_settings)
    if local_session.runtime.lcu_connected or local_session.runtime.bridge_connected:
        return local_session

    latest_bridge = await repository.latest_bridge_session()
    if latest_bridge is not None:
        bridge_session = registry.get_or_create(latest_bridge.device_id, default_settings)
        return hydrate_session_from_bridge_record(bridge_session, latest_bridge)

    return local_session
