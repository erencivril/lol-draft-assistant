from __future__ import annotations

from app.domain.draft import DraftState
from app.services.runtime_state import RuntimeState


def test_runtime_state_clears_draft_role_overrides_when_session_is_inactive() -> None:
    runtime = RuntimeState(
        draft_state=DraftState(session_status="active"),
        draft_role_overrides={("enemy", 6): "support"},
    )

    assert runtime.clear_draft_role_overrides_if_inactive() is False
    assert runtime.draft_role_overrides == {("enemy", 6): "support"}

    runtime.draft_state = DraftState(session_status="idle")

    assert runtime.clear_draft_role_overrides_if_inactive() is True
    assert runtime.draft_role_overrides == {}
