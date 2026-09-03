from __future__ import annotations

from pathlib import Path

from src.runtime_v3.precompute_target_execution import resolve_target_execution

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_package_import_is_dependency_light_and_side_effect_free() -> None:
    source = (ROOT / "src" / "runtime_v3" / "__init__.py").read_text(encoding="utf-8")
    assert "frontier_evidence_contract" not in source
    assert "numpy" not in source
    assert "install(" not in source


def test_exhaustive_optimizer_explicitly_owns_richer_frontier_installation() -> None:
    from src.engines import package_optimizer_exhaustive_accelerated as accelerated
    from src.engines import package_optimizer_exhaustive_finalize as base
    from src.runtime_v3 import frontier_evidence_contract as frontier

    assert base._Frontier is frontier.Frontier
    assert base._metrics is frontier.metrics
    assert base._dominates is frontier.dominates
    assert accelerated.exact_skyline_indices is frontier.skyline_indices


def test_target_execution_mapping_is_registry_driven_for_deep_deadline_live_and_silent() -> None:
    deep = resolve_target_execution("NORMAL_DEEP_REVIEW")
    assert deep["seed_profile"] == "deep_stats"
    assert deep["execution_mode"] == "daily"
    assert deep["execution_extra"] == "--deep-stats"
    assert deep["deep_stats"] is True

    deadline = resolve_target_execution("DEADLINE_DAY")
    assert deadline["seed_profile"] == "fast_decision"
    assert deadline["execution_mode"] == "deadline"
    assert deadline["execution_extra"] == ""

    live = resolve_target_execution("MATCH_MODE")
    assert live["seed_profile"] == "live"
    assert live["execution_mode"] == "live"
    assert live["execution_extra"] == ""

    silent = resolve_target_execution("SILENT")
    assert silent["selected_mode_key"] == "DEFAULT"
    assert silent["seed_profile"] == "fast_decision"
    assert silent["execution_mode"] == "daily"
    assert silent["execution_extra"] == ""

    assert {deep["authority_profile"], deadline["authority_profile"], live["authority_profile"], silent["authority_profile"]} == {"exhaustive_precompute"}


def test_sharded_workflow_consumes_target_execution_outputs_instead_of_reimplementing_mapping() -> None:
    workflow = (ROOT / ".github" / "workflows" / "v3-package-precompute.yml").read_text(encoding="utf-8")
    assert "python -m src.runtime_v3.precompute_target_execution" in workflow
    assert "TARGET_EXECUTION_MODE" in workflow
    assert "TARGET_EXECUTION_PROFILE" in workflow
    assert "TARGET_EXECUTION_EXTRA" in workflow
    assert "AUTHORITY_PROFILE" in workflow
    assert "domain_orchestrator --mode daily --stats --profile fast_decision" not in workflow
    assert "sharded_pipeline_resume --mode daily --stats --profile exhaustive_precompute" not in workflow
