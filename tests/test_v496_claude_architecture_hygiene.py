from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(ROOT).with_suffix("").parts)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_superseded_wc_decision_writer_is_removed():
    assert not (ROOT / "src/engines/v4_wc_decision.py").exists()


def test_metrics_and_leakage_have_single_registered_owners():
    ownership = json.loads((ROOT / "config/architecture_ownership_registry.json").read_text())
    primitives = {row["id"]: row for row in ownership["shared_primitives"]}
    assert primitives["MODEL_EVALUATION_METRICS"]["implementation"] == "src.models.metrics"
    assert primitives["PREDICTIVE_LEAKAGE_TIMING"]["implementation"] == "src.engines.leakage_guard.availability_before_deadline"

    model_registry = (ROOT / "src/models/model_registry.py").read_text()
    calibration = (ROOT / "src/models/v4_calibration.py").read_text()
    reliability = (ROOT / "src/engines/reliability.py").read_text()
    assert "from src.models.metrics import" in model_registry
    assert "from src.models.metrics import" in calibration
    assert "availability_before_deadline" in calibration
    assert "availability_before_deadline" in reliability


def test_dormant_modules_are_registry_classified_and_not_production_imported():
    ownership = json.loads((ROOT / "config/architecture_ownership_registry.json").read_text())
    lifecycle = {row["module"]: row for row in ownership.get("module_lifecycle", [])}
    assert lifecycle["src.models.rank_sim"]["status"] == "DORMANT_EXPERIMENTAL"
    assert lifecycle["src.models.rank_sim"]["production_import_allowed"] is False

    production_paths = [p for p in (ROOT / "src").rglob("*.py") if _module_name(p) != "src.models.rank_sim"]
    imports = set().union(*(_imports(path) for path in production_paths))
    assert "src.models.rank_sim" not in imports


def test_recent_competitive_load_contract_is_truthful_about_runtime_consumption():
    cfg = json.loads((ROOT / "config/recent_competitive_load.json").read_text())
    status = cfg["runtime_consumption"]
    assert status["status"] == "EXTERNAL_REPORT_EVIDENCE_REQUIRED"
    assert status["automated_python_consumer"] is None
    assert status["visible_report_executor_must_verify"] is True
    assert status["future_automation_requires_new_registered_consumer"] is True


def test_release_manifest_points_to_current_ownership_registry():
    manifest = json.loads((ROOT / "config/release_manifest.json").read_text())
    ownership = json.loads((ROOT / "config/architecture_ownership_registry.json").read_text())
    assert manifest["registries"]["ownership"] == ownership["registry"]
