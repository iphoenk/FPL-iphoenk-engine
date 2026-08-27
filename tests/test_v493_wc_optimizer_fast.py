import json
from pathlib import Path

from src.engines.v4_wc_optimizer import build_candidates, decision_report_from_candidates
from src.engines.v4_wc_optimizer_fast import decision_report_from_candidates_fast


ROOT = Path(__file__).resolve().parents[1]


def _load(path: str):
    return json.loads((ROOT / path).read_text())


def test_exact_streaming_optimizer_matches_reference_acceptance_snapshot():
    predictions = _load("data/predictions_v4.json")
    universe = _load("data/universe.json")
    locked = _load("config/locked_squad.json")
    candidates = build_candidates(predictions, universe)

    reference = decision_report_from_candidates(candidates, locked)
    optimized = decision_report_from_candidates_fast(candidates, locked)

    assert optimized["optimized_elements"] == reference["optimized_elements"]
    assert optimized["classification"] == reference["classification"]
    assert optimized["delta"] == reference["delta"]
    assert optimized["current"] == reference["current"]
    assert optimized["optimized"] == reference["optimized"]
    assert optimized["out"] == reference["out"]
    assert optimized["in"] == reference["in"]
    assert optimized["direct_challengers"] == reference["direct_challengers"]
    assert optimized["budget_tenths"] == reference["budget_tenths"]

    perf = optimized["performance"]
    assert perf["beam_size_unchanged"] is True
    assert perf["exact_streaming_topk"] is True
    assert perf["stable_tie_semantics"] is True
    assert perf["safe_objective_bound"] is True
    assert perf["fixed_position_finalist_scoring"] is True
    assert perf["finalist_materialization_removed"] is True
    assert perf["search_quality_reduction"] is False
    assert perf["generated_states"] > 0
    assert perf["objective_bound_pruned"] >= 0
