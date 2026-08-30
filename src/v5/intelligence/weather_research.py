from __future__ import annotations

from collections import Counter
from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/intelligence/weather_context.json"
RESEARCH_STATES = (
    "INSUFFICIENT_SAMPLE",
    "EXPLORATORY",
    "CALIBRATING",
    "VALIDATED_CANDIDATE",
    "REJECTED_SIGNAL",
)


def _cfg() -> dict[str, Any]:
    return load_json_config(CONFIG)


def retain_observed_effects(raw: dict[str, Any] | None) -> dict[str, Any]:
    cfg = _cfg()
    allowed = set((cfg.get("research") or {}).get("observed_match_effects") or [])
    if not isinstance(raw, dict):
        return {}
    retained: dict[str, Any] = {}
    for key in allowed:
        value = raw.get(key)
        if not isinstance(value, dict):
            continue
        reliability = str(value.get("reliability") or value.get("confidence") or "").upper()
        if reliability not in {"RELIABLE", "VERIFIED", "HIGH"}:
            continue
        retained[key] = {
            "value": value.get("value"),
            "source": value.get("source"),
            "timestamp": value.get("timestamp"),
            "reliability": reliability,
            "attribution": "POSSIBLE_CONTRIBUTING_FACTOR",
        }
    return retained


def sustainability_record(raw: dict[str, Any] | None) -> dict[str, Any]:
    row = raw if isinstance(raw, dict) else {}
    return {
        "actual_fpl_return": row.get("actual_fpl_return"),
        "opportunity_quality": row.get("opportunity_quality"),
        "weather_associated_event": row.get("weather_associated_event"),
        "future_repeatability": row.get("future_repeatability"),
        "governance": {
            "observed_return_is_not_sustainable_rate": True,
            "weather_associated_event_is_not_causal_proof": True,
            "opponent_slip_goal_does_not_raise_attacking_rate_by_itself": True,
        },
    }


def matched_cohort_evidence(records: list[dict[str, Any]] | None) -> dict[str, Any]:
    rows = [row for row in records or [] if isinstance(row, dict)]
    weather_rows = [row for row in rows if bool(row.get("weather_exposed"))]
    controls = [row for row in rows if bool(row.get("matched_non_weather_control"))]
    venues = {str(row.get("venue")) for row in weather_rows if row.get("venue")}
    gameweeks = {str(row.get("gameweek")) for row in weather_rows if row.get("gameweek") is not None}
    return {
        "weather_matches": len(weather_rows),
        "matched_controls": len(controls),
        "distinct_venues": len(venues),
        "distinct_gameweeks": len(gameweeks),
        "matched_baseline_required": True,
        "confounders_present": Counter(
            key
            for row in rows
            for key, value in (row.get("confounders") or {}).items()
            if value not in (None, False, "", 0)
        ),
    }


def research_state(
    cohort: dict[str, Any],
    validation: dict[str, Any] | None = None,
) -> str:
    cfg = _cfg()
    thresholds = ((cfg.get("research") or {}).get("validation") or {})
    validation = validation if isinstance(validation, dict) else {}
    sample_sufficient = (
        int(cohort.get("weather_matches") or 0) >= int(thresholds.get("minimum_weather_matches") or 0)
        and int(cohort.get("matched_controls") or 0) >= int(thresholds.get("minimum_matched_controls") or 0)
        and int(cohort.get("distinct_venues") or 0) >= int(thresholds.get("minimum_distinct_venues") or 0)
        and int(cohort.get("distinct_gameweeks") or 0) >= int(thresholds.get("minimum_distinct_gameweeks") or 0)
    )
    if not sample_sufficient:
        return "INSUFFICIENT_SAMPLE"
    if validation.get("rejected_signal") is True:
        return "REJECTED_SIGNAL"
    requirements = {
        "repeatability": bool(validation.get("repeatability")),
        "out_of_sample_validation": bool(validation.get("out_of_sample_validation")),
        "calibration_improvement": bool(validation.get("calibration_improvement")),
        "non_regression": bool(validation.get("non_regression")),
    }
    if all(requirements.values()):
        return "VALIDATED_CANDIDATE"
    if any(requirements.values()):
        return "CALIBRATING"
    return "EXPLORATORY"


def promotion_gate(state: str, validation: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = _cfg()
    governance = cfg.get("governance") or {}
    validation = validation if isinstance(validation, dict) else {}
    checks = {
        "validated_candidate": state == "VALIDATED_CANDIDATE",
        "repeatability": bool(validation.get("repeatability")),
        "out_of_sample_validation": bool(validation.get("out_of_sample_validation")),
        "calibration_improvement": bool(validation.get("calibration_improvement")),
        "non_regression": bool(validation.get("non_regression")),
        "explicit_governance_authorization": bool(governance.get("promotion_authorized")),
    }
    return {
        "eligible": all(checks.values()),
        "checks": checks,
        "current_authority": "SHADOW_ADVISORY_ONLY",
        "v3_v4_quantitative_consumption_allowed": False if not all(checks.values()) else True,
    }


def build_weather_research(
    fixtures: list[dict[str, Any]] | None,
    *,
    cohort_records: list[dict[str, Any]] | None = None,
    validation_by_signal: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cfg = _cfg()
    research_cfg = cfg.get("research") or {}
    cohort = matched_cohort_evidence(cohort_records)
    validation_by_signal = validation_by_signal if isinstance(validation_by_signal, dict) else {}
    candidate_signals: dict[str, Any] = {}
    states: list[str] = []
    for signal in research_cfg.get("candidate_signals") or []:
        validation = validation_by_signal.get(str(signal)) or {}
        state = research_state(cohort, validation)
        states.append(state)
        candidate_signals[str(signal)] = {
            "state": state,
            "quantitative_modifier": None,
            "validation": validation,
            "promotion_gate": promotion_gate(state, validation),
        }
    aggregate = "INSUFFICIENT_SAMPLE"
    for state in ("REJECTED_SIGNAL", "VALIDATED_CANDIDATE", "CALIBRATING", "EXPLORATORY"):
        if state in states:
            aggregate = state
            break
    observed = {}
    sustainability = {}
    for fixture in fixtures or []:
        if not isinstance(fixture, dict):
            continue
        fixture_id = str(fixture.get("fixture_id") or "")
        if not fixture_id:
            continue
        effects = retain_observed_effects(fixture.get("observed_match_effects"))
        if effects:
            observed[fixture_id] = effects
        sustainability_raw = fixture.get("sustainability")
        if isinstance(sustainability_raw, dict):
            sustainability[fixture_id] = sustainability_record(sustainability_raw)
    return {
        "contract": "V5_WEATHER_SHADOW_RESEARCH_V1",
        "mode": "SHADOW_ADVISORY_ONLY",
        "state": aggregate,
        "observed_match_effects": observed,
        "sustainability": sustainability,
        "interactions": list(research_cfg.get("interactions") or []),
        "confounders": list(research_cfg.get("confounders") or []),
        "matched_cohort_evidence": cohort,
        "candidate_signals": candidate_signals,
        "governance": {
            "attribution_label": "POSSIBLE_CONTRIBUTING_FACTOR",
            "weather_caused_forbidden_without_validated_causal_evidence": True,
            "no_quantitative_signal_is_consumed_by_v5_decisions": True,
            "promotion_to_v3_v4_requires_validation_and_explicit_authorization": True,
        },
    }
