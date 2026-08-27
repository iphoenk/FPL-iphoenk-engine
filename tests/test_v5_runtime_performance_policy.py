from pathlib import Path

from src.v5.config_cache import load_json_config


def test_runtime_performance_policy_is_release_blocking_and_sub_five_seconds():
    perf = load_json_config("config/v5_performance_budgets.json")
    budgets = perf["budgets"]
    hard = float(budgets["decision_pipeline_hard_limit_seconds"])
    hot = float(budgets["decision_pipeline_hot_target_seconds"])

    assert 0.0 < hot < 1.0
    assert hot < hard <= 4.5
    assert float(budgets["decision_pipeline_soft_target_seconds"]) <= 5.0
    assert perf["policy"]["block_unreviewed_regression"] is True

    acceptance = load_json_config("config/v5_acceptance_registry.json")
    performance_gate = acceptance["performance_gate"]
    assert performance_gate["required_for_operational_acceptance"] is True
    assert performance_gate["budget_registry"] == "config/v5_performance_budgets.json"
    assert performance_gate["hard_metric"] == "decision_pipeline_hard_limit_seconds"
    assert performance_gate["hot_metric"] == "decision_pipeline_hot_target_seconds"
    assert performance_gate["hot_target_is_advisory"] is True


def test_runtime_fingerprint_covers_performance_and_weather_venue_authority():
    integrity = load_json_config("config/v5_release_integrity_registry.json")
    assert "config/venues" in set(integrity["include_roots"])
    assert "config/v5_performance_budgets.json" in set(integrity["include_files"])


def test_existing_workflows_cover_beta6_without_new_workflow_family():
    unified = Path(".github/workflows/v5-unified-gate.yml").read_text(encoding="utf-8")
    shadow = Path(".github/workflows/v5-shadow-cycle.yml").read_text(encoding="utf-8")

    assert "v5-beta6-roadmap" in unified
    assert "tests/test_v5_runtime_performance_policy.py" in unified
    assert "v5-beta6-roadmap" in shadow
    assert "decision_pipeline_hard_limit_seconds" in shadow
    assert "orchestrator_wall_ms" in shadow
