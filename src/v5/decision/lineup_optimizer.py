from __future__ import annotations

import itertools
from collections import Counter
from typing import Any, Iterable, Mapping

from src.v5.config_cache import load_json_config
from src.v5.decision.projection_index import gw_projection, index_player

CONFIG = "config/v5_decision_registry.json"


def _cfg() -> dict[str, Any]:
    data = load_json_config(CONFIG)
    if not isinstance(data.get("lineup"), dict):
        raise RuntimeError("invalid V5 decision registry lineup section")
    return data


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _required_int(mapping: Mapping[str, Any], key: str, context: str) -> int:
    value = mapping.get(key)
    if value is None:
        raise RuntimeError(f"lineup optimizer missing required {context}.{key}")
    return int(value)


def _minutes_probabilities(player: dict[str, Any]) -> tuple[float, float]:
    xmins = player.get("xmins") if isinstance(player.get("xmins"), dict) else {}
    return _f(xmins.get("start_probability")), _f(xmins.get("dnp_probability"))


def _score_from_metrics(
    policy: Mapping[str, Any],
    projection: Mapping[str, float],
    start_probability: float,
    dnp_probability: float,
) -> float:
    return (
        _f(policy.get("mean_weight")) * float(projection["mean"])
        + _f(policy.get("ceiling_std_weight")) * float(projection["std"])
        - _f(policy.get("risk_std_penalty")) * float(projection["std"])
        + _f(policy.get("start_probability_weight")) * start_probability
        - _f(policy.get("dnp_probability_penalty")) * dnp_probability
    )


def player_score(player: dict[str, Any], gw: int, profile: str = "player_score") -> float:
    policy = _cfg()["lineup"].get(profile)
    if not isinstance(policy, dict):
        raise KeyError(f"unknown V5 lineup score profile: {profile}")
    projection = gw_projection(player, gw)
    start_probability, dnp_probability = _minutes_probabilities(player)
    return _score_from_metrics(policy, projection, start_probability, dnp_probability)


def _tie_values(
    player: dict[str, Any],
    projection: Mapping[str, float],
    start_probability: float,
    tie_breakers: tuple[str, ...],
) -> tuple[float, ...]:
    values = []
    for name in tie_breakers:
        if name == "mean":
            values.append(float(projection["mean"]))
        elif name == "start_probability":
            values.append(start_probability)
        elif name == "lower_cost":
            values.append(-float(int(player.get("now_cost") or 0)))
        elif name == "element_id":
            values.append(-float(int(player.get("element") or 0)))
        else:
            raise RuntimeError(f"unsupported V5 lineup tie breaker: {name}")
    return tuple(values)


def _rank(players: Iterable[dict[str, Any]], gw: int, profile: str) -> list[dict[str, Any]]:
    lineup_cfg = _cfg()["lineup"]
    policy = lineup_cfg.get(profile)
    if not isinstance(policy, dict):
        raise KeyError(f"unknown V5 lineup score profile: {profile}")
    tie_breakers = tuple(str(value) for value in lineup_cfg.get("tie_breakers") or ())
    if not tie_breakers:
        raise RuntimeError("V5 lineup tie_breakers registry is empty")
    ranked = []
    for player in players:
        row = index_player(player)
        projection = gw_projection(row, gw)
        start_probability, dnp_probability = _minutes_probabilities(row)
        score = _score_from_metrics(policy, projection, start_probability, dnp_probability)
        ranked.append(((score, *_tie_values(row, projection, start_probability, tie_breakers)), row))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in ranked]


def _formation_counts(formation: str, lineup_rules: Mapping[str, Any]) -> dict[str, int]:
    defender, midfielder, forward = (int(value) for value in str(formation).split("-"))
    goalkeeper = _required_int(lineup_rules, "starting_goalkeepers", "rules.lineup")
    return {"GK": goalkeeper, "DEF": defender, "MID": midfielder, "FWD": forward}


def _selection_context(players: list[dict[str, Any]], gw: int) -> dict[str, Any]:
    lineup_cfg = _cfg()["lineup"]
    positions = tuple(str(value) for value in lineup_cfg.get("positions") or ())
    if not positions:
        raise RuntimeError("V5 lineup positions registry is empty")
    policy = lineup_cfg.get("player_score")
    if not isinstance(policy, dict):
        raise RuntimeError("V5 lineup player_score policy missing")
    tie_breakers = tuple(str(value) for value in lineup_cfg.get("tie_breakers") or ())
    if not tie_breakers:
        raise RuntimeError("V5 lineup tie_breakers registry is empty")

    by_position: dict[str, list[tuple[tuple[float, ...], dict[str, Any]]]] = {position: [] for position in positions}
    metrics: dict[int, dict[str, float]] = {}
    indexed: list[dict[str, Any]] = []
    for player in players:
        row = index_player(player)
        indexed.append(row)
        element = int(row.get("element") or -1)
        projection = gw_projection(row, gw)
        start_probability, dnp_probability = _minutes_probabilities(row)
        score = _score_from_metrics(policy, projection, start_probability, dnp_probability)
        metrics[element] = {
            "score": score,
            "mean": float(projection["mean"]),
            "variance": float(projection["std"]) ** 2,
        }
        position = str(row.get("position"))
        if position in by_position:
            by_position[position].append(((score, *_tie_values(row, projection, start_probability, tie_breakers)), row))

    ranked_by_position: dict[str, list[dict[str, Any]]] = {}
    for position, rows in by_position.items():
        rows.sort(key=lambda item: item[0], reverse=True)
        ranked_by_position[position] = [item[1] for item in rows]
    return {"ranked_by_position": ranked_by_position, "metrics": metrics, "players": indexed}


def _select_formation(players: list[dict[str, Any]], gw: int, lineup_rules: dict[str, Any]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    starting_size = _required_int(lineup_rules, "starting_xi_size", "rules.lineup")
    formations = tuple(str(value) for value in lineup_rules.get("legal_formations") or ())
    if not formations:
        raise RuntimeError("Official rules contain no legal formations")
    context = _selection_context(players, gw)
    ranked_by_position = context["ranked_by_position"]
    metrics = context["metrics"]

    for formation in formations:
        counts = _formation_counts(formation, lineup_rules)
        starters: list[dict[str, Any]] = []
        valid = True
        for position, count in counts.items():
            ranked = ranked_by_position.get(position, [])
            if len(ranked) < count:
                valid = False
                break
            starters.extend(ranked[:count])
        if not valid or len(starters) != starting_size:
            continue
        starter_metrics = [metrics[int(player["element"])] for player in starters]
        score = sum(item["score"] for item in starter_metrics)
        mean = sum(item["mean"] for item in starter_metrics)
        variance = sum(item["variance"] for item in starter_metrics)
        candidate = {
            "formation": formation,
            "starters": starters,
            "selection_score": round(score, 4),
            "mean": round(mean, 4),
            "variance": round(variance, 4),
        }
        if best is None or (candidate["selection_score"], candidate["mean"]) > (best["selection_score"], best["mean"]):
            best = candidate
    return best



def _defensive_route_proxy(player: dict[str, Any], gw: int) -> float:
    for row in player.get("xpts_by_gw") or []:
        if not isinstance(row, dict) or int(row.get("gw") or -1) != int(gw):
            continue
        total = 0.0
        for fixture in row.get("fixtures") or []:
            components = fixture.get("components") if isinstance(fixture.get("components"), dict) else {}
            total += _f(components.get("clean_sheet"))
            total += _f(components.get("saves"))
            total += _f(components.get("defensive_contribution"))
        return max(0.0, total)
    return 0.0


def _lineup_risk_adjustment(
    starters: list[dict[str, Any]],
    bench_rows: list[dict[str, Any]],
    gw: int,
    lineup_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    cfg = lineup_cfg.get("lineup_risk") if isinstance(lineup_cfg.get("lineup_risk"), dict) else {}
    if not bool(cfg.get("enabled", False)):
        return {"adjustment": 0.0, "enabled": False}

    defensive = [row for row in starters if row.get("position") in {"GK", "DEF"}]
    team_counts = Counter(int(row.get("team_id") or -1) for row in defensive if int(row.get("team_id") or -1) > 0)
    clustered_extras = sum(max(0, count - 1) for count in team_counts.values())
    cluster_penalty = clustered_extras * _f(cfg.get("same_team_defensive_cluster_penalty"), 0.08)

    defensive_route_points = sum(_defensive_route_proxy(row, gw) for row in starters)
    total_points = sum(max(0.0, _cached_metrics(row, gw, "player_score", lineup_cfg)["mean"]) for row in starters)
    route_share = defensive_route_points / total_points if total_points > 1e-9 else 0.0
    concentration_penalty = max(0.0, route_share - 0.50) * _f(cfg.get("defensive_route_concentration_penalty"), 0.06)

    usable_bench = [row for row in bench_rows if row.get("position") != "GK"]
    bench_scores = [max(0.0, _cached_metrics(row, gw, "bench_score", lineup_cfg)["score"]) for row in usable_bench[:3]]
    bench_utility = sum(bench_scores) / max(1, len(bench_scores))
    bench_bonus = min(0.12, _f(cfg.get("bench_utility_weight"), 0.03) * bench_utility / 5.0)

    raw_adjustment = -cluster_penalty - concentration_penalty + bench_bonus
    limit = max(0.0, _f(cfg.get("maximum_close_call_adjustment"), 0.30))
    adjustment = max(-limit, min(limit, raw_adjustment))
    return {
        "enabled": True,
        "adjustment": round(adjustment, 4),
        "defensive_cluster_penalty": round(cluster_penalty, 4),
        "defensive_route_concentration_penalty": round(concentration_penalty, 4),
        "bench_utility_bonus": round(bench_bonus, 4),
        "same_team_defensive_cluster_extras": clustered_extras,
        "defensive_route_share": round(route_share, 4),
        "bench_utility_proxy": round(bench_utility, 4),
        "governance": {
            "bounded_decision_adjustment_only": True,
            "raw_xpts_unchanged": True,
            "no_artificial_attacking_formation_bonus": True,
        },
    }

def _enumerate_final_candidates(players: list[dict[str, Any]], gw: int, lineup_rules: dict[str, Any]) -> list[dict[str, Any]]:
    context = _selection_context(players, gw)
    indexed = context["players"]
    metrics = context["metrics"]
    lineup_cfg = _cfg()["lineup"]
    starting_size = _required_int(lineup_rules, "starting_xi_size", "rules.lineup")
    required_gk = _required_int(lineup_rules, "starting_goalkeepers", "rules.lineup")
    legal_formations = {str(value) for value in lineup_rules.get("legal_formations") or ()}
    candidates: list[dict[str, Any]] = []
    all_ids = {int(player["element"]) for player in indexed}
    for combo in itertools.combinations(indexed, starting_size):
        rows = list(combo)
        if sum(1 for player in rows if player.get("position") == "GK") != required_gk:
            continue
        counts = {
            position: sum(1 for player in rows if player.get("position") == position)
            for position in ("DEF", "MID", "FWD")
        }
        formation = f"{counts['DEF']}-{counts['MID']}-{counts['FWD']}"
        if formation not in legal_formations:
            continue
        starter_metrics = [metrics[int(player["element"])] for player in rows]
        base_score = sum(item["score"] for item in starter_metrics)
        starter_ids = {int(player["element"]) for player in rows}
        bench_rows = [player for player in indexed if int(player["element"]) in all_ids - starter_ids]
        risk = _lineup_risk_adjustment(rows, bench_rows, gw, lineup_cfg)
        decision_score = base_score + _f(risk.get("adjustment"))
        candidates.append(
            {
                "formation": formation,
                "starters": rows,
                "selection_score": round(decision_score, 4),
                "base_score": round(base_score, 4),
                "risk_adjustment": risk,
                "mean": round(sum(item["mean"] for item in starter_metrics), 4),
                "variance": round(sum(item["variance"] for item in starter_metrics), 4),
            }
        )

    base_sorted = sorted(candidates, key=lambda row: (row["base_score"], row["mean"], row["formation"]), reverse=True)
    risk_cfg = lineup_cfg.get("lineup_risk") if isinstance(lineup_cfg.get("lineup_risk"), dict) else {}
    if not bool(risk_cfg.get("enabled", False)) or not base_sorted:
        return base_sorted
    anchor = _f(base_sorted[0].get("base_score"))
    gap = max(0.0, _f(risk_cfg.get("close_call_rerank_gap"), 0.75))
    close = [row for row in base_sorted if anchor - _f(row.get("base_score")) <= gap + 1e-9]
    distant = [row for row in base_sorted if row not in close]
    close.sort(key=lambda row: (row["selection_score"], row["base_score"], row["mean"]), reverse=True)
    return close + distant


def best_lineup(players: list[dict[str, Any]], gw: int, lineup_rules: dict[str, Any]) -> dict[str, Any]:
    """Fast lineup authority for package scoring; final owned XI uses full enumeration once."""
    selected = _select_formation(players, gw, lineup_rules)
    if selected is None:
        return {"valid": False, "mean": 0.0, "variance": 0.0, "starters": []}
    return {
        "valid": True,
        "formation": selected["formation"],
        "mean": selected["mean"],
        "variance": selected["variance"],
        "starters": [int(player["element"]) for player in selected["starters"]],
    }


def _merged_owned_players(team: dict[str, Any], prediction: dict[str, Any]) -> list[dict[str, Any]]:
    pmap = {
        int(player["element"]): index_player(player)
        for player in prediction.get("players") or []
        if player.get("element") is not None
    }
    merged = []
    for squad_row in team.get("squad") or []:
        try:
            element = int(squad_row["element"])
        except (KeyError, TypeError, ValueError):
            continue
        projected = pmap.get(element)
        if not projected:
            continue
        merged.append(index_player({**projected, "squad_position": squad_row.get("position")}))
    return merged


def _safe_captain_pool(starters: list[dict[str, Any]], gw: int) -> list[dict[str, Any]]:
    safety = _cfg()["lineup"].get("captain_safety")
    if not isinstance(safety, dict):
        raise RuntimeError("V5 lineup captain_safety policy missing")
    minimum_start = _f(safety.get("minimum_start_probability"))
    maximum_dnp = _f(safety.get("maximum_dnp_probability"))
    minimum_pool = int(safety.get("minimum_pool_size") or 2)
    safe_pool_size = max(minimum_pool, int(safety.get("safe_pool_size") or minimum_pool))
    ranked = _rank(starters, gw, "captain_score")
    safe = []
    for player in ranked:
        start_probability, dnp_probability = _minutes_probabilities(player)
        if start_probability >= minimum_start and dnp_probability <= maximum_dnp:
            safe.append(player)
    if len(safe) < minimum_pool and bool(safety.get("fallback_to_all_starters", True)):
        safe = ranked
    return safe[:safe_pool_size]


def _battle(best: dict[str, Any], second: dict[str, Any] | None, gw: int) -> dict[str, Any]:
    if second is None:
        return {"status": "NO_ALTERNATIVE", "margin": None, "starter_side": [], "bench_side": []}
    threshold = _f(((_cfg()["lineup"].get("alternatives") or {}).get("close_margin_threshold")))
    best_ids = {int(player["element"]) for player in best["starters"]}
    second_ids = {int(player["element"]) for player in second["starters"]}
    pmap = {int(player["element"]): player for player in [*best["starters"], *second["starters"]]}
    margin = round(float(best["selection_score"]) - float(second["selection_score"]), 4)

    def compact(element: int) -> dict[str, Any]:
        player = pmap[element]
        return {
            "element": element,
            "name": player.get("name"),
            "position": player.get("position"),
            "selection_score": round(player_score(player, gw, "player_score"), 4),
        }

    return {
        "status": "CLOSE" if margin < threshold else "CLEAR",
        "margin": margin,
        "starter_side": [compact(element) for element in sorted(best_ids - second_ids)],
        "bench_side": [compact(element) for element in sorted(second_ids - best_ids)],
        "alternative_formation": second.get("formation"),
    }


def optimize_lineup(team: dict[str, Any], prediction: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    players = _merged_owned_players(team, prediction)
    lineup_rules = rules.get("lineup") if isinstance(rules.get("lineup"), dict) else {}
    squad_rules = rules.get("squad") if isinstance(rules.get("squad"), dict) else {}
    if prediction.get("planning_gw") is None:
        raise RuntimeError("prediction.planning_gw is required for lineup optimization")
    planning_gw = int(prediction["planning_gw"])
    expected_size = _required_int(squad_rules, "squad_size", "rules.squad")
    if len(players) != expected_size:
        return {
            "status": "BLOCKED",
            "reason": "owned prediction coverage incomplete",
            "planning_gw": planning_gw,
            "predicted_owned": len(players),
            "expected_owned": expected_size,
        }

    alternatives_cfg = _cfg()["lineup"].get("alternatives") or {}
    enumerate_all = bool(alternatives_cfg.get("enumerate_all_legal_xi_for_final_squad", True))
    candidates = _enumerate_final_candidates(players, planning_gw, lineup_rules) if enumerate_all else []
    selected = candidates[0] if candidates else _select_formation(players, planning_gw, lineup_rules)
    if selected is None:
        return {"status": "BLOCKED", "reason": "no legal formation", "planning_gw": planning_gw}

    starters = selected["starters"]
    starter_ids = {int(player["element"]) for player in starters}
    safe_pool = _safe_captain_pool(starters, planning_gw)
    if len(safe_pool) < 2:
        return {"status": "BLOCKED", "reason": "captain safe pool has fewer than two players", "planning_gw": planning_gw}
    captain = safe_pool[0]
    safe_ids = {int(player["element"]) for player in safe_pool}
    vice_rank = _rank(
        (
            player
            for player in starters
            if int(player["element"]) != int(captain["element"]) and int(player["element"]) in safe_ids
        ),
        planning_gw,
        "vice_score",
    )
    if not vice_rank:
        return {"status": "BLOCKED", "reason": "vice-captain safe pool empty", "planning_gw": planning_gw}
    vice = vice_rank[0]

    bench_players = [player for player in players if int(player["element"]) not in starter_ids]
    reserve_gks = _rank((player for player in bench_players if player.get("position") == "GK"), planning_gw, "bench_score")
    reserve_outfield = _rank((player for player in bench_players if player.get("position") != "GK"), planning_gw, "bench_score")
    bench = reserve_outfield + reserve_gks

    def view(player: dict[str, Any], *, profile: str) -> dict[str, Any]:
        projection = gw_projection(player, planning_gw)
        start_probability, dnp_probability = _minutes_probabilities(player)
        return {
            "element": int(player["element"]),
            "name": player.get("name"),
            "position": player.get("position"),
            "team_id": player.get("team_id"),
            "mean": round(projection["mean"], 3),
            "std": round(projection["std"], 3),
            "start_probability": round(start_probability, 4),
            "dnp_probability": round(dnp_probability, 4),
            "score": round(player_score(player, planning_gw, profile), 4),
        }

    publish_top_n = max(1, int(alternatives_cfg.get("publish_top_n") or 1))
    published_candidates = (candidates or [selected])[:publish_top_n]
    published_alternatives = [
        {
            "rank": index + 1,
            "formation": candidate["formation"],
            "selection_score": candidate["selection_score"],
            "mean": candidate["mean"],
            "std": round(float(candidate["variance"]) ** 0.5, 3),
            "element_ids": sorted(int(player["element"]) for player in candidate["starters"]),
        }
        for index, candidate in enumerate(published_candidates)
    ]

    return {
        "status": "READY",
        "planning_gw": planning_gw,
        "formation": selected["formation"],
        "starters": [view(player, profile="player_score") for player in starters],
        "bench": [view(player, profile="bench_score") for player in bench],
        "captain": view(captain, profile="captain_score"),
        "vice_captain": view(vice, profile="vice_score"),
        "captain_safe_pool": [view(player, profile="captain_score") for player in safe_pool],
        "main_starting_xi_battle": _battle(selected, candidates[1] if len(candidates) > 1 else None, planning_gw),
        "alternatives": published_alternatives,
        "expected_starting_xi_mean": round(selected["mean"], 3),
        "selection_score": round(selected["selection_score"], 3),
        "authority": "v5_decision_lineup_optimizer",
        "performance": {
            "projection_lookup": "indexed_o1",
            "package_scoring_formation_ranking": "single_rank_per_position_per_gw",
            "final_lineup_enumeration": "all_legal_xi_once" if enumerate_all else "formation_rank_only",
            "legal_xi_candidates": len(candidates),
        },
    }
