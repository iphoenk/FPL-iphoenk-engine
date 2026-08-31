import json
import os
import time
from pathlib import Path

import pytest

from src.engines.base_snapshot_service import _reusable_state_from_previous
from src.engines.production_contract_validate import (
    _validate_runtime_architecture,
    _validate_runtime_service_states,
)
from src.runtime_v3 import orchestrator
from src.runtime_v3.performance_guard import evaluate
from src.runtime_v3.publish_snapshot import materialize

ROOT = Path(__file__).resolve().parents[1]


def test_fast_profile_and_slo_are_registry_owned():
    profiles = json.loads((ROOT / "config/runtime/execution_profiles.json").read_text())
    slo = json.loads((ROOT / "config/runtime/performance_slo.json").read_text())
    fast = profiles["profiles"]["fast_decision"]
    assert fast["max_parallel_services"] <= 5
    assert set(fast["reuse_services"]) >= {"advanced_stats", "historical_prior", "source_layer", "official_detail"}
    assert profiles["policy"]["reused_service_latest_state_is_carried_forward"] is True
    assert profiles["policy"]["parallelism_follows_v5_bounded_fanout_principle"] is True
    assert slo["profiles"]["fast_decision"]["target_wall_ms"] == 3000
    assert slo["profiles"]["fast_decision"]["legacy_ceiling_ms"] == 3000
    assert slo["profiles"]["fast_decision"]["enforcement"] == "HARD_CEILING"
    assert slo["profiles"]["instant_serving"]["target_wall_ms"] == 500
    assert slo["profiles"]["instant_serving"]["legacy_ceiling_ms"] == 1000
    assert slo["policy"]["sub_second_target_applies_to_validated_warm_serving"] is True
    assert slo["policy"]["external_network_refresh_is_measured_separately"] is True


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
    payload={"profile_config":{"reuse_services":{"source_layer":{"max_age_seconds":60}}},"services":{"official_snapshot":{"status":"SUCCESS"},"source_layer":{"status":"REUSED","artifact_validation":[{"artifact":"source_health.json","validation":"PARSE_ONLY"}]}}}
    _validate_runtime_service_states(payload)
    bad=json.loads(json.dumps(payload)); bad["services"]["source_layer"]["artifact_validation"]=[]
    with pytest.raises(AssertionError):
        _validate_runtime_service_states(bad)
    undeclared=json.loads(json.dumps(payload)); undeclared["profile_config"]["reuse_services"]={}
    with pytest.raises(AssertionError):
        _validate_runtime_service_states(undeclared)


def test_production_contract_accepts_registry_owned_domain_and_phase_runtime():
    domains = json.loads((ROOT / "config/runtime/execution_domains.json").read_text())
    canonical_domains = [name for phase_domains in domains["canonical_phases"].values() for name in phase_domains]
    domain_count = int(domains["domain_count"])
    phase_count = int(domains["phase_count"])
    capability_count = len(json.loads((ROOT / "config/v3_service_registry.json").read_text())["services"])
    assert domain_count == 12
    assert phase_count == 6
    assert capability_count == 22
    snapshot = {"id":"v3-domain-pipeline-v2","architecture":"V3_CANONICAL_DOMAIN_PIPELINE","dependency_aware_scheduling":True,"shared_official_cache":True,"shared_canonical_domain_workspace":True,"cross_capability_copy_promotion":False,"execution_domain_count":domain_count,"execution_phase_count":phase_count,"service_count":domain_count,"capability_owner_count":capability_count}
    runtime = {"runtime_id":"v3-domain-pipeline-v2","architecture":"V3_CANONICAL_DOMAIN_PIPELINE","execution_domain_count":domain_count,"execution_phase_count":phase_count,"capability_owner_count":capability_count,"cross_capability_copy_promotion":False,"canonical_domain_order":canonical_domains,"execution_domains":{name:{"status":"SUCCESS"} for name in canonical_domains},"execution_phase_results":{phase:{"status":"SUCCESS"} for phase in domains["canonical_phases"]},"services":{f"capability_{index}":{} for index in range(capability_count)}}
    _validate_runtime_architecture(snapshot, runtime)


def test_rec32_carries_only_registry_owned_reusable_latest_state(monkeypatch):
    monkeypatch.setenv("FPL_EXECUTION_PROFILE","fast_decision")
    previous={"official_detail_summary":{"detail_requested":40},"official_health_panel":{"overall":"HEALTHY"},"historical_prior_summary":{"model":"historical_player_priors_v1"},"source_layer_summary":{"overall":"GREEN"},"price_summary":{"must_not_be_carried":True},"arbitrary_stale_state":{"must_not_be_carried":True},"files":{"prior_season":"data/prior_season.json","vaastav_previous_season":"data/stats/vaastav_previous_season.json","source_health":"data/source_health.json","source_registry_runtime":"data/source_registry_runtime.json","challenger_observations":"data/challenger_observations.json","fixture_weather":"data/fixture_weather.json","price_alerts":"data/price_alerts.json"}}
    state,files,audit=_reusable_state_from_previous(previous)
    assert set(state)=={"official_detail_summary","official_health_panel","historical_prior_summary","source_layer_summary"}
    assert set(files)=={"prior_season","vaastav_previous_season","source_health","source_registry_runtime","challenger_observations","fixture_weather"}
    assert "price_summary" not in state and "arbitrary_stale_state" not in state and "price_alerts" not in files
    assert set(audit)=={"historical_prior","source_layer","official_detail"}
    monkeypatch.setenv("FPL_EXECUTION_PROFILE","full_refresh")
    state,files,audit=_reusable_state_from_previous(previous)
    assert state=={} and files=={} and audit=={}


def test_publish_snapshot_is_whitelist_only_and_generates_manifest(tmp_path):
    source=tmp_path/"source"; output=tmp_path/"publish"; source.mkdir(); (source/"latest.json").write_text("{}"); (source/"history.jsonl").write_text("should-not-publish\n"); (source/"runtime_performance.json").write_text(json.dumps({"total_wall_ms":2900,"target_wall_ms":3000,"within_target_slo":True,"within_legacy_ceiling":True,"resources":{"peak_rss_kb":1000,"child_peak_rss_kb":2000}}))
    manifest=materialize(source,output,"fast_decision","deadbeef")
    assert (output/"data/latest.json").exists() and (output/"data/runtime_performance.json").exists() and (output/"data/runtime_manifest.json").exists() and not (output/"data/history.jsonl").exists()
    assert manifest["source_commit"]=="deadbeef" and manifest["publication"]["rolling_snapshot_intended"] is True


def test_performance_guard_transition_semantics():
    slo=json.loads((ROOT/"config/runtime/performance_slo.json").read_text()); performance={"total_wall_ms":3200,"resources":{"peak_rss_kb":1,"child_peak_rss_kb":1,"temporary_bytes":1,"seed_input_bytes":1,"promoted_output_bytes":1}}; result=evaluate(performance,slo,"fast_decision")
    assert result["within_target_slo"] is False and result["within_legacy_ceiling"] is False and result["resource_observability_complete"] is True


def test_player_features_are_consumed_only_after_explicit_rec01_activation():
    registry=json.loads((ROOT/"config/v3_service_registry.json").read_text()); services=registry["services"]; prediction=services["prediction"]; advanced=services["advanced_stats"]; feature_cfg=json.loads((ROOT/"config/intelligence/player_features.json").read_text()); prediction_text=(ROOT/"src/engines/prediction_service.py").read_text()
    assert registry["policy"]["player_feature_model_opt_in_rec01_active"] is True and "player_features.json" in (prediction.get("inputs") or []) and "player_features" in prediction_text
    assert feature_cfg["policy"]["decision_neutral_plumbing_only"] is False and feature_cfg["policy"]["model_opt_in"]=="REC-01"
    assert any(command.get("module")=="src.engines.player_features" for command in advanced.get("commands") or []) and "player_features.json" in (advanced.get("artifacts") or [])


def test_workflows_are_unified_shallow_and_runtime_data_is_rolling():
    compat=(ROOT/".github/workflows/fpl-engine.yml").read_text()
    ci=(ROOT/".github/workflows/v3-ci.yml").read_text()
    runtime=(ROOT/".github/workflows/v3-runtime.yml").read_text()
    collector=json.loads((ROOT/"config/runtime/collector_policy.json").read_text())
    profile_policy=json.loads((ROOT/"config/runtime/execution_profile_policy.json").read_text())
    publish=json.loads((ROOT/"config/runtime/runtime_publish_registry.json").read_text())
    schedules=collector["schedules"]
    hydrate=set(publish["hydrate_paths"])
    deep=profile_policy["visible_modes"]["NORMAL_DEEP_REVIEW"]
    assert {"source_health.json","source_registry_runtime.json","challenger_observations.json","fixture_weather.json"}.issubset(hydrate)
    assert "schedule:" not in compat
    assert f'cron: "{schedules["primary"]}"' in runtime
    assert f'cron: "{schedules["adaptive"]}"' in runtime
    assert deep["profile"] == "deep_stats" and deep["extra"] == "--deep-stats"
    assert "execution_profile_resolver" in runtime and 'profile="deep_stats"' not in runtime
    assert not (ROOT/".github/workflows/v3-runtime-fast.yml").exists()
    assert not (ROOT/".github/workflows/v3-refresh-full.yml").exists()
    assert "fetch-depth: 0" not in ci+runtime
    assert "fetch-depth: 1" in ci and "fetch-depth: 1" in runtime
    assert '--force-with-lease="refs/heads/${RUNTIME_BRANCH}:${RUNTIME_BASE_SHA}"' in runtime
    assert "git push --force origin" not in runtime
    assert "runtime_publish_registry.json" in runtime and "/data/**" in (ROOT/".gitignore").read_text()
