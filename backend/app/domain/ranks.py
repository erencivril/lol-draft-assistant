from __future__ import annotations

EXACT_RANKS = [
    "iron",
    "bronze",
    "silver",
    "gold",
    "platinum",
    "emerald",
    "diamond",
    "master",
    "grandmaster",
    "challenger",
]

OPTIONAL_AGGREGATE_RANKS = [
    "all",
    "gold_plus",
    "platinum_plus",
    "emerald_plus",
    "diamond_plus",
    "grandmaster_plus",
]

SUPPORTED_RANKS = EXACT_RANKS + OPTIONAL_AGGREGATE_RANKS
DEFAULT_SCRAPE_RANKS = EXACT_RANKS

RANK_DISPLAY_NAMES = {
    "all": "All Ranks",
    "gold_plus": "Gold+",
    "platinum_plus": "Platinum+",
    "emerald_plus": "Emerald+",
    "diamond_plus": "Diamond+",
    "grandmaster_plus": "Grandmaster+",
}

LEGACY_RANK_ALIASES = {
    "master_plus": "grandmaster_plus",
}


def normalize_rank_tier(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower().replace(" ", "_").replace("+", "_plus")
    normalized = LEGACY_RANK_ALIASES.get(normalized, normalized)
    return normalized if normalized in SUPPORTED_RANKS else normalized


def rank_display_name(rank_tier: str) -> str:
    normalized = normalize_rank_tier(rank_tier) or rank_tier
    return RANK_DISPLAY_NAMES.get(normalized, normalized.replace("_", " ").title())
