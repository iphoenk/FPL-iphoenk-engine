import json
import importlib.util
import subprocess
from pathlib import Path

import pytest

from src.services.contracts import MISSING, validate_contract, value_at
from src.services.orchestrator import _ordered_services, _render_command, orchestrate


ROOT = Path(__file__).resolve().parents[1]


def test_registered_services_are_ordered_and_contract_complete():
    services = json.loads((ROOT / "config/service_registry.json").read_text())
    contracts = json.loads((ROOT / "config/service_contract_registry.json").read_text())
    ordered = _ordered_services(services)
    assert len(ordered) == 8
    assert ordered[0]["id"] == "raw_snapshot"
    assert ordered[-1]["id"] == "report_governance"
    assert all(row["boundary_state"] == "INDEPENDENT" for row in ordered)
    assert [row["id"] for row in ordered[:3]] == ["raw_snapshot", "enrichment", "prediction"]
    declared = contracts["contracts"]
    assert all(name in declared for service in ordered for name in service["produces"])
    assert services["guardrails"]["gate0_checks_unchanged"] == 16
    assert services["guardrails"]["registry_counts_unchanged"] == {
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
