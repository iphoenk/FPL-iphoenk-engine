import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.runtime_v3 import fast_entrypoint

ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_fast_reuse_uses_logical_time_not_hydration_mtime(tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    path = tmp_path / "artifact.json"
    _write(path, {"generated_at": old, "value": 1})
    os.utime(path, None)  # simulate `git show > file` hydration now
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


def test_fast_profile_closes_rec41_fence_and_declares_semantic_reuse():
    profiles = json.loads((ROOT / "config/runtime/execution_profiles.json").read_text())
    fast = profiles["profiles"]["fast_decision"]
    assert profiles["policy"]["rec41_player_feature_migration_fence_active"] is False
    assert fast["reuse_services"]["advanced_stats"]["max_age_seconds"] == 21600
    assert fast["reuse_services"]["prediction"]["mode"] == "semantic_signature"
    assert {"prediction", "lineup_governance", "challenger", "governance", "watchlist"}.issubset(fast["reuse_services"])
    assert set(fast["command_bundles"]) == {"governance", "watchlist", "reporting", "report_materializer"}


def test_fast_hydrates_previous_validated_decision_outputs_and_metadata():
    publish = json.loads((ROOT / "config/runtime/runtime_publish_registry.json").read_text())
    hydrate = set(publish["hydrate_paths"])
    assert {"runtime_performance.json", "projections.json", "package_optimizer.json", "prediction_quality.json", "lineup_decision.json", "package_decision.json", "framework_health.json", "dss_operational_evidence.json", "dss_watchlist.json"}.issubset(hydrate)


def test_capability_master_registry_is_deduplicated_and_explicit():
    registry = json.loads((ROOT / "config/intelligence/capability_master_registry.json").read_text())
    rows = registry["capabilities"]
    ids = [row["id"] for row in rows]
    assert registry["expected_count"] == 30 == len(rows)
    assert len(ids) == len(set(ids))
    assert registry["policy"]["enhancements_are_rollups_not_extra_capabilities"] is True
    assert registry["policy"]["rec_items_are_delivery_milestones_not_extra_capabilities"] is True
    assert registry["policy"]["safe_fallback_is_not_feature_completion"] is True
    tactical = next(row for row in rows if row["id"] == "CAP-06")
    assert "DSS-07" in tactical["maps"]["dss"] and "REC-41" in tactical["maps"]["rec"]
    calibration = next(row for row in rows if row["id"] == "CAP-20")
    assert set(calibration["maps"]["rec"]) == {"REC-04", "REC-07", "REC-26"}


def test_fast_workflow_uses_low_latency_adapter():
    workflow = (ROOT / ".github/workflows/v3-runtime-fast.yml").read_text()
    assert "python -m src.runtime_v3.fast_entrypoint" in workflow
