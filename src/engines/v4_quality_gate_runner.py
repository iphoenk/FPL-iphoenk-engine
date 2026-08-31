from __future__ import annotations

import json
from collections.abc import Callable

from src.engines import v4_quality_gate_core as core
from src.engines.reliability import validate_snapshot

FrameworkAssertion = Callable[[], tuple[dict, dict]]
OrchestrationAssertion = Callable[[dict], tuple[dict, list[dict]]]
PredictionAssertion = Callable[[dict], tuple[dict, dict]]


def run(
    *,
    assert_framework_health: FrameworkAssertion,
    assert_orchestration: OrchestrationAssertion,
    assert_prediction_and_validation: PredictionAssertion,
) -> dict:
    """Execute one quality-gate pipeline with explicit assertion dependencies.

    The runner owns orchestration only. Assertion implementations stay in either
    the canonical strict profile or the read-only baseline core. No module globals
    are monkey-patched and the decision/football semantics are untouched.
    """
    _pre, health = assert_framework_health()
    latest = core._load("latest.json")
    assert validate_snapshot(latest)["ok"]
    core._assert_version(
        latest,
        "latest",
        496,
        f"{core.RELEASE_VERSION}-official-first-reporting",
        field="engine_version",
    )
    assert latest.get("files", {}).get("effective_plan") == "data/effective_plan_v4.json"
    assert latest.get("files", {}).get("gw_scorecard") == "data/gw_scorecard_v4.json"

    official = latest.get("official_context") or {}
    assert official.get("official_fpl_first") is True
    assert official.get("source") == "raw_snapshot.official.bootstrap+fixtures"
    assert int(official.get("team_strength_rows_complete") or 0) == int(official.get("teams") or 0) > 0
    assert int(official.get("fixture_context_rows_complete") or 0) == int(official.get("upcoming_fixture_rows") or 0) > 0
    assert official.get("effective_ownership_available_from_official_fpl") is False
    assert (latest.get("meta") or {}).get("official_fpl_first_for_available_fields") is True

    baseline = latest.get("projection_baseline") or {}
    assert baseline.get("default_rule") == "PLANNING_GW_FROM_PREVIOUS_OFFICIAL_SUBMITTED_SQUAD"
    assert baseline.get("baseline_gw") == (latest.get("phase") or {}).get("submitted_gw")

    orchestration, services = assert_orchestration(latest)
    _lifecycle, _predictions = assert_prediction_and_validation(health)
    compliance = core._load("compliance_audit.json")
    assert compliance.get("overall") == "PASS"
    _wc, _packages, _lineup, pipeline = core._assert_engine_advisory(latest)
    core._assert_effective_plan(latest)
    _scorecard, checkpoint = core._assert_scorecard_and_report(latest)

    assert core.RELEASE_VERSION == "4.9.6"
    result = {
        "status": "PASS",
        "release": core.RELEASE_VERSION,
        "services": len(services),
        "pipeline_health": health.get("pipeline_health"),
        "prediction_health": health.get("prediction_health"),
        "capability_health": health.get("capability_health"),
        "decision_engine": health.get("decision_engine"),
        "gate0": health.get("gate0", {}).get("counts"),
        "orchestration_ms": orchestration.get("duration_ms"),
        "decision_compute_ms": (pipeline.get("performance_slo") or {}).get("actual_ms"),
        "checkpoint": (checkpoint.get("checkpoint_context") or {}).get("policy_id"),
        "recommendation_allowed": health.get("recommendation_allowed"),
        "go_allowed": health.get("go_allowed"),
    }
    print(json.dumps(result, separators=(",", ":")))
    return result
