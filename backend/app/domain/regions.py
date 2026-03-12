from __future__ import annotations

SUPPORTED_REGIONS = ["BR", "EUNE", "EUW", "JP", "KR", "NA", "OCE", "RU", "TR"]


def normalize_region(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().upper()
    return normalized if normalized in SUPPORTED_REGIONS else normalized
