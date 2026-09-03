from __future__ import annotations

import math
from datetime import datetime, timezone
from statistics import NormalDist
from typing import Any

from src.models.package_optimizer_v2 import (
    _scoring_context,
    legal_squad,
    load_config as load_optimizer_config,
    score_package,
    simulate_objective,
)
from src.rules import RULESET_ID


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _optimizer_row(proj: dict[str, Any], sell_cost_value: int | None = None) -> dict[str, Any]:
    return {
        "element": int(proj["element"]),
        "name": proj.get("name"),
        "position": proj.get("position"),
        "team_id": int(proj.get("team_id") or -1),
        "now_cost": int(proj.get("now_cost") or 0),
        "sell_cost": int(sell_cost_value if sell_cost_value is not None else proj.get("now_cost") or 0),
        "status": proj.get("status"),
        "xpts_by_gw": proj.get("xpts_by_gw") or [],
        "horizons": proj.get("horizons") or {},
        "tactical_matchup": proj.get("tactical_matchup") or {},
        "xmins": proj.get("xmins") or {},
    }


def _candidate_score(proj: dict[str, Any], risk_aversion: float) -> float:
    horizon = (proj.get("horizons") or {}).get("5") or {}
    return _f(horizon.get("mean")) - risk_aversion * _f(horizon.get("std"))


def _horizon_metric(row: dict[str, Any], horizon: int, field: str) -> float:
    return _f(((row.get("horizons") or {}).get(str(horizon)) or {}).get(field))


def _candidate_dominates(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Deterministic team-position Pareto relation used only for search pruning.

    Cross-team dominance is intentionally forbidden because club-slot structure can
    make an otherwise weaker player strategically useful. This relation does not
    mutate projections or xPts; it only identifies clearly inferior search rows
    within the same Official-FPL team and position on the declared dimensions.
    """
    if left.get("position") != right.get("position") or int(left.get("team_id") or -1) != int(right.get("team_id") or -1):
        return False
    no_worse = int(left.get("now_cost") or 0) <= int(right.get("now_cost") or 0)
    strict = int(left.get("now_cost") or 0) < int(right.get("now_cost") or 0)
    for horizon in (3, 5, 10, 15):
        left_mean = _horizon_metric(left, horizon, "mean")
        right_mean = _horizon_metric(right, horizon, "mean")
        left_std = _horizon_metric(left, horizon, "std")
        right_std = _horizon_metric(right, horizon, "std")
        if left_mean < right_mean - 1e-9 or left_std > right_std + 1e-9:
            no_worse = False
            break
        strict = strict or left_mean > right_mean + 1e-9 or left_std < right_std - 1e-9
    return no_worse and strict


def _team_position_pareto_pool(full_pool: dict[str, list[dict[str, Any]]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    search_pool: dict[str, list[dict[str, Any]]] = {pos: [] for pos in full_pool}
    groups = 0
    pruned = 0
    group_diagnostics: list[dict[str, Any]] = []
    for position, rows in full_pool.items():
        by_team: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            by_team.setdefault(int(row.get("team_id") or -1), []).append(row)
        for team_id in sorted(by_team):
            group = by_team[team_id]
            groups += 1
            kept = []
            for candidate in group:
                if any(other is not candidate and _candidate_dominates(other, candidate) for other in group):
                    pruned += 1
                    continue
                kept.append(candidate)
            kept.sort(key=lambda row: (row["candidate_score"], -int(row.get("now_cost") or 0), -int(row.get("element") or -1)), reverse=True)
            search_pool[position].extend(kept)
            group_diagnostics.append({
                "position": position,
                "team_id": team_id,
                "eligible": len(group),
                "pareto_kept": len(kept),
                "pruned": len(group) - len(kept),
            })
        search_pool[position].sort(key=lambda row: (row["candidate_score"], -int(row.get("now_cost") or 0), -int(row.get("element") or -1)), reverse=True)
    return search_pool, {
        "team_position_groups": groups,
        "pareto_pruned_count": pruned,
        "groups": group_diagnostics,
    }


def _step_legal_transfer_sequence(
    current: list[dict[str, Any]],
    outs: list[dict[str, Any]],
    ins: list[dict[str, Any]],
    itb: int,
) -> tuple[bool, dict[str, Any]]:
    if len(outs) != len(ins):
        return False, {"reason": "out_in_count_mismatch", "orders_checked": 0}
    if not outs:
        return legal_squad(current), {"resulting_itb": int(itb), "steps": [], "execution_order": [], "orders_checked": 1}
    if len(outs) == 1:
        orders = [(0,)]
    elif len(outs) == 2:
        orders = [(0, 1), (1, 0)]
    else:
        return False, {"reason": "unsupported_transfer_sequence_length", "orders_checked": 0}

    for order in orders:
        squad = list(current)
        cash = int(itb)
        steps: list[dict[str, Any]] = []
        valid = True
        for idx in order:
            outgoing = outs[idx]
            incoming = ins[idx]
            out_element = int(outgoing.get("element") or -1)
            if out_element not in {int(p.get("element") or -1) for p in squad}:
                valid = False
                break
            cash_before = cash
            cash += int(outgoing.get("sell_cost") or 0)
            incoming_cost = int(incoming.get("now_cost") or 0)
            if incoming_cost > cash:
                valid = False
                break
            next_squad = [p for p in squad if int(p.get("element") or -1) != out_element] + [incoming]
            cash -= incoming_cost
            if not legal_squad(next_squad):
                valid = False
                break
            steps.append({
                "out": out_element,
                "in": int(incoming.get("element") or -1),
                "itb_before": cash_before,
                "sell_value": int(outgoing.get("sell_cost") or 0),
                "buy_price": incoming_cost,
                "itb_after": cash,
                "legal_squad_after_step": True,
            })
            squad = next_squad
        if valid and len(steps) == len(outs) and legal_squad(squad):
            return True, {
                "resulting_itb": cash,
                "steps": steps,
                "execution_order": list(order),
                "orders_checked": len(orders),
            }
    return False, {"reason": "no_step_legal_execution_order", "orders_checked": len(orders)}


def _package_frontier(packages: list[dict[str, Any]], hold: dict[str, Any] | None, limit: int) -> dict[str, Any]:
    if not packages:
        return {"count": 0, "packages": [], "authority": "EMPTY"}
    hold_horizons = ((hold or {}).get("score") or {}).get("horizons") or {}

    def metrics(package: dict[str, Any]) -> dict[str, Any]:
        score = package.get("score") or {}
        horizons = score.get("horizons") or {}
        net = {}
        for horizon in (3, 5, 10, 15):
            row = horizons.get(str(horizon)) or {}
            base = hold_horizons.get(str(horizon)) or {}
            net[str(horizon)] = _f(row.get("mean")) - _f(base.get("mean"))
        return {
            "net": net,
            "changes": int(package.get("changes") or 0),
            "uncertainty": _f(score.get("objective_std"), 1e9),
        }

    measured = [(package, metrics(package)) for package in packages]
    frontier: list[dict[str, Any]] = []
    for package, row in measured:
        dominated = False
        for other, other_row in measured:
            if other is package:
                continue
            at_least_as_good = (
                all(other_row["net"][h] >= row["net"][h] for h in ("3", "5", "10", "15"))
                and other_row["changes"] <= row["changes"]
                and other_row["uncertainty"] <= row["uncertainty"]
            )
            strictly_better = (
                any(other_row["net"][h] > row["net"][h] for h in ("3", "5", "10", "15"))
                or other_row["changes"] < row["changes"]
                or other_row["uncertainty"] < row["uncertainty"]
            )
            if at_least_as_good and strictly_better:
                dominated = True
                break
        if not dominated:
            frontier.append({
                "id": package.get("id"),
                "changes": package.get("changes"),
                "robust_score": (package.get("score") or {}).get("robust_score"),
                "net_xpts": row["net"],
                "objective_std": row["uncertainty"],
                "resulting_itb": (package.get("affordability") or {}).get("resulting_itb"),
            })
    frontier.sort(key=lambda row: _f(row.get("robust_score")), reverse=True)
    return {
        "count": len(frontier),
        "packages": frontier[: max(1, int(limit))],
        "authority": "REPRESENTATION_ONLY",
        "dimensions_used": ["net_xpts3", "net_xpts5", "net_xpts10", "net_xpts15", "changes", "objective_std"],
        "dimensions_pending_richer_runtime_evidence": ["tactical_role_uncertainty", "price_risk", "structural_flexibility"],
        "never_second_scoring_authority": True,
    }


def _select_exact_single_stubs(stubs: list[dict[str, Any]], budget: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not stubs or budget <= 0:
        return [], {"available": len(stubs), "selected": 0, "budget": budget, "budget_exhausted": bool(stubs)}

    def priority(stub: dict[str, Any]) -> tuple[float, int, int]:
        return (
            _f(stub.get("cheap_delta")),
            -int((stub.get("in") or {}).get("now_cost") or 0),
            -int((stub.get("in") or {}).get("element") or -1),
        )

    by_team_position: dict[tuple[str, int], dict[str, Any]] = {}
    by_outgoing: dict[int, dict[str, Any]] = {}
    for stub in stubs:
        incoming = stub["in"]
        outgoing = stub["out"]
        team_key = (str(incoming.get("position")), int(incoming.get("team_id") or -1))
        out_key = int(outgoing.get("element") or -1)
        if team_key not in by_team_position or priority(stub) > priority(by_team_position[team_key]):
            by_team_position[team_key] = stub
        if out_key not in by_outgoing or priority(stub) > priority(by_outgoing[out_key]):
            by_outgoing[out_key] = stub

    mandatory = list(by_team_position.values()) + list(by_outgoing.values())
    unique: dict[tuple[int, int], dict[str, Any]] = {}
    for stub in mandatory:
        key = (int(stub["out"]["element"]), int(stub["in"]["element"]))
        if key not in unique or priority(stub) > priority(unique[key]):
            unique[key] = stub
    mandatory_rows = sorted(unique.values(), key=priority, reverse=True)

    selected = mandatory_rows[:budget]
    selected_keys = {(int(stub["out"]["element"]), int(stub["in"]["element"])) for stub in selected}
    if len(selected) < budget:
        remaining = sorted(
            [
                stub for stub in stubs
                if (int(stub["out"]["element"]), int(stub["in"]["element"])) not in selected_keys
            ],
            key=priority,
            reverse=True,
        )
        selected.extend(remaining[: budget - len(selected)])

    selected_team_positions = {
        (str(stub["in"].get("position")), int(stub["in"].get("team_id") or -1))
        for stub in selected
    }
    all_team_positions = {
        (str(stub["in"].get("position")), int(stub["in"].get("team_id") or -1))
        for stub in stubs
    }
    selected_outs = {int(stub["out"].get("element") or -1) for stub in selected}
    all_outs = {int(stub["out"].get("element") or -1) for stub in stubs}
    return selected, {
        "available": len(stubs),
        "selected": len(selected),
        "budget": budget,
        "budget_exhausted": len(stubs) > len(selected),
        "team_position_groups_available": len(all_team_positions),
        "team_position_groups_selected": len(selected_team_positions),
        "team_position_coverage": round(len(selected_team_positions) / max(1, len(all_team_positions)), 4),
        "outgoing_elements_available": len(all_outs),
        "outgoing_elements_selected": len(selected_outs),
        "outgoing_coverage": round(len(selected_outs) / max(1, len(all_outs)), 4),
        "mandatory_seed_policy": ["incoming_team_position", "outgoing_element"],
    }


def build_package_optimizer(projections: dict[str, Any], team: dict[str, Any]) -> dict[str, Any]:
    cfg = load_optimizer_config()
    planning_gw = int(projections.get("planning_gw") or 1)
    scoring_context = _scoring_context(cfg, planning_gw)
    pmap = {int(p["element"]): p for p in projections.get("players") or []}
    ledger = list(team.get("team_value_ledger") or [])
    current = []
    owned_ids = set()
    for row in ledger:
        element = int(row.get("element") or -1)
        proj = pmap.get(element)
        if not proj:
            continue
        owned_ids.add(element)
        current.append(_optimizer_row(proj, row.get("sell_cost")))
    if not legal_squad(current):
        return {
            "generated_at": _now(),
            "model": cfg.get("model_id"),
            "status": "BLOCKED",
            "reason": "current squad failed legality precheck",
            "packages": [],
        }

    itb = int((team.get("totals") or {}).get("itb") or 0)
    allowed = set(cfg.get("allowed_statuses") or ["a", "d"])
    require_available = bool(cfg.get("require_available_status", True))
    candidate_risk_aversion = _f(cfg.get("risk_aversion"), 0.12)
    full_pool: dict[str, list[dict[str, Any]]] = {pos: [] for pos in ("GK", "DEF", "MID", "FWD")}
    universe_seen = excluded_owned = excluded_status = excluded_invalid = 0
    for proj in projections.get("players") or []:
        universe_seen += 1
        try:
            element = int(proj["element"])
        except (KeyError, TypeError, ValueError):
            excluded_invalid += 1
            continue
        position = str(proj.get("position") or "")
        if position not in full_pool:
            excluded_invalid += 1
            continue
        if element in owned_ids:
            excluded_owned += 1
            continue
        if require_available and proj.get("status") not in allowed:
            excluded_status += 1
            continue
        row = _optimizer_row(proj)
        row["candidate_score"] = _candidate_score(proj, candidate_risk_aversion)
        full_pool[position].append(row)
    for rows in full_pool.values():
        rows.sort(key=lambda r: (r["candidate_score"], -r["now_cost"], -r["element"]), reverse=True)

    search_cfg = cfg.get("search_frontier") or {}
    search_pool, pareto_diag = _team_position_pareto_pool(full_pool)
    exact_single_budget = max(1, int(search_cfg.get("single_exact_evaluation_budget") or 80))
    exact_package_limit = max(1, int(search_cfg.get("max_exact_packages") or 220))

    hold_score = score_package(current, planning_gw, changes=0, scoring_context=scoring_context)
    hold_robust = _f(hold_score.get("robust_score"))
    packages = [{
        "id": "HOLD",
        "changes": 0,
        "outs": [],
        "ins": [],
        "affordability": {"resulting_itb": itb},
        "score": hold_score,
        "legal": True,
        "sequential_legality": {"resulting_itb": itb, "steps": [], "execution_order": []},
    }]

    owned_candidate_scores = {int(row["element"]): _candidate_score(pmap[int(row["element"])], candidate_risk_aversion) for row in current}
    legal_single_stubs: list[dict[str, Any]] = []
    cheap_single_considered = 0
    for out in current:
        for incoming in search_pool.get(str(out.get("position")), []):
            cheap_single_considered += 1
            step_ok, sequence = _step_legal_transfer_sequence(current, [out], [incoming], itb)
            if not step_ok:
                continue
            legal_single_stubs.append({
                "out": out,
                "in": incoming,
                "sequence": sequence,
                "cheap_delta": _f(incoming.get("candidate_score")) - _f(owned_candidate_scores.get(int(out["element"]))),
            })

    exact_stubs, single_selection_diag = _select_exact_single_stubs(legal_single_stubs, exact_single_budget)
    single_moves: list[dict[str, Any]] = []
    for stub in exact_stubs:
        out = stub["out"]
        incoming = stub["in"]
        sequence = stub["sequence"]
        candidate = [p for p in current if p["element"] != out["element"]] + [incoming]
        score = score_package(candidate, planning_gw, changes=1, scoring_context=scoring_context)
        if not score.get("valid"):
            continue
        finance = {
            "cash_available": int(itb) + int(out.get("sell_cost") or 0),
            "incoming_cost": int(incoming.get("now_cost") or 0),
            "resulting_itb": int(sequence["resulting_itb"]),
        }
        move = {"out": out, "in": incoming, "candidate": candidate, "finance": finance, "score": score, "sequence": sequence}
        single_moves.append(move)
        packages.append({
            "id": f"1:{out['element']}->{incoming['element']}",
            "changes": 1,
            "outs": [{"element": out["element"], "name": out["name"], "sell_cost": out["sell_cost"]}],
            "ins": [{"element": incoming["element"], "name": incoming["name"], "now_cost": incoming["now_cost"]}],
            "affordability": finance,
            "score": score,
            "legal": True,
            "sequential_legality": sequence,
        })

    pair_candidates: list[dict[str, Any]] = []
    pair_seen: set[tuple[int, ...]] = set()
    if int(cfg.get("max_changes") or 2) >= 2:
        for i, a in enumerate(single_moves):
            for b in single_moves[i + 1 :]:
                outs = [a["out"], b["out"]]
                ins = [a["in"], b["in"]]
                if outs[0]["element"] == outs[1]["element"] or ins[0]["element"] == ins[1]["element"]:
                    continue
                key = tuple(sorted([outs[0]["element"], outs[1]["element"]])) + tuple(sorted([ins[0]["element"], ins[1]["element"]]))
                if key in pair_seen:
                    continue
                pair_seen.add(key)
                pair_candidates.append({
                    "outs": outs,
                    "ins": ins,
                    "priority": _f((a.get("score") or {}).get("robust_score")) + _f((b.get("score") or {}).get("robust_score")) - hold_robust,
                })
    pair_candidates.sort(
        key=lambda row: (
            _f(row.get("priority")),
            tuple(int(x.get("element") or -1) for x in row["ins"]),
        ),
        reverse=True,
    )

    pair_considered = pair_evaluated = pair_legal = 0
    package_limit_hit = False
    for pair in pair_candidates:
        pair_considered += 1
        if len(packages) >= exact_package_limit:
            package_limit_hit = True
            break
        outs = pair["outs"]
        ins = pair["ins"]
        step_ok, sequence = _step_legal_transfer_sequence(current, outs, ins, itb)
        if not step_ok:
            continue
        pair_evaluated += 1
        out_ids = {x["element"] for x in outs}
        candidate = [p for p in current if p["element"] not in out_ids] + ins
        score = score_package(candidate, planning_gw, changes=2, scoring_context=scoring_context)
        if not score.get("valid"):
            continue
        pair_legal += 1
        finance = {
            "cash_available": int(itb) + sum(int(x.get("sell_cost") or 0) for x in outs),
            "incoming_cost": sum(int(x.get("now_cost") or 0) for x in ins),
            "resulting_itb": int(sequence["resulting_itb"]),
        }
        packages.append({
            "id": f"2:{outs[0]['element']},{outs[1]['element']}->{ins[0]['element']},{ins[1]['element']}",
            "changes": 2,
            "outs": [{"element": x["element"], "name": x["name"], "sell_cost": x["sell_cost"]} for x in outs],
            "ins": [{"element": x["element"], "name": x["name"], "now_cost": x["now_cost"]} for x in ins],
            "affordability": finance,
            "score": score,
            "legal": True,
            "sequential_legality": sequence,
        })

    packages = [p for p in packages if p.get("score", {}).get("valid")]
    packages.sort(key=lambda p: (_f((p.get("score") or {}).get("robust_score")), str(p.get("id"))), reverse=True)
    mc_top = int(cfg.get("monte_carlo_top_n") or 20)
    simulations = int(cfg.get("monte_carlo_simulations") or 300)
    base_seed = int(cfg.get("monte_carlo_seed") or 1)
    hold_mean = _f(hold_score.get("objective_mean"))
    hold_std = _f(hold_score.get("objective_std"))
    for idx, package in enumerate(packages[:mc_top]):
        mean = _f(package["score"].get("objective_mean"))
        std = _f(package["score"].get("objective_std"))
        package["monte_carlo"] = simulate_objective(mean, std, simulations, base_seed + idx)
        diff_std = math.sqrt(std ** 2 + hold_std ** 2)
        if diff_std > 0:
            p_out = 1.0 - NormalDist(mu=mean - hold_mean, sigma=diff_std).cdf(0.0)
        else:
            p_out = 1.0 if mean > hold_mean else 0.5 if mean == hold_mean else 0.0
        package["monte_carlo"]["p_outperform_hold_independent_baseline"] = round(p_out, 4)

    hold = next((p for p in packages if p["id"] == "HOLD"), None)
    frontier_cfg = cfg.get("frontier") or {}
    frontier = _package_frontier(packages, hold, int(frontier_cfg.get("publish_limit") or 20)) if frontier_cfg.get("enabled", True) else {"count": 0, "packages": [], "authority": "DISABLED"}
    preview_limit = max(1, int(cfg.get("candidate_pool_preview_per_position") or 20))
    pool_preview = {
        pos: [
            {"element": p["element"], "name": p["name"], "now_cost": p["now_cost"], "candidate_score": round(p["candidate_score"], 3)}
            for p in rows[:preview_limit]
        ]
        for pos, rows in full_pool.items()
    }
    eligible_by_position = {position: len(rows) for position, rows in full_pool.items()}
    pareto_by_position = {position: len(rows) for position, rows in search_pool.items()}
    lossy_pruning = (
        int(pareto_diag.get("pareto_pruned_count") or 0) > 0
        or bool(single_selection_diag.get("budget_exhausted"))
        or package_limit_hit
        or pair_evaluated < len(pair_candidates)
    )
    search_authority = str(search_cfg.get("authority_when_applied") or "PARTIAL") if lossy_pruning else "FULL"
    frontier["search_authority"] = search_authority

    return {
        "generated_at": _now(),
        "model": cfg.get("model_id"),
        "status": "READY",
        "planning_gw": planning_gw,
        "ruleset_id": RULESET_ID,
        "gate0_prevalidated": True,
        "simulation_assumption": cfg.get("simulation_assumption"),
        "candidate_pool": pool_preview,
        "candidate_pool_is_preview_only": True,
        "package_count": len(packages),
        "hold": hold,
        "packages": packages[:mc_top],
        "efficient_frontier": frontier,
        "search_diagnostics": {
            "candidate_origin": cfg.get("candidate_origin", "COMPLETE_ELIGIBLE_OFFICIAL_FPL_UNIVERSE"),
            "official_projection_universe_count": universe_seen,
            "owned_excluded_count": excluded_owned,
            "status_excluded_count": excluded_status,
            "invalid_excluded_count": excluded_invalid,
            "eligible_universe_count": sum(eligible_by_position.values()),
            "eligible_by_position": eligible_by_position,
            "search_frontier_method": search_cfg.get("method"),
            "pareto_frontier_by_position": pareto_by_position,
            "pareto_pruned_count": pareto_diag.get("pareto_pruned_count"),
            "team_position_groups": pareto_diag.get("team_position_groups"),
            "team_position_group_diagnostics": pareto_diag.get("groups"),
            "fixed_top_n_per_position_applied": False,
            "fixed_top_n_per_outgoing_applied": False,
            "watchlist_used_as_optimizer_input": False,
            "cheap_single_moves_considered": cheap_single_considered,
            "legal_single_stubs": len(legal_single_stubs),
            "single_exact_selection": single_selection_diag,
            "single_exact_scored": len(single_moves),
            "pair_candidate_pool": len(pair_candidates),
            "pair_candidates_considered_before_stop": pair_considered,
            "pair_candidates_exact_scored": pair_evaluated,
            "pair_candidates_legal": pair_legal,
            "exact_package_limit": exact_package_limit,
            "exact_package_limit_hit": package_limit_hit,
            "lossy_pruning": lossy_pruning,
            "search_authority": search_authority,
            "authority_reason": search_cfg.get("reason") if lossy_pruning else None,
            "optimizer_runtime_status_separate_from_search_authority": True,
        },
        "governance": {
            "candidate_generation_only": True,
            "final_go_requires_framework_governance_and_postflight_gate0": True,
            "price_uses_sell_value_for_outs_and_now_cost_for_ins": True,
            "official_fpl_full_universe_scanned_before_pruning": True,
            "fixed_top_n_per_position_forbidden": True,
            "fixed_top_n_per_outgoing_forbidden": True,
            "watchlist_is_output_only": True,
            "hardcoded_player_seed_forbidden": True,
            "team_diversity_preserved_before_exact_budget": True,
            "step_legal_transfer_recomputation": True,
            "final_squad_reoptimized_by_existing_score_package": True,
            "prediction_scoring_semantics_unchanged": True,
            "efficient_frontier_never_second_scoring_authority": True,
            "lossy_pruning_is_explicit": lossy_pruning,
        },
    }
