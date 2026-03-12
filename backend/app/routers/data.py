from __future__ import annotations

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api", tags=["data"])


async def _get_session(request: Request, session_id: str | None):
    resolver = getattr(request.app.state, "resolve_session", None)
    if resolver is not None:
        return await resolver(session_id)
    return request.app.state.session_registry.get_or_create(
        session_id or "__local__",
        request.app.state.default_user_settings,
    )


@router.get("/tierlist")
async def get_tierlist(
    request: Request,
    role: str = Query(default="middle"),
    rank: str = Query(default="emerald"),
    region: str = Query(default="TR"),
):
    patch = await request.app.state.repository.latest_patch()
    if not patch:
        return []
    records = await request.app.state.repository.load_tier_stats(region=region, rank_tier=rank, role=role, patch=patch)
    champion_lookup = await request.app.state.repository.get_champion_lookup()
    return [
        {
            "champion_id": record.champion_id,
            "champion_name": champion_lookup.get(record.champion_id).name if champion_lookup.get(record.champion_id) else str(record.champion_id),
            "tier_grade": record.tier_grade,
            "win_rate": record.win_rate,
        }
        for record in sorted(records, key=lambda item: item.win_rate, reverse=True)[:20]
    ]


@router.get("/recommendations")
async def get_recommendations(request: Request, session: str | None = None):
    return (await _get_session(request, session)).runtime.recommendations
