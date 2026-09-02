from __future__ import annotations

from src.sources.base import SourceResult, SourceSpec
from src.utils import DATA, read_json


def probe(spec: SourceSpec, timeout_seconds: float) -> SourceResult:
    """Project the governed Understat artifact into source-health semantics.

    Network ownership remains with the tactical-context capability. This probe is
    deliberately artifact-only so source-layer health never creates a second
    fetch path or N×player request pattern.
    """
    payload = read_json(DATA / "understat_tactical_v3.json", {})
    source = payload.get("source") if isinstance(payload, dict) else {}
    health = payload.get("health") if isinstance(payload, dict) else {}
    source = source if isinstance(source, dict) else {}
    health = health if isinstance(health, dict) else {}

    availability = str(source.get("availability") or "UNAVAILABLE").upper()
    freshness = str(source.get("freshness") or "UNAVAILABLE").upper()
    schema_valid = source.get("schema_valid") is True
    usable = int(health.get("tactical_matchup_usable_count") or 0)

    if availability == "AVAILABLE" and schema_valid and freshness == "FRESH":
        status = "LIVE"
        state = "AVAILABLE"
        reachable = True
    elif availability in {"AVAILABLE", "STALE_FALLBACK"} and schema_valid:
        status = "PARTIAL"
        state = "STALE" if freshness in {"STALE", "EXPIRED"} or availability == "STALE_FALLBACK" else "AVAILABLE"
        reachable = True
    else:
        status = "UNAVAILABLE"
        state = "UNAVAILABLE"
        reachable = False

    capabilities = {capability: state for capability in spec.capabilities}
    return SourceResult(
        source_id=spec.source_id,
        status=status,
        reachable=reachable,
        latency_ms=None,
        observation_count=usable,
        capabilities=capabilities,
        detail={
            "adapter": "understat_artifact",
            "network_fetch_performed": False,
            "availability": availability,
            "freshness": freshness,
            "fetched_at": source.get("fetched_at"),
            "latest_match_covered": source.get("latest_match_covered"),
            "schema_valid": schema_valid,
            "fallback": bool(source.get("fallback")),
            "cache_age_minutes": source.get("cache_age_minutes"),
            "player_mapping_coverage": health.get("player_mapping_coverage"),
            "tactical_matchup_coverage": health.get("tactical_matchup_coverage"),
            "degradation_reason": health.get("degradation_reason"),
            "optional_enrichment": True,
        },
    )
