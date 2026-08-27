import json
import os
import time
from pathlib import Path

import pytest

from src.engines.production_contract_validate import _validate_runtime_service_states
from src.runtime_v3 import orchestrator
from src.runtime_v3.performance_guard import evaluate
from src.runtime_v3.publish_snapshot import materialize

ROOT = Path(__file__).resolve().parents[1]


def test_fast_profile_and_slo_are_registry_owned():
    profiles = json.loads((ROOT / "config/runtime/execution_profiles.json").read_text())
    slo = json.loads((ROOT / "config/runtime/performance_slo.json").read_text())
    fast = profiles["profiles"]["fast_decision"]
    assert fast["max_parallel_services"] <= 4
    assert set(fast["reuse_services"]) >= {"advanced_stats", "historical_prior", "source_layer", "official_detail"}
    assert slo["profiles"]["fast_decision"]["target_wall_ms"] == 10000
    assert slo["profiles"]["fast_decision"]["legacy_ceiling_ms"] == 45000


def test_reuse_service_requires_fresh_complete_artifacts(monkeypatch, tmp_path):
    monkeypatch.setattr(orchestrator, "validate_artifact", lambda path, name: {"artifact": name, "valid": True})
    spec = {"artifacts": ["a.json", "b.json"]}
    profile = {"reuse_services": {"heavy": {"max_age_seconds": 60}}}
    assert orchestrator._reuse_service("heavy", spec, tmp_path, profile) is None
    for name in spec["artifacts"]:
        (tmp_path / name).write_text("{}")
    reused = orchestrator._reuse_service("heavy", spec, tmp_path, profile)
    assert reused and reused["status"] == "REUSED"
    old = time.time() - 120
    os.utime(tmp_path / "a.json", (old, old))
    assert orchestrator._reuse_service("heavy", spec, tmp_path, profile) is None


def test_profile_aware_production_contract_accepts_only_validated_declared_reuse():
    payload = {
        "profile_config": {"reuse_services": {"source_layer": {"max_age_seconds": 60}}},
        "services": {
            "official_snapshot": {"status": "SUCCESS"},
            "source_layer": {"status": "REUSED", "artifact_validation": [{"artifact": "source_health.json", "validation": "PARSE_ONLY"}]},
        },
    }
    _validate_runtime_service_states(payload)
    bad = json.loads(json.dumps(payload))
    bad["services"]["source_layer"]["artifact_validation"] = []
    with pytest.raises(AssertionError):
        _validate_runtime_service_states(bad)
    undeclared = json.loads(json.dumps(payload))
    undeclared["profile_config"]["reuse_services"] = {}
    with pytest.raises(AssertionError):
        _validate_runtime_service_states(undeclared)


def test_publish_snapshot_is_whitelist_only_and_generates_manifest(tmp_path):
    source = tmp_path / "source"
    output = tmp_path / "publish"
    source.mkdir()
    (source / "latest.json").write_text("{}")
    (source / "history.jsonl").write_text("should-not-publish\n")
    (source / "runtime_performance.json").write_text(json.dumps({
        "total_wall_ms": 9000,
        "target_wall_ms": 10000,
        "within_target_slo": True,
        "within_legacy_ceiling": True,
        "resources": {"peak_rss_kb": 1000, "child_peak_rss_kb": 2000},
    }))
    manifest = materialize(source, output, "fast_decision", "deadbeef")
    assert (output / "data/latest.json").exists()
    assert (output / "data/runtime_performance.json").exists()
    assert (output / "data/runtime_manifest.json").exists()
    assert not (output / "data/history.jsonl").exists()
    assert manifest["source_commit"] == "deadbeef"
    assert manifest["publication"]["rolling_snapshot_intended"] is True


def test_performance_guard_transition_semantics():
    slo = json.loads((ROOT / "config/runtime/performance_slo.json").read_text())
    performance = {
        "total_wall_ms": 12000,
        "resources": {
            "peak_rss_kb": 1,
            "child_peak_rss_kb": 1,
            "temporary_bytes": 1,
            "seed_input_bytes": 1,
            "promoted_output_bytes": 1,
        },
    }
    result = evaluate(performance, slo, "fast_decision")
    assert result["within_target_slo"] is False
    assert result["within_legacy_ceiling"] is True
    assert result["resource_observability_complete"] is True


def test_rec20_player_features_remain_decision_neutral_until_explicit_activation():
    services = json.loads((ROOT / "config/v3_service_registry.json").read_text())["services"]
    prediction = services["prediction"]
    advanced = services["advanced_stats"]
    prediction_text = (ROOT / "src/engines/prediction_service.py").read_text()
    assert "player_features.json" not in (prediction.get("inputs") or [])
    assert "player_features" not in prediction_text
    assert any(command.get("module") == "src.engines.player_features" for command in advanced.get("commands") or [])
    assert "player_features.json" in (advanced.get("artifacts") or [])


def test_workflows_are_split_shallow_and_runtime_data_is_rolling():
    legacy = (ROOT / ".github/workflows/fpl-engine.yml").read_text()
    ci = (ROOT / ".github/workflows/v3-ci.yml").read_text()
    fast = (ROOT / ".github/workflows/v3-runtime-fast.yml").read_text()
    full = (ROOT / ".github/workflows/v3-refresh-full.yml").read_text()
    collector = json.loads((ROOT / "config/runtime/collector_policy.json").read_text())
    publish = json.loads((ROOT / "config/runtime/runtime_publish_registry.json").read_text())
    schedules = collector["schedules"]
    hydrate = set(publish["hydrate_paths"])
    assert {"source_health.json", "source_registry_runtime.json", "challenger_observations.json", "fixture_weather.json"}.issubset(hydrate)
    assert "schedule:" not in legacy
    assert f'cron: "{schedules["primary"]}"' in fast
    assert f'cron: "{schedules["adaptive"]}"' in fast
    assert f'cron: "{schedules["deep_stats"]}"' in full
    assert "fetch-depth: 0" not in ci + fast + full
    assert "fetch-depth: 1" in ci and "fetch-depth: 1" in fast and "fetch-depth: 1" in full
    assert "git push --force origin HEAD:\"$RUNTIME_BRANCH\"" in fast
    assert "git push --force origin HEAD:\"$RUNTIME_BRANCH\"" in full
    assert "runtime_publish_registry.json" in fast and "runtime_publish_registry.json" in full
    assert "/data/**" in (ROOT / ".gitignore").read_text()
