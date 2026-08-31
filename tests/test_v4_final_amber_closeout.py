from __future__ import annotations

from src.services.governance_service import (
    _align_prediction_telemetry_maturity,
    _normalize_health_maturity_semantics,
)
from src.services.weather_health_overlay import apply_weather_health


def _maturity(**overrides):
    out = {
        "overall": "GREEN",
        "pipeline_health": "GREEN",
        "critical_failed": [],
        "critical_partial": [],
        "critical_warmup": ["DSS-44", "DSS-X12"],
        "capability_coverage": {
            "active": 72,
            "warmup": 2,
            "partial": 0,
            "failed": 0,
            "declared": 74,
        },
        "gate0": {"pass": True, "counts": {"PASS": 16, "FAIL": 0}},
        "governance": {},
    }
    out.update(overrides)
    return out


def _readiness(**overrides):
    out = {
        "status": "PASS",
        "stage": "PREDEADLINE_READY",
        "pending": ["gw_finish", "post_gw_reconciliation"],
        "blockers": [],
    }
    out.update(overrides)
    return out


def test_expected_warmup_is_green_operationally_but_stays_provisional_and_blocks_go():
    out = _normalize_health_maturity_semantics(_maturity(), _readiness())
    assert out["prediction_health"] == "GREEN"
    assert out["capability_health"] == "GREEN"
    assert out["capability_maturity"] == "WARMUP"
    assert out["decision_engine"] == "PROVISIONAL"
    assert out["go_allowed"] is False
    assert out["critical_warmup"] == ["DSS-44", "DSS-X12"]
    assert out["capability_coverage"]["active"] == 72
    assert out["capability_coverage"]["warmup"] == 2


def test_critical_partial_and_failure_remain_fail_closed():
    partial = _normalize_health_maturity_semantics(
        _maturity(critical_partial=["DSS-09"], critical_warmup=[]),
        _readiness(),
    )
    assert partial["prediction_health"] == "AMBER"
    assert partial["decision_engine"] == "DEGRADED"
    assert partial["go_allowed"] is False

    failed = _normalize_health_maturity_semantics(
        _maturity(
            critical_failed=["DSS-01"],
            critical_warmup=[],
            capability_coverage={"active": 73, "warmup": 0, "partial": 0, "failed": 1, "declared": 74},
        ),
        _readiness(),
    )
    assert failed["prediction_health"] == "RED"
    assert failed["capability_health"] == "RED"
    assert failed["decision_engine"] == "BLOCKED"
    assert failed["go_allowed"] is False


def test_unexpected_warmup_is_not_false_green_prediction_health():
    out = _normalize_health_maturity_semantics(
        _maturity(critical_warmup=["DSS-44", "DSS-X12", "DSS-99"]),
        _readiness(),
    )
    assert out["prediction_health"] == "AMBER"
    assert out["decision_engine"] == "PROVISIONAL"
    assert out["go_allowed"] is False


def test_prediction_telemetry_preserves_provisional_as_warmup_not_active():
    maturity = _normalize_health_maturity_semantics(_maturity(), _readiness())
    maturity["capability_telemetry"] = {
        "capabilities": {
            "Prediction": {"state": "ACTIVE", "evidence": {"players": 626}},
            "Official Truth": {"state": "ACTIVE", "evidence": {}},
        },
        "summary": {"ACTIVE": 2},
    }
    out = _align_prediction_telemetry_maturity(maturity)
    prediction = out["capability_telemetry"]["capabilities"]["Prediction"]
    assert prediction["state"] == "WARMUP"
    assert prediction["evidence"]["prediction_health"] == "GREEN"
    assert prediction["evidence"]["decision_engine"] == "PROVISIONAL"
    assert out["capability_telemetry"]["summary"] == {"WARMUP": 1, "ACTIVE": 1}


def _health_for_weather():
    return {
        "pipeline_health": "GREEN",
        "capability_telemetry": {
            "capabilities": {
                "Tactical Matchup": {"state": "ACTIVE", "evidence": {"owned": 15, "watchlist": 20}},
                "Prediction": {"state": "WARMUP", "evidence": {}},
            },
            "summary": {"ACTIVE": 1, "WARMUP": 1},
        },
        "governance": {},
    }


def test_retained_historical_weather_gap_does_not_downgrade_future_tactical_health():
    weather = {
        "generated_at": "2026-08-31T12:00:00+00:00",
        "health": {
            "status": "PARTIAL",
            "reason": "SOME_FIXTURES_UNAVAILABLE",
            "required_for_tactical_context": True,
            "tactical_context_completeness": "PARTIAL",
        },
        "fixture_count": 2,
        "available_count": 1,
        "fixtures": [
            {
                "fixture_id": 1,
                "kickoff_time": "2026-08-30T15:00:00+00:00",
                "finished": True,
                "selected_evidence": None,
                "evidence_state": "UNAVAILABLE",
            },
            {
                "fixture_id": 2,
                "kickoff_time": "2026-09-01T15:00:00+00:00",
                "finished": False,
                "selected_evidence": {"source_kind": "FRESH_FORECAST", "weather": {"temperature_c": 18}},
                "evidence_state": "FRESH_FORECAST",
            },
        ],
        "governance": {"advisory_only": True},
    }
    out = apply_weather_health(_health_for_weather(), weather=weather, tactical={}, write=False)
    assert out["weather_context"]["status"] == "PASS"
    assert out["weather_context"]["raw_collection_status"] == "PARTIAL"
    assert out["weather_context"]["tactical_context_completeness"] == "FULL"
    assert out["weather_context"]["decision_relevant_fixture_count"] == 1
    assert out["weather_context"]["decision_relevant_available_count"] == 1
    assert out["weather_context"]["retained_reconciliation_fixture_count"] == 1
    assert out["weather_context"]["retained_reconciliation_missing_count"] == 1
    assert out["capability_telemetry"]["capabilities"]["Tactical Matchup"]["state"] == "ACTIVE"


def test_missing_future_weather_still_downgrades_tactical_health():
    weather = {
        "generated_at": "2026-08-31T12:00:00+00:00",
        "health": {"status": "PARTIAL", "required_for_tactical_context": True},
        "fixture_count": 2,
        "available_count": 1,
        "fixtures": [
            {
                "fixture_id": 2,
                "kickoff_time": "2026-09-01T15:00:00+00:00",
                "finished": False,
                "selected_evidence": {"source_kind": "FRESH_FORECAST", "weather": {"temperature_c": 18}},
            },
            {
                "fixture_id": 3,
                "kickoff_time": "2026-09-02T15:00:00+00:00",
                "finished": False,
                "selected_evidence": None,
            },
        ],
        "governance": {"advisory_only": True},
    }
    out = apply_weather_health(_health_for_weather(), weather=weather, tactical={}, write=False)
    assert out["weather_context"]["status"] == "PARTIAL"
    assert out["weather_context"]["decision_relevant_missing_count"] == 1
    assert out["capability_telemetry"]["capabilities"]["Tactical Matchup"]["state"] == "PARTIAL"
