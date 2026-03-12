from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field
from app.domain.settings import ResolvedFilters


class RecommendationScoreComponent(BaseModel):
    key: str
    label: str
    value: float
    weight: float
    contribution: float
    note: str | None = None


class RecommendationRelationDetail(BaseModel):
    kind: Literal["counter", "synergy", "threat", "enemy_synergy"]
    champion_id: int
    champion_name: str
    role: str | None = None
    normalized_score: float
    sample_confidence: float = 1.0
    signed_edge: float = 0.0
    shrinkage_weight: float = 1.0
    net_contribution: float = 0.0
    match_role_source: Literal["lcu", "manual", "inferred", "unknown"] = "unknown"
    metric_label: str
    metric_value: float
    win_rate: float
    games: int
    summary: str


class RecommendationExplanation(BaseModel):
    summary: str = ""
    scenario_summary: str = ""
    scoring: list[RecommendationScoreComponent] = Field(default_factory=list)
    counters: list[RecommendationRelationDetail] = Field(default_factory=list)
    synergies: list[RecommendationRelationDetail] = Field(default_factory=list)
    penalties: list[str] = Field(default_factory=list)


class RecommendationItem(BaseModel):
    champion_id: int
    champion_name: str
    suggested_role: str
    total_score: float
    display_band: Literal["elite", "strong", "situational", "risky"] = "situational"
    counter_score: float
    synergy_score: float
    tier_score: float
    role_fit_score: float
    matchup_coverage: float = 0.0
    synergy_coverage: float = 0.0
    evidence_score: float = 0.0
    role_certainty: float = 1.0
    sample_confidence: float = 1.0
    thin_evidence: bool = False
    confidence: float
    reasons: list[str] = Field(default_factory=list)
    explanation: RecommendationExplanation = Field(default_factory=RecommendationExplanation)


class RecommendationBundle(BaseModel):
    picks: list[RecommendationItem] = Field(default_factory=list)
    bans: list[RecommendationItem] = Field(default_factory=list)
    region: str | None = None
    rank_tier: str | None = None
    patch: str | None = None
    active_patch_generation: str | None = None
    exact_data_available: bool = False
    patch_trusted: bool = True
    scope_complete: bool = True
    scope_ready: bool = False
    scope_last_synced_at: str | None = None
    scope_freshness: str = "unknown"
    fallback_used_recently: bool = False
    warnings: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RecommendationPreviewResponse(BaseModel):
    filters: ResolvedFilters
    recommendations: RecommendationBundle
