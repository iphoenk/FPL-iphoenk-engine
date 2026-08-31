from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from src.utils import DATA, atomic_json, parse_dt, read_json

HEALTH_OUT = DATA / "framework_health_v4.json"
WEATHER_OUT = DATA / "weather_context_v4.json"
TACTICAL_OUT = DATA / "tactical_serving_v4.json"

_ALLOWED = {"PASS", "PARTIAL", "STALE", "UNAVAILABLE"}


def _decision_relevant_weather_health(weather: dict, required: bool) -> dict:
    """Evaluate tactical weather health only over fixtures still relevant to decisions.

    The weather collector intentionally retains recently completed fixtures for
    post-match reconciliation. Missing forecast evidence on those historical rows
    must remain visible, but it must not downgrade forward-looking tactical health.
    """
    generated_at = parse_dt(weather.get("generated_at")) or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    generated_at = generated_at.astimezone(timezone.utc)

    fixtures = [row for row in (weather.get("fixtures") or []) if isinstance(row, dict)]
    if not fixtures:
        raw_health = weather.get("health") or {}
        raw_status = str(raw_health.get("status") or "UNAVAILABLE").upper()
        status = raw_status if raw_status in _ALLOWED else "UNAVAILABLE"
        return {
            "status": status,
            "reason": raw_health.get("reason") or "NO_WEATHER_EVIDENCE",
            "tactical_context_completeness": "FULL" if status == "PASS" else "PARTIAL" if required else "OPTIONAL_PARTIAL",
            "decision_relevant_fixture_count": 0,
            "decision_relevant_available_count": 0,
            "decision_relevant_missing_count": 0,
            "retained_reconciliation_fixture_count": 0,
            "retained_reconciliation_available_count": 0,
            "retained_reconciliation_missing_count": 0,
        }

    decision_relevant: list[dict] = []
    retained: list[dict] = []
    for row in fixtures:
        kickoff = parse_dt(row.get("kickoff_time"))
        if kickoff is not None and kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=timezone.utc)
        if kickoff is not None and kickoff.astimezone(timezone.utc) >= generated_at and not bool(row.get("finished")):
            decision_relevant.append(row)
        else:
            retained.append(row)

    available = [row for row in decision_relevant if row.get("selected_evidence") is not None]
    missing = len(decision_relevant) - len(available)
    retained_available = sum(row.get("selected_evidence") is not None for row in retained)

    if not decision_relevant:
        status, reason = "PASS", "NO_DECISION_RELEVANT_FIXTURES_RETAINED_HISTORY_ONLY"
    elif not available:
        status = "UNAVAILABLE" if required else "PARTIAL"
        reason = "NO_DECISION_RELEVANT_WEATHER_EVIDENCE"
    else:
        kinds = {
            str(((row.get("selected_evidence") or {}).get("source_kind") or row.get("evidence_state") or ""))
            for row in available
        }
        if missing:
            status, reason = "PARTIAL", "SOME_DECISION_RELEVANT_FIXTURES_UNAVAILABLE"
        elif kinds == {"STALE_FORECAST"}:
            status, reason = "STALE", "ONLY_STALE_DECISION_RELEVANT_FORECAST_AVAILABLE"
        elif "STALE_FORECAST" in kinds:
            status, reason = "PARTIAL", "MIXED_FRESH_AND_STALE_DECISION_RELEVANT_EVIDENCE"
        else:
            status = "PASS"
            reason = (
                "DECISION_RELEVANT_WEATHER_COMPLETE_RETAINED_HISTORY_GAPS_VISIBLE"
                if retained and retained_available < len(retained)
                else "GOVERNED_DECISION_RELEVANT_WEATHER_EVIDENCE_AVAILABLE"
            )

    return {
        "status": status,
        "reason": reason,
        "tactical_context_completeness": "FULL" if status == "PASS" else "PARTIAL" if required else "OPTIONAL_PARTIAL",
        "decision_relevant_fixture_count": len(decision_relevant),
        "decision_relevant_available_count": len(available),
        "decision_relevant_missing_count": missing,
        "retained_reconciliation_fixture_count": len(retained),
        "retained_reconciliation_available_count": retained_available,
        "retained_reconciliation_missing_count": len(retained) - retained_available,
    }


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
    raw_status = raw_status if raw_status in _ALLOWED else "UNAVAILABLE"
    required = bool((weather.get("health") or {}).get("required_for_tactical_context", True))
    scoped = _decision_relevant_weather_health(weather, required)
    status = str(scoped["status"])
    completeness = str(scoped["tactical_context_completeness"])

    health["weather_context"] = {
        "status": status,
        "raw_collection_status": raw_status,
        "reason": scoped["reason"],
        "required_for_tactical_context": required,
        "tactical_context_completeness": completeness,
        "fixture_count": weather.get("fixture_count", 0),
        "available_count": weather.get("available_count", 0),
        "material_count": weather.get("material_count", 0),
        "decision_relevant_fixture_count": scoped["decision_relevant_fixture_count"],
        "decision_relevant_available_count": scoped["decision_relevant_available_count"],
        "decision_relevant_missing_count": scoped["decision_relevant_missing_count"],
        "retained_reconciliation_fixture_count": scoped["retained_reconciliation_fixture_count"],
        "retained_reconciliation_available_count": scoped["retained_reconciliation_available_count"],
        "retained_reconciliation_missing_count": scoped["retained_reconciliation_missing_count"],
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
        evidence["weather_collection_status"] = raw_status
        evidence["weather_context_required"] = required
        evidence["weather_tactical_context_completeness"] = completeness
        evidence["weather_decision_relevant_fixtures"] = scoped["decision_relevant_fixture_count"]
        evidence["weather_decision_relevant_available"] = scoped["decision_relevant_available_count"]
        evidence["weather_retained_reconciliation_fixtures"] = scoped["retained_reconciliation_fixture_count"]
        evidence["weather_retained_reconciliation_missing"] = scoped["retained_reconciliation_missing_count"]
        if required and status != "PASS" and tactical_cap.get("state") == "ACTIVE":
            tactical_cap["state"] = "STALE" if status == "STALE" else "PARTIAL"
    if capabilities:
        telemetry["summary"] = dict(Counter(
            row.get("state") for row in capabilities.values() if isinstance(row, dict)
        ))
        health["capability_telemetry"] = telemetry

    health.setdefault("governance", {}).update({
        "weather_health_truthful": True,
        "weather_decision_relevant_scope_separate_from_reconciliation_retention": True,
        "weather_retained_history_gaps_remain_visible": True,
        "weather_retained_history_gaps_do_not_downgrade_future_tactical_completeness": True,
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
