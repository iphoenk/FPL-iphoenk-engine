import json
from pathlib import Path

import pytest

from src.runtime_v3.artifact_contracts import validate_artifact
from src.runtime_v3.orchestrator import _attempt_promotion

ROOT = Path(__file__).resolve().parents[1]


def _valid_observations() -> dict:
    return {
        "schema_version": 2,
        "contract": "challenger_observation_v2",
        "generated_at": "2026-08-27T00:00:00+00:00",
        "observations": [],
        "counts": {"fresh": 0, "cached_last_known_good": 0, "stale": 0, "legacy": 0},
        "cross_source": [],
        "policy": {},
    }


def test_generic_declared_json_must_parse(tmp_path):
    path = tmp_path / "generic.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="malformed JSON artifact"):
        validate_artifact(path, "generic.json")


def test_challenger_observations_wrong_contract_is_integrity_failure(tmp_path):
    path = tmp_path / "challenger_observations.json"
    payload = _valid_observations()
    payload["contract"] = "wrong-contract"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="contract.*mismatch"):
        validate_artifact(path, "challenger_observations.json")


def test_challenger_observations_valid_empty_is_allowed(tmp_path):
    path = tmp_path / "challenger_observations.json"
    path.write_text(json.dumps(_valid_observations()), encoding="utf-8")
    result = validate_artifact(path, "challenger_observations.json")
    assert result["validation"] == "CONTRACT_VALID"


def test_malformed_isolated_artifact_fails_before_promotion(tmp_path):
    service_dir = tmp_path / "service"
    canonical = tmp_path / "canonical"
    service_dir.mkdir()
    canonical.mkdir()
    (service_dir / "bad.json").write_text("[broken", encoding="utf-8")
    spec = {"critical": True, "isolated": True, "inputs": [], "artifacts": ["bad.json"], "latest_keys": [], "latest_file_keys": []}
    result = {"service": "bad", "status": "SUCCESS", "isolated": True, "data_dir": str(service_dir), "elapsed_ms": 1.0, "commands": []}
    accepted = _attempt_promotion("bad", result, spec, canonical)
    assert accepted["status"] == "FAILED"
    assert accepted["failure_stage"] == "artifact_validation"
    assert not (canonical / "bad.json").exists()


def test_malformed_nonisolated_artifact_also_fails_contract(tmp_path):
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    (canonical / "bad.json").write_text("{broken", encoding="utf-8")
    spec = {"critical": True, "isolated": False, "inputs": [], "artifacts": ["bad.json"], "latest_keys": [], "latest_file_keys": []}
    result = {"service": "bad", "status": "SUCCESS", "isolated": False, "data_dir": str(canonical), "elapsed_ms": 1.0, "commands": []}
    accepted = _attempt_promotion("bad", result, spec, canonical)
    assert accepted["status"] == "FAILED"
    assert accepted["failure_stage"] == "artifact_validation"


def test_runtime_registry_declares_artifact_integrity_policy():
    registry = json.loads((ROOT / "config" / "v3_service_registry.json").read_text(encoding="utf-8"))
    contracts = json.loads((ROOT / "config" / "runtime" / "artifact_contracts.json").read_text(encoding="utf-8"))
    assert registry["schema_version"] >= 12
    assert registry["policy"]["declared_json_artifacts_are_validated_before_acceptance"] is True
    assert registry["policy"]["malformed_internal_artifact_is_integrity_failure"] is True
    assert contracts["contracts"]["challenger_observations.json"]["equals"]["contract"] == "challenger_observation_v2"
