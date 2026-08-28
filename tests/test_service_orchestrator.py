import json
import importlib.util
import subprocess
from pathlib import Path

import pytest

from src.services.contracts import MISSING, validate_contract, value_at
from src.services.orchestrator import _ordered_services, _render_command, _service_levels, orchestrate


ROOT = Path(__file__).resolve().parents[1]


def test_registered_services_are_ordered_and_contract_complete():
    services = json.loads((ROOT / "config/service_registry.json").read_text())
    contracts = json.loads((ROOT / "config/service_contract_registry.json").read_text())
    ordered = _ordered_services(services)
    levels = _service_levels(services)
    ids = [row["id"] for row in ordered]
    by_id = {row["id"]: row for row in ordered}
    assert len(ordered) == 11
    assert ordered[0]["id"] == "raw_snapshot"
    assert ordered[-1]["id"] == "report_governance"
    assert all(row["boundary_state"] == "INDEPENDENT" for row in ordered)
    assert ids[:3] == ["raw_snapshot", "enrichment", "prediction"]
    assert set(by_id["rules_compliance"]["depends_on"]) == {"prediction"}
    assert set(by_id["validation_lifecycle"]["depends_on"]) == {"prediction"}
    assert set(by_id["framework_preflight"]["depends_on"]) == {"validation_lifecycle", "rules_compliance"}
    assert ids.index("optimization") < ids.index("user_decision_overlay") < ids.index("personal_gw_scorecard")
    assert set(ordered[-1]["depends_on"]) == {"framework_postflight", "personal_gw_scorecard"}
    assert any({row["id"] for row in level} == {"validation_lifecycle", "rules_compliance"} for level in levels)
    assert any({row["id"] for row in level} == {"personal_gw_scorecard", "framework_postflight"} for level in levels)
    declared = contracts["contracts"]
    assert all(name in declared for service in ordered for name in service["produces"])
    guardrails = services["guardrails"]
    assert services["execution_model"] == "process_isolated_dag_parallel_single_host"
    assert guardrails["gate0_checks_unchanged"] == 16
    assert guardrails["validation_lifecycle_no_official_refetch"] is True
    assert guardrails["deadline_snapshot_immutable"] is True
    assert guardrails["retroactive_snapshot_rejected"] is True
    assert guardrails["reconciliation_archive_immutable"] is True
    assert guardrails["reconciliation_idempotent"] is True
    assert guardrails["health_view_current_model_only"] is True
    assert guardrails["personal_gw_scorecard_no_official_refetch"] is True
    assert guardrails["finished_gw_archive_immutable"] is True
    assert guardrails["scorecard_simulation_never_mutates_archive"] is True
    assert guardrails["scorecard_projection_from_effective_plan_contract"] is True
    assert guardrails["user_decision_overlay_process_isolated"] is True
    assert guardrails["engine_is_advisory"] is True
    assert guardrails["user_decision_is_final_authority"] is True
    assert guardrails["engine_never_auto_overwrites_valid_user_override"] is True
    assert guardrails["projection_default_baseline_previous_submitted_gw"] is True
    assert guardrails["planning_override_requires_target_gw"] is True
    assert guardrails["stale_planning_override_rejected"] is True
    assert guardrails["advanced_ablation_observational_outside_decision_chain"] is True
    assert guardrails["advanced_ablation_full_shadow_parity_required"] is True
    assert guardrails["advanced_ablation_diagnostic_not_arbitrary_gate"] is True
    assert guardrails["official_fpl_first_when_field_available"] is True
    assert guardrails["dag_parallel_ready_services"] is True
    assert guardrails["parallel_services_must_have_no_dependency_edge"] is True
    assert guardrails["human_report_language_governed"] is True
    assert guardrails["scheduled_checkpoint_recovery_enabled"] is True
    assert guardrails["registry_counts_unchanged"] == {
        "dss_core": 50,
        "dss_extensions": 16,
        "enhancements": 8,
    }
    assert all(importlib.util.find_spec(service["module"]) is not None for service in ordered)


def test_contract_validation_is_fail_closed(tmp_path):
    artifact = tmp_path / "artifact.json"
    artifact.write_text(json.dumps({"schema_version": 5, "state": {"ok": True}, "rows": [1, 2]}))
    spec = {
        "path": "artifact.json",
        "min_schema_version": 5,
        "required_paths": ["state.ok", "rows"],
        "equals": {"state.ok": True},
        "min_lengths": {"rows": 2},
    }
    assert validate_contract("valid", spec, root=tmp_path)["valid"] is True
    broken = dict(spec, required_paths=["state.missing"])
    result = validate_contract("broken", broken, root=tmp_path)
    assert result["valid"] is False
    assert "required_path_missing:state.missing" in result["errors"]
    assert value_at({}, "missing") is MISSING


def _mini_registries():
    services = {
        "registry": "test_services",
        "execution_model": "process_isolated_single_host",
        "guardrails": {"single_snapshot_authority": True},
        "services": [
            {"id": "snapshot", "name": "snapshot", "boundary_state": "TRANSITIONAL_COMPOSITE", "command": ["{python}", "snapshot"], "depends_on": [], "produces": ["latest"], "timeout_seconds": 5},
            {"id": "decision", "name": "decision", "boundary_state": "INDEPENDENT", "command": ["{python}", "decision"], "depends_on": ["snapshot"], "produces": ["decision"], "timeout_seconds": 5},
        ],
    }
    contracts = {
        "registry": "test_contracts",
        "contracts": {
            "latest": {"path": "data/latest.json", "required_paths": ["generated_at"]},
            "decision": {"path": "data/decision.json", "required_paths": ["ok"], "equals": {"ok": True}},
        },
    }
    return services, contracts


def test_orchestrator_runs_dependencies_and_preserves_snapshot(tmp_path):
    services, contracts = _mini_registries()
    data = tmp_path / "data"
    data.mkdir()

    def runner(command, **kwargs):
        if command[-1] == "snapshot":
            (data / "latest.json").write_text(json.dumps({"generated_at": "2026-08-26T00:00:00+00:00"}))
        else:
            (data / "decision.json").write_text(json.dumps({"ok": True}))
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    out = orchestrate(service_registry=services, contract_registry=contracts, runner=runner, root=tmp_path, outfile=data / "orchestration.json")
    assert out["status"] == "PASS"
    assert [row["status"] for row in out["services"]] == ["PASS", "PASS"]
    assert out["snapshot_identity"]["sha256"]


def test_orchestrator_fails_closed_when_downstream_mutates_snapshot(tmp_path):
    services, contracts = _mini_registries()
    data = tmp_path / "data"
    data.mkdir()

    def runner(command, **kwargs):
        if command[-1] == "snapshot":
            (data / "latest.json").write_text(json.dumps({"generated_at": "original"}))
        else:
            (data / "latest.json").write_text(json.dumps({"generated_at": "mutated"}))
            (data / "decision.json").write_text(json.dumps({"ok": True}))
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    with pytest.raises(RuntimeError, match="immutable snapshot changed"):
        orchestrate(service_registry=services, contract_registry=contracts, runner=runner, root=tmp_path, outfile=data / "orchestration.json")
    report = json.loads((data / "orchestration.json").read_text())
    assert report["status"] == "FAIL"
    assert report["summary"]["fail_closed"] is True


def test_runtime_flags_only_reach_services_that_declare_them():
    service = {"command": ["{python}", "-m", "service", "{mode}"], "runtime_flags": {"stats": "--stats", "as_of": "--as-of"}}
    command = _render_command(service, "deadline", True, False, "2026-08-28T21:30:00+07:00")
    assert command[-3:] == ["--stats", "--as-of", "2026-08-28T21:30:00+07:00"]
    assert "deadline" in command


def test_only_raw_snapshot_service_imports_official_fpl_client():
    service_sources = {path.name: path.read_text() for path in (ROOT / "src/services").glob("*.py")}
    importers = {name for name, source in service_sources.items() if "src.sources.official_fpl" in source}
    assert importers == {"raw_snapshot_service.py"}


def test_latest_contract_preserves_file_pointers_including_effective_plan():
    contracts = json.loads((ROOT / "config/service_contract_registry.json").read_text())
    required = set(contracts["contracts"]["latest_snapshot"]["required_paths"])
    assert {f"files.{name}" for name in (
        "team", "live", "prices", "health", "universe", "chips", "predictions",
        "effective_plan", "gw_scorecard", "checkpoint_decision", "service_orchestration",
    )} <= required
    assert {"official_context.source", "official_context.official_fpl_first"} <= required
