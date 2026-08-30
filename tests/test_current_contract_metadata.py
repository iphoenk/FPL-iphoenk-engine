from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_current_metadata_uses_canonical_fast_3s_contract() -> None:
    slo = _read("config/runtime/performance_slo.json")
    service = _read("config/v3_service_registry.json")
    status = _read("IMPLEMENTATION_STATUS.json")

    fast = slo["profiles"]["fast_decision"]
    assert fast["target_wall_ms"] == 3000
    assert fast["legacy_ceiling_ms"] == 3000

    assert "10s" not in service["production_contract"].lower()
    assert "3s" in service["production_contract"].lower()
    assert "3000ms" in service["runtime"]["performance_target"]

    production = status["production_acceptance"]
    architecture = status["architecture"]
    assert production["fast_target_ms"] == fast["target_wall_ms"]
    assert architecture["fast_slo_ms"] == fast["target_wall_ms"]
    assert production["canonical_performance_slo"] == "config/runtime/performance_slo.json"
    assert production["runtime_evidence_authority"] == "runtime-data/data/runtime_manifest.json"
    assert production["current_operational_evidence"]["execution_domain_count"] == 11
    assert production["current_operational_evidence"]["execution_phase_count"] == 6
    assert production["current_operational_evidence"]["background_capability_count"] == 21


def test_historical_evidence_is_not_presented_as_current_runtime_authority() -> None:
    status = _read("IMPLEMENTATION_STATUS.json")
    assert "Historical" in status["production_acceptance"]["accepted_code_commit_semantics"]
    assert status["release_candidate"].get("execution_domain_count_at_time") == 7
    assert "execution_domain_count" not in status["release_candidate"]
    assert status["calibration_monitors"]["settled_prediction_validation"] == "MONITOR_GENUINE_EVIDENCE_ONLY"
    assert status["calibration_monitors"]["fast_runtime_headroom"] == "MONITOR_WITHOUT_CEILING_INCREASE"
