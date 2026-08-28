import ast
import json
import subprocess
from pathlib import Path

import pytest

from src.services.orchestrator import _render_command, _service_levels, orchestrate


ROOT = Path(__file__).resolve().parents[1]


def _mini_registries():
    services = {
        "registry": "mini",
        "execution_model": "process_isolated_dag_parallel_single_host",
        "guardrails": {},
        "services": [
            {
                "id": "snapshot",
                "name": "snapshot",
                "boundary_state": "INDEPENDENT",
                "command": ["python", "snapshot"],
                "depends_on": [],
                "produces": ["latest"],
            },
            {
                "id": "decision",
                "name": "decision",
                "boundary_state": "INDEPENDENT",
                "command": ["python", "decision"],
                "depends_on": ["snapshot"],
                "produces": ["decision"],
            },
        ],
    }
    contracts = {
        "registry": "mini-contracts",
        "contracts": {
            "latest": {"path": "data/latest.json", "required_paths": ["generated_at"]},
            "decision": {"path": "data/decision.json", "required_paths": ["ok"]},
        },
    }
    return services, contracts


def test_service_levels_are_registry_driven_and_dependency_safe():
    registry = json.loads((ROOT / "config/service_registry.json").read_text())
    levels = _service_levels(registry)
    ids = [row["id"] for level in levels for row in level]
    assert len(ids) == len(set(ids)) == len(registry["services"])
    assert set(levels[0][0].keys()) >= {"id", "depends_on"}
    completed = set()
    for level in levels:
        for row in level:
            assert set(row.get("depends_on") or []) <= completed
        completed.update(row["id"] for row in level)


def test_orchestrator_runs_isolated_services_and_validates_contracts(tmp_path):
    services, contracts = _mini_registries()
    data = tmp_path / "data"
    data.mkdir()

    def runner(command, **kwargs):
        if command[-1] == "snapshot":
            (data / "latest.json").write_text(json.dumps({"generated_at": "now"}))
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


def test_orchestrator_surfaces_bounded_service_stderr_on_nonzero_exit(tmp_path):
    services, contracts = _mini_registries()
    data = tmp_path / "data"
    data.mkdir()

    def runner(command, **kwargs):
        if command[-1] == "snapshot":
            (data / "latest.json").write_text(json.dumps({"generated_at": "original"}))
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")
        return subprocess.CompletedProcess(command, 7, stdout="service stdout", stderr="POSTFLIGHT_TRACE_MARKER")

    with pytest.raises(RuntimeError, match="decision exit=7: POSTFLIGHT_TRACE_MARKER"):
        orchestrate(service_registry=services, contract_registry=contracts, runner=runner, root=tmp_path, outfile=data / "orchestration.json")
    report = json.loads((data / "orchestration.json").read_text())
    failed = next(row for row in report["services"] if row["id"] == "decision")
    assert failed["status"] == "FAIL"
    assert failed["stderr_tail"] == "POSTFLIGHT_TRACE_MARKER"


def test_runtime_flags_only_reach_services_that_declare_them():
    service = {"command": ["{python}", "-m", "service", "{mode}"], "runtime_flags": {"stats": "--stats", "as_of": "--as-of"}}
    command = _render_command(service, "deadline", True, False, "2026-08-28T21:30:00+07:00")
    assert command[-3:] == ["--stats", "--as-of", "2026-08-28T21:30:00+07:00"]
    assert "deadline" in command


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_only_raw_snapshot_service_imports_official_fpl_client():
    importers = {
        path.name
        for path in (ROOT / "src/services").glob("*.py")
        if "src.sources.official_fpl" in _imported_modules(path)
    }
    assert importers == {"raw_snapshot_service.py"}


def test_latest_contract_preserves_file_pointers_including_effective_plan():
    contracts = json.loads((ROOT / "config/service_contract_registry.json").read_text())
    required = set(contracts["contracts"]["latest_snapshot"]["required_paths"])
    assert {f"files.{name}" for name in (
        "team", "live", "prices", "health", "universe", "chips", "predictions",
        "effective_plan", "gw_scorecard", "checkpoint_decision", "service_orchestration",
    )} <= required
    assert {"official_context.source", "official_context.official_fpl_first"} <= required
