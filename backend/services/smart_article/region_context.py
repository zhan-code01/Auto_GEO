from __future__ import annotations

from backend.services.geo_evaluation_prompt_service import (
    CITY_REGION_EXPANSIONS,
    PROVINCE_REGION_EXPANSIONS,
)


def build_region_context(location: str) -> tuple[str, list[str], list[str]]:
    """Return a controlled region whitelist; never infer service coverage."""
    normalized = str(location or "").strip()
    if not normalized:
        return "", ["全国", "国内", "中国大陆"], []

    matched = None
    expansions: list[str] = []
    for name, values in CITY_REGION_EXPANSIONS.items():
        if name in normalized or name == normalized:
            matched, expansions = name, list(values)
            break
    if matched is None:
        for name, values in PROVINCE_REGION_EXPANSIONS.items():
            if name in normalized or name == normalized:
                matched, expansions = name, list(values)
                break

    if matched is None:
        expansions = [normalized, "全国"]

    # These are allowed expressions for questions and retrieval only.
    allowed = list(dict.fromkeys(expansions + (["国内", "中国大陆"] if "全国" in expansions else [])))
    all_regions = set(CITY_REGION_EXPANSIONS) | set(PROVINCE_REGION_EXPANSIONS)
    for values in CITY_REGION_EXPANSIONS.values():
        all_regions.update(values)
    for values in PROVINCE_REGION_EXPANSIONS.values():
        all_regions.update(values)
    blocked = sorted(all_regions - set(allowed))
    return matched or normalized, allowed, blocked


def detect_region(text: str, allowed_regions: list[str]) -> str | None:
    value = str(text or "")
    return next((region for region in allowed_regions if region and region in value), None)
