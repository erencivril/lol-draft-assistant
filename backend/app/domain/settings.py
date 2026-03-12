from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.domain.roles import normalize_role_name
from app.domain.ranks import normalize_rank_tier


class RecommendationWeights(BaseModel):
    counter: float = 0.35
    synergy: float = 0.25
    tier: float = 0.25
    role_fit: float = 0.15


class UserSettings(BaseModel):
    region_mode: Literal["auto", "manual"] = "auto"
    rank_mode: Literal["auto", "manual"] = "auto"
    role_mode: Literal["auto", "manual"] = "auto"
    region_override: str = "TR"
    rank_override: str = "emerald"
    role_override: str = "middle"
    auto_refresh: bool = True
    top_n: int = 4
    weights: RecommendationWeights = Field(default_factory=RecommendationWeights)

    @field_validator("rank_override", mode="before")
    @classmethod
    def normalize_rank_override(cls, value: str | None) -> str:
        return normalize_rank_tier(value) or "emerald"

    @field_validator("role_override", mode="before")
    @classmethod
    def normalize_role_override(cls, value: str | None) -> str:
        return normalize_role_name(value) or "middle"


class ResolvedFilters(BaseModel):
    region: str
    rank_tier: str
    role: str | None = None

    @field_validator("rank_tier", mode="before")
    @classmethod
    def normalize_rank_tier_value(cls, value: str | None) -> str:
        return normalize_rank_tier(value) or "emerald"

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role_value(cls, value: str | None) -> str | None:
        return normalize_role_name(value)
