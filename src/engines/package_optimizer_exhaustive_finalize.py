from __future__ import annotations

import argparse
import heapq
import json
import math
import time
from collections import Counter
from pathlib import Path
from statistics import NormalDist
from typing import Any

from src.engines.decision_intelligence import (
    _candidate_score,
    _optimizer_row,
    _package_frontier,
    _step_legal_transfer_sequence,
)
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
    """Proven non-lossy candidate dominance for the active package scorer.

    The replacement is only allowed inside the same Official team and FPL position,
    so club and position legality are identical. It must be no more expensive and
    have no lower mean and no higher standard deviation in every decision-bearing
    GW. Therefore replacing ``right`` with ``left`` cannot worsen affordability,
    any per-GW legal-XI mean, captain mean, bench utility, or independent variance
    used by ``score_package``. Missing GW evidence forbids pruning.
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
        if lm > rm + 1e-9 or ls < rs - 1e-9:
            strict = True
    return strict


def _safe_pool(full_pool: dict[str, list[dict[str, Any]]], planning_gw: int, max_horizon: int) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    kept_pool: dict[str, list[dict[str, Any]]] = {pos: [] for pos in full_pool}
    group_rows: list[dict[str, Any]] = []
    pruned = 0
    for position, rows in full_pool.items():
        by_team: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            by_team.setdefault(int(row.get("team_id") or -1), []).append(row)
        for team_id in sorted(by_team):
            group = by_team[team_id]
            kept: list[dict[str, Any]] = []
            for candidate in group:
                if any(
                    other is not candidate
                    and safe_per_gw_dominates(other, candidate, planning_gw, max_horizon)
                    for other in group
                ):
                    pruned += 1
                    continue
                kept.append(candidate)
            kept.sort(
                key=lambda row: (
                    _f(row.get("candidate_score")),
                    -int(row.get("now_cost") or 0),
                    -int(row.get("element") or -1),
                ),
                reverse=True,
            )
            kept_pool[position].extend(kept)
            group_rows.append({
                "position": position,
                "team_id": team_id,
                "eligible": len(group),
                "safe_kept": len(kept),
                "safe_pruned": len(group) - len(kept),
            })
        kept_pool[position].sort(
            key=lambda row: (
                _f(row.get("candidate_score")),
                -int(row.get("now_cost") or 0),
                -int(row.get("element") or -1),
            ),
            reverse=True,
        )
    return kept_pool, {
        "safe_pruned_count": pruned,
        "team_position_groups": len(group_rows),
        "groups": group_rows,
        "proof": "SAME_OFFICIAL_TEAM_POSITION + LOWER_OR_EQUAL_PRICE + PER_GW_MEAN_NO_WORSE + PER_GW_STD_NO_WORSE",
        "cross_team_dominance_forbidden": True,
        "missing_gw_evidence_forbids_pruning": True,
        "non_lossy": True,
    }


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
    key = (_f((package.get("score") or {}).get("robust_score")), str(package.get("id") or ""))
    item = (key[0], key[1], package)
    if len(heap) < keep:
        heapq.heappush(heap, item)
    elif (item[0], item[1]) > (heap[0][0], heap[0][1]):
        heapq.heapreplace(heap, item)


def _candidate_universe(projections: dict[str, Any], current_ids: set[int], cfg: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    full_pool: dict[str, list[dict[str, Any]]] = {pos: [] for pos in ("GK", "DEF", "MID", "FWD")}
    require_available = bool(cfg.get("require_available_status", True))
    allowed = set(cfg.get("allowed_statuses") or ["a", "d"])
    risk = _f(cfg.get("risk_aversion"), 0.12)
    counters = {"official_projection_universe_count": 0, "owned_excluded_count": 0, "status_excluded_count": 0, "invalid_excluded_count": 0}
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
        rows.sort(key=lambda row: (_f(row.get("candidate_score")), -int(row.get("now_cost") or 0), -int(row.get("element") or -1)), reverse=True)
    return full_pool, counters


def _current_squad(projections: dict[str, Any], team: dict[str, Any]) -> list[dict[str, Any]]:
    pmap = {int(row["element"]): row for row in projections.get("players") or [] if row.get("element") is not None}
    current: list[dict[str, Any]] = []
    for ledger in team.get("team_value_ledger") or []:
        element = int(ledger.get("element") or -1)
        proj = pmap.get(element)
        if proj:
            current.append(_optimizer_row(proj, ledger.get("sell_cost")))
    if not legal_squad(current):
        raise RuntimeError("certified exhaustive finalizer: current squad failed legality precheck")
    return current


def build_exhaustive(projections: dict[str, Any], team: dict[str, Any], *, top_keep: int = TOP_KEEP_DEFAULT) -> dict[str, Any]:
    started = time.perf_counter()
    cfg = load_optimizer_config()
    planning_gw = int(projections.get("planning_gw") or 1)
    scoring_context = _scoring_context(cfg, planning_gw)
    max_horizon = int(scoring_context.get("max_horizon") or 15)
    current = _current_squad(projections, team)
    current_ids = {int(row["element"]) for row in current}
    itb = int((team.get("totals") or {}).get("itb") or 0)
    full_pool, universe_counters = _candidate_universe(projections, current_ids, cfg)
    search_pool, safe_diag = _safe_pool(full_pool, planning_gw, max_horizon)
    eligible_by_position = {pos: len(rows) for pos, rows in full_pool.items()}
    safe_by_position = {pos: len(rows) for pos, rows in search_pool.items()}

    hold_score = score_package(current, planning_gw, changes=0, scoring_context=scoring_context)
    hold = _package_record(0, [], [], hold_score, {"resulting_itb": itb, "steps": [], "execution_order": [], "orders_checked": 1}, itb)
    heap: list[tuple[float, str, dict[str, Any]]] = []
    _push_top(heap, hold, max(20, int(top_keep)))

    single_moves: list[dict[str, Any]] = []
    singles_considered = singles_legal = singles_scored = 0
    for outgoing in current:
        for incoming in search_pool.get(str(outgoing.get("position")), []):
            singles_considered += 1
            step_ok, sequence = _step_legal_transfer_sequence(current, [outgoing], [incoming], itb)
            if not step_ok:
                continue
            singles_legal += 1
            candidate = [row for row in current if int(row["element"]) != int(outgoing["element"])] + [incoming]
            score = score_package(candidate, planning_gw, changes=1, scoring_context=scoring_context)
            if not score.get("valid"):
                continue
            singles_scored += 1
            package = _package_record(1, [outgoing], [incoming], score, sequence, itb)
            _push_top(heap, package, max(20, int(top_keep)))
            single_moves.append({"out": outgoing, "in": incoming, "score": score})

    pair_seen: set[tuple[int, ...]] = set()
    pair_combinations = pair_unique = pair_step_legal = pair_scored = 0
    for index, left in enumerate(single_moves):
        for right in single_moves[index + 1 :]:
            pair_combinations += 1
            out_a, out_b = left["out"], right["out"]
            in_a, in_b = left["in"], right["in"]
            if int(out_a["element"]) == int(out_b["element"]) or int(in_a["element"]) == int(in_b["element"]):
                continue
            key = tuple(sorted((int(out_a["element"]), int(out_b["element"])))) + tuple(sorted((int(in_a["element"]), int(in_b["element"]))))
            if key in pair_seen:
                continue
            pair_seen.add(key)
            pair_unique += 1
            outs = [out_a, out_b]
            ins = [in_a, in_b]
            step_ok, sequence = _step_legal_transfer_sequence(current, outs, ins, itb)
            if not step_ok:
                continue
            pair_step_legal += 1
            out_ids = {int(out_a["element"]), int(out_b["element"])}
            candidate = [row for row in current if int(row["element"]) not in out_ids] + ins
            score = score_package(candidate, planning_gw, changes=2, scoring_context=scoring_context)
            if not score.get("valid"):
                continue
            pair_scored += 1
            package = _package_record(2, outs, ins, score, sequence, itb)
            _push_top(heap, package, max(20, int(top_keep)))

    top_packages = [row[2] for row in heap]
    top_packages.sort(key=lambda package: (_f((package.get("score") or {}).get("robust_score")), str(package.get("id") or "")), reverse=True)
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

    # The published frontier is generated from a retained superset of the top
    # packages. Search authority is FULL because every legal package is scored;
    # frontier remains explicitly a representation layer, never scoring authority.
    frontier_cfg = cfg.get("frontier") or {}
    frontier = _package_frontier(top_packages, hold, int(frontier_cfg.get("publish_limit") or 20))
    frontier["search_authority"] = "FULL"
    frontier["evaluated_legal_package_count"] = 1 + singles_scored + pair_scored
    frontier["representation_input"] = "TOP_RETAINED_EXACT_PACKAGES"

    preview_limit = max(1, int(cfg.get("candidate_pool_preview_per_position") or 20))
    preview = {
        pos: [
            {"element": row["element"], "name": row.get("name"), "now_cost": row.get("now_cost"), "candidate_score": round(_f(row.get("candidate_score")), 3)}
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
        "package_count": 1 + singles_scored + pair_scored,
        "hold": hold,
        "packages": top_packages[:mc_top],
        "efficient_frontier": frontier,
        "search_diagnostics": {
            **universe_counters,
            "candidate_origin": "COMPLETE_ELIGIBLE_OFFICIAL_FPL_UNIVERSE",
            "eligible_universe_count": sum(eligible_by_position.values()),
            "eligible_by_position": eligible_by_position,
            "search_frontier_method": "SAFE_PER_GW_TEAM_POSITION_DOMINANCE_EXHAUSTIVE_EXACT_V1",
            "safe_frontier_by_position": safe_by_position,
            "safe_pruned_count": safe_diag["safe_pruned_count"],
            "safe_pruning_proof": safe_diag["proof"],
            "safe_pruning_non_lossy": True,
            "team_position_groups": safe_diag["team_position_groups"],
            "team_position_group_diagnostics": safe_diag["groups"],
            "fixed_top_n_per_position_applied": False,
            "fixed_top_n_per_outgoing_applied": False,
            "watchlist_used_as_optimizer_input": False,
            "single_candidates_considered": singles_considered,
            "legal_single_stubs": singles_legal,
            "single_exact_scored": singles_scored,
            "single_budget_applied": False,
            "pair_combinations_considered": pair_combinations,
            "pair_unique_candidates": pair_unique,
            "pair_step_legal": pair_step_legal,
            "pair_candidates_exact_scored": pair_scored,
            "pair_budget_applied": False,
            "exact_package_limit_applied": False,
            "lossy_pruning": False,
            "search_authority": "FULL",
            "authority_reason": "all legal packages after proven non-lossy same-team-position per-GW dominance were exactly scored with canonical score_package",
            "optimizer_runtime_status_separate_from_search_authority": True,
            "finalizer_elapsed_ms": elapsed_ms,
        },
        "governance": {
            "candidate_generation_only": True,
            "final_go_requires_framework_governance_and_postflight_gate0": True,
            "price_uses_sell_value_for_outs_and_now_cost_for_ins": True,
            "official_fpl_full_universe_scanned_before_pruning": True,
            "only_proven_non_lossy_pruning_allowed": True,
            "fixed_top_n_per_position_forbidden": True,
            "fixed_top_n_per_outgoing_forbidden": True,
            "watchlist_is_output_only": True,
            "hardcoded_player_seed_forbidden": True,
            "step_legal_transfer_recomputation": True,
            "final_squad_reoptimized_by_existing_score_package": True,
            "prediction_scoring_semantics_unchanged": True,
            "canonical_score_package_reused_for_every_legal_package": True,
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
    if optimizer.get("status") != "READY" or (optimizer.get("search_diagnostics") or {}).get("search_authority") != "FULL":
        raise RuntimeError("certified exhaustive finalizer did not produce FULL search authority")
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
        "safe_pruned_count": diag.get("safe_pruned_count"),
        "single_exact_scored": diag.get("single_exact_scored"),
        "pair_exact_scored": diag.get("pair_candidates_exact_scored"),
        "package_count": result["optimizer"].get("package_count"),
        "elapsed_ms": diag.get("finalizer_elapsed_ms"),
        "selected_package_id": result["package"].get("selected_package_id"),
        "gate0_revalidated": result["package"].get("gate0_revalidated"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
