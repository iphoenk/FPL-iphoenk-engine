import json
from pathlib import Path

import pytest

from src.engines.fpl_legality import plan_legality_checks
from src.engines.v4_reconciliation_truth import actual_by_element
from src.engines.v4_validation import minutes_metrics
from src.services.optimization_slo_service import DECISION_COMPUTE_SLO_MS

ROOT = Path(__file__).resolve().parents[1]


def _live():
    return {
        "elements": [
            {"id": 1, "stats": {"minutes": 30, "starts": 1, "total_points": 2}},
            {"id": 2, "stats": {"minutes": 70, "starts": 0, "total_points": 4}},
            {"id": 3, "stats": {"minutes": 90, "total_points": 6}},
        ]
    }


def test_official_starts_is_only_start_truth():
    actual = actual_by_element(_live())
    assert actual[1]["started"] is True
    assert actual[2]["started"] is False
    assert actual[3]["started"] is None


def test_missing_start_is_excluded_from_start_brier_not_inferred():
    rows = [
        {"predicted_minutes": 70, "actual_minutes": 30, "actual_started": True, "start_probability": .9, "p60": .7},
        {"predicted_minutes": 60, "actual_minutes": 70, "actual_started": False, "start_probability": .2, "p60": .7},
        {"predicted_minutes": 80, "actual_minutes": 90, "actual_started": None, "start_probability": .8, "p60": .8},
    ]
    metrics = minutes_metrics(rows)
    assert metrics["n"] == 3
    assert metrics["start_n"] == 2
    assert metrics["start_missing"] == 1
    assert metrics["start_brier"] == pytest.approx(.025, abs=1e-4)
    assert metrics["p60_brier"] is not None


def _plan(formation="3-5-2"):
    xi = [{"element": i, "position": "GK" if i == 1 else "DEF" if i in (2, 3, 4) else "MID" if i in (5, 6, 7, 8, 9) else "FWD"} for i in range(1, 12)]
    return {
        "formation": formation,
        "starting_xi": xi,
        "captain": {"element": 5},
        "vice_captain": {"element": 10},
        "bench": {"gk": {"element": 12, "position": "GK"}, "order": [{"element": 13}, {"element": 14}, {"element": 15}]},
        "chip_context": {"single_chip_rule_respected": True},
    }


def test_effective_plan_legality_is_independently_testable_through_canonical_owner():
    checks = plan_legality_checks(_plan(), {"overall": "PASS"})
    assert all(ok for ok, _ in checks.values())
    bad = _plan()
    bad["captain"] = {"element": 99}
    assert plan_legality_checks(bad, {"overall": "PASS"})["G0-12"][0] is False


def test_runtime_architecture_preserves_hard_5s_compute_slo_and_adds_independent_guard():
    registry = json.loads((ROOT / "config" / "service_registry.json").read_text())
    services = registry["services"]
    declared_count = int(registry["guardrails"]["service_count"])
    ids = [row["id"] for row in services]
    assert len(services) == declared_count == len(set(ids))
    by_id = {row["id"]: row for row in services}
    assert by_id["architecture_guard"]["module"] == "src.services.architecture_guard_service"
    assert by_id["reconciliation_readiness"]["module"] == "src.services.reconciliation_readiness_service"
    assert by_id["optimization"]["module"] == "src.services.optimization_slo_service"
    assert by_id["framework_postflight"]["module"] == "src.services.framework_postflight_truth_service"
    assert "user_decision_overlay" in by_id["framework_postflight"]["depends_on"]
    assert "architecture_guard" in by_id["framework_preflight"]["depends_on"]
    assert DECISION_COMPUTE_SLO_MS == 5000.0
    assert registry["guardrails"]["decision_compute_slo_ms"] == 5000
    assert registry["guardrails"]["decision_compute_slo_excludes_external_network_io"] is True
    assert registry["guardrails"]["reconciliation_started_from_official_stats_starts"] is True
    assert registry["guardrails"]["engine_effective_plan_legality_reported_separately"] is True
    assert registry["guardrails"]["reconciliation_readiness_read_only"] is True


def test_reconciliation_truth_has_one_owner_and_no_minutes_threshold():
    store = (ROOT / "src/engines/v4_backtest_store.py").read_text()
    truth = (ROOT / "src/engines/v4_reconciliation_truth.py").read_text()
    validation = (ROOT / "src/engines/v4_validation.py").read_text()
    assert "def actual_by_element" not in store
    assert "def reconcile_finished_gw" not in store
    assert "def actual_by_element" in truth
    assert "def reconcile_finished_gw" in truth
    for text in (store, truth, validation):
        assert "minutes\", 0) or 0) >= 45" not in text
        assert "actual_minutes'])>=45" not in text
