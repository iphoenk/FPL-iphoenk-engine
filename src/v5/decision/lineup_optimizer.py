from __future__ import annotations

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
        ranked.append(
            (
                (score, *_tie_values(row, projection, start_probability, tie_breakers)),
                row,
            )
        )
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
    for player in players:
        row = index_player(player)
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
            by_position[position].append(
                (
                    (score, *_tie_values(row, projection, start_probability, tie_breakers)),
                    row,
                )
            )

    ranked_by_position: dict[str, list[dict[str, Any]]] = {}
    for position, rows in by_position.items():
        rows.sort(key=lambda item: item[0], reverse=True)
        ranked_by_position[position] = [item[1] for item in rows]
    return {"ranked_by_position": ranked_by_position, "metrics": metrics}


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


def best_lineup(players: list[dict[str, Any]], gw: int, lineup_rules: dict[str, Any]) -> dict[str, Any]:
    """Single lineup authority used by package scoring and final lineup governance."""
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

    selected = _select_formation(players, planning_gw, lineup_rules)
    if selected is None:
        return {"status": "BLOCKED", "reason": "no legal formation", "planning_gw": planning_gw}

    starters = selected["starters"]
    starter_ids = {int(player["element"]) for player in starters}
    captain_rank = _rank(starters, planning_gw, "captain_score")
    if not captain_rank:
        return {"status": "BLOCKED", "reason": "captain pool empty", "planning_gw": planning_gw}
    vice_rank = _rank(
        (player for player in starters if int(player["element"]) != int(captain_rank[0]["element"])),
        planning_gw,
        "vice_score",
    )
    if not vice_rank:
        return {"status": "BLOCKED", "reason": "vice-captain pool empty", "planning_gw": planning_gw}
    captain, vice = captain_rank[0], vice_rank[0]

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

    return {
        "status": "READY",
        "planning_gw": planning_gw,
        "formation": selected["formation"],
        "starters": [view(player, profile="player_score") for player in starters],
        "bench": [view(player, profile="bench_score") for player in bench],
        "captain": view(captain, profile="captain_score"),
        "vice_captain": view(vice, profile="vice_score"),
        "expected_starting_xi_mean": round(selected["mean"], 3),
        "selection_score": round(selected["selection_score"], 3),
        "authority": "v5_decision_lineup_optimizer",
        "performance": {
            "projection_lookup": "indexed_o1",
            "formation_ranking": "single_rank_per_position_per_gw",
        },
    }
