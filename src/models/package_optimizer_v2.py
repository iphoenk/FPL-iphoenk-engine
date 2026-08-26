from __future__ import annotations

import json
import math
import random
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.rules import LINEUP_RULES, SQUAD_RULES

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "intelligence" / "package_optimizer.json"


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _gw_row(player: dict[str, Any], gw: int) -> dict[str, Any]:
    for row in player.get("xpts_by_gw") or []:
        if int(row.get("gw") or -1) == int(gw):
            return row
    return {"mean": 0.0, "std": 0.0}


def _gw_index(players: list[dict[str, Any]]) -> dict[int, dict[int, dict[str, Any]]]:
    return {
        int(player.get("element") or -1): {
            int(row.get("gw") or -1): row
            for row in (player.get("xpts_by_gw") or [])
        }
        for player in players
    }


def _indexed_row(index: dict[int, dict[int, dict[str, Any]]], player: dict[str, Any], gw: int) -> dict[str, Any]:
    return index.get(int(player.get("element") or -1), {}).get(int(gw), {"mean": 0.0, "std": 0.0})


def legal_squad(players: list[dict[str, Any]]) -> bool:
    expected = {k: int(v) for k, v in (SQUAD_RULES.get("position_counts") or {}).items()}
    if len(players) != int(SQUAD_RULES.get("squad_size") or 0):
        return False
    counts = {k: 0 for k in expected}
    clubs: dict[int, int] = {}
    seen = set()
    for player in players:
        element = int(player.get("element") or -1)
        if element in seen:
            return False
        seen.add(element)
        position = player.get("position")
        if position not in counts:
            return False
        counts[position] += 1
        team_id = int(player.get("team_id") or -1)
        clubs[team_id] = clubs.get(team_id, 0) + 1
    return counts == expected and max(clubs.values(), default=0) <= int(SQUAD_RULES.get("max_players_per_club") or 0)


def _best_lineup_indexed(players: list[dict[str, Any]], gw: int, index: dict[int, dict[int, dict[str, Any]]]) -> dict[str, Any]:
    by_position = {
        pos: sorted(
            [p for p in players if p.get("position") == pos],
            key=lambda p: _f(_indexed_row(index, p, gw).get("mean")),
            reverse=True,
        )
        for pos in ("GK", "DEF", "MID", "FWD")
    }
    gks = by_position["GK"]
    if not gks:
        return {"valid": False, "mean": 0.0, "variance": 0.0, "starters": []}
    best: dict[str, Any] | None = None
    for formation in LINEUP_RULES.get("legal_formations") or []:
        d, m, f = [int(x) for x in str(formation).split("-")]
        selected = [gks[0]]
        ok = True
        for pos, count in (("DEF", d), ("MID", m), ("FWD", f)):
            pool = by_position[pos]
            if len(pool) < count:
                ok = False
                break
            selected.extend(pool[:count])
        if not ok or len(selected) != int(LINEUP_RULES.get("starting_xi_size") or 11):
            continue
        mean = sum(_f(_indexed_row(index, p, gw).get("mean")) for p in selected)
        variance = sum(_f(_indexed_row(index, p, gw).get("std")) ** 2 for p in selected)
        candidate = {
            "valid": True,
            "formation": formation,
            "mean": mean,
            "variance": variance,
            "starters": [int(p["element"]) for p in selected],
        }
        if best is None or candidate["mean"] > best["mean"]:
            best = candidate
    return best or {"valid": False, "mean": 0.0, "variance": 0.0, "starters": []}


def best_lineup(players: list[dict[str, Any]], gw: int) -> dict[str, Any]:
    return _best_lineup_indexed(players, gw, _gw_index(players))


def score_package(players: list[dict[str, Any]], planning_gw: int, changes: int = 0) -> dict[str, Any]:
    cfg = load_config()
    horizons = [int(x) for x in cfg.get("horizons") or [3, 5, 10, 15]]
    bench_weight = _f(cfg.get("bench_utility_weight"), 0.10)
    captain_weight = _f(cfg.get("captain_bonus_weight"), 1.0)
    index = _gw_index(players)
    horizon_results: dict[str, dict[str, Any]] = {}
    max_horizon = max(horizons, default=0)
    horizon_set = set(horizons)
    total_mean = 0.0
    total_var = 0.0
    valid = True

    for offset in range(max_horizon):
        gw = planning_gw + offset
        lineup = _best_lineup_indexed(players, gw, index)
        if not lineup["valid"]:
            valid = False
        if valid:
            starter_ids = set(lineup["starters"])
            bench = [p for p in players if int(p["element"]) not in starter_ids]
            bench_mean = sum(_f(_indexed_row(index, p, gw).get("mean")) for p in bench)
            bench_var = sum(_f(_indexed_row(index, p, gw).get("std")) ** 2 for p in bench)
            starter_rows = [_indexed_row(index, p, gw) for p in players if int(p["element"]) in starter_ids]
            captain_mean = max((_f(row.get("mean")) for row in starter_rows), default=0.0)
            captain_std = max((_f(row.get("std")) for row in starter_rows), default=0.0)
            total_mean += lineup["mean"] + bench_weight * bench_mean + captain_weight * captain_mean
            total_var += lineup["variance"] + (bench_weight ** 2) * bench_var + (captain_weight ** 2) * captain_std ** 2

        elapsed = offset + 1
        if elapsed in horizon_set:
            horizon_results[str(elapsed)] = {
                "valid": valid,
                "mean": round(total_mean, 3) if valid else None,
                "std": round(math.sqrt(total_var), 3) if valid else None,
            }

    for horizon in horizons:
        horizon_results.setdefault(str(horizon), {"valid": False, "mean": None, "std": None})

    weights = {str(k): _f(v) for k, v in (cfg.get("horizon_weights") or {}).items()}
    available = [(h, horizon_results[str(h)]) for h in horizons if horizon_results[str(h)]["valid"]]
    weight_sum = sum(weights.get(str(h), 0.0) for h, _ in available)
    if not available or weight_sum <= 0:
        return {"valid": False, "horizons": horizon_results}
    objective_mean = sum(weights.get(str(h), 0.0) * row["mean"] for h, row in available) / weight_sum
    objective_var = sum((weights.get(str(h), 0.0) / weight_sum) ** 2 * row["std"] ** 2 for h, row in available)
    objective_std = math.sqrt(objective_var)
    robust = objective_mean - _f(cfg.get("risk_aversion"), 0.12) * objective_std - changes * _f(cfg.get("change_penalty_points"), 0.20)
    return {
        "valid": True,
        "horizons": horizon_results,
        "objective_mean": round(objective_mean, 3),
        "objective_std": round(objective_std, 3),
        "robust_score": round(robust, 3),
    }


def affordable_package(outs: list[dict[str, Any]], ins: list[dict[str, Any]], itb: int) -> tuple[bool, dict[str, int]]:
    cash_available = int(itb) + sum(int(p.get("sell_cost") or 0) for p in outs)
    incoming_cost = sum(int(p.get("now_cost") or 0) for p in ins)
    return incoming_cost <= cash_available, {
        "cash_available": cash_available,
        "incoming_cost": incoming_cost,
        "resulting_itb": cash_available - incoming_cost,
    }


def simulate_objective(mean: float, std: float, simulations: int, seed: int) -> dict[str, float]:
    rng = random.Random(seed)
    samples = sorted(rng.gauss(mean, max(0.0001, std)) for _ in range(max(20, simulations)))
    def pct(q: float) -> float:
        idx = min(len(samples) - 1, max(0, int(round((len(samples) - 1) * q))))
        return samples[idx]
    return {"p25": round(pct(0.25), 3), "p50": round(pct(0.50), 3), "p75": round(pct(0.75), 3)}
