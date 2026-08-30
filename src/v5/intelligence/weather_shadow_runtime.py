from __future__ import annotations

from typing import Any

from src.v5.intelligence.weather_advisory import assert_advisory_governance, build_weather_shadow_evidence


def enrich_weather_shadow(evidence_bundle: dict[str, Any] | None) -> dict[str, Any]:
    """Runtime enrichment boundary for V5 weather research. Never mutates production decisions."""
    assert_advisory_governance()
    bundle = evidence_bundle if isinstance(evidence_bundle, dict) else {}
    result = build_weather_shadow_evidence(
        snapshots=bundle.get("snapshots"),
        observed_effects=bundle.get("observed_match_effects"),
        interactions=bundle.get("interactions"),
        confounders=bundle.get("confounders"),
        calibration=bundle.get("calibration"),
    )
    return {
        "capability": "weather_shadow_research",
        "runtime_state": "ACTIVE",
        "Weather Context": result["weather_context"]["health"],
        "research_state": result["research_state"],
        "evidence": result,
        "decision_authority": "ZERO",
        "decision_mutations": {},
    }
