from pathlib import Path

from src.v5.config_cache import load_json_config


def test_runtime_performance_policy_is_release_blocking_and_sub_second():
    perf = load_json_config("config/v5_performance_budgets.json")
    budgets = perf["budgets"]
    hard = float(budgets["hot_path_hard_limit_seconds"])
    hot = float(budgets["hot_path_hot_target_seconds"])
    soft = float(budgets["hot_path_soft_target_seconds"])
    refresh_ceiling = float(budgets["refresh_pipeline_observability_ceiling_seconds"])

    assert 0.0 < hot < soft < hard < 1.0
    assert refresh_ceiling >= 1.0
    assert perf["policy"]["block_unreviewed_regression"] is True
    assert perf["policy"]["subsecond_runtime_is_release_blocking"] is True
    assert perf["policy"]["subsecond_sla_applies_to_user_facing_hot_path"] is True
    assert perf["policy"]["refresh_plane_is_precomputation_not_user_latency"] is True
    assert perf["policy"]["quality_may_not_be_reduced_to_meet_runtime"] is True
    assert perf["policy"]["hot_path_target_is_advisory_until_canary"] is False

    execution = load_json_config("config/v5_execution_plane_registry.json")
    hot_plane = execution["planes"]["hot"]
    assert float(hot_plane["hard_limit_ms"]) == hard * 1000.0
    assert hot_plane["network_refresh_allowed"] is False
    assert hot_plane["stale_materialization_action"] == "FAIL_CLOSED"

    acceptance = load_json_config("config/v5_acceptance_registry.json")
    performance_gate = acceptance["performance_gate"]
    assert acceptance["convergence"]["subsecond_end_to_end_runtime_required"] is True
    assert acceptance["convergence"]["subsecond_hot_path_runtime_required"] is True
    assert acceptance["convergence"]["refresh_hot_execution_plane_required"] is True
    assert performance_gate["required_for_operational_acceptance"] is True
    assert performance_gate["budget_registry"] == "config/v5_performance_budgets.json"
    assert performance_gate["hard_metric"] == "hot_path_hard_limit_seconds"
    assert performance_gate["refresh_observability_metric"] == "refresh_pipeline_observability_ceiling_seconds"
    assert performance_gate["hot_metric"] == "hot_path_hot_target_seconds"
    assert performance_gate["hot_target_is_advisory"] is False
    assert performance_gate["subsecond_required"] is True
    assert performance_gate["hot_path_external_round_trip_required"] is True
    assert performance_gate["refresh_plane_latency_release_blocking"] is False
    assert performance_gate["quality_reduction_for_speed_forbidden"] is True
    assert performance_gate["stale_materialization_must_fail_closed"] is True
    assert performance_gate["hidden_synchronous_refresh_forbidden"] is True


def test_runtime_fingerprint_covers_performance_execution_plane_and_weather_venue_authority():
    integrity = load_json_config("config/v5_release_integrity_registry.json")
    assert "config/venues" in set(integrity["include_roots"])
    assert "config/v5_performance_budgets.json" in set(integrity["include_files"])
    assert "config/v5_execution_plane_registry.json" in set(integrity["include_files"])
    assert integrity["governance"]["execution_plane_policy_change_resets_acceptance"] is True


def test_existing_workflows_and_shadow_cycle_enforce_hot_runtime_contract():
    unified = Path(".github/workflows/v5-unified-gate.yml").read_text(encoding="utf-8")
    shadow = Path(".github/workflows/v5-shadow-cycle.yml").read_text(encoding="utf-8")
    dev_perf = Path(".github/workflows/v5-dev-subsecond-performance.yml").read_text(encoding="utf-8")
    shadow_cycle = Path("src/v5/shadow_cycle.py").read_text(encoding="utf-8")
    beta = Path("src/v5/services/orchestrator_beta.py").read_text(encoding="utf-8")

    assert "v5-beta6-roadmap" in unified
    assert "tests/test_v5_runtime_performance_policy.py" in unified
    assert "v5-beta6-roadmap" in shadow
    assert "hot_path_hard_limit_seconds" in shadow
    assert "hot_path_wall_ms" in shadow
    assert "hot_path_hard_limit_seconds" in dev_perf
    assert "/v1/invoke/{operation}" in dev_perf
    assert "invoke('hot_run'" in dev_perf
    assert "hot_path_hard_limit_seconds" in shadow_cycle
    assert "hot_path_under_one_second" in shadow_cycle
    assert 'operation == "hot_run"' in beta
    assert "hot_path_wall_ms" in beta
