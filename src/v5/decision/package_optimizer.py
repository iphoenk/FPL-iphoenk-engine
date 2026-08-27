from __future__ import annotations

import hashlib
import math
import random
from statistics import NormalDist
from typing import Any, Mapping

from src.v5.config_cache import load_json_config
from src.v5.decision.lineup_optimizer import _cached_metrics, _formation_counts
from src.v5.decision.projection_index import index_player, index_players

CONFIG = "config/intelligence/package_optimizer.json"


def _cfg() -> dict[str, Any]:
    data = load_json_config(CONFIG)
    required = (
        "horizons",
        "horizon_weights",
        "candidate_ranking_horizon",
        "positions",
        "max_changes",
        "max_candidates_per_position",
        "max_single_moves_per_out",
        "double_move_seed_limit",
        "max_deterministic_packages",
        "monte_carlo_top_n",
        "monte_carlo_simulations",
        "monte_carlo_minimum_simulations",
        "monte_carlo_seed_policy",
        "bench_utility_weight",
        "captain_bonus_weight",
        "risk_aversion",
        "change_penalty_points",
    )
    missing = [key for key in required if key not in data]
    if missing:
        raise RuntimeError(f"package optimizer config missing required fields: {missing}")
    return data


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _required_int(mapping: Mapping[str, Any], key: str, context: str) -> int:
    value = mapping.get(key)
    if value is None:
        raise RuntimeError(f"package optimizer missing required {context}.{key}")
    return int(value)


def legal_squad(players: list[dict[str, Any]], squad_rules: dict[str, Any]) -> bool:
    expected = {str(k): int(v) for k, v in (squad_rules.get("position_counts") or {}).items()}
    if not expected:
        raise RuntimeError("Official squad position counts are required")
    squad_size = _required_int(squad_rules, "squad_size", "rules.squad")
    club_limit = _required_int(squad_rules, "max_players_per_club", "rules.squad")
    if len(players) != squad_size:
        return False
    counts = {key: 0 for key in expected}
    clubs: dict[int, int] = {}
    seen: set[int] = set()
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
    return counts == expected and max(clubs.values(), default=0) <= club_limit


def _build_scoring_context(
    universe: list[dict[str, Any]],
    planning_gw: int,
    rules: dict[str, Any],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Precompute immutable GW ranking/metric data once for package search.

    Player ranking keys are squad-independent. Ranking the universe once and
    filtering it to a candidate squad is therefore exactly equivalent to
    re-ranking the same squad for every package, while avoiding thousands of
    repeated score calculations and sorts.
    """
    lineup_rules = rules.get("lineup") if isinstance(rules.get("lineup"), dict) else {}
    positions = tuple(str(value) for value in cfg["positions"])
    horizons = sorted({int(value) for value in cfg["horizons"]})
    max_horizon = max(horizons)
    metrics_by_gw: dict[int, dict[int, dict[str, float]]] = {}
    rank_by_gw: dict[int, dict[str, dict[int, int]]] = {}
    position_by_id = {
        int(player["element"]): str(player.get("position"))
        for player in universe
        if isinstance(player, dict) and player.get("element") is not None
    }

    for offset in range(max_horizon):
        gw = int(planning_gw + offset)
        rows_by_position: dict[str, list[tuple[tuple[float, ...], int]]] = {position: [] for position in positions}
        metrics: dict[int, dict[str, float]] = {}
        for player in universe:
            if not isinstance(player, dict) or player.get("element") is None:
                continue
            element = int(player["element"])
            cached = _cached_metrics(player, gw, "player_score")
            metrics[element] = {
                "score": float(cached["score"]),
                "mean": float(cached["mean"]),
                "std": float(cached["std"]),
                "variance": float(cached["variance"]),
            }
            position = str(player.get("position"))
            if position in rows_by_position:
                rows_by_position[position].append(((float(cached["score"]), *cached["tie_values"]), element))
        ranks: dict[str, dict[int, int]] = {}
        for position, rows in rows_by_position.items():
            rows.sort(key=lambda item: item[0], reverse=True)
            ranks[position] = {element: rank for rank, (_key, element) in enumerate(rows)}
        metrics_by_gw[gw] = metrics
        rank_by_gw[gw] = ranks

    return {
        "planning_gw": int(planning_gw),
        "lineup_rules": lineup_rules,
        "metrics_by_gw": metrics_by_gw,
        "rank_by_gw": rank_by_gw,
        "position_by_id": position_by_id,
        "model": "precomputed_global_rank_filter_exact_v1",
    }


def _squad_ids_by_position(players: list[dict[str, Any]]) -> dict[str, list[int]]:
    grouped: dict[str, list[int]] = {}
    for player in players:
        if not isinstance(player, dict) or player.get("element") is None:
            continue
        grouped.setdefault(str(player.get("position")), []).append(int(player["element"]))
    return grouped


def _single_gw_score_from_context(
    squad_by_position: dict[str, list[int]],
    gw: int,
    lineup_rules: dict[str, Any],
    cfg: dict[str, Any],
    scoring_context: dict[str, Any],
) -> tuple[bool, float, float]:
    metrics = (scoring_context.get("metrics_by_gw") or {}).get(int(gw))
    ranks = (scoring_context.get("rank_by_gw") or {}).get(int(gw))
    if not isinstance(metrics, dict) or not isinstance(ranks, dict):
        return False, 0.0, 0.0

    starting_size = _required_int(lineup_rules, "starting_xi_size", "rules.lineup")
    formations = tuple(str(value) for value in lineup_rules.get("legal_formations") or ())
    if not formations:
        raise RuntimeError("Official rules contain no legal formations")

    selected: dict[str, Any] | None = None
    for formation in formations:
        counts = _formation_counts(formation, lineup_rules)
        starters: list[int] = []
        valid = True
        for position, count in counts.items():
            available = squad_by_position.get(position, [])
            rank_map = ranks.get(position) if isinstance(ranks.get(position), dict) else {}
            if len(available) < count or any(element not in rank_map for element in available):
                valid = False
                break
            ranked = sorted(available, key=rank_map.__getitem__)
            starters.extend(ranked[:count])
        if not valid or len(starters) != starting_size or any(element not in metrics for element in starters):
            continue
        starter_metrics = [metrics[element] for element in starters]
        candidate = {
            "formation": formation,
            "starters": starters,
            "selection_score": round(sum(item["score"] for item in starter_metrics), 4),
            "mean": round(sum(item["mean"] for item in starter_metrics), 4),
            "variance": round(sum(item["variance"] for item in starter_metrics), 4),
        }
        if selected is None or (candidate["selection_score"], candidate["mean"]) > (
            selected["selection_score"],
            selected["mean"],
        ):
            selected = candidate

    if selected is None:
        return False, 0.0, 0.0

    all_ids = [element for rows in squad_by_position.values() for element in rows]
    starter_ids = set(selected["starters"])
    if any(element not in metrics for element in all_ids):
        return False, 0.0, 0.0
    bench_ids = [element for element in all_ids if element not in starter_ids]
    bench_weight = _f(cfg["bench_utility_weight"])
    captain_weight = _f(cfg["captain_bonus_weight"])
    bench_mean = sum(metrics[element]["mean"] for element in bench_ids)
    bench_var = sum(metrics[element]["variance"] for element in bench_ids)
    captain = max(
        ((metrics[element]["mean"], metrics[element]["std"]) for element in selected["starters"]),
        default=(0.0, 0.0),
    )
    mean = float(selected["mean"]) + bench_weight * bench_mean + captain_weight * captain[0]
    variance = float(selected["variance"]) + bench_weight**2 * bench_var + captain_weight**2 * captain[1] ** 2
    return True, mean, variance


def score_package(
    players: list[dict[str, Any]],
    planning_gw: int,
    rules: dict[str, Any],
    changes: int = 0,
    *,
    scoring_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = _cfg()
    lineup_rules = rules.get("lineup") if isinstance(rules.get("lineup"), dict) else {}
    horizons = sorted({int(value) for value in cfg["horizons"]})
    if not horizons or horizons[0] <= 0:
        raise RuntimeError("package optimizer horizons must contain positive integers")
    indexed_players = index_players(players)
    context = scoring_context or _build_scoring_context(indexed_players, planning_gw, rules, cfg)
    squad_by_position = _squad_ids_by_position(indexed_players)
    max_horizon = max(horizons)
    cumulative_mean: list[float] = []
    cumulative_variance: list[float] = []
    total_mean = 0.0
    total_variance = 0.0
    valid_gws = 0
    for offset in range(max_horizon):
        valid, gw_mean, gw_variance = _single_gw_score_from_context(
            squad_by_position,
            planning_gw + offset,
            lineup_rules,
            cfg,
            context,
        )
        if not valid:
            break
        total_mean += gw_mean
        total_variance += gw_variance
        cumulative_mean.append(total_mean)
        cumulative_variance.append(total_variance)
        valid_gws += 1

    results: dict[str, dict[str, Any]] = {}
    for horizon in horizons:
        valid = valid_gws >= horizon
        results[str(horizon)] = {
            "valid": valid,
            "mean": round(cumulative_mean[horizon - 1], 3) if valid else None,
            "std": round(math.sqrt(cumulative_variance[horizon - 1]), 3) if valid else None,
        }

    weights = {str(k): _f(v) for k, v in cfg["horizon_weights"].items()}
    missing_weights = [str(horizon) for horizon in horizons if str(horizon) not in weights]
    if missing_weights:
        raise RuntimeError(f"package optimizer horizon weights missing: {missing_weights}")
    available = [(horizon, results[str(horizon)]) for horizon in horizons if results[str(horizon)]["valid"]]
    weight_sum = sum(weights[str(horizon)] for horizon, _ in available)
    if not available or weight_sum <= 0:
        return {"valid": False, "horizons": results, "performance": {"gw_lineups_evaluated": valid_gws}}
    mean = sum(weights[str(horizon)] * float(row["mean"]) for horizon, row in available) / weight_sum
    variance = sum((weights[str(horizon)] / weight_sum) ** 2 * float(row["std"]) ** 2 for horizon, row in available)
    std = math.sqrt(variance)
    robust = mean - _f(cfg["risk_aversion"]) * std - changes * _f(cfg["change_penalty_points"])
    return {
        "valid": True,
        "horizons": results,
        "objective_mean": round(mean, 3),
        "objective_std": round(std, 3),
        "robust_score": round(robust, 3),
        "performance": {
            "projection_lookup": "indexed_o1",
            "horizon_evaluation": "single_pass_prefix",
            "package_lineup_ranking": str(context.get("model") or "precomputed_global_rank_filter_exact_v1"),
            "gw_lineups_evaluated": valid_gws,
        },
    }


def affordable(outs: list[dict[str, Any]], ins: list[dict[str, Any]], itb: int) -> tuple[bool, dict[str, int]]:
    cash = int(itb) + sum(int(player.get("sell_cost") or 0) for player in outs)
    cost = sum(int(player.get("now_cost") or 0) for player in ins)
    return cost <= cash, {"cash_available": cash, "incoming_cost": cost, "resulting_itb": cash - cost}


def _stable_seed(cfg: dict[str, Any], *, ruleset_id: str, planning_gw: int, package_id: str) -> int:
    policy = cfg.get("monte_carlo_seed_policy")
    if not isinstance(policy, dict) or policy.get("strategy") != "stable_sha256":
        raise RuntimeError("unsupported package optimizer Monte Carlo seed policy")
    context = {
        "model_id": cfg.get("model_id"),
        "ruleset_id": ruleset_id,
        "planning_gw": planning_gw,
        "package_id": package_id,
    }
    components = tuple(str(value) for value in policy.get("components") or ())
    if not components or any(component not in context for component in components):
        raise RuntimeError("invalid package optimizer Monte Carlo seed components")
    namespace = str(policy.get("namespace") or "")
    if not namespace:
        raise RuntimeError("Monte Carlo seed namespace is required")
    raw = "|".join([namespace, *(str(context[name]) for name in components)]).encode("utf-8")
    return int(hashlib.sha256(raw).hexdigest()[:16], 16)


def _simulate(mean: float, std: float, simulations: int, minimum: int, seed: int) -> dict[str, float]:
    count = max(int(minimum), int(simulations))
    rng = random.Random(seed)
    samples = sorted(rng.gauss(mean, max(0.0001, std)) for _ in range(count))

    def percentile(q: float) -> float:
        return samples[min(len(samples) - 1, max(0, int(round((len(samples) - 1) * q))))]

    return {
        "p25": round(percentile(0.25), 3),
        "p50": round(percentile(0.50), 3),
        "p75": round(percentile(0.75), 3),
    }


def build_packages(prediction: dict[str, Any], team: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg()
    players = index_players([player for player in prediction.get("players") or [] if isinstance(player, dict)])
    pmap = {int(player["element"]): player for player in players if player.get("element") is not None}
    finance = team.get("finance") if isinstance(team.get("finance"), dict) else {}
    ledger = finance.get("players") if isinstance(finance.get("players"), list) else []
    current: list[dict[str, Any]] = []
    owned_ids: set[int] = set()
    for row in ledger:
        element = int(row.get("element") or -1)
        projected = pmap.get(element)
        if not projected:
            continue
        owned_ids.add(element)
        current.append(index_player({**projected, "sell_cost": row.get("sell_cost")}))
    squad_rules = rules.get("squad") if isinstance(rules.get("squad"), dict) else {}
    if not finance.get("sell_value_complete") or not legal_squad(current, squad_rules):
        return {
            "status": "BLOCKED",
            "reason": "finance incomplete or current squad illegal",
            "packages": [],
            "local_legality_prevalidated": False,
        }
    if prediction.get("planning_gw") is None:
        raise RuntimeError("prediction.planning_gw is required for package optimization")
    planning_gw = int(prediction["planning_gw"])
    if finance.get("bank") is None:
        return {
            "status": "BLOCKED",
            "reason": "bank unavailable for affordability",
            "packages": [],
            "local_legality_prevalidated": False,
        }
    itb = int(finance["bank"])
    allowed = {str(value) for value in cfg.get("allowed_statuses") or []}
    require_status = bool(cfg.get("require_available_status", True))
    positions = tuple(str(value) for value in cfg["positions"])
    candidate_horizon = str(int(cfg["candidate_ranking_horizon"]))
    max_candidates = int(cfg["max_candidates_per_position"])
    risk_aversion = _f(cfg["risk_aversion"])

    pools: dict[str, list[dict[str, Any]]] = {}
    for position in positions:
        rows = []
        for player in players:
            if player.get("position") != position or int(player["element"]) in owned_ids:
                continue
            if require_status and str(player.get("status")) not in allowed:
                continue
            candidate = index_player({**player, "sell_cost": player.get("now_cost")})
            horizon = (player.get("horizons") or {}).get(candidate_horizon) or {}
            candidate["candidate_score"] = _f(horizon.get("mean")) - risk_aversion * _f(horizon.get("std"))
            rows.append(candidate)
        rows.sort(key=lambda item: (item["candidate_score"], -int(item.get("now_cost") or 0)), reverse=True)
        pools[position] = rows[:max_candidates]

    scoring_context = _build_scoring_context(players, planning_gw, rules, cfg)
    hold_score = score_package(current, planning_gw, rules, changes=0, scoring_context=scoring_context)
    packages: list[dict[str, Any]] = [
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
    max_single_moves = int(cfg["max_single_moves_per_out"])
    for outgoing in current:
        for incoming in pools.get(str(outgoing["position"]), [])[:max_single_moves]:
            ok, money = affordable([outgoing], [incoming], itb)
            candidate = [player for player in current if int(player["element"]) != int(outgoing["element"])] + [incoming]
            if not ok or not legal_squad(candidate, squad_rules):
                continue
            score = score_package(candidate, planning_gw, rules, changes=1, scoring_context=scoring_context)
            singles.append((outgoing, incoming, candidate, money, score))
            packages.append(
                {
                    "id": f"1:{outgoing['element']}->{incoming['element']}",
                    "changes": 1,
                    "outs": [{"element": outgoing["element"], "name": outgoing.get("name"), "sell_cost": outgoing.get("sell_cost")}],
                    "ins": [{"element": incoming["element"], "name": incoming.get("name"), "now_cost": incoming.get("now_cost")}],
                    "affordability": money,
                    "score": score,
                    "legal": True,
                }
            )

    singles.sort(key=lambda item: _f(item[4].get("robust_score")), reverse=True)
    seeds = singles[: int(cfg["double_move_seed_limit"])]
    seen: set[tuple[int, ...]] = set()
    package_limit = int(cfg["max_deterministic_packages"])
    if int(cfg["max_changes"]) >= 2:
        for index, first in enumerate(seeds):
            for second in seeds[index + 1 :]:
                outs, ins = [first[0], second[0]], [first[1], second[1]]
                if outs[0]["element"] == outs[1]["element"] or ins[0]["element"] == ins[1]["element"]:
                    continue
                key = tuple(sorted([int(outs[0]["element"]), int(outs[1]["element"])])) + tuple(
                    sorted([int(ins[0]["element"]), int(ins[1]["element"])])
                )
                if key in seen:
                    continue
                seen.add(key)
                ok, money = affordable(outs, ins, itb)
                out_ids = {int(player["element"]) for player in outs}
                candidate = [player for player in current if int(player["element"]) not in out_ids] + ins
                if not ok or not legal_squad(candidate, squad_rules):
                    continue
                score = score_package(candidate, planning_gw, rules, changes=2, scoring_context=scoring_context)
                packages.append(
                    {
                        "id": f"2:{outs[0]['element']},{outs[1]['element']}->{ins[0]['element']},{ins[1]['element']}",
                        "changes": 2,
                        "outs": [
                            {"element": player["element"], "name": player.get("name"), "sell_cost": player.get("sell_cost")}
                            for player in outs
                        ],
                        "ins": [
                            {"element": player["element"], "name": player.get("name"), "now_cost": player.get("now_cost")}
                            for player in ins
                        ],
                        "affordability": money,
                        "score": score,
                        "legal": True,
                    }
                )
                if len(packages) >= package_limit:
                    break
            if len(packages) >= package_limit:
                break

    packages = [package for package in packages if (package.get("score") or {}).get("valid")]
    packages.sort(key=lambda package: _f((package.get("score") or {}).get("robust_score")), reverse=True)
    hold_mean = _f(hold_score.get("objective_mean"))
    hold_std = _f(hold_score.get("objective_std"))
    top_n = int(cfg["monte_carlo_top_n"])
    ruleset_id = str(rules.get("ruleset_id") or "")
    if not ruleset_id:
        raise RuntimeError("ruleset_id is required for deterministic package simulation")
    simulations = int(cfg["monte_carlo_simulations"])
    minimum_simulations = int(cfg["monte_carlo_minimum_simulations"])
    for package in packages[:top_n]:
        mean = _f(package["score"].get("objective_mean"))
        std = _f(package["score"].get("objective_std"))
        mc = _simulate(
            mean,
            std,
            simulations,
            minimum_simulations,
            _stable_seed(cfg, ruleset_id=ruleset_id, planning_gw=planning_gw, package_id=str(package["id"])),
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
        "ruleset_id": ruleset_id,
        "local_legality_prevalidated": True,
        "simulation_assumption": cfg.get("simulation_assumption"),
        "package_count": len(packages),
        "hold": next((package for package in packages if package["id"] == "HOLD"), None),
        "candidate_pool": {
            position: [
                {
                    "element": player["element"],
                    "name": player.get("name"),
                    "now_cost": player.get("now_cost"),
                    "candidate_score": round(_f(player.get("candidate_score")), 3),
                }
                for player in rows
            ]
            for position, rows in pools.items()
        },
        "packages": packages[:top_n],
        "governance": {
            "candidate_generation_only": True,
            "local_legality_prevalidated": True,
            "final_go_requires_framework_governance_and_postflight_gate0": True,
            "price_uses_sell_value_for_outs_and_now_cost_for_ins": True,
            "lineup_authority": "src.v5.decision.lineup_optimizer",
            "projection_lookup": "indexed_o1",
            "horizon_evaluation": "single_pass_prefix",
            "package_lineup_ranking": "precomputed_global_rank_filter_exact_v1",
            "monte_carlo_seed": "stable_sha256_policy",
        },
    }
