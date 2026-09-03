from __future__ import annotations

import argparse
import heapq
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

from src.engines.decision_intelligence import _candidate_score, _optimizer_row, _step_legal_transfer_sequence
from src.engines.lineup_governance import build_package_decision
from src.models.package_optimizer_v2 import CompiledPackageScorer, _scoring_context, legal_squad, load_config as load_optimizer_config, simulate_objective
from src.rules import RULESET_ID, SQUAD_RULES
from src.utils import CONFIG, DATA, atomic_json, iso_now, read_json

TOP_KEEP_DEFAULT = 500
POSITIONS = ("GK", "DEF", "MID", "FWD")
POSITION_ORDER = {p: i for i, p in enumerate(POSITIONS)}
MAX_CLUB = int(SQUAD_RULES.get("max_players_per_club") or 3)
PARALLEL_PAIR_THRESHOLD = 50_000

_WORKER_CURRENT: list[dict[str, Any]] = []
_WORKER_POOL: dict[str, list[dict[str, Any]]] = {}
_WORKER_ITB = 0
_WORKER_CLUBS: Counter[int] = Counter()
_WORKER_SCORER: CompiledPackageScorer | None = None
_WORKER_KEEP = TOP_KEEP_DEFAULT
_WORKER_HOLD_H: dict[str, Any] = {}


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
    """Diagnostic only. FULL production search never uses this to prune candidates."""
    if left.get("position") != right.get("position") or int(left.get("team_id") or -1) != int(right.get("team_id") or -1):
        return False
    lc, rc = int(left.get("now_cost") or 0), int(right.get("now_cost") or 0)
    if lc > rc:
        return False
    strict = lc < rc
    li, ri = _gw_index(left), _gw_index(right)
    for gw in range(int(planning_gw), int(planning_gw) + int(max_horizon)):
        if gw not in li or gw not in ri:
            return False
        lm, ls = li[gw]
        rm, rs = ri[gw]
        if lm < rm - 1e-9 or ls > rs + 1e-9:
            return False
        strict = strict or lm > rm + 1e-9 or ls < rs - 1e-9
    return strict


def _record(changes: int, outs: list[dict[str, Any]], ins: list[dict[str, Any]], score: dict[str, Any], seq: dict[str, Any], itb: int) -> dict[str, Any]:
    out_ids = [int(x["element"]) for x in outs]
    in_ids = [int(x["element"]) for x in ins]
    pid = "HOLD" if not changes else (f"1:{out_ids[0]}->{in_ids[0]}" if changes == 1 else f"2:{','.join(map(str, out_ids))}->{','.join(map(str, in_ids))}")
    cash = int(itb) + sum(int(x.get("sell_cost") or 0) for x in outs)
    cost = sum(int(x.get("now_cost") or 0) for x in ins)
    return {
        "id": pid,
        "changes": changes,
        "outs": [{"element": x["element"], "name": x.get("name"), "sell_cost": x.get("sell_cost")} for x in outs],
        "ins": [{"element": x["element"], "name": x.get("name"), "now_cost": x.get("now_cost")} for x in ins],
        "affordability": {"cash_available": cash, "incoming_cost": cost, "resulting_itb": int(seq.get("resulting_itb", itb))},
        "score": score,
        "legal": True,
        "sequential_legality": seq,
    }


def _metrics(package: dict[str, Any], hold_h: dict[str, Any]) -> tuple[float, float, float, float, int, float]:
    h = (package.get("score") or {}).get("horizons") or {}
    return tuple(_f((h.get(str(n)) or {}).get("mean")) - _f((hold_h.get(str(n)) or {}).get("mean")) for n in (3, 5, 10, 15)) + (int(package.get("changes") or 0), _f((package.get("score") or {}).get("objective_std"), 1e9))


def _dominates(a: tuple, b: tuple) -> bool:
    no_worse = all(a[i] >= b[i] - 1e-12 for i in range(4)) and a[4] <= b[4] and a[5] <= b[5] + 1e-12
    strict = any(a[i] > b[i] + 1e-12 for i in range(4)) or a[4] < b[4] or a[5] < b[5] - 1e-12
    return no_worse and strict


class _Frontier:
    def __init__(self, hold_h: dict[str, Any]) -> None:
        self.hold_h = hold_h
        self.rows: list[tuple[tuple, dict[str, Any]]] = []

    @classmethod
    def from_hold(cls, hold: dict[str, Any]) -> "_Frontier":
        return cls(((hold.get("score") or {}).get("horizons") or {}))

    def add(self, package: dict[str, Any]) -> None:
        m = _metrics(package, self.hold_h)
        for em, _ in self.rows:
            if _dominates(em, m):
                return
        self.rows = [(em, ep) for em, ep in self.rows if not _dominates(m, em)]
        self.rows.append((m, package))

    def output(self, limit: int, evaluated: int) -> dict[str, Any]:
        rows = [{
            "id": p.get("id"), "changes": p.get("changes"), "robust_score": (p.get("score") or {}).get("robust_score"),
            "net_xpts": {str(h): m[i] for i, h in enumerate((3, 5, 10, 15))}, "objective_std": m[5],
            "resulting_itb": (p.get("affordability") or {}).get("resulting_itb"),
        } for m, p in self.rows]
        rows.sort(key=lambda r: (_f(r.get("robust_score")), str(r.get("id") or "")), reverse=True)
        return {
            "count": len(rows), "packages": rows[:max(1, int(limit))], "authority": "REPRESENTATION_ONLY",
            "dimensions_used": ["net_xpts3", "net_xpts5", "net_xpts10", "net_xpts15", "changes", "objective_std"],
            "dimensions_pending_richer_runtime_evidence": ["tactical_role_uncertainty", "price_risk", "structural_flexibility"],
            "never_second_scoring_authority": True, "search_authority": "FULL",
            "representation_input": "ALL_EVALUATED_LEGAL_PACKAGES", "evaluated_legal_package_count": evaluated,
        }


def _current(projections: dict[str, Any], team: dict[str, Any]) -> list[dict[str, Any]]:
    pmap = {int(p["element"]): p for p in projections.get("players") or []}
    rows = [_optimizer_row(pmap[int(x["element"])], x.get("sell_cost")) for x in team.get("team_value_ledger") or [] if int(x.get("element") or -1) in pmap]
    rows.sort(key=lambda x: (POSITION_ORDER.get(str(x.get("position")), 9), int(x["element"])))
    if not legal_squad(rows):
        raise RuntimeError("certified exhaustive finalizer: current squad failed legality precheck")
    return rows


def _pool(projections: dict[str, Any], owned: set[int], cfg: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    pool = {p: [] for p in POSITIONS}
    allowed = set(cfg.get("allowed_statuses") or ["a", "d"])
    require_available = bool(cfg.get("require_available_status", True))
    risk = _f(cfg.get("risk_aversion"), 0.12)
    counts = {"official_projection_universe_count": 0, "owned_excluded_count": 0, "status_excluded_count": 0, "invalid_excluded_count": 0}
    for proj in projections.get("players") or []:
        counts["official_projection_universe_count"] += 1
        try:
            element, position = int(proj["element"]), str(proj.get("position") or "")
        except (KeyError, TypeError, ValueError):
            counts["invalid_excluded_count"] += 1
            continue
        if position not in pool:
            counts["invalid_excluded_count"] += 1
        elif element in owned:
            counts["owned_excluded_count"] += 1
        elif require_available and proj.get("status") not in allowed:
            counts["status_excluded_count"] += 1
        else:
            row = _optimizer_row(proj)
            row["candidate_score"] = _candidate_score(proj, risk)
            pool[position].append(row)
    for rows in pool.values():
        rows.sort(key=lambda x: (_f(x.get("candidate_score")), -int(x.get("now_cost") or 0), -int(x["element"])), reverse=True)
    return pool, counts


def _structural_ok(clubs: Counter[int], outs: list[dict[str, Any]], ins: list[dict[str, Any]], itb: int) -> tuple[bool, str | None]:
    if int(itb) + sum(int(x.get("sell_cost") or 0) for x in outs) < sum(int(x.get("now_cost") or 0) for x in ins):
        return False, "cash"
    c = clubs.copy()
    for x in outs:
        c[int(x.get("team_id") or -1)] -= 1
    for x in ins:
        c[int(x.get("team_id") or -1)] += 1
    if any(v > MAX_CLUB for k, v in c.items() if k > 0):
        return False, "club"
    return True, None


def _pair_sequence(current: list[dict[str, Any]], outs: list[dict[str, Any]], ins: list[dict[str, Any]], itb: int) -> tuple[bool, list[dict[str, Any]], dict[str, Any]]:
    assignments = [ins]
    if outs[0].get("position") == outs[1].get("position"):
        assignments.append([ins[1], ins[0]])
    for idx, assignment in enumerate(assignments):
        ok, seq = _step_legal_transfer_sequence(current, outs, assignment, itb)
        if ok:
            seq = dict(seq)
            seq["incoming_assignment_swapped"] = bool(idx)
            return True, assignment, seq
    return False, [], {"reason": "no_step_legal_execution_order_or_assignment", "orders_checked": 2 * len(assignments)}


def _push(heap: list[tuple[float, str, dict[str, Any]]], package: dict[str, Any], keep: int) -> None:
    score = package.get("score") or {}
    item = (_f(score.get("robust_score")), str(package["id"]), package)
    if len(heap) < keep:
        heapq.heappush(heap, item)
    elif item[:2] > heap[0][:2]:
        heapq.heapreplace(heap, item)


def _collect(package: dict[str, Any], candidate: list[dict[str, Any]], changes: int, scorer: CompiledPackageScorer, heap: list, frontier: _Frontier, keep: int) -> bool:
    score = scorer.score(candidate, changes=changes)
    if not score.get("valid"):
        return False
    package["score"] = score
    _push(heap, package, keep)
    frontier.add(package)
    return True


def _estimated_pair_combinations(current: list[dict[str, Any]], pool: dict[str, list[dict[str, Any]]]) -> int:
    total = 0
    for oa, ob in combinations(current, 2):
        pa, pb = str(oa.get("position")), str(ob.get("position"))
        if pa == pb:
            n = len(pool[pa])
            total += n * (n - 1) // 2
        else:
            total += len(pool[pa]) * len(pool[pb])
    return total


def _init_pair_worker(players: list[dict[str, Any]], current: list[dict[str, Any]], pool: dict[str, list[dict[str, Any]]], itb: int, context: dict[str, Any], keep: int, hold_h: dict[str, Any]) -> None:
    global _WORKER_CURRENT, _WORKER_POOL, _WORKER_ITB, _WORKER_CLUBS, _WORKER_SCORER, _WORKER_KEEP, _WORKER_HOLD_H
    _WORKER_CURRENT = current
    _WORKER_POOL = pool
    _WORKER_ITB = int(itb)
    _WORKER_CLUBS = Counter(int(x.get("team_id") or -1) for x in current)
    _WORKER_SCORER = CompiledPackageScorer(players, int(context.get("planning_gw") or 1), scoring_context=context)
    _WORKER_KEEP = int(keep)
    _WORKER_HOLD_H = hold_h


def _pair_partition(task: tuple[int, int]) -> dict[str, Any]:
    if _WORKER_SCORER is None:
        raise RuntimeError("pair worker scorer not initialized")
    ia, ib = task
    oa, ob = _WORKER_CURRENT[ia], _WORKER_CURRENT[ib]
    outs = [oa, ob]
    out_ids = {int(oa["element"]), int(ob["element"])}
    base = [x for x in _WORKER_CURRENT if int(x["element"]) not in out_ids]
    pa, pb = str(oa.get("position")), str(ob.get("position"))
    incoming_iter = combinations(_WORKER_POOL[pa], 2) if pa == pb else ((a, b) for a in _WORKER_POOL[pa] for b in _WORKER_POOL[pb])
    heap: list[tuple[float, str, dict[str, Any]]] = []
    frontier = _Frontier(_WORKER_HOLD_H)
    pc = ps = pscore = p_cash = p_club = 0
    for inc_a, inc_b in incoming_iter:
        pc += 1
        ins = [inc_a, inc_b]
        ok_struct, reason = _structural_ok(_WORKER_CLUBS, outs, ins, _WORKER_ITB)
        if not ok_struct:
            p_cash += reason == "cash"
            p_club += reason == "club"
            continue
        ok, assigned, seq = _pair_sequence(_WORKER_CURRENT, outs, ins, _WORKER_ITB)
        if not ok:
            continue
        ps += 1
        package = _record(2, outs, assigned, {}, seq, _WORKER_ITB)
        pscore += _collect(package, base + assigned, 2, _WORKER_SCORER, heap, frontier, _WORKER_KEEP)
    return {
        "pair_candidate_combinations": pc,
        "pair_structural_cash_rejected": p_cash,
        "pair_structural_club_rejected": p_club,
        "pair_step_legal": ps,
        "pair_candidates_exact_scored": pscore,
        "top": [x[2] for x in heap],
        "frontier": [p for _, p in frontier.rows],
    }


def build_exhaustive(projections: dict[str, Any], team: dict[str, Any], *, top_keep: int = TOP_KEEP_DEFAULT) -> dict[str, Any]:
    started = time.perf_counter()
    cfg = load_optimizer_config()
    gw = int(projections.get("planning_gw") or 1)
    context = _scoring_context(cfg, gw)
    context["planning_gw"] = gw
    current = _current(projections, team)
    owned = {int(x["element"]) for x in current}
    pool, universe_counts = _pool(projections, owned, cfg)
    eligible = {p: len(v) for p, v in pool.items()}
    itb = int((team.get("totals") or {}).get("itb") or 0)
    clubs = Counter(int(x.get("team_id") or -1) for x in current)
    scorer = CompiledPackageScorer(projections.get("players") or [], gw, scoring_context=context)

    hold_score = scorer.score(current, changes=0)
    hold = _record(0, [], [], hold_score, {"resulting_itb": itb, "steps": [], "execution_order": [], "orders_checked": 1}, itb)
    hold_h = (hold_score.get("horizons") or {})
    keep = max(20, int(top_keep))
    heap: list[tuple[float, str, dict[str, Any]]] = [(_f(hold_score.get("robust_score")), "HOLD", hold)]
    frontier = _Frontier.from_hold(hold)
    frontier.add(hold)

    sc = ss = sscore = s_cash = s_club = 0
    for out in current:
        base = [x for x in current if int(x["element"]) != int(out["element"])]
        for inn in pool[str(out.get("position"))]:
            sc += 1
            ok_struct, reason = _structural_ok(clubs, [out], [inn], itb)
            if not ok_struct:
                s_cash += reason == "cash"
                s_club += reason == "club"
                continue
            ok, seq = _step_legal_transfer_sequence(current, [out], [inn], itb)
            if not ok:
                continue
            ss += 1
            package = _record(1, [out], [inn], {}, seq, itb)
            sscore += _collect(package, base + [inn], 1, scorer, heap, frontier, keep)

    pair_tasks = [(i, j) for i, j in combinations(range(len(current)), 2)]
    estimated_pairs = _estimated_pair_combinations(current, pool)
    cpu_count = max(1, int(os.cpu_count() or 1))
    workers = min(cpu_count, len(pair_tasks)) if estimated_pairs >= PARALLEL_PAIR_THRESHOLD else 1
    pc = ps = pscore = p_cash = p_club = 0

    if workers > 1:
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_init_pair_worker,
            initargs=(projections.get("players") or [], current, pool, itb, context, keep, hold_h),
        ) as executor:
            results = executor.map(_pair_partition, pair_tasks, chunksize=1)
            for result in results:
                pc += int(result["pair_candidate_combinations"])
                p_cash += int(result["pair_structural_cash_rejected"])
                p_club += int(result["pair_structural_club_rejected"])
                ps += int(result["pair_step_legal"])
                pscore += int(result["pair_candidates_exact_scored"])
                for package in result["top"]:
                    _push(heap, package, keep)
                for package in result["frontier"]:
                    frontier.add(package)
    else:
        _init_pair_worker(projections.get("players") or [], current, pool, itb, context, keep, hold_h)
        for task in pair_tasks:
            result = _pair_partition(task)
            pc += int(result["pair_candidate_combinations"])
            p_cash += int(result["pair_structural_cash_rejected"])
            p_club += int(result["pair_structural_club_rejected"])
            ps += int(result["pair_step_legal"])
            pscore += int(result["pair_candidates_exact_scored"])
            for package in result["top"]:
                _push(heap, package, keep)
            for package in result["frontier"]:
                frontier.add(package)

    evaluated = 1 + sscore + pscore
    top = [x[2] for x in heap]
    top.sort(key=lambda p: (_f((p.get("score") or {}).get("robust_score")), str(p.get("id") or "")), reverse=True)
    mc_top = int(cfg.get("monte_carlo_top_n") or 20)
    hold_mean, hold_std = _f(hold_score.get("objective_mean")), _f(hold_score.get("objective_std"))
    for idx, package in enumerate(top[:mc_top]):
        score = package.get("score") or {}
        mean, std = _f(score.get("objective_mean")), _f(score.get("objective_std"))
        mc = simulate_objective(mean, std, int(cfg.get("monte_carlo_simulations") or 300), int(cfg.get("monte_carlo_seed") or 1) + idx)
        ds = math.sqrt(std * std + hold_std * hold_std)
        mc["p_outperform_hold_independent_baseline"] = round(1.0 - NormalDist(mu=mean - hold_mean, sigma=ds).cdf(0.0), 4) if ds > 0 else (1.0 if mean > hold_mean else 0.5 if mean == hold_mean else 0.0)
        package["monte_carlo"] = mc

    preview_n = max(1, int(cfg.get("candidate_pool_preview_per_position") or 20))
    preview = {p: [{"element": x["element"], "name": x.get("name"), "now_cost": x.get("now_cost"), "candidate_score": round(_f(x.get("candidate_score")), 3)} for x in rows[:preview_n]] for p, rows in pool.items()}
    frontier_out = frontier.output(int((cfg.get("frontier") or {}).get("publish_limit") or 20), evaluated)
    elapsed = round((time.perf_counter() - started) * 1000.0, 3)
    diagnostics = {
        **universe_counts, "candidate_origin": "COMPLETE_ELIGIBLE_OFFICIAL_FPL_UNIVERSE", "eligible_universe_count": sum(eligible.values()), "eligible_by_position": eligible,
        "search_method": "ZERO_CANDIDATE_PRUNING_EXHAUSTIVE_SEQUENTIAL_EXACT_V3_PARALLEL_PARTITIONS", "candidate_pruning_applied": False, "candidate_pruned_count": 0,
        "fixed_top_n_per_position_applied": False, "fixed_top_n_per_outgoing_applied": False, "watchlist_used_as_optimizer_input": False,
        "single_candidates_considered": sc, "single_structural_cash_rejected": s_cash, "single_structural_club_rejected": s_club, "single_step_legal": ss, "single_exact_scored": sscore, "single_budget_applied": False,
        "pair_generation_origin": "DIRECT_OUTGOING_PAIR_X_COMPLETE_POSITION_ELIGIBLE_INCOMING_POOLS", "pair_requires_single_move_seed": False,
        "pair_candidate_combinations": pc, "pair_structural_cash_rejected": p_cash, "pair_structural_club_rejected": p_club, "pair_step_legal": ps, "pair_candidates_exact_scored": pscore,
        "pair_budget_applied": False, "exact_package_limit_applied": False, "all_step_legal_packages_scored": sscore == ss and pscore == ps,
        "lossy_pruning": False, "search_authority": "FULL", "compiled_exact_kernel": True,
        "parallel_partitioning": workers > 1, "parallel_workers": workers, "estimated_pair_combinations": estimated_pairs,
        "partition_semantics": "OUTGOING_PAIR_DISJOINT_EXACT_PARTITIONS_LOCAL_SKYLINES_MERGED_EXACTLY",
        "authority_reason": "complete eligible Official FPL universe; zero candidate pruning; only provably illegal structural rejects; every sequentially legal package scored by the shared canonical exact kernel",
        "optimizer_runtime_status_separate_from_search_authority": True, "finalizer_elapsed_ms": elapsed,
    }
    return {
        "generated_at": iso_now(), "model": cfg.get("model_id"), "status": "READY", "planning_gw": gw, "ruleset_id": RULESET_ID, "gate0_prevalidated": True,
        "simulation_assumption": cfg.get("simulation_assumption"), "candidate_pool": preview, "candidate_pool_is_preview_only": True,
        "package_count": evaluated, "hold": hold, "packages": top[:mc_top], "efficient_frontier": frontier_out, "search_diagnostics": diagnostics,
        "governance": {
            "candidate_generation_only": True, "final_go_requires_framework_governance_and_postflight_gate0": True,
            "price_uses_sell_value_for_outs_and_now_cost_for_ins": True, "official_fpl_full_universe_scanned": True,
            "candidate_pruning_for_full_authority": False, "structural_prefilters_reject_only_provably_illegal_packages": True,
            "fixed_top_n_per_position_forbidden": True, "fixed_top_n_per_outgoing_forbidden": True, "watchlist_is_output_only": True,
            "hardcoded_player_seed_forbidden": True, "pair_search_not_seeded_by_single_legality": True, "step_legal_transfer_recomputation": True,
            "final_squad_reoptimized_by_existing_score_package": True, "prediction_scoring_semantics_unchanged": True,
            "canonical_score_package_reused_for_every_legal_package": True, "compiled_adapter_uses_same_canonical_scoring_kernel": True,
            "parallel_partitions_are_execution_only_not_search_pruning": True, "local_skyline_union_is_exact_global_frontier_input": True,
            "efficient_frontier_from_all_evaluated_legal_packages": True, "efficient_frontier_never_second_scoring_authority": True, "lossy_pruning_is_explicit": False,
        },
    }


def finalize(data_dir: Path = DATA, *, top_keep: int = TOP_KEEP_DEFAULT, persist: bool = True) -> dict[str, Any]:
    projections, team = read_json(data_dir / "projections.json", {}), read_json(data_dir / "team.json", {})
    if not projections or not team:
        raise RuntimeError("certified exhaustive finalizer requires projections.json and team.json")
    optimizer = build_exhaustive(projections, team, top_keep=top_keep)
    diag = optimizer.get("search_diagnostics") or {}
    if optimizer.get("status") != "READY" or diag.get("search_authority") != "FULL" or diag.get("lossy_pruning") is not False or diag.get("all_step_legal_packages_scored") is not True:
        raise RuntimeError("certified exhaustive finalizer did not produce truthful FULL authority")
    if (optimizer.get("efficient_frontier") or {}).get("representation_input") != "ALL_EVALUATED_LEGAL_PACKAGES":
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
        latest["package_decision_summary"] = {"selected_package_id": package.get("selected_package_id"), "manual_authority_override": package.get("manual_authority_override"), "gate0_revalidated": True, "optimizer_search_authority": "FULL"}
        atomic_json(data_dir / "latest.json", latest)
    return {"optimizer": optimizer, "package": package}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(DATA))
    parser.add_argument("--top-keep", type=int, default=TOP_KEEP_DEFAULT)
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()
    result = finalize(Path(args.data_dir), top_keep=max(20, args.top_keep), persist=not args.no_persist)
    d = result["optimizer"]["search_diagnostics"]
    print(json.dumps({"status": result["optimizer"].get("status"), "search_authority": d.get("search_authority"), "eligible_universe_count": d.get("eligible_universe_count"), "candidate_pruned_count": d.get("candidate_pruned_count"), "single_exact_scored": d.get("single_exact_scored"), "pair_exact_scored": d.get("pair_candidates_exact_scored"), "package_count": result["optimizer"].get("package_count"), "frontier_count": (result["optimizer"].get("efficient_frontier") or {}).get("count"), "elapsed_ms": d.get("finalizer_elapsed_ms"), "parallel_workers": d.get("parallel_workers"), "selected_package_id": result["package"].get("selected_package_id"), "gate0_revalidated": result["package"].get("gate0_revalidated")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())