from __future__ import annotations

from fastapi import APIRouter, Request

from app.domain.settings import UserSettings

router = APIRouter(prefix="/api", tags=["settings"])


async def _get_session(request: Request, session_id: str | None):
    resolver = getattr(request.app.state, "resolve_session", None)
    if resolver is not None:
        return await resolver(session_id)
    return request.app.state.session_registry.get_or_create(
        session_id or "__local__",
        request.app.state.default_user_settings,
    )


@router.get("/settings", response_model=UserSettings)
async def get_settings(request: Request, session: str | None = None) -> UserSettings:
    return (await _get_session(request, session)).user_settings


@router.put("/settings", response_model=UserSettings)
async def update_settings(
    payload: UserSettings,
    request: Request,
    session: str | None = None,
) -> UserSettings:
    user_session = await _get_session(request, session)
    user_session.user_settings = payload.model_copy(deep=True)
    user_session.touch()
    await request.app.state.recompute_session(user_session)
    await request.app.state.ws_manager.broadcast_session(user_session)
    return user_session.user_settings
