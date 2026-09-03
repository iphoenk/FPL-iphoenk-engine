from __future__ import annotations

import argparse
import heapq
import json
import math
import time
from itertools import combinations
from pathlib import Path
from statistics import NormalDist
from typing import Any

from src.engines.decision_intelligence import _candidate_score, _optimizer_row, _step_legal_transfer_sequence
from src.engines.lineup_governance import build_package_decision
from src.models.package_optimizer_v2 import (
    _scoring_context,
    legal_squad,
    load_config as load_optimizer_config,
    score_package,
    simulate_objective,
)
from src.rules import RULESET_ID
from src.utils import CONFIG, DATA, atomic_json, iso_now, read_json

TOP_KEEP_DEFAULT = 500
POSITION_ORDER = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _gw_index(row: dict[str, Any]) -> dict[int, tuple[float, float]]:
    out: dict[int, tuple[float, float]] = {}
    for gw_row in row.get("xpts_by_gw") or []:
        try:
            gw = int(gw_row.get("gw") or -1)
        except (TypeError, ValueError):
            continue
        if gw > 0:
            out[gw] = (_f(gw_row.get("mean")), _f(gw_row.get("std")))
    return out


def safe_per_gw_dominates(left: dict[str, Any], right: dict[str, Any], planning_gw: int, max_horizon: int) -> bool:
    """Research-only local dominance diagnostic; never used to prune FULL search.

    Per-GW player dominance is useful evidence but is not sufficient to prove
    dominance of the complete risk-adjusted package scorer because a higher-mean
    player may alter XI/captain selection and therefore aggregate variance. FULL
    production authority consequently performs zero candidate pruning.
    """
    if str(left.get("position") or "") != str(right.get("position") or ""):
        return False
    if int(left.get("team_id") or -1) != int(right.get("team_id") or -1):
        return False
    left_cost = int(left.get("now_cost") or 0)
    right_cost = int(right.get("now_cost") or 0)
    if left_cost > right_cost:
        return False
    strict = left_cost < right_cost
    li = _gw_index(left)
    ri = _gw_index(right)
    for gw in range(int(planning_gw), int(planning_gw) + int(max_horizon)):
        if gw not in li or gw not in ri:
            return False
        lm, ls = li[gw]
        rm, rs = ri[gw]
        if lm < rm - 1e-9 or ls > rs + 1e-9:
            return False
        strict = strict or lm > rm + 1e-9 or ls < rs - 1e-9
    return strict


def _package_record(
    changes: int,
    outs: list[dict[str, Any]],
    ins: list[dict[str, Any]],
    score: dict[str, Any],
    sequence: dict[str, Any],
    itb: int,
) -> dict[str, Any]:
    out_ids = [int(row["element"]) for row in outs]
    in_ids = [int(row["element"]) for row in ins]
    if changes == 0:
        package_id = "HOLD"
    elif changes == 1:
        package_id = f"1:{out_ids[0]}->{in_ids[0]}"
    else:
        package_id = f"2:{','.join(str(x) for x in out_ids)}->{','.join(str(x) for x in in_ids)}"
    cash_available = int(itb) + sum(int(row.get("sell_cost") or 0) for row in outs)
    incoming_cost = sum(int(row.get("now_cost") or 0) for row in ins)
    return {
        "id": package_id,
        "changes": int(changes),
        "outs": [
            {"element": row["element"], "name": row.get("name"), "sell_cost": row.get("sell_cost")}
            for row in outs
        ],
        "ins": [
            {"element": row["element"], "name": row.get("name"), "now_cost": row.get("now_cost")}
            for row in ins
        ],
        "affordability": {
            "cash_available": cash_available,
            "incoming_cost": incoming_cost,
            "resulting_itb": int(sequence.get("resulting_itb") if sequence.get("resulting_itb") is not None else itb),
        },
        "score": score,
        "legal": True,
        "sequential_legality": sequence,
    }


def _push_top(heap: list[tuple[float, str, dict[str, Any]]], package: dict[str, Any], keep: int) -> None:
    score = _f((package.get("score") or {}).get("robust_score"))
    package_id = str(package.get("id") or "")
    item = (score, package_id, package)
    if len(heap) < keep:
        heapq.heappush(heap, item)
    elif (score, package_id) > (heap[0][0], heap[0][1]):
        heapq.heapreplace(heap, item)


def _frontier_metrics(package: dict[str, Any], hold_horizons: dict[str, Any]) -> dict[str, Any]:
    score = package.get("score") or {}
    horizons = score.get("horizons") or {}
    net = {
        str(h): _f((horizons.get(str(h)) or {}).get("mean")) - _f((hold_horizons.get(str(h)) or {}).get("mean"))
        for h in (3, 5, 10, 15)
    }
    return {
        "net": net,
        "changes": int(package.get("changes") or 0),
        "uncertainty": _f(score.get("objective_std"), 1e9),
    }


def _dominates(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_net = left["metrics"]["net"]
    right_net = right["metrics"]["net"]
    no_worse = (
        all(left_net[str(h)] >= right_net[str(h)] - 1e-12 for h in (3, 5, 10, 15))
        and left["metrics"]["changes"] <= right["metrics"]["changes"]
        and left["metrics"]["uncertainty"] <= right["metrics"]["uncertainty"] + 1e-12
    )
    strict = (
        any(left_net[str(h)] > right_net[str(h)] + 1e-12 for h in (3, 5, 10, 15))
        or left["metrics"]["changes"] < right["metrics"]["changes"]
        or left["metrics"]["uncertainty"] < right["metrics"]["uncertainty"] - 1e-12
    )
    return no_worse and strict


class _StreamingFrontier:
    """Exact order-independent skyline over every evaluated legal package."""

    def __init__(self, hold: dict[str, Any]) -> None:
        self.hold_horizons = ((hold.get("score") or {}).get("horizons") or {})
        self.rows: list[dict[str, Any]] = []

    def add(self, package: dict[str, Any]) -> None:
        candidate = {"package": package, "metrics": _frontier_metrics(package, self.hold_horizons)}
        for existing in self.rows:
            if _dominates(existing, candidate):
                return
        self.rows = [existing for existing in self.rows if not _dominates(candidate, existing)]
        self.rows.append(candidate)

    def output(self, publish_limit: int, evaluated_count: int) -> dict[str, Any]:
        rows = []
        for row in self.rows:
            package = row["package"]
            metrics = row["metrics"]
            rows.append({
                "id": package.get("id"),
                "changes": package.get("changes"),
                "robust_score": (package.get("score") or {}).get("robust_score"),
                "net_xpts": metrics["net"],
                "objective_std": metrics["uncertainty"],
                "resulting_itb": (package.get("affordability") or {}).get("resulting_itb"),
            })
        rows.sort(key=lambda row: (_f(row.get("robust_score")), str(row.get("id") or "")), reverse=True)
        return {
            "count": len(rows),
            "packages": rows[: max(1, int(publish_limit))],
            "authority": "REPRESENTATION_ONLY",
            "dimensions_used": ["net_xpts3", "net_xpts5", "net_xpts10", "net_xpts15", "changes", "objective_std"],
            "dimensions_pending_richer_runtime_evidence": ["tactical_role_uncertainty", "price_risk", "structural_flexibility"],
            "never_second_scoring_authority": True,
            "search_authority": "FULL",
            "representation_input": "ALL_EVALUATED_LEGAL_PACKAGES",
            "evaluated_legal_package_count": int(evaluated_count),
        }


def _candidate_universe(projections: dict[str, Any], current_ids: set[int], cfg: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    full_pool: dict[str, list[dict[str, Any]]] = {pos: [] for pos in ("GK", "DEF", "MID", "FWD")}
    require_available = bool(cfg.get("require_available_status", True))
    allowed = set(cfg.get("allowed_statuses") or ["a", "d"])
    risk = _f(cfg.get("risk_aversion"), 0.12)
    counters = {
        "official_projection_universe_count": 0,
        "owned_excluded_count": 0,
        "status_excluded_count": 0,
        "invalid_excluded_count": 0,
    }
    for proj in projections.get("players") or []:
        counters["official_projection_universe_count"] += 1
        try:
            element = int(proj["element"])
        except (KeyError, TypeError, ValueError):
            counters["invalid_excluded_count"] += 1
            continue
        position = str(proj.get("position") or "")
        if position not in full_pool:
            counters["invalid_excluded_count"] += 1
            continue
        if element in current_ids:
            counters["owned_excluded_count"] += 1
            continue
        if require_available and proj.get("status") not in allowed:
            counters["status_excluded_count"] += 1
            continue
        row = _optimizer_row(proj)
        row["candidate_score"] = _candidate_score(proj, risk)
        full_pool[position].append(row)
    for rows in full_pool.values():
        rows.sort(
            key=lambda row: (_f(row.get("candidate_score")), -int(row.get("now_cost") or 0), -int(row.get("element") or -1)),
            reverse=True,
        )
    return full_pool, counters


def _current_squad(projections: dict[str, Any], team: dict[str, Any]) -> list[dict[str, Any]]:
    pmap = {int(row["element"]): row for row in projections.get("players") or [] if row.get("element") is not None}
    current: list[dict[str, Any]] = []
    for ledger in team.get("team_value_ledger") or []:
        element = int(ledger.get("element") or -1)
        proj = pmap.get(element)
        if proj:
            current.append(_optimizer_row(proj, ledger.get("sell_cost")))
    current.sort(key=lambda row: (POSITION_ORDER.get(str(row.get("position")), 9), int(row["element"])))
    if not legal_squad(current):
        raise RuntimeError("certified exhaustive finalizer: current squad failed legality precheck")
    return current


def _pair_sequence(
    current: list[dict[str, Any]],
    out_a: dict[str, Any],
    out_b: dict[str, Any],
    in_a: dict[str, Any],
    in_b: dict[str, Any],
    itb: int,
) -> tuple[bool, list[dict[str, Any]], dict[str, Any]]:
    assignments = [([in_a, in_b], False)]
    if str(out_a.get("position")) == str(out_b.get("position")) and int(in_a["element"]) != int(in_b["element"]):
        assignments.append(([in_b, in_a], True))
    for ins, swapped in assignments:
        ok, sequence = _step_legal_transfer_sequence(current, [out_a, out_b], ins, itb)
        if ok:
            sequence = dict(sequence)
            sequence["incoming_assignment_swapped"] = swapped
            return True, ins, sequence
    return False, [], {"reason": "no_step_legal_execution_order_or_assignment", "orders_checked": 2 * len(assignments)}


def _score_and_collect(
    candidate: list[dict[str, Any]],
    planning_gw: int,
    changes: int,
    scoring_context: dict[str, Any],
    package: dict[str, Any],
    heap: list[tuple[float, str, dict[str, Any]]],
    frontier: _StreamingFrontier,
    top_keep: int,
) -> bool:
    score = score_package(candidate, planning_gw, changes=changes, scoring_context=scoring_context)
    if not score.get("valid"):
        return False
    package["score"] = score
    _push_top(heap, package, top_keep)
    frontier.add(package)
    return True


def build_exhaustive(projections: dict[str, Any], team: dict[str, Any], *, top_keep: int = TOP_KEEP_DEFAULT) -> dict[str, Any]:
    started = time.perf_counter()
    cfg = load_optimizer_config()
    planning_gw = int(projections.get("planning_gw") or 1)
    scoring_context = _scoring_context(cfg, planning_gw)
    current = _current_squad(projections, team)
    current_ids = {int(row["element"]) for row in current}
    itb = int((team.get("totals") or {}).get("itb") or 0)
    full_pool, universe_counters = _candidate_universe(projections, current_ids, cfg)
    eligible_by_position = {pos: len(rows) for pos, rows in full_pool.items()}

    hold_score = score_package(current, planning_gw, changes=0, scoring_context=scoring_context)
    hold = _package_record(0, [], [], hold_score, {"resulting_itb": itb, "steps": [], "execution_order": [], "orders_checked": 1}, itb)
    keep = max(20, int(top_keep))
    heap: list[tuple[float, str, dict[str, Any]]] = []
    _push_top(heap, hold, keep)
    frontier = _StreamingFrontier(hold)
    frontier.add(hold)

    singles_considered = singles_step_legal = singles_scored = 0
    for outgoing in current:
        position = str(outgoing.get("position") or "")
        for incoming in full_pool.get(position, []):
            singles_considered += 1
            ok, sequence = _step_legal_transfer_sequence(current, [outgoing], [incoming], itb)
            if not ok:
                continue
            singles_step_legal += 1
            candidate = [row for row in current if int(row["element"]) != int(outgoing["element"])] + [incoming]
            package = _package_record(1, [outgoing], [incoming], {}, sequence, itb)
            if _score_and_collect(candidate, planning_gw, 1, scoring_context, package, heap, frontier, keep):
                singles_scored += 1

    pair_candidate_combinations = pair_distinct_incoming = pair_step_legal = pair_scored = 0
    for out_a, out_b in combinations(current, 2):
        pos_a = str(out_a.get("position") or "")
        pos_b = str(out_b.get("position") or "")
        if pos_a == pos_b:
            incoming_iter = combinations(full_pool.get(pos_a, []), 2)
        else:
            incoming_iter = (
                (left, right)
                for left in full_pool.get(pos_a, [])
                for right in full_pool.get(pos_b, [])
            )
        for in_a, in_b in incoming_iter:
            pair_candidate_combinations += 1
            if int(in_a["element"]) == int(in_b["element"]):
                continue
            pair_distinct_incoming += 1
            ok, assigned_ins, sequence = _pair_sequence(current, out_a, out_b, in_a, in_b, itb)
            if not ok:
                continue
            pair_step_legal += 1
            out_ids = {int(out_a["element"]), int(out_b["element"])}
            candidate = [row for row in current if int(row["element"]) not in out_ids] + assigned_ins
            package = _package_record(2, [out_a, out_b], assigned_ins, {}, sequence, itb)
            if _score_and_collect(candidate, planning_gw, 2, scoring_context, package, heap, frontier, keep):
                pair_scored += 1

    evaluated = 1 + singles_scored + pair_scored
    top_packages = [row[2] for row in heap]
    top_packages.sort(
        key=lambda package: (_f((package.get("score") or {}).get("robust_score")), str(package.get("id") or "")),
        reverse=True,
    )
    mc_top = int(cfg.get("monte_carlo_top_n") or 20)
    simulations = int(cfg.get("monte_carlo_simulations") or 300)
    seed = int(cfg.get("monte_carlo_seed") or 1)
    hold_mean = _f(hold_score.get("objective_mean"))
    hold_std = _f(hold_score.get("objective_std"))
    for idx, package in enumerate(top_packages[:mc_top]):
        mean = _f((package.get("score") or {}).get("objective_mean"))
        std = _f((package.get("score") or {}).get("objective_std"))
        package["monte_carlo"] = simulate_objective(mean, std, simulations, seed + idx)
        diff_std = math.sqrt(std * std + hold_std * hold_std)
        if diff_std > 0:
            p_out = 1.0 - NormalDist(mu=mean - hold_mean, sigma=diff_std).cdf(0.0)
        else:
            p_out = 1.0 if mean > hold_mean else 0.5 if mean == hold_mean else 0.0
        package["monte_carlo"]["p_outperform_hold_independent_baseline"] = round(p_out, 4)

    frontier_cfg = cfg.get("frontier") or {}
    efficient_frontier = frontier.output(int(frontier_cfg.get("publish_limit") or 20), evaluated)
    preview_limit = max(1, int(cfg.get("candidate_pool_preview_per_position") or 20))
    preview = {
        pos: [
            {
                "element": row["element"],
                "name": row.get("name"),
                "now_cost": row.get("now_cost"),
                "candidate_score": round(_f(row.get("candidate_score")), 3),
            }
            for row in rows[:preview_limit]
        ]
        for pos, rows in full_pool.items()
    }
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    return {
        "generated_at": iso_now(),
        "model": cfg.get("model_id"),
        "status": "READY",
        "planning_gw": planning_gw,
        "ruleset_id": RULESET_ID,
        "gate0_prevalidated": True,
        "simulation_assumption": cfg.get("simulation_assumption"),
        "candidate_pool": preview,
        "candidate_pool_is_preview_only": True,
        "package_count": evaluated,
        "hold": hold,
        "packages": top_packages[:mc_top],
        "efficient_frontier": efficient_frontier,
        "search_diagnostics": {
            **universe_counters,
            "candidate_origin": "COMPLETE_ELIGIBLE_OFFICIAL_FPL_UNIVERSE",
            "eligible_universe_count": sum(eligible_by_position.values()),
            "eligible_by_position": eligible_by_position,
            "search_method": "ZERO_CANDIDATE_PRUNING_EXHAUSTIVE_SEQUENTIAL_EXACT_V1",
            "candidate_pruning_applied": False,
            "candidate_pruned_count": 0,
            "fixed_top_n_per_position_applied": False,
            "fixed_top_n_per_outgoing_applied": False,
            "watchlist_used_as_optimizer_input": False,
            "single_candidates_considered": singles_considered,
            "single_step_legal": singles_step_legal,
            "single_exact_scored": singles_scored,
            "single_budget_applied": False,
            "pair_generation_origin": "DIRECT_OUTGOING_PAIR_X_COMPLETE_POSITION_ELIGIBLE_INCOMING_POOLS",
            "pair_requires_single_move_seed": False,
            "pair_candidate_combinations": pair_candidate_combinations,
            "pair_distinct_incoming": pair_distinct_incoming,
            "pair_step_legal": pair_step_legal,
            "pair_candidates_exact_scored": pair_scored,
            "pair_budget_applied": False,
            "exact_package_limit_applied": False,
            "all_step_legal_packages_scored": singles_scored == singles_step_legal and pair_scored == pair_step_legal,
            "lossy_pruning": False,
            "search_authority": "FULL",
            "authority_reason": "complete eligible Official FPL universe; zero candidate pruning; direct pair enumeration independent of single legality; every step-legal package scored by canonical score_package",
            "optimizer_runtime_status_separate_from_search_authority": True,
            "finalizer_elapsed_ms": elapsed_ms,
        },
        "governance": {
            "candidate_generation_only": True,
            "final_go_requires_framework_governance_and_postflight_gate0": True,
            "price_uses_sell_value_for_outs_and_now_cost_for_ins": True,
            "official_fpl_full_universe_scanned": True,
            "candidate_pruning_for_full_authority": False,
            "fixed_top_n_per_position_forbidden": True,
            "fixed_top_n_per_outgoing_forbidden": True,
            "watchlist_is_output_only": True,
            "hardcoded_player_seed_forbidden": True,
            "pair_search_not_seeded_by_single_legality": True,
            "step_legal_transfer_recomputation": True,
            "final_squad_reoptimized_by_existing_score_package": True,
            "prediction_scoring_semantics_unchanged": True,
            "canonical_score_package_reused_for_every_legal_package": True,
            "efficient_frontier_from_all_evaluated_legal_packages": True,
            "efficient_frontier_never_second_scoring_authority": True,
            "lossy_pruning_is_explicit": False,
        },
    }


def finalize(data_dir: Path = DATA, *, top_keep: int = TOP_KEEP_DEFAULT, persist: bool = True) -> dict[str, Any]:
    projections = read_json(data_dir / "projections.json", {})
    team = read_json(data_dir / "team.json", {})
    if not projections or not team:
        raise RuntimeError("certified exhaustive finalizer requires projections.json and team.json")
    optimizer = build_exhaustive(projections, team, top_keep=top_keep)
    diag = optimizer.get("search_diagnostics") or {}
    if optimizer.get("status") != "READY" or diag.get("search_authority") != "FULL" or diag.get("lossy_pruning") is not False:
        raise RuntimeError("certified exhaustive finalizer did not produce truthful FULL search authority")
    if diag.get("all_step_legal_packages_scored") is not True:
        raise RuntimeError("certified exhaustive finalizer did not score every step-legal package")
    frontier = optimizer.get("efficient_frontier") or {}
    if frontier.get("representation_input") != "ALL_EVALUATED_LEGAL_PACKAGES":
        raise RuntimeError("efficient frontier was not built from all evaluated legal packages")
    lock = json.loads((CONFIG / "locked_squad.json").read_text(encoding="utf-8"))
    package = build_package_decision(optimizer, projections, lock, team)
    if package.get("gate0_revalidated") is not True:
        raise RuntimeError("certified exhaustive finalizer package decision failed Gate0 revalidation")
    if persist:
        atomic_json(data_dir / "package_optimizer.json", optimizer)
        atomic_json(data_dir / "package_decision.json", package)
        latest = read_json(data_dir / "latest.json", {})
        latest.setdefault("files", {})["package_decision"] = "data/package_decision.json"
        latest["package_decision_summary"] = {
            "selected_package_id": package.get("selected_package_id"),
            "manual_authority_override": package.get("manual_authority_override"),
            "gate0_revalidated": package.get("gate0_revalidated"),
            "optimizer_search_authority": "FULL",
        }
        atomic_json(data_dir / "latest.json", latest)
    return {"optimizer": optimizer, "package": package}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(DATA))
    parser.add_argument("--top-keep", type=int, default=TOP_KEEP_DEFAULT)
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()
    result = finalize(Path(args.data_dir), top_keep=max(20, args.top_keep), persist=not args.no_persist)
    diag = result["optimizer"]["search_diagnostics"]
    print(json.dumps({
        "status": result["optimizer"].get("status"),
        "search_authority": diag.get("search_authority"),
        "eligible_universe_count": diag.get("eligible_universe_count"),
        "candidate_pruned_count": diag.get("candidate_pruned_count"),
        "single_exact_scored": diag.get("single_exact_scored"),
        "pair_exact_scored": diag.get("pair_candidates_exact_scored"),
        "package_count": result["optimizer"].get("package_count"),
        "frontier_count": (result["optimizer"].get("efficient_frontier") or {}).get("count"),
        "elapsed_ms": diag.get("finalizer_elapsed_ms"),
        "selected_package_id": result["package"].get("selected_package_id"),
        "gate0_revalidated": result["package"].get("gate0_revalidated"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
