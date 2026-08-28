import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.runtime_v3 import fast_entrypoint, release_acceptance, reuse_manifest

ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_fast_reuse_uses_logical_time_not_hydration_mtime(tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    path = tmp_path / "artifact.json"
    _write(path, {"generated_at": old, "value": 1})
    os.utime(path, None)
    logical = fast_entrypoint._logical_generated_at(path)
    assert logical is not None
    assert (datetime.now(timezone.utc) - logical).total_seconds() > 7000


def test_semantic_signature_ignores_runtime_metadata_but_not_decision_data(tmp_path):
    cfg = {"signature_inputs": ["a.json"], "signature_config_files": []}
    _write(tmp_path / "a.json", {"generated_at": "2026-01-01T00:00:00+00:00", "fetched_at": "2026-01-01T00:00:00+00:00", "price": 100})
    first = fast_entrypoint._input_signature("prediction", cfg, tmp_path)
    _write(tmp_path / "a.json", {"generated_at": "2026-01-02T00:00:00+00:00", "fetched_at": "2026-01-02T00:00:00+00:00", "price": 100})
    second = fast_entrypoint._input_signature("prediction", cfg, tmp_path)
    assert first == second
    _write(tmp_path / "a.json", {"generated_at": "2026-01-02T00:00:00+00:00", "price": 101})
    third = fast_entrypoint._input_signature("prediction", cfg, tmp_path)
    assert third != second


def test_semantic_field_selector_ignores_unselected_health_metadata(tmp_path):
    cfg = {
        "signature_inputs": [{"path": "official.json", "include_paths": ["bootstrap.elements", "fixtures"]}],
        "signature_config_files": [],
    }
    base = {"bootstrap": {"elements": [{"id": 1, "now_cost": 100}]}, "fixtures": [{"id": 1}], "endpoint_health": {"bootstrap": {"cache_hit": False}}}
    _write(tmp_path / "official.json", base)
    first = fast_entrypoint._input_signature("prediction", cfg, tmp_path)
    base["endpoint_health"]["bootstrap"]["cache_hit"] = True
    _write(tmp_path / "official.json", base)
    assert fast_entrypoint._input_signature("prediction", cfg, tmp_path) == first
    base["bootstrap"]["elements"][0]["now_cost"] = 101
    _write(tmp_path / "official.json", base)
    assert fast_entrypoint._input_signature("prediction", cfg, tmp_path) != first


def test_semantic_list_field_selector_ignores_irrelevant_dynamic_fields(tmp_path):
    cfg = {
        "signature_inputs": [{
            "path": "official.json",
            "include_list_fields": {"bootstrap.elements": ["id", "now_cost", "status"]},
        }],
        "signature_config_files": [],
    }
    payload = {"bootstrap": {"elements": [{"id": 1, "now_cost": 100, "status": "a", "transfers_in_event": 10}]}}
    _write(tmp_path / "official.json", payload)
    first = fast_entrypoint._input_signature("prediction", cfg, tmp_path)
    payload["bootstrap"]["elements"][0]["transfers_in_event"] = 999
    _write(tmp_path / "official.json", payload)
    assert fast_entrypoint._input_signature("prediction", cfg, tmp_path) == first
    payload["bootstrap"]["elements"][0]["now_cost"] = 101
    _write(tmp_path / "official.json", payload)
    assert fast_entrypoint._input_signature("prediction", cfg, tmp_path) != first


def test_semantic_field_selector_fails_closed_on_missing_field(tmp_path):
    cfg = {"signature_inputs": [{"path": "a.json", "include_paths": ["phase.planning_gw"]}], "signature_config_files": []}
    _write(tmp_path / "a.json", {"phase": {}})
    assert fast_entrypoint._input_signature("prediction", cfg, tmp_path) is None


def test_semantic_list_field_selector_fails_closed_on_missing_row_field(tmp_path):
    cfg = {"signature_inputs": [{"path": "a.json", "include_list_fields": {"players": ["id", "price"]}}], "signature_config_files": []}
    _write(tmp_path / "a.json", {"players": [{"id": 1}]})
    assert fast_entrypoint._input_signature("prediction", cfg, tmp_path) is None


def test_output_hash_detects_mutated_reused_artifact(tmp_path):
    path = tmp_path / "out.json"
    _write(path, {"generated_at": "2026-01-01T00:00:00+00:00", "value": 1})
    first = reuse_manifest.file_sha256(path)
    _write(path, {"generated_at": "2026-01-01T00:00:00+00:00", "value": 2})
    assert reuse_manifest.file_sha256(path) != first


def test_fast_profile_closes_rec41_fence_and_declares_state_safe_semantic_reuse():
    profiles = json.loads((ROOT / "config/runtime/execution_profiles.json").read_text())
    fast = profiles["profiles"]["fast_decision"]
    assert profiles["policy"]["rec41_player_feature_migration_fence_active"] is False
    assert profiles["policy"]["semantic_reuse_manifest_is_separate_from_performance_telemetry"] is True
    assert profiles["policy"]["semantic_signature_fields_are_config_owned"] is True
    assert profiles["policy"]["semantic_signature_list_fields_are_config_owned"] is True
    assert profiles["policy"]["time_dependent_or_state_transition_services_are_not_reused_without_explicit_time_contract"] is True
    assert fast["reuse_services"]["advanced_stats"]["max_age_seconds"] == 21600
    assert fast["reuse_services"]["prediction"]["mode"] == "semantic_signature"
    assert {"prediction", "lineup_governance", "challenger", "governance"}.issubset(fast["reuse_services"])
    assert "prediction_evaluation" not in fast["reuse_services"]
    assert "watchlist" not in fast["reuse_services"]
    assert "reporting" not in fast["reuse_services"] and "report_materializer" not in fast["reuse_services"]
    prediction_inputs = fast["reuse_services"]["prediction"]["signature_inputs"]
    assert any(isinstance(row, dict) and row.get("path") == "latest.json" and "phase.planning_gw" in row.get("include_paths", []) for row in prediction_inputs)
    official_selector = next(row for row in prediction_inputs if isinstance(row, dict) and row.get("path") == "official_snapshot.json")
    assert "bootstrap.elements" in official_selector["include_list_fields"]
    assert "transfers_in_event" not in official_selector["include_list_fields"]["bootstrap.elements"]
    team_selector = next(row for row in prediction_inputs if isinstance(row, dict) and row.get("path") == "team.json")
    assert team_selector["include_paths"] == ["totals.itb"]
    assert team_selector["include_list_fields"]["team_value_ledger"] == ["element", "sell_cost"]
    assert set(fast["command_bundles"]) == {"governance", "watchlist", "reporting", "report_materializer"}


def test_fast_hydrates_validated_reuse_manifest_and_decision_outputs():
    publish = json.loads((ROOT / "config/runtime/runtime_publish_registry.json").read_text())
    hydrate = set(publish["hydrate_paths"])
    published = set(publish["publish_paths"])
    required = {"runtime_reuse_manifest.json", "projections.json", "package_optimizer.json", "prediction_quality.json", "prediction_ledger.json", "prediction_accuracy.json", "lineup_decision.json", "package_decision.json", "framework_health.json", "dss_operational_evidence.json", "dss_watchlist.json"}
    assert required.issubset(hydrate)
    assert "runtime_reuse_manifest.json" in published
    assert publish["policy"]["semantic_reuse_state_is_separate_from_performance_telemetry"] is True


def test_capability_master_registry_has_exact_single_primitive_ownership():
    registry = json.loads((ROOT / "config/intelligence/capability_master_registry.json").read_text())
    core = json.loads((ROOT / "config/dss_core_registry.json").read_text())
    ext = json.loads((ROOT / "config/dss_extension_registry.json").read_text())
    rows = registry["capabilities"]
    ids = [row["id"] for row in rows]
    assert registry["expected_count"] == 30 == len(rows)
    assert len(ids) == len(set(ids))
    dss_owned = [value for row in rows for value in (row.get("owns") or {}).get("dss", [])]
    ext_owned = [value for row in rows for value in (row.get("owns") or {}).get("extensions", [])]
    assert len(dss_owned) == len(set(dss_owned)) == 50
    assert len(ext_owned) == len(set(ext_owned)) == 16
    assert set(dss_owned) == {row["id"] for row in core["modules"]}
    assert set(ext_owned) == {row["id"] for row in ext["modules"]}
    tactical = next(row for row in rows if row["id"] == "CAP-06")
    assert tactical["owns"]["dss"] == ["DSS-07"] and "REC-41" in tactical["references"]["rec"]
    calibration = next(row for row in rows if row["id"] == "CAP-20")
    assert calibration["owns"]["dss"] == ["DSS-44"]
    assert set(calibration["references"]["rec"]) == {"REC-04", "REC-07", "REC-26"}


def test_fast_release_acceptance_uses_validated_manifest_warmup_then_measurement():
    gates = {gate.name: gate.command for gate in release_acceptance.integration_gates()}
    assert "src.runtime_v3.fast_entrypoint" in gates["fast_semantic_warmup"]
    assert "src.runtime_v3.reuse_manifest" in gates["capture_reuse_manifest"]
    assert "src.runtime_v3.fast_entrypoint" in gates["fast_runtime"]
    assert "src.runtime_v3.orchestrator" not in gates["fast_runtime"]


def test_fast_workflow_uses_low_latency_adapter_and_post_validation_manifest_capture():
    workflow = (ROOT / ".github/workflows/v3-runtime-fast.yml").read_text()
    assert "python -m src.runtime_v3.fast_entrypoint" in workflow
    assert "python -m src.runtime_v3.reuse_manifest --profile fast_decision" in workflow
    assert workflow.index("Validate production decision contracts") < workflow.index("Capture validated FAST semantic reuse manifest")
