from __future__ import annotations

import math
from datetime import datetime, timezone
from statistics import NormalDist
from typing import Any

from src.models.package_optimizer_v2 import affordable_package, legal_squad, load_config as load_optimizer_config, score_package, simulate_objective
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
    }


def build_package_optimizer(projections: dict[str, Any], team: dict[str, Any]) -> dict[str, Any]:
    cfg = load_optimizer_config()
    planning_gw = int(projections.get("planning_gw") or 1)
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
    candidate_pool: dict[str, list[dict[str, Any]]] = {}
    max_candidates = int(cfg.get("max_candidates_per_position") or 7)
    candidate_risk_aversion = _f(cfg.get("risk_aversion"), 0.12)
    for position in ("GK", "DEF", "MID", "FWD"):
        rows = []
        for proj in projections.get("players") or []:
            if proj.get("position") != position or int(proj["element"]) in owned_ids:
                continue
            if require_available and proj.get("status") not in allowed:
                continue
            row = _optimizer_row(proj)
            row["candidate_score"] = _f((proj.get("horizons") or {}).get("5", {}).get("mean")) - candidate_risk_aversion * _f((proj.get("horizons") or {}).get("5", {}).get("std"))
            rows.append(row)
        rows.sort(key=lambda r: (r["candidate_score"], -r["now_cost"]), reverse=True)
        candidate_pool[position] = rows[:max_candidates]

    hold_score = score_package(current, planning_gw, changes=0)
    packages = [{
        "id": "HOLD",
        "changes": 0,
        "outs": [],
        "ins": [],
        "affordability": {"resulting_itb": itb},
        "score": hold_score,
        "legal": True,
    }]
    single_moves = []
    max_per_out = int(cfg.get("max_single_moves_per_out") or 4)
    for out in current:
        candidate_rows = candidate_pool.get(out["position"], [])[:max_per_out]
        for incoming in candidate_rows:
            ok_cash, finance = affordable_package([out], [incoming], itb)
            if not ok_cash:
                continue
            candidate = [p for p in current if p["element"] != out["element"]] + [incoming]
            if not legal_squad(candidate):
                continue
            score = score_package(candidate, planning_gw, changes=1)
            move = {"out": out, "in": incoming, "candidate": candidate, "finance": finance, "score": score}
            single_moves.append(move)
            packages.append({
                "id": f"1:{out['element']}->{incoming['element']}",
                "changes": 1,
                "outs": [{"element": out["element"], "name": out["name"], "sell_cost": out["sell_cost"]}],
                "ins": [{"element": incoming["element"], "name": incoming["name"], "now_cost": incoming["now_cost"]}],
                "affordability": finance,
                "score": score,
                "legal": True,
            })

    if int(cfg.get("max_changes") or 2) >= 2:
        single_moves.sort(key=lambda x: _f((x.get("score") or {}).get("robust_score")), reverse=True)
        seed_moves = single_moves[: min(40, len(single_moves))]
        seen = set()
        for i, a in enumerate(seed_moves):
            for b in seed_moves[i + 1 :]:
                outs = [a["out"], b["out"]]
                ins = [a["in"], b["in"]]
                if outs[0]["element"] == outs[1]["element"] or ins[0]["element"] == ins[1]["element"]:
                    continue
                key = tuple(sorted([outs[0]["element"], outs[1]["element"]])) + tuple(sorted([ins[0]["element"], ins[1]["element"]]))
                if key in seen:
                    continue
                seen.add(key)
                ok_cash, finance = affordable_package(outs, ins, itb)
                if not ok_cash:
                    continue
                out_ids = {x["element"] for x in outs}
                candidate = [p for p in current if p["element"] not in out_ids] + ins
                if not legal_squad(candidate):
                    continue
                score = score_package(candidate, planning_gw, changes=2)
                packages.append({
                    "id": f"2:{outs[0]['element']},{outs[1]['element']}->{ins[0]['element']},{ins[1]['element']}",
                    "changes": 2,
                    "outs": [{"element": x["element"], "name": x["name"], "sell_cost": x["sell_cost"]} for x in outs],
                    "ins": [{"element": x["element"], "name": x["name"], "now_cost": x["now_cost"]} for x in ins],
                    "affordability": finance,
                    "score": score,
                    "legal": True,
                })
                if len(packages) >= int(cfg.get("max_deterministic_packages") or 220):
                    break
            if len(packages) >= int(cfg.get("max_deterministic_packages") or 220):
                break

    packages = [p for p in packages if p.get("score", {}).get("valid")]
    packages.sort(key=lambda p: _f((p.get("score") or {}).get("robust_score")), reverse=True)
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

    pool_summary = {
        pos: [
            {"element": p["element"], "name": p["name"], "now_cost": p["now_cost"], "candidate_score": round(p["candidate_score"], 3)}
            for p in rows
        ]
        for pos, rows in candidate_pool.items()
    }
    return {
        "generated_at": _now(),
        "model": cfg.get("model_id"),
        "status": "READY",
        "planning_gw": planning_gw,
        "ruleset_id": RULESET_ID,
        "gate0_prevalidated": True,
        "simulation_assumption": cfg.get("simulation_assumption"),
        "candidate_pool": pool_summary,
        "package_count": len(packages),
        "hold": next((p for p in packages if p["id"] == "HOLD"), None),
        "packages": packages[:mc_top],
        "governance": {
            "candidate_generation_only": True,
            "final_go_requires_framework_governance_and_postflight_gate0": True,
            "price_uses_sell_value_for_outs_and_now_cost_for_ins": True,
        },
    }
