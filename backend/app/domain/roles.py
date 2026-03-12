from __future__ import annotations

ROLE_ORDER = ["top", "jungle", "middle", "bottom", "support"]
TEAMMATE_ROLE_ORDER = ["top", "jungle", "bottom", "support"]

ROLE_ALIASES = {
    "top": "top",
    "upper": "top",
    "jungle": "jungle",
    "middle": "middle",
    "mid": "middle",
    "center": "middle",
    "bottom": "bottom",
    "bot": "bottom",
    "adc": "bottom",
    "support": "support",
    "utility": "support",
    "sup": "support",
}


def normalize_role_name(value: str | None) -> str | None:
    if not value:
        return None
    return ROLE_ALIASES.get(value.strip().lower())
