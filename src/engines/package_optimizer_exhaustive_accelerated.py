from __future__ import annotations

import argparse
import json
import math
import os
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from itertools import combinations
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np

from src.engines import package_optimizer_exhaustive_finalize as base
from src.engines.lineup_governance import build_package_decision
from src.models.package_optimizer_exact_batch import ExactBatchScorer
from src.models.package_optimizer_v2 import CompiledPackageScorer, _scoring_context, load_config as load_optimizer_config, simulate_objective
from src.rules import RULESET_ID
from src.runtime_v3.frontier_evidence_contract import install as _install_frontier_evidence_contract, skyline_indices as exact_skyline_indices
from src.utils import CONFIG, DATA, atomic_json, iso_now, read_json

_install_frontier_evidence_contract()
del _install_frontier_evidence_contract

BATCH_SIZE = 512
PAIR_PARALLEL_THRESHOLD = 50_000

_W_CURRENT: list[dict[str, Any]] = []
_W_POOL: dict[str, list[dict[str, Any]]] = {}
_W_ITB = 0
_W_CLUBS: Counter[int] = Counter()
_W_BATCH: ExactBatchScorer | None = None
_W_KEEP = 500
_W_HOLD_H: dict[str, Any] = {}


def _frontier_reduce(packages: list[dict[str, Any]], hold_h: dict[str, Any]) -> list[dict[str, Any]]:
    if len(packages) <= 1:
        return packages
    metrics = np.asarray([base._metrics(package, hold_h) for package in packages], dtype=np.float64)
    return [packages[int(index)] for index in exact_skyline_indices(metrics)]


def _flush_batch(
    pending: list[tuple[dict[str, Any], list[int]]],
    scorer: ExactBatchScorer,
    heap: list,
    frontier: base._Frontier,
    hold_h: dict[str, Any],
    keep: int,
) -> tuple[int, int]:
    if not pending:
        return 0, 0
    scores = scorer.score_ids_compact([candidate_ids for _, candidate_ids in pending], changes=2)
    scored_packages: list[dict[str, Any]] = []
    valid = 0
    for (package, _), score in zip(pending, scores):
        if not score.get("valid"):
            continue
        package["score"] = score
        base._push(heap, package, keep)
        scored_packages.append(package)
        valid += 1
    for package in _frontier_reduce(scored_packages, hold_h):
        frontier.add(package)
    fallback_count = int(scorer.last_scalar_fallback_count)
    pending.clear()
    return valid, fallback_count


def _init_worker(
    players: list[dict[str, Any]],
    current: list[dict[str, Any]],
    pool: dict[str, list[dict[str, Any]]],
    itb: int,
    context: dict[str, Any],
    keep: int,
    hold_h: dict[str, Any],
) -> None:
    global _W_CURRENT, _W_POOL, _W_ITB, _W_CLUBS, _W_BATCH, _W_KEEP, _W_HOLD_H
    _W_CURRENT = current
    _W_POOL = pool
    _W_ITB = int(itb)
    _W_CLUBS = Counter(int(row.get("team_id") or -1) for row in current)
    _W_BATCH = ExactBatchScorer(players, int(context.get("planning_gw") or 1), scoring_context=context)
    _W_KEEP = int(keep)
    _W_HOLD_H = hold_h


def _pair_partition(task: tuple[int, int]) -> dict[str, Any]:
    if _W_BATCH is None:
        raise RuntimeError("accelerated pair worker not initialized")
    ia, ib = task
    out_a, out_b = _W_CURRENT[ia], _W_CURRENT[ib]
    outs = [out_a, out_b]
    out_ids = {int(out_a["element"]), int(out_b["element"])}
    base_squad = [row for row in _W_CURRENT if int(row["element"]) not in out_ids]
    pos_a, pos_b = str(out_a.get("position")), str(out_b.get("position"))
    incoming_iter = combinations(_W_POOL[pos_a], 2) if pos_a == pos_b else ((left, right) for left in _W_POOL[pos_a] for right in _W_POOL[pos_b])

    heap: list[tuple[float, str, dict[str, Any]]] = []
    frontier = base._Frontier(_W_HOLD_H)
    pending: list[tuple[dict[str, Any], list[int]]] = []
    considered = step_legal = exact_scored = cash_rejected = club_rejected = scalar_fallbacks = 0

    for in_a, in_b in incoming_iter:
        considered += 1
        ins = [in_a, in_b]
        structural, reason = base._structural_ok(_W_CLUBS, outs, ins, _W_ITB)
        if not structural:
            cash_rejected += int(reason == "cash")
            club_rejected += int(reason == "club")
            continue
        legal, assigned, sequence = base._pair_sequence(_W_CURRENT, _W_CLUBS, outs, ins, _W_ITB)
        if not legal:
            continue
        step_legal += 1
        package = base._record(2, outs, assigned, {}, sequence, _W_ITB)
        candidate = base_squad + assigned
        pending.append((package, [int(row["element"]) for row in candidate]))
        if len(pending) >= BATCH_SIZE:
            scored, fallbacks = _flush_batch(pending, _W_BATCH, heap, frontier, _W_HOLD_H, _W_KEEP)
            exact_scored += scored
            scalar_fallbacks += fallbacks

    scored, fallbacks = _flush_batch(pending, _W_BATCH, heap, frontier, _W_HOLD_H, _W_KEEP)
    exact_scored += scored
    scalar_fallbacks += fallbacks
    return {
        "pair_candidate_combinations": considered,
        "pair_structural_cash_rejected": cash_rejected,
        "pair_structural_club_rejected": club_rejected,
        "pair_step_legal": step_legal,
        "pair_candidates_exact_scored": exact_scored,
        "batch_scalar_fallback_count": scalar_fallbacks,
        "top": [row[2] for row in heap],
        "frontier": [package for _, package in frontier.rows],
    }


def _rehydrate_top_scores(
    packages: list[dict[str, Any]],
    current: list[dict[str, Any]],
    pool: dict[str, list[dict[str, Any]]],
    scalar: CompiledPackageScorer,
) -> None:
    rows = {int(row["element"]): row for row in current}
    for position_rows in pool.values():
        rows.update({int(row["element"]): row for row in position_rows})
    for package in packages:
        changes = int(package.get("changes") or 0)
        if changes == 0:
            continue
        out_ids = {int(row["element"]) for row in package.get("outs") or []}
        in_ids = [int(row["element"]) for row in package.get("ins") or []]
        candidate = [row for row in current if int(row["element"]) not in out_ids] + [rows[element] for element in in_ids]
        score = scalar.score(candidate, changes=changes)
        if not score.get("valid"):
            raise RuntimeError(f"canonical top-package rehydration failed: {package.get('id')}")
        package["score"] = score


def build_exhaustive(projections: dict[str, Any], team: dict[str, Any], *, top_keep: int = 500) -> dict[str, Any]:
    started = time.perf_counter()
    cfg = load_optimizer_config()
    gw = int(projections.get("planning_gw") or 1)
    context = _scoring_context(cfg, gw)
    context["planning_gw"] = gw
    current = base._current(projections, team)
    owned = {int(row["element"]) for row in current}
    pool, universe_counts = base._pool(projections, owned, cfg)
    eligible = {position: len(rows) for position, rows in pool.items()}
    itb = int((team.get("totals") or {}).get("itb") or 0)
    clubs = Counter(int(row.get("team_id") or -1) for row in current)
    scalar = CompiledPackageScorer(projections.get("players") or [], gw, scoring_context=context)

    hold_score = scalar.score(current, changes=0)
    hold = base._record(0, [], [], hold_score, {"resulting_itb": itb, "steps": [], "execution_order": [], "orders_checked": 1}, itb)
    hold_h = hold_score.get("horizons") or {}
    keep = max(20, int(top_keep))
    heap: list[tuple[float, str, dict[str, Any]]] = [(base._f(hold_score.get("robust_score")), "HOLD", hold)]
    frontier = base._Frontier.from_hold(hold)
    frontier.add(hold)

    single_considered = single_legal = single_scored = single_cash = single_club = 0
    for outgoing in current:
        residual = [row for row in current if int(row["element"]) != int(outgoing["element"])]
        for incoming in pool[str(outgoing.get("position"))]:
            single_considered += 1
            structural, reason = base._structural_ok(clubs, [outgoing], [incoming], itb)
            if not structural:
                single_cash += int(reason == "cash")
                single_club += int(reason == "club")
                continue
            legal, sequence = base._fast_step_sequence(current, clubs, [outgoing], [incoming], itb)
            if not legal:
                continue
            single_legal += 1
            package = base._record(1, [outgoing], [incoming], {}, sequence, itb)
            single_scored += base._collect(package, residual + [incoming], 1, scalar, heap, frontier, keep)

    pair_tasks = [(i, j) for i, j in combinations(range(len(current)), 2)]
    estimated_pairs = base._estimated_pair_combinations(current, pool)
    workers = min(max(1, int(os.cpu_count() or 1)), len(pair_tasks)) if estimated_pairs >= PAIR_PARALLEL_THRESHOLD else 1
    pair_considered = pair_legal = pair_scored = pair_cash = pair_club = scalar_fallbacks = 0

    args = (projections.get("players") or [], current, pool, itb, context, keep, hold_h)
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker, initargs=args) as executor:
            results = executor.map(_pair_partition, pair_tasks, chunksize=1)
            for result in results:
                pair_considered += int(result["pair_candidate_combinations"])
                pair_cash += int(result["pair_structural_cash_rejected"])
                pair_club += int(result["pair_structural_club_rejected"])
                pair_legal += int(result["pair_step_legal"])
                pair_scored += int(result["pair_candidates_exact_scored"])
                scalar_fallbacks += int(result["batch_scalar_fallback_count"])
                for package in result["top"]:
                    base._push(heap, package, keep)
                for package in result["frontier"]:
                    frontier.add(package)
    else:
        _init_worker(*args)
        for task in pair_tasks:
            result = _pair_partition(task)
            pair_considered += int(result["pair_candidate_combinations"])
            pair_cash += int(result["pair_structural_cash_rejected"])
            pair_club += int(result["pair_structural_club_rejected"])
            pair_legal += int(result["pair_step_legal"])
            pair_scored += int(result["pair_candidates_exact_scored"])
            scalar_fallbacks += int(result["batch_scalar_fallback_count"])
            for package in result["top"]:
                base._push(heap, package, keep)
            for package in result["frontier"]:
                frontier.add(package)

    evaluated = 1 + single_scored + pair_scored
    top = [row[2] for row in heap]
    _rehydrate_top_scores(top, current, pool, scalar)
    top.sort(key=lambda package: (base._f((package.get("score") or {}).get("robust_score")), str(package.get("id") or "")), reverse=True)

    mc_top = int(cfg.get("monte_carlo_top_n") or 20)
    hold_mean = base._f(hold_score.get("objective_mean"))
    hold_std = base._f(hold_score.get("objective_std"))
    for index, package in enumerate(top[:mc_top]):
        score = package.get("score") or {}
        mean = base._f(score.get("objective_mean"))
        std = base._f(score.get("objective_std"))
        mc = simulate_objective(mean, std, int(cfg.get("monte_carlo_simulations") or 300), int(cfg.get("monte_carlo_seed") or 1) + index)
        diff_std = math.sqrt(std * std + hold_std * hold_std)
        mc["p_outperform_hold_independent_baseline"] = round(1.0 - NormalDist(mu=mean - hold_mean, sigma=diff_std).cdf(0.0), 4) if diff_std > 0 else (1.0 if mean > hold_mean else 0.5 if mean == hold_mean else 0.0)
        package["monte_carlo"] = mc

    preview_n = max(1, int(cfg.get("candidate_pool_preview_per_position") or 20))
    preview = {
        position: [
            {"element": row["element"], "name": row.get("name"), "now_cost": row.get("now_cost"), "candidate_score": round(base._f(row.get("candidate_score")), 3)}
            for row in rows[:preview_n]
        ]
        for position, rows in pool.items()
    }
    frontier_out = frontier.output(int((cfg.get("frontier") or {}).get("publish_limit") or 20), evaluated)
    elapsed = round((time.perf_counter() - started) * 1000.0, 3)
    diagnostics = {
        **universe_counts,
        "candidate_origin": "COMPLETE_ELIGIBLE_OFFICIAL_FPL_UNIVERSE",
        "eligible_universe_count": sum(eligible.values()),
        "eligible_by_position": eligible,
        "search_method": "ZERO_CANDIDATE_PRUNING_EXHAUSTIVE_SEQUENTIAL_EXACT_V3_GUARDED_BATCH",
        "candidate_pruning_applied": False,
        "candidate_pruned_count": 0,
        "fixed_top_n_per_position_applied": False,
        "fixed_top_n_per_outgoing_applied": False,
        "watchlist_used_as_optimizer_input": False,
        "single_candidates_considered": single_considered,
        "single_structural_cash_rejected": single_cash,
        "single_structural_club_rejected": single_club,
        "single_step_legal": single_legal,
        "single_exact_scored": single_scored,
        "single_budget_applied": False,
        "pair_generation_origin": "DIRECT_OUTGOING_PAIR_X_COMPLETE_POSITION_ELIGIBLE_INCOMING_POOLS",
        "pair_requires_single_move_seed": False,
        "pair_candidate_combinations": pair_considered,
        "pair_structural_cash_rejected": pair_cash,
        "pair_structural_club_rejected": pair_club,
        "pair_step_legal": pair_legal,
        "pair_candidates_exact_scored": pair_scored,
        "pair_budget_applied": False,
        "exact_package_limit_applied": False,
        "all_step_legal_packages_scored": single_scored == single_legal and pair_scored == pair_legal,
        "lossy_pruning": False,
        "search_authority": "FULL",
        "compiled_exact_kernel": True,
        "guarded_batch_acceleration": True,
        "batch_size": BATCH_SIZE,
        "batch_scalar_fallback_count": scalar_fallbacks,
        "batch_scalar_fallback_rate": round(scalar_fallbacks / max(1, pair_scored), 6),
        "parallel_partitioning": workers > 1,
        "parallel_workers": workers,
        "estimated_pair_combinations": estimated_pairs,
        "chunk_skyline_reduction_exact": True,
        "top_packages_canonical_scalar_rehydrated": True,
        "authority_reason": "complete eligible Official FPL universe; zero candidate pruning; only provably illegal structural rejects; every sequentially legal package scored by guarded canonical-equivalent batch kernel with scalar fallback at numerical boundaries",
        "optimizer_runtime_status_separate_from_search_authority": True,
        "finalizer_elapsed_ms": elapsed,
    }
    return {
        "generated_at": iso_now(),
        "model": cfg.get("model_id"),
        "status": "READY",
        "planning_gw": gw,
        "ruleset_id": RULESET_ID,
        "gate0_prevalidated": True,
        "simulation_assumption": cfg.get("simulation_assumption"),
        "candidate_pool": preview,
        "candidate_pool_is_preview_only": True,
        "package_count": evaluated,
        "hold": hold,
        "packages": top[:mc_top],
        "efficient_frontier": frontier_out,
        "search_diagnostics": diagnostics,
        "governance": {
            "candidate_generation_only": True,
            "final_go_requires_framework_governance_and_postflight_gate0": True,
            "price_uses_sell_value_for_outs_and_now_cost_for_ins": True,
            "official_fpl_full_universe_scanned": True,
            "candidate_pruning_for_full_authority": False,
            "structural_prefilters_reject_only_provably_illegal_packages": True,
            "fixed_top_n_per_position_forbidden": True,
            "fixed_top_n_per_outgoing_forbidden": True,
            "watchlist_is_output_only": True,
            "hardcoded_player_seed_forbidden": True,
            "pair_search_not_seeded_by_single_legality": True,
            "step_legal_transfer_recomputation": True,
            "prediction_scoring_semantics_unchanged": True,
            "guarded_batch_accelerator_is_not_scoring_authority": True,
            "numerical_boundary_cases_use_canonical_scalar_fallback": True,
            "top_packages_canonical_scalar_rehydrated": True,
            "parallel_partitions_are_execution_only_not_search_pruning": True,
            "chunk_skyline_union_is_exact_global_frontier_input": True,
            "efficient_frontier_from_all_evaluated_legal_packages": True,
            "efficient_frontier_never_second_scoring_authority": True,
            "lossy_pruning_is_explicit": False,
        },
    }


def finalize(data_dir: Path = DATA, *, top_keep: int = 500, persist: bool = True) -> dict[str, Any]:
    projections = read_json(data_dir / "projections.json", {})
    team = read_json(data_dir / "team.json", {})
    if not projections or not team:
        raise RuntimeError("accelerated exhaustive finalizer requires projections.json and team.json")
    optimizer = build_exhaustive(projections, team, top_keep=top_keep)
    diag = optimizer.get("search_diagnostics") or {}
    if optimizer.get("status") != "READY" or diag.get("search_authority") != "FULL" or diag.get("lossy_pruning") is not False or diag.get("all_step_legal_packages_scored") is not True:
        raise RuntimeError("accelerated exhaustive finalizer did not produce truthful FULL authority")
    if (optimizer.get("efficient_frontier") or {}).get("representation_input") != "ALL_EVALUATED_LEGAL_PACKAGES":
        raise RuntimeError("efficient frontier was not built from all evaluated legal packages")
    lock = json.loads((CONFIG / "locked_squad.json").read_text(encoding="utf-8"))
    package = build_package_decision(optimizer, projections, lock, team)
    if package.get("gate0_revalidated") is not True:
        raise RuntimeError("accelerated exhaustive finalizer package decision failed Gate0 revalidation")
    if persist:
        atomic_json(data_dir / "package_optimizer.json", optimizer)
        atomic_json(data_dir / "package_decision.json", package)
        latest = read_json(data_dir / "latest.json", {})
        latest.setdefault("files", {})["package_decision"] = "data/package_decision.json"
        latest["package_decision_summary"] = {
            "selected_package_id": package.get("selected_package_id"),
            "manual_authority_override": package.get("manual_authority_override"),
            "gate0_revalidated": True,
            "optimizer_search_authority": "FULL",
        }
        atomic_json(data_dir / "latest.json", latest)
    return {"optimizer": optimizer, "package": package}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(DATA))
    parser.add_argument("--top-keep", type=int, default=500)
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()
    result = finalize(Path(args.data_dir), top_keep=max(20, args.top_keep), persist=not args.no_persist)
    diag = result["optimizer"]["search_diagnostics"]
    print(json.dumps({
        "status": result["optimizer"].get("status"),
        "search_authority": diag.get("search_authority"),
        "eligible_universe_count": diag.get("eligible_universe_count"),
        "pair_candidate_combinations": diag.get("pair_candidate_combinations"),
        "pair_exact_scored": diag.get("pair_candidates_exact_scored"),
        "batch_scalar_fallback_count": diag.get("batch_scalar_fallback_count"),
        "batch_scalar_fallback_rate": diag.get("batch_scalar_fallback_rate"),
        "package_count": result["optimizer"].get("package_count"),
        "frontier_count": (result["optimizer"].get("efficient_frontier") or {}).get("count"),
        "elapsed_ms": diag.get("finalizer_elapsed_ms"),
        "selected_package_id": result["package"].get("selected_package_id"),
        "gate0_revalidated": result["package"].get("gate0_revalidated"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
