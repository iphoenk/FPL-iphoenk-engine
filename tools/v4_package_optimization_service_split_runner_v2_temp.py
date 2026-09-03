from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT / "tools/v4_package_optimization_service_split_runner_temp.py"), run_name="__main__")

path = ROOT / "tests/test_v4_p1_structural_hardening.py"
text = path.read_text(encoding="utf-8")
old = '''    decision_source = _text("src/engines/v4_decision_pipeline.py")
    assert manifest["registries"]["optimizer_equivalence"] == registry["registry"]
    assert "from src.engines.v4_wc_optimizer_fast import decision_report_from_candidates_fast" in decision_source
    assert "from src.engines.v4_full_universe_package_search import search_full_universe_packages" in decision_source
    assert "decision_report_from_candidates_fast(" in decision_source
    assert "search_full_universe_packages(" in decision_source
    assert "audit_packages_from_candidates_fast(" not in decision_source
'''
new = '''    decision_source = _text("src/engines/v4_decision_pipeline.py")
    package_service_source = _text("src/services/package_optimization_service.py")
    assert manifest["registries"]["optimizer_equivalence"] == registry["registry"]
    assert "from src.engines.v4_wc_optimizer_fast import decision_report_from_candidates_fast" in decision_source
    assert "from src.engines.v4_package_artifact_contract import validate_package_optimization_artifact" in decision_source
    assert "decision_report_from_candidates_fast(" in decision_source
    assert "search_full_universe_packages(" not in decision_source
    assert "validate_package_optimization_artifact()" in decision_source
    assert "from src.engines.v4_full_universe_package_search import search_full_universe_packages" in package_service_source
    assert "search_full_universe_packages(" in package_service_source
    assert "audit_packages_from_candidates_fast(" not in decision_source
'''
if text.count(old) != 1:
    raise RuntimeError(f"structural authority test patch expected once, found {text.count(old)}")
path.write_text(text.replace(old, new), encoding="utf-8")
print("structural authority test aligned to package_optimization single writer")
