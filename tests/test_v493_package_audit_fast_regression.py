import json
from collections import Counter
from itertools import combinations
from pathlib import Path

from src.engines import v4_wc_package_audit as base
from src.engines.v4_wc_optimizer import build_candidates, reconcile_owned_costs
from src.engines.v4_wc_package_audit_fast import (
    _chosen_profile,
    _club_signature,
    _keep_profile,
    _keep_profile_from_baseline,
    _legal_small_candidates,
    _metrics_from_profiles,
    _small_candidate_template,
)

ROOT = Path(__file__).resolve().parents[1]


def _load(path: str):
    return json.loads((ROOT / path).read_text())


def _setup():
    predictions = _load("data/predictions_v4.json")
    universe = _load("data/universe.json")
    locked = _load("config/locked_squad.json")
    cands = build_candidates(predictions, universe)
    cands, affordability = reconcile_owned_costs(cands, locked)
    budget = int(affordability["available_budget_tenths"])
    by = {p.element: p for p in cands}
    ids = {int(row["element"]) for row in locked["players"]}
    cur = [by[element] for element in ids]
    fr = base.frontier(cands, ids, 7)
    bp = {pos: [p for p in fr if p.position == pos] for pos in base.POSITION_COUNTS}
    return cur, bp, budget


def test_k2_candidate_state_generation_matches_reference_exactly():
    cur, bp, budget = _setup()
    basecost = sum(p.cost for p in cur)
    baseline_clubs = _club_signature(cur)

    for outs in combinations(cur, 2):
        outids = {p.element for p in outs}
        need = Counter(p.position for p in outs)
        if any(len(bp[pos]) < count for pos, count in need.items()):
            continue
        reference = base._candidate_states(cur, outids, need, bp, budget, 2, 28)
        template = _small_candidate_template(need, bp)
        keep_cost = basecost - sum(p.cost for p in outs)
        keep_clubs = baseline_clubs
        for player in outs:
            keep_clubs -= 1 << ((player.team_id - 1) * 2)
        optimized = _legal_small_candidates(template, keep_cost, keep_clubs, budget, 2)
        reference_ids = [tuple(p.element for p in chosen) for chosen in reference]
        optimized_ids = [tuple(p.element for p in chosen) for chosen in optimized]
        assert optimized_ids == reference_ids, {
            "outs": [p.element for p in outs],
            "need": dict(need),
            "reference_first": reference_ids[:5],
            "optimized_first": optimized_ids[:5],
        }


def test_baseline_derived_keep_profile_matches_direct_reference_metrics_for_k2():
    cur, bp, budget = _setup()
    baseline_profile = _keep_profile(cur)

    for outs in combinations(cur, 2):
        outids = {p.element for p in outs}
        need = Counter(p.position for p in outs)
        if any(len(bp[pos]) < count for pos, count in need.items()):
            continue
        keep = [p for p in cur if p.element not in outids]
        derived = _keep_profile_from_baseline(baseline_profile, outs)
        for chosen in base._candidate_states(cur, outids, need, bp, budget, 2, 28):
            reference = base._fast_metrics(keep + list(chosen), include_detail=False)
            optimized = _metrics_from_profiles(derived, _chosen_profile(chosen))
            assert optimized == reference, {
                "outs": [p.element for p in outs],
                "chosen": [p.element for p in chosen],
                "reference": reference,
                "optimized": optimized,
            }
