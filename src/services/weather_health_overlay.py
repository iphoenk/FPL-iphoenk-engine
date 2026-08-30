from __future__ import annotations

from collections import Counter

from src.utils import DATA, atomic_json, read_json

HEALTH_OUT = DATA / "framework_health_v4.json"
WEATHER_OUT = DATA / "weather_context_v4.json"
TACTICAL_OUT = DATA / "tactical_serving_v4.json"

_ALLOWED = {"PASS", "PARTIAL", "STALE", "UNAVAILABLE"}


def apply_weather_health(
    health: dict | None = None,
    *,
    weather: dict | None = None,
    tactical: dict | None = None,
    write: bool = True,
) -> dict:
    health = health if health is not None else read_json(HEALTH_OUT, {})
    weather = weather if weather is not None else read_json(WEATHER_OUT, {})
    tactical = tactical if tactical is not None else read_json(TACTICAL_OUT, {})

    raw_status = str((weather.get("health") or {}).get("status") or "UNAVAILABLE").upper()
    status = raw_status if raw_status in _ALLOWED else "UNAVAILABLE"
    required = bool((weather.get("health") or {}).get("required_for_tactical_context", True))
    completeness = (weather.get("health") or {}).get("tactical_context_completeness") or (
        "FULL" if status == "PASS" else "PARTIAL"
    )
    health["weather_context"] = {
        "status": status,
        "reason": (weather.get("health") or {}).get("reason") or "WEATHER_EVIDENCE_NOT_AVAILABLE",
        "required_for_tactical_context": required,
        "tactical_context_completeness": completeness,
        "fixture_count": weather.get("fixture_count", 0),
        "available_count": weather.get("available_count", 0),
        "material_count": weather.get("material_count", 0),
        "evidence_precedence": weather.get("evidence_precedence") or [],
        "advisory_only": (weather.get("governance") or {}).get("advisory_only", True),
        "expected_xpts_mean_adjustment": 0.0,
    }

    telemetry = health.get("capability_telemetry") or {}
    capabilities = telemetry.get("capabilities") or {}
    tactical_cap = capabilities.get("Tactical Matchup")
    if isinstance(tactical_cap, dict):
        evidence = tactical_cap.setdefault("evidence", {})
        evidence["weather_context_status"] = status
        evidence["weather_context_required"] = required
        evidence["weather_tactical_context_completeness"] = completeness
        if required and status != "PASS" and tactical_cap.get("state") == "ACTIVE":
            tactical_cap["state"] = "STALE" if status == "STALE" else "PARTIAL"
    if capabilities:
        telemetry["summary"] = dict(Counter(
            row.get("state") for row in capabilities.values() if isinstance(row, dict)
        ))
        health["capability_telemetry"] = telemetry

    health.setdefault("governance", {}).update({
        "weather_health_truthful": True,
        "weather_unavailable_downgrades_tactical_context_completeness": True,
        "weather_unavailable_does_not_fabricate_core_failure": True,
        "weather_expected_xpts_mean_adjustment": 0.0,
        "weather_numeric_coefficient_forbidden_until_calibrated": True,
    })
    health.setdefault("pipeline_components", {})["Weather Context"] = status
    if write:
        atomic_json(HEALTH_OUT, health)
    return health


if __name__ == "__main__":
    apply_weather_health()
