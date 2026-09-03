from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT / "tools/v4_precompute_microservice_finalize_temp.py"), run_name="__main__")

path = ROOT / "tests/test_v4_package_optimization_service_boundary.py"
text = path.read_text(encoding="utf-8")
old = '''def test_package_and_decision_slos_are_governed_separately():\n    registry = json.loads((v4_package_artifact_contract.CONFIG / "service_registry.json").read_text())\n    guard = registry["guardrails"]\n    assert guard["package_optimization_slo_ms"] == 90000\n    assert guard["decision_compute_slo_ms"] == 5000\n    assert guard["package_slo_separate_from_decision_compute_slo"] is True\n    assert guard["optimization_recomputes_package_search"] is False\n'''
new = '''def test_package_and_decision_slos_are_governed_separately():\n    registry = json.loads((v4_package_artifact_contract.CONFIG / "service_registry.json").read_text())\n    guard = registry["guardrails"]\n    package = next(row for row in registry["services"] if row["id"] == "package_optimization")\n    assert guard["package_optimization_slo_ms"] > guard["decision_compute_slo_ms"]\n    assert package["timeout_seconds"] == guard["package_optimization_process_timeout_seconds"]\n    assert package["execution_role"] == "TARGETED_PRECOMPUTE_WITH_FAST_REUSE"\n    assert package["reuse_authority"] == "SEMANTIC_FINGERPRINT"\n    assert guard["package_optimization_not_part_of_decision_compute_slo"] is True\n    assert guard["package_slo_separate_from_decision_compute_slo"] is True\n    assert guard["optimization_recomputes_package_search"] is False\n'''
if text.count(old) != 1:
    raise RuntimeError(f"expected one legacy SLO assertion block, found {text.count(old)}")
path.write_text(text.replace(old, new), encoding="utf-8")
print("precompute SLO test converted from literal timeout to registry semantics")
