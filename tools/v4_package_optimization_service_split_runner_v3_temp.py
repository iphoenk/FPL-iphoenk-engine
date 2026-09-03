from __future__ import annotations

import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT / "tools/v4_package_optimization_service_split_runner_v2_temp.py"), run_name="__main__")


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one replacement in {relative}, found {count}: {old[:120]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")

# Remove contradictory legacy parallelism claim now that optimization waits on package_optimization.
service_path = ROOT / "config/service_registry.json"
registry = json.loads(service_path.read_text(encoding="utf-8"))
registry["guardrails"]["validation_and_optimization_may_parallelize_after_prediction"] = False
registry["guardrails"]["validation_and_package_optimization_may_parallelize_after_prediction"] = True
service_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")

replace_once(
    "tests/test_v4943_reconciliation_truth_runtime.py",
    "    assert len(services) == declared_count == len(set(ids)) == 8\n",
    "    assert len(services) == declared_count == len(set(ids)) == 9\n    assert \"package_optimization\" in ids\n",
)

replace_once(
    "tests/test_v495_official_first_reporting.py",
    '''    assert by_id["validation"]["depends_on"] == ["prediction"]\n    assert by_id["optimization"]["depends_on"] == ["prediction"]\n    assert level_index["validation"] == level_index["optimization"]\n''',
    '''    assert by_id["validation"]["depends_on"] == ["prediction"]\n    assert by_id["package_optimization"]["depends_on"] == ["prediction"]\n    assert by_id["optimization"]["depends_on"] == ["prediction", "package_optimization"]\n    assert level_index["validation"] == level_index["package_optimization"]\n    assert level_index["optimization"] > level_index["package_optimization"]\n''',
)
replace_once(
    "tests/test_v495_official_first_reporting.py",
    '    assert registry["guardrails"]["validation_and_optimization_may_parallelize_after_prediction"] is True\n',
    '    assert registry["guardrails"]["validation_and_optimization_may_parallelize_after_prediction"] is False\n    assert registry["guardrails"]["validation_and_package_optimization_may_parallelize_after_prediction"] is True\n',
)

replace_once(
    "tests/test_v496_housekeeping_integrity.py",
    '''        "validation",\n        "optimization",\n''',
    '''        "validation",\n        "package_optimization",\n        "optimization",\n''',
)
replace_once(
    "tests/test_v496_housekeeping_integrity.py",
    '    assert len(services) == registry["guardrails"]["service_count"] == 8\n',
    '    assert len(services) == registry["guardrails"]["service_count"] == 9\n',
)
replace_once(
    "tests/test_v496_housekeeping_integrity.py",
    '''    assert set(row["produces"]) == {\n        "wc_decision",\n        "wc_package",\n        "lineup",\n''',
    '''    assert set(row["produces"]) == {\n        "wc_decision",\n        "lineup",\n''',
)
# Add explicit single-writer package boundary assertion rather than silently dropping ownership coverage.
insert_anchor = '''def test_governance_boundary_preserves_and_declares_serving_artifact_contracts():\n'''
path = ROOT / "tests/test_v496_housekeeping_integrity.py"
text = path.read_text(encoding="utf-8")
if text.count(insert_anchor) != 1:
    raise RuntimeError("housekeeping insertion anchor not unique")
new_test = '''def test_package_optimization_boundary_is_single_exact_package_writer():\n    registry = json.loads((ROOT / "config/service_registry.json").read_text())\n    row = next(item for item in registry["services"] if item["id"] == "package_optimization")\n    assert set(row["produces"]) == {\n        "tactical_interaction",\n        "wc_package",\n        "package_optimization_manifest",\n    }\n    producers = [\n        item["id"]\n        for item in registry["services"]\n        if "wc_package" in (item.get("produces") or [])\n    ]\n    assert producers == ["package_optimization"]\n\n\n'''
path.write_text(text.replace(insert_anchor, new_test + insert_anchor), encoding="utf-8")

replace_once(
    "tests/test_v4_final_yellow_closeout.py",
    "    assert len(rows) == 8\n",
    "    assert len(rows) == 9\n    assert rows[\"package_optimization\"][\"module\"] == \"src.services.package_optimization_service\"\n",
)

replace_once(
    "tests/test_v4_match_mode_live_score_contract.py",
    "def test_service_registry_preserves_eight_boundaries_and_uses_live_overlays() -> None:\n",
    "def test_service_registry_preserves_nine_boundaries_and_uses_live_overlays() -> None:\n",
)
replace_once(
    "tests/test_v4_match_mode_live_score_contract.py",
    "    assert len(services) == 8\n",
    "    assert len(services) == 9\n",
)

print("legacy eight-boundary assertions versioned to governed package_optimization service")
