import json
from pathlib import Path

from src.engines.v4_wc_optimizer import build_candidates
from src.engines.v4_wc_package_audit import _fast_metrics, audit_packages_from_candidates
from src.engines.v4_wc_package_audit_fast import (
    _chosen_profile,
    _keep_profile,
    _metrics_from_profiles,
    audit_packages_from_candidates_fast,
)


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
    assert perf["exact_streaming_top_packages"] is True
    assert perf["stable_top_package_tie_semantics"] is True
    assert perf["full_result_sort_removed"] is True
    assert perf["target_metrics_cache_removed"] is True
    assert perf["sorted_keep_position_prefixes"] is True
    assert perf["unaffected_position_prefix_reuse"] is True
    assert perf["chosen_profile_cache_entries"] > 0
    assert perf["chosen_profile_cache_hits"] > 0
    assert perf["search_quality_reduction"] is False
    assert perf["evaluated_packages"] == reference["performance"]["evaluated_packages"]


def test_prefix_metric_evaluator_matches_reference_metric_semantics():
    predictions = _load("data/predictions_v4.json")
    universe = _load("data/universe.json")
    locked = _load("config/locked_squad.json")
    candidates = build_candidates(predictions, universe)
    by_element = {player.element: player for player in candidates}
    squad = [by_element[int(row["element"])] for row in locked["players"]]

    # Deliberately split the same legal 15 into keep/chosen components. The
    # prefix evaluator must reconstruct the exact reference metrics regardless
    # of which positions happen to be in the chosen component.
    keep = squad[:-4]
    chosen = squad[-4:]
    reference = _fast_metrics(squad, include_detail=False)
    optimized = _metrics_from_profiles(_keep_profile(keep), _chosen_profile(chosen))

    assert optimized == reference
