from __future__ import annotations

from src.sources.base import SourceResult, SourceSpec
from src.sources.public_web import probe_public_web


def probe(spec: SourceSpec, timeout_seconds: float = 2.5) -> SourceResult:
    result = probe_public_web(spec, timeout_seconds)
    if not result.reachable:
        return result
    capabilities = dict(result.capabilities)
    for key in capabilities:
        capabilities[key] = "SOURCE_REACHABLE_NOT_INGESTED"
    if "box_shot_location_proxy" in capabilities:
        capabilities["box_shot_location_proxy"] = "PROXY_AVAILABLE_NOT_INGESTED"
    detail = dict(result.detail)
    detail.update({
        "governance": {
            "shot_coordinates_can_support_box_shot_location_proxy": True,
            "actual_box_touches_are_not_claimed": True,
            "key_pass_context_requires_structured_ingestion": True,
        },
        "recommended_cadence": spec.config.get("cadence") or "daily_or_post_match",
    })
    return SourceResult(
        result.source_id,
        result.status,
        result.reachable,
        result.latency_ms,
        0,
        capabilities,
        detail,
    )
