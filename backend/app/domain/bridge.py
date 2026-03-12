from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.draft import DraftState


class BridgeRegisterPayload(BaseModel):
    device_id: str
    label: str = ""


class BridgeHeartbeatPayload(BaseModel):
    device_id: str
    lcu_connected: bool = False
    auto_region: str | None = None
    auto_rank_tier: str | None = None
    client_patch: str | None = None
    queue_type: str | None = None


class BridgeDraftStatePayload(BaseModel):
    device_id: str
    lcu_connected: bool = False
    auto_region: str | None = None
    auto_rank_tier: str | None = None
    client_patch: str | None = None
    queue_type: str | None = None
    draft_state: DraftState = Field(default_factory=DraftState)


class BridgeRegisterResponse(BaseModel):
    device_id: str
    heartbeat_interval_seconds: int
    status: str = "registered"
