import json
from pathlib import Path

from src.runtime_v3.registry_compiler import compile_execution_plan

ROOT = Path(__file__).resolve().parents[1]


def _json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_canonical_registry_has_eleven_runtime_services_and_covers_legacy_steps_once():
    execution = _json("config/runtime/execution_registry.json")
    implementation = _json("config/v3_service_registry.json")["services"]
    assert execution["registry"] == "V3_CANONICAL_EXECUTION_REGISTRY_V1"
    assert execution["phase_count"] == 6
    assert execution["service_count"] == 11
    assert execution["canonical_phases"] == {
        "ACQUIRE": ["official_state", "personal_team_state"],
        "ENRICH": ["football_context", "market_context"],
        "MODEL": ["prediction"],
        "DECISION": ["squad_decision", "challenger_analysis"],
        "GOVERNANCE": ["framework_governance", "prediction_validation"],
        "PUBLISH": ["reporting", "serving"],
    }
    steps = [step for spec in execution["services"].values() for step in spec["implementation_steps"]]
    assert len(steps) == 21
    assert len(set(steps)) == 21
    assert set(steps) == set(implementation)


def test_non_negotiable_boundaries_remain_separate():
    execution = _json("config/runtime/execution_registry.json")
    services = execution["services"]
    assert services["prediction"]["implementation_steps"] == ["prediction"]
    assert services["squad_decision"]["implementation_steps"] == ["lineup_governance"]
    assert services["challenger_analysis"]["implementation_steps"] == ["challenger"]
    assert services["prediction_validation"]["implementation_steps"] == ["prediction_evaluation"]
    assert services["framework_governance"]["implementation_steps"] == ["governance"]
    assert services["reporting"]["implementation_steps"] == ["watchlist", "reporting"]
    assert services["serving"]["implementation_steps"] == ["report_materializer"]
    assert "prediction_validation" in services["framework_governance"]["depends_on"]
    assert execution["policy"]["prediction_separate_from_decision"] is True
    assert execution["policy"]["decision_separate_from_challenger"] is True
    assert execution["policy"]["prediction_production_separate_from_validation"] is True
    assert execution["policy"]["governance_separate_from_reporting"] is True


def test_compiled_plan_is_deterministic_and_matches_expected_waves():
    first = compile_execution_plan(write=False)
    second = compile_execution_plan(write=False)
    assert first == second
    assert first["service_count"] == 11
    assert first["implementation_step_count"] == 21
    assert first["waves"] == [
        ["official_state"],
        ["personal_team_state"],
        ["football_context"],
        ["market_context", "prediction"],
        ["squad_decision", "prediction_validation"],
        ["challenger_analysis"],
        ["framework_governance"],
        ["reporting"],
        ["serving"],
    ]
    assert first["module_batches_runtime_authority"] is False
    assert first["plan_hash"] == second["plan_hash"]


def test_legacy_execution_domains_are_compatibility_projection_not_active_ssot():
    legacy_domains = _json("config/runtime/execution_domains.json")
    execution = _json("config/runtime/execution_registry.json")
    for service_id, spec in execution["services"].items():
        assert legacy_domains["domains"][service_id]["capabilities"] == spec["implementation_steps"]
    assert legacy_domains["domain_count"] == execution["service_count"]


def test_active_runtime_uses_compiled_orchestrator_and_workflow_remains_single_scheduler():
    workflows = ROOT / ".github/workflows"
    runtime = (workflows / "v3-runtime.yml").read_text(encoding="utf-8")
    compat = (workflows / "fpl-engine.yml").read_text(encoding="utf-8")
    assert "python -m src.runtime_v3.compiled_orchestrator" in runtime
    assert "python -m src.runtime_v3.registry_compiler --check" in runtime
    assert "schedule:" in runtime
    assert "schedule:" not in compat
    assert not (workflows / "v3-runtime-fast.yml").exists()
    assert not (workflows / "v3-refresh-full.yml").exists()


def test_module_batches_are_not_imported_by_active_control_plane():
    orchestrator = (ROOT / "src/runtime_v3/compiled_orchestrator.py").read_text(encoding="utf-8")
    runner = (ROOT / "src/runtime_v3/coarse_service_runner.py").read_text(encoding="utf-8")
    assert "module_batch_runner" not in orchestrator
    assert "module_batch_runner" not in runner
