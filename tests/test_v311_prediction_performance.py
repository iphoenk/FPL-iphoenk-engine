import math

from src.models.package_optimizer_v2 import _f, _gw_row, best_lineup, load_config, score_package


def _players():
    positions = ["GK", "GK"] + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    rows = []
    for idx, position in enumerate(positions, start=1):
        rows.append({
            "element": idx,
            "position": position,
            "team_id": ((idx - 1) % 8) + 1,
            "now_cost": 45 + idx,
            "sell_cost": 45 + idx,
            "status": "a",
            "xpts_by_gw": [
                {"gw": gw, "mean": round(1.0 + idx * 0.11 + (gw - 2) * 0.07, 3), "std": round(0.8 + idx * 0.013, 3)}
                for gw in range(2, 17)
            ],
        })
    return rows


def _reference_score(players, planning_gw, changes=0):
    cfg = load_config()
    horizons = [int(x) for x in cfg.get("horizons") or [3, 5, 10, 15]]
    bench_weight = _f(cfg.get("bench_utility_weight"), 0.10)
    captain_weight = _f(cfg.get("captain_bonus_weight"), 1.0)
    horizon_results = {}
    for horizon in horizons:
        total_mean = 0.0
        total_var = 0.0
        valid = True
        for offset in range(horizon):
            gw = planning_gw + offset
            lineup = best_lineup(players, gw)
            if not lineup["valid"]:
                valid = False
                break
            starter_ids = set(lineup["starters"])
            bench = [p for p in players if int(p["element"]) not in starter_ids]
            bench_mean = sum(_f(_gw_row(p, gw).get("mean")) for p in bench)
            bench_var = sum(_f(_gw_row(p, gw).get("std")) ** 2 for p in bench)
            captain_mean = max((_f(_gw_row(p, gw).get("mean")) for p in players if int(p["element"]) in starter_ids), default=0.0)
            captain_std = max((_f(_gw_row(p, gw).get("std")) for p in players if int(p["element"]) in starter_ids), default=0.0)
            total_mean += lineup["mean"] + bench_weight * bench_mean + captain_weight * captain_mean
            total_var += lineup["variance"] + (bench_weight ** 2) * bench_var + (captain_weight ** 2) * captain_std ** 2
        horizon_results[str(horizon)] = {
            "valid": valid,
            "mean": round(total_mean, 3) if valid else None,
            "std": round(math.sqrt(total_var), 3) if valid else None,
        }
    weights = {str(k): _f(v) for k, v in (cfg.get("horizon_weights") or {}).items()}
    available = [(h, horizon_results[str(h)]) for h in horizons if horizon_results[str(h)]["valid"]]
    weight_sum = sum(weights.get(str(h), 0.0) for h, _ in available)
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


def test_optimized_package_score_is_exactly_reference_equivalent():
    players = _players()
    assert score_package(players, 2, changes=0) == _reference_score(players, 2, changes=0)
    assert score_package(players, 2, changes=2) == _reference_score(players, 2, changes=2)
