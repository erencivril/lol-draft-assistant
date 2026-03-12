from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.domain.draft import DraftRoleOverridePayload
from app.domain.recommendation import RecommendationPreviewResponse
from app.domain.settings import ResolvedFilters

router = APIRouter(prefix="/api/draft", tags=["draft"])


async def _get_session(request: Request, session_id: str | None):
    resolver = getattr(request.app.state, "resolve_session", None)
    if resolver is not None:
        return await resolver(session_id)
    return request.app.state.session_registry.get_or_create(
        session_id or "__local__",
        request.app.state.default_user_settings,
    )


@router.put("/overrides")
async def update_draft_overrides(
    payload: DraftRoleOverridePayload,
    request: Request,
    session: str | None = None,
):
    user_session = await _get_session(request, session)
    runtime = user_session.runtime
    if runtime.draft_state.session_status != "active":
        raise HTTPException(status_code=409, detail="Draft role overrides require an active champ select session.")

    for override in payload.overrides:
        runtime.set_draft_role_override(team=override.team, cell_id=override.cell_id, role=override.role)

    await request.app.state.recompute_session(user_session)
    await request.app.state.ws_manager.broadcast_session(user_session)
    return request.app.state.ws_manager.build_payload(runtime)


@router.post("/preview", response_model=RecommendationPreviewResponse)
async def preview_draft_recommendations(
    filters: ResolvedFilters,
    request: Request,
    session: str | None = None,
) -> RecommendationPreviewResponse:
    user_session = await _get_session(request, session)
    runtime = user_session.runtime
    recommendation_service = request.app.state.recommendation_service
    snapshot = await recommendation_service.analyze(
        runtime.draft_state,
        filters,
        user_session.user_settings,
        runtime.draft_role_overrides,
    )
    return RecommendationPreviewResponse(
        filters=ResolvedFilters(
            region=snapshot.recommendations.region or filters.region,
            rank_tier=snapshot.recommendations.rank_tier or filters.rank_tier,
            role=filters.role,
        ),
        recommendations=snapshot.recommendations,
    )
