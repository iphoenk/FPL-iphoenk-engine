import json
from pathlib import Path

from src.engines.v4_wc_optimizer import build_candidates
from src.engines.v4_wc_package_audit import audit_packages_from_candidates
from src.engines.v4_wc_package_audit_fast import audit_packages_from_candidates_fast


ROOT = Path(__file__).resolve().parents[1]


def _load(path: str):
    return json.loads((ROOT / path).read_text())


def test_compact_package_audit_matches_reference_acceptance_snapshot():
    predictions = _load("data/predictions_v4.json")
    universe = _load("data/universe.json")
    locked = _load("config/locked_squad.json")
    candidates = build_candidates(predictions, universe)

    reference = audit_packages_from_candidates(candidates, locked)
    optimized = audit_packages_from_candidates_fast(candidates, locked)

    assert optimized["overall_verdict"] == reference["overall_verdict"]
    assert optimized["recommended_package"] == reference["recommended_package"]
    assert optimized["best_by_replacement_count"] == reference["best_by_replacement_count"]
    assert optimized["packages"] == reference["packages"]
    assert optimized["baseline"] == reference["baseline"]
    assert optimized["affordability"] == reference["affordability"]
    assert optimized["frontier_players"] == reference["frontier_players"]
    assert optimized["max_replacements"] == reference["max_replacements"]

    perf = optimized["performance"]
    assert perf["compact_keep_profile"] is True
    assert perf["scalar_delta_metrics"] is True
    assert perf["position_value_reuse"] is True
    assert perf["search_quality_reduction"] is False
    assert perf["evaluated_packages"] == reference["performance"]["evaluated_packages"]
