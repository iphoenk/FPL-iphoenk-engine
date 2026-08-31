from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_current_metadata_uses_canonical_runtime_contracts() -> None:
    slo = _read("config/runtime/performance_slo.json")
    service = _read("config/v3_service_registry.json")
    domains = _read("config/runtime/execution_domains.json")
    status = _read("IMPLEMENTATION_STATUS.json")

    fast = slo["profiles"]["fast_decision"]
    assert fast["target_wall_ms"] == 3000
    assert fast["legacy_ceiling_ms"] == 3000

    assert "10s" not in service["production_contract"].lower()
    assert "3s" in service["production_contract"].lower()
    assert "3000ms" in service["runtime"]["performance_target"]

    production = status["production_acceptance"]
    architecture = status["architecture"]
    current = production["current_operational_evidence"]
    capability_count = len(service["services"])
    domain_count = int(domains["domain_count"])
    phase_count = int(domains["phase_count"])

    assert production["fast_target_ms"] == fast["target_wall_ms"]
    assert architecture["fast_slo_ms"] == fast["target_wall_ms"]
    assert production["canonical_performance_slo"] == "config/runtime/performance_slo.json"
    assert production["runtime_evidence_authority"] == "runtime-data/data/runtime_manifest.json"
    assert current["execution_domain_count"] == domain_count
    assert current["execution_phase_count"] == phase_count
    assert current["background_capability_count"] == capability_count
    assert architecture["execution_domain_count"] == domain_count
    assert architecture["execution_phase_count"] == phase_count
    assert architecture["active_background_capability_count"] == capability_count
    assert architecture["latest_production_evidence_domain_count"] == domain_count


def test_historical_evidence_is_not_presented_as_current_runtime_authority() -> None:
    status = _read("IMPLEMENTATION_STATUS.json")
    assert "Historical" in status["production_acceptance"]["accepted_code_commit_semantics"]
    assert status["release_candidate"].get("execution_domain_count_at_time") == 7
    assert "execution_domain_count" not in status["release_candidate"]
    assert status["architecture_closeout"]["topology_semantics"] == "HISTORICAL_AT_TIME"
    assert status["calibration_monitors"]["settled_prediction_validation"] == "MONITOR_GENUINE_EVIDENCE_ONLY"
    assert status["calibration_monitors"]["fast_runtime_headroom"] == "MONITOR_WITHOUT_CEILING_INCREASE"
