from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.domain.draft import DraftState
from app.domain.recommendation import RecommendationBundle


@dataclass
class RuntimeState:
    lcu_connected: bool = False
    bridge_connected: bool = False
    source_device_id: str | None = None
    bridge_last_seen_at: str | None = None
    auto_region: str | None = None
    auto_rank_tier: str | None = None
    draft_state: DraftState = field(default_factory=DraftState)
    recommendations: RecommendationBundle = field(default_factory=RecommendationBundle)
    draft_role_overrides: dict[tuple[str, int], str] = field(default_factory=dict)

    def set_draft_role_override(self, *, team: str, cell_id: int, role: str | None) -> None:
        key = (team, cell_id)
        if role is None:
            self.draft_role_overrides.pop(key, None)
            return
        self.draft_role_overrides[key] = role

    def clear_draft_role_overrides(self) -> None:
        self.draft_role_overrides.clear()

    def clear_draft_role_overrides_if_inactive(self) -> bool:
        if self.draft_state.session_status == "active":
            return False
        if not self.draft_role_overrides:
            return False
        self.draft_role_overrides.clear()
        return True

    def mark_bridge_seen(self, *, device_id: str) -> None:
        self.bridge_connected = True
        self.source_device_id = device_id
        self.bridge_last_seen_at = datetime.now(UTC).isoformat()

    def clear_bridge(self) -> bool:
        changed = self.bridge_connected or self.source_device_id is not None or self.bridge_last_seen_at is not None
        self.bridge_connected = False
        self.source_device_id = None
        self.bridge_last_seen_at = None
        return changed

    def bridge_is_stale(self, *, timeout_seconds: int) -> bool:
        if not self.bridge_connected or not self.bridge_last_seen_at:
            return False
        try:
            last_seen = datetime.fromisoformat(self.bridge_last_seen_at)
        except ValueError:
            return True
        return datetime.now(UTC) - last_seen > timedelta(seconds=timeout_seconds)
