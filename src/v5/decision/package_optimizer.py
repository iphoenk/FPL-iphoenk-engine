from __future__ import annotations

import math
import random
from statistics import NormalDist
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.decision.lineup_optimizer import best_lineup

CONFIG = "config/intelligence/package_optimizer.json"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _gw_row(player: dict[str, Any], gw: int) -> dict[str, Any]:
    return next(
        (row for row in player.get("xpts_by_gw") or [] if int(row.get("gw") or -1) == int(gw)),
        {"mean": 0.0, "std": 0.0},
    )


def legal_squad(players: list[dict[str, Any]], squad_rules: dict[str, Any]) -> bool:
    expected = {str(k): int(v) for k, v in (squad_rules.get("position_counts") or {}).items()}
    if len(players) != int(squad_rules.get("squad_size") or 0):
        return False
    counts = {k: 0 for k in expected}
    clubs: dict[int, int] = {}
    seen = set()
    for player in players:
        element = int(player.get("element") or -1)
        if element in seen:
            return False
        seen.add(element)
        position = str(player.get("position"))
        if position not in counts:
            return False
        counts[position] += 1
        club = int(player.get("team_id") or -1)
        clubs[club] = clubs.get(club, 0) + 1
    return counts == expected and max(clubs.values(), default=0) <= int(squad_rules.get("max_players_per_club") or 0)


def score_package(players: list[dict[str, Any]], planning_gw: int, rules: dict[str, Any], changes: int = 0) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)
    lineup_rules = rules.get("lineup") or {}
    horizons = [int(x) for x in cfg.get("horizons") or [3, 5, 10, 15]]
    results = {}
    for horizon in horizons:
        total_mean = total_var = 0.0
        valid = True
        for offset in range(horizon):
            gw = planning_gw + offset
            lineup = best_lineup(players, gw, lineup_rules)
            if not lineup["valid"]:
                valid = False
                break
            starter_ids = set(lineup["starters"])
            bench = [p for p in players if int(p["element"]) not in starter_ids]
            bench_weight = _f(cfg.get("bench_utility_weight"), 0.10)
            captain_weight = _f(cfg.get("captain_bonus_weight"), 1.0)
            bench_mean = sum(_f(_gw_row(p, gw).get("mean")) for p in bench)
            bench_var = sum(_f(_gw_row(p, gw).get("std")) ** 2 for p in bench)
            captain = max(
                (
                    (_f(_gw_row(p, gw).get("mean")), _f(_gw_row(p, gw).get("std")))
                    for p in players
                    if int(p["element"]) in starter_ids
                ),
                default=(0.0, 0.0),
            )
            total_mean += lineup["mean"] + bench_weight * bench_mean + captain_weight * captain[0]
            total_var += lineup["variance"] + bench_weight**2 * bench_var + captain_weight**2 * captain[1] ** 2
        results[str(horizon)] = {
            "valid": valid,
            "mean": round(total_mean, 3) if valid else None,
            "std": round(math.sqrt(total_var), 3) if valid else None,
        }
    weights = {str(k): _f(v) for k, v in (cfg.get("horizon_weights") or {}).items()}
    available = [(h, results[str(h)]) for h in horizons if results[str(h)]["valid"]]
    weight_sum = sum(weights.get(str(h), 0.0) for h, _ in available)
    if not available or weight_sum <= 0:
        return {"valid": False, "horizons": results}
    mean = sum(weights[str(h)] * row["mean"] for h, row in available) / weight_sum
    variance = sum((weights[str(h)] / weight_sum) ** 2 * row["std"] ** 2 for h, row in available)
    std = math.sqrt(variance)
    robust = mean - _f(cfg.get("risk_aversion"), 0.12) * std - changes * _f(cfg.get("change_penalty_points"), 0.20)
    return {
        "valid": True,
        "horizons": results,
        "objective_mean": round(mean, 3),
        "objective_std": round(std, 3),
        "robust_score": round(robust, 3),
    }


def affordable(outs: list[dict[str, Any]], ins: list[dict[str, Any]], itb: int) -> tuple[bool, dict[str, int]]:
    cash = int(itb) + sum(int(p.get("sell_cost") or 0) for p in outs)
    cost = sum(int(p.get("now_cost") or 0) for p in ins)
    return cost <= cash, {"cash_available": cash, "incoming_cost": cost, "resulting_itb": cash - cost}


def _simulate(mean: float, std: float, simulations: int, seed: int) -> dict[str, float]:
    rng = random.Random(seed)
    samples = sorted(rng.gauss(mean, max(0.0001, std)) for _ in range(max(20, simulations)))

    def pct(q: float) -> float:
        return samples[min(len(samples) - 1, max(0, int(round((len(samples) - 1) * q))))]

    return {"p25": round(pct(0.25), 3), "p50": round(pct(0.5), 3), "p75": round(pct(0.75), 3)}


def build_packages(prediction: dict[str, Any], team: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)
    players = prediction.get("players") or []
    pmap = {int(p["element"]): p for p in players}
    finance = team.get("finance") or {}
    ledger = finance.get("players") or []
    current = []
    owned_ids = set()
    for row in ledger:
        eid = int(row.get("element") or -1)
        proj = pmap.get(eid)
        if not proj:
            continue
        owned_ids.add(eid)
        current.append({**proj, "sell_cost": row.get("sell_cost")})
    if not finance.get("sell_value_complete") or not legal_squad(current, rules.get("squad") or {}):
        return {
            "status": "BLOCKED",
            "reason": "finance incomplete or current squad illegal",
            "packages": [],
            "gate0_prevalidated": False,
        }

    planning_gw = int(prediction.get("planning_gw") or 1)
    itb = int(finance.get("bank") or 0)
    allowed = set(cfg.get("allowed_statuses") or ["a", "d"])
    pools: dict[str, list[dict[str, Any]]] = {}
    for position in ("GK", "DEF", "MID", "FWD"):
        rows = []
        for player in players:
            if (
                player.get("position") != position
                or int(player["element"]) in owned_ids
                or player.get("status") not in allowed
            ):
                continue
            candidate = {**player, "sell_cost": player.get("now_cost")}
            h5 = (player.get("horizons") or {}).get("5") or {}
            candidate["candidate_score"] = _f(h5.get("mean")) - _f(cfg.get("risk_aversion"), 0.12) * _f(h5.get("std"))
            rows.append(candidate)
        rows.sort(key=lambda x: (x["candidate_score"], -int(x.get("now_cost") or 0)), reverse=True)
        pools[position] = rows[: int(cfg.get("max_candidates_per_position") or 7)]

    hold_score = score_package(current, planning_gw, rules, changes=0)
    packages = [
        {
            "id": "HOLD",
            "changes": 0,
            "outs": [],
            "ins": [],
            "affordability": {"resulting_itb": itb},
            "score": hold_score,
            "legal": True,
        }
    ]
    singles = []
    for outgoing in current:
        for incoming in pools.get(outgoing["position"], [])[: int(cfg.get("max_single_moves_per_out") or 4)]:
            ok, money = affordable([outgoing], [incoming], itb)
            candidate = [p for p in current if int(p["element"]) != int(outgoing["element"])] + [incoming]
            if not ok or not legal_squad(candidate, rules.get("squad") or {}):
                continue
            score = score_package(candidate, planning_gw, rules, changes=1)
            singles.append((outgoing, incoming, candidate, money, score))
            packages.append(
                {
                    "id": f"1:{outgoing['element']}->{incoming['element']}",
                    "changes": 1,
                    "outs": [
                        {
                            "element": outgoing["element"],
                            "name": outgoing.get("name"),
                            "sell_cost": outgoing.get("sell_cost"),
                        }
                    ],
                    "ins": [
                        {
                            "element": incoming["element"],
                            "name": incoming.get("name"),
                            "now_cost": incoming.get("now_cost"),
                        }
                    ],
                    "affordability": money,
                    "score": score,
                    "legal": True,
                }
            )

    singles.sort(key=lambda x: _f(x[4].get("robust_score")), reverse=True)
    seeds = singles[: int(cfg.get("double_move_seed_limit") or 40)]
    seen = set()
    if int(cfg.get("max_changes") or 2) >= 2:
        for index, first in enumerate(seeds):
            for second in seeds[index + 1 :]:
                outs, ins = [first[0], second[0]], [first[1], second[1]]
                if outs[0]["element"] == outs[1]["element"] or ins[0]["element"] == ins[1]["element"]:
                    continue
                key = tuple(sorted([outs[0]["element"], outs[1]["element"]])) + tuple(
                    sorted([ins[0]["element"], ins[1]["element"]])
                )
                if key in seen:
                    continue
                seen.add(key)
                ok, money = affordable(outs, ins, itb)
                out_ids = {int(x["element"]) for x in outs}
                candidate = [p for p in current if int(p["element"]) not in out_ids] + ins
                if not ok or not legal_squad(candidate, rules.get("squad") or {}):
                    continue
                score = score_package(candidate, planning_gw, rules, changes=2)
                packages.append(
                    {
                        "id": f"2:{outs[0]['element']},{outs[1]['element']}->{ins[0]['element']},{ins[1]['element']}",
                        "changes": 2,
                        "outs": [
                            {"element": x["element"], "name": x.get("name"), "sell_cost": x.get("sell_cost")}
                            for x in outs
                        ],
                        "ins": [
                            {"element": x["element"], "name": x.get("name"), "now_cost": x.get("now_cost")}
                            for x in ins
                        ],
                        "affordability": money,
                        "score": score,
                        "legal": True,
                    }
                )
                if len(packages) >= int(cfg.get("max_deterministic_packages") or 220):
                    break
            if len(packages) >= int(cfg.get("max_deterministic_packages") or 220):
                break

    packages = [p for p in packages if (p.get("score") or {}).get("valid")]
    packages.sort(key=lambda p: _f((p.get("score") or {}).get("robust_score")), reverse=True)
    hold_mean, hold_std = _f(hold_score.get("objective_mean")), _f(hold_score.get("objective_std"))
    top_n = int(cfg.get("monte_carlo_top_n") or 20)
    for idx, package in enumerate(packages[:top_n]):
        mean, std = _f(package["score"].get("objective_mean")), _f(package["score"].get("objective_std"))
        mc = _simulate(
            mean,
            std,
            int(cfg.get("monte_carlo_simulations") or 300),
            int(cfg.get("monte_carlo_seed") or 1) + idx,
        )
        diff_std = math.sqrt(std**2 + hold_std**2)
        mc["p_outperform_hold_independent_baseline"] = (
            round(1.0 - NormalDist(mu=mean - hold_mean, sigma=diff_std).cdf(0.0), 4)
            if diff_std > 0
            else (1.0 if mean > hold_mean else 0.5)
        )
        package["monte_carlo"] = mc

    return {
        "model": cfg.get("model_id"),
        "status": "READY",
        "planning_gw": planning_gw,
        "ruleset_id": rules.get("ruleset_id"),
        "gate0_prevalidated": True,
        "simulation_assumption": cfg.get("simulation_assumption"),
        "package_count": len(packages),
        "hold": next((p for p in packages if p["id"] == "HOLD"), None),
        "candidate_pool": {
            pos: [
                {
                    "element": p["element"],
                    "name": p.get("name"),
                    "now_cost": p.get("now_cost"),
                    "candidate_score": round(_f(p.get("candidate_score")), 3),
                }
                for p in rows
            ]
            for pos, rows in pools.items()
        },
        "packages": packages[:top_n],
        "governance": {
            "candidate_generation_only": True,
            "final_go_requires_framework_governance_and_postflight_gate0": True,
            "price_uses_sell_value_for_outs_and_now_cost_for_ins": True,
            "lineup_authority": "src.v5.decision.lineup_optimizer",
        },
    }
