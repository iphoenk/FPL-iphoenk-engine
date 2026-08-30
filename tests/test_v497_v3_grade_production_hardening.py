from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from src.engines import v4_checkpoint_governance, v4_serving_contract
from src.services import architecture_guard_service

ROOT = Path(__file__).resolve().parents[1]


def test_capability_ownership_matrix_is_complete_unique_and_governed():
    ownership = json.loads((ROOT / "config/architecture_ownership_registry.json").read_text())
    rows = ownership["capability_matrix"]
    ids = [row["capability"] for row in rows]
    assert len(ids) == len(set(ids))
    assert architecture_guard_service.REQUIRED_CAPABILITIES <= set(ids)
    for row in rows:
        assert row["current_owner"]
        assert row["input_contract"]
        assert row["output_artifact"]
        assert row["consumers"]
        assert row["duplicates_overlap"]
        assert row["action"] in architecture_guard_service.VALID_OVERLAP_ACTIONS


def test_checkpoint_reporting_does_not_recompute_canonical_arbitration():
    path = ROOT / "src/engines/v4_checkpoint_governance.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "resolve_decision" not in calls


def test_checkpoint_reporting_fails_closed_without_canonical_artifact(monkeypatch):
    monkeypatch.setattr(v4_checkpoint_governance, "read_json", lambda path, default=None: {})
    latest = {
        "checkpoint_context": {"duplicate_report_forbidden": True},
        "squad_authority": "OFFICIAL_SUBMITTED",
        "generated_at": "2026-08-30T00:00:00+00:00",
    }
    health = {"gate0": {"pass": True}, "overall": "GREEN"}
    with pytest.raises(RuntimeError, match="report-layer recomputation is forbidden"):
        v4_checkpoint_governance.govern_checkpoint(
            latest,
            health,
            {},
            {},
            {},
            scorecard={},
            now="2026-08-30T00:00:00+00:00",
            canonical={},
        )


def test_serving_contract_has_no_decision_or_official_acquisition_imports():
    path = ROOT / "src/engines/v4_serving_contract.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "src.sources.official_fpl" not in modules
    assert "src.engines.v4_decision_arbitration" not in modules
    assert "src.engines.v4_lineup_optimizer" not in modules
    assert "src.models.v4_prediction" not in modules


def test_warm_serving_benchmark_reports_repeated_median_and_p95(monkeypatch):
    monkeypatch.setattr(v4_serving_contract, "read_json", lambda path, default=None: {})
    samples = [0.5 + index * 0.01 for index in range(v4_serving_contract.WARM_BENCHMARK_RUNS)]
    out = v4_serving_contract.build_benchmark({"quick_serving_ms": samples[0]}, {}, orchestration={}, warm_samples_ms=samples)
    warm = out["warm_serving"]
    assert warm["runs"] == v4_serving_contract.WARM_BENCHMARK_RUNS
    assert warm["median_ms"] > 0
    assert warm["p95_ms"] >= warm["median_ms"]
    assert warm["target_p95_ms"] == 1000.0
    assert warm["status"] == "PASS"
    assert warm["production_sized_materialized_inputs"] is True
    assert warm["decision_semantics_recomputed"] is False


def test_release_manifest_names_current_ownership_registry():
    release = json.loads((ROOT / "config/release_manifest.json").read_text())
    ownership = json.loads((ROOT / "config/architecture_ownership_registry.json").read_text())
    assert release["registries"]["ownership"] == ownership["registry"]
    assert release["production_acceptance_lifecycle"] == [
        "IMPLEMENTED",
        "TESTED",
        "GATE_GREEN",
        "RUNTIME_PUBLISHED",
        "RUNTIME_VALIDATED",
        "PRODUCTION_ACCEPTED",
    ]


def test_postflight_publishes_all_canonical_capability_groups():
    source = (ROOT / "src/services/framework_postflight_truth_service.py").read_text(encoding="utf-8")
    expected = {
        "Official Truth",
        "Personal State",
        "Phase Authority",
        "Prediction",
        "xMins",
        "Opponent Model",
        "Tactical Matchup",
        "Competitive Load",
        "Set Pieces",
        "Price/Finance",
        "Comparator",
        "Package Optimizer",
        "XI/Bench",
        "Captaincy",
        "External Consensus",
        "Validation/Calibration",
        "Reporting/Serving",
    }
    tree = ast.parse(source)
    literals = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert expected <= literals


def test_moving_operational_identity_has_no_secondary_constant_owner():
    assert architecture_guard_service._moving_operational_literal_violations() == []
