from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _module_path(module: str) -> Path:
    return ROOT / (module.replace(".", "/") + ".py")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_every_registered_service_has_real_module_matching_command_and_contracts():
    registry = json.loads((ROOT / "config/service_registry.json").read_text())
    contracts = json.loads((ROOT / "config/service_contract_registry.json").read_text())["contracts"]
    services = registry["services"]

    expected_ids = [
        "raw_snapshot",
        "enrichment",
        "prediction",
        "validation",
        "optimization",
        "user_decision_overlay",
        "personal_gw_scorecard",
        "governance",
    ]
    assert [row["id"] for row in services] == expected_ids
    assert len(services) == registry["guardrails"]["service_count"] == 8
    assert len({row["id"] for row in services}) == len(services)

    for service in services:
        assert service["boundary_state"] == "INDEPENDENT", service["id"]
        assert _module_path(service["module"]).is_file(), service["module"]
        command = service["command"]
        assert "-m" in command, service["id"]
        module_index = command.index("-m") + 1
        assert command[module_index] == service["module"], service["id"]
        assert service["id"] not in (service.get("depends_on") or []), service["id"]
        assert len(service.get("depends_on") or []) == len(set(service.get("depends_on") or [])), service["id"]
        for produced in service.get("produces") or []:
            assert produced in contracts, (service["id"], produced)


def test_registered_contract_producers_are_unique_and_complete():
    registry = json.loads((ROOT / "config/service_registry.json").read_text())
    contracts = json.loads((ROOT / "config/service_contract_registry.json").read_text())["contracts"]
    produced = [name for row in registry["services"] for name in (row.get("produces") or [])]
    assert len(produced) == len(set(produced))
    assert all((contracts[name].get("path") or "").strip() for name in produced)


def test_architecture_guard_is_startup_assurance_not_runtime_microservice():
    registry = json.loads((ROOT / "config/service_registry.json").read_text())
    registered = {row["module"] for row in registry["services"]}
    assert "src.services.architecture_guard_service" not in registered
    orchestrator = (ROOT / "src/services/orchestrator.py").read_text(encoding="utf-8")
    assert "from src.services import architecture_guard_service" in orchestrator
    assert "startup_assurance = architecture_guard_service.run()" in orchestrator


def test_support_modules_are_not_accidental_business_microservices():
    registry = json.loads((ROOT / "config/service_registry.json").read_text())
    registered = {row["module"] for row in registry["services"]}
    support_only = {
        "src.services.orchestrator",
        "src.services.hot_orchestrator",
        "src.services.contracts",
        "src.services.checkpoint_timing_probe",
        "src.services.runtime_publish_stamp",
        "src.services.competitive_load_service",
        "src.services.architecture_guard_service",
        "src.services.prediction_model_cache",
    }
    assert not (registered & support_only)


def test_validation_boundary_preserves_old_artifact_contracts():
    registry = json.loads((ROOT / "config/service_registry.json").read_text())
    row = next(item for item in registry["services"] if item["id"] == "validation")
    assert set(row["produces"]) == {
        "validation_lifecycle",
        "reconciliation_readiness",
        "compliance",
        "framework_preflight",
    }


def test_governance_boundary_preserves_old_artifact_contracts():
    registry = json.loads((ROOT / "config/service_registry.json").read_text())
    row = next(item for item in registry["services"] if item["id"] == "governance")
    assert set(row["produces"]) == {"framework_postflight", "checkpoint_decision"}


def test_manual_authority_registry_points_to_user_overlay_owner():
    extensions = json.loads((ROOT / "config/dss_extension_registry.json").read_text())
    row = next(item for item in extensions["modules"] if item["id"] == "DSS-X09")
    required = set(row["required_files"])
    assert "src/services/user_decision_overlay_service.py" in required
    assert "config/manual_lineup.json" in required


def test_enhancement_decision_vocabulary_matches_canonical_arbitration():
    enhancements = json.loads((ROOT / "config/enhancement_layers_registry.json").read_text())
    row = next(item for item in enhancements["layers"] if item["id"] == "ENH-08")
    capabilities = " ".join(row["capabilities"])
    assert "HOLD/REVIEW/CHANGE" in capabilities
    assert "GO/HOLD/WAIT/REJECT" not in capabilities
    assert "src/engines/v4_decision_arbitration.py" in row["required_files"]


def test_duplicate_legacy_calibration_module_is_removed():
    assert not (ROOT / "src/models/calibration.py").exists()
    assert (ROOT / "src/models/metrics.py").is_file()
    imports = set().union(*(_imports(path) for path in (ROOT / "src").rglob("*.py")))
    assert "src.models.calibration" not in imports


def test_registry_cardinality_and_ids_are_canonical():
    core = json.loads((ROOT / "config/dss_core_registry.json").read_text())["modules"]
    extensions = json.loads((ROOT / "config/dss_extension_registry.json").read_text())["modules"]
    enhancements = json.loads((ROOT / "config/enhancement_layers_registry.json").read_text())["layers"]
    gate0 = json.loads((ROOT / "config/gate0_registry.json").read_text())["checks"]

    assert [row["id"] for row in core] == [f"DSS-{index:02d}" for index in range(1, 51)]
    assert [row["id"] for row in extensions] == [f"DSS-X{index:02d}" for index in range(1, 17)]
    assert [row["id"] for row in enhancements] == [f"ENH-{index:02d}" for index in range(1, 9)]
    assert len(gate0) == 16
    assert len({row["id"] for row in gate0}) == 16
