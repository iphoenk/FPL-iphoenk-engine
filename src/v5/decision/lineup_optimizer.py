from __future__ import annotations

from typing import Any, Iterable

from src.v5.config_cache import load_json_config

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


def gw_projection(player: dict[str, Any], gw: int) -> dict[str, float]:
    for row in player.get("xpts_by_gw") or []:
        try:
            if int(row.get("gw")) == int(gw):
                return {"mean": _f(row.get("mean")), "std": _f(row.get("std"))}
        except (TypeError, ValueError):
            continue
    return {"mean": 0.0, "std": 0.0}


def _minutes_probabilities(player: dict[str, Any]) -> tuple[float, float]:
    xmins = player.get("xmins") if isinstance(player.get("xmins"), dict) else {}
    return _f(xmins.get("start_probability")), _f(xmins.get("dnp_probability"))


def player_score(player: dict[str, Any], gw: int, profile: str = "player_score") -> float:
    policy = (_cfg()["lineup"].get(profile) or {})
    projection = gw_projection(player, gw)
    start_probability, dnp_probability = _minutes_probabilities(player)
    return (
        _f(policy.get("mean_weight"), 1.0) * projection["mean"]
        + _f(policy.get("ceiling_std_weight")) * projection["std"]
        - _f(policy.get("risk_std_penalty")) * projection["std"]
        + _f(policy.get("start_probability_weight")) * start_probability
        - _f(policy.get("dnp_probability_penalty")) * dnp_probability
    )


def _rank(players: Iterable[dict[str, Any]], gw: int, profile: str) -> list[dict[str, Any]]:
    return sorted(
        players,
        key=lambda player: (
            player_score(player, gw, profile),
            gw_projection(player, gw)["mean"],
            _minutes_probabilities(player)[0],
            -int(player.get("now_cost") or 0),
            -int(player.get("element") or 0),
        ),
        reverse=True,
    )


def _formation_counts(formation: str) -> dict[str, int]:
    defender, midfielder, forward = (int(value) for value in str(formation).split("-"))
    return {"GK": 1, "DEF": defender, "MID": midfielder, "FWD": forward}


def _select_formation(players: list[dict[str, Any]], gw: int, lineup_rules: dict[str, Any]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for formation in lineup_rules.get("legal_formations") or []:
        counts = _formation_counts(str(formation))
        starters: list[dict[str, Any]] = []
        valid = True
        for position, count in counts.items():
            ranked = _rank((p for p in players if p.get("position") == position), gw, "player_score")
            if len(ranked) < count:
                valid = False
                break
            starters.extend(ranked[:count])
        if not valid or len(starters) != int(lineup_rules.get("starting_xi_size") or 11):
            continue
        score = sum(player_score(player, gw, "player_score") for player in starters)
        mean = sum(gw_projection(player, gw)["mean"] for player in starters)
        variance = sum(gw_projection(player, gw)["std"] ** 2 for player in starters)
        candidate = {
            "formation": str(formation),
            "starters": starters,
            "selection_score": round(score, 4),
            "mean": round(mean, 4),
            "variance": round(variance, 4),
        }
        if best is None or (candidate["selection_score"], candidate["mean"]) > (best["selection_score"], best["mean"]):
            best = candidate
    return best


def best_lineup(players: list[dict[str, Any]], gw: int, lineup_rules: dict[str, Any]) -> dict[str, Any]:
    """Single lineup authority used by both package scoring and final lineup governance."""
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
    pmap = {int(player["element"]): player for player in prediction.get("players") or [] if player.get("element") is not None}
    merged = []
    for squad_row in team.get("squad") or []:
        try:
            element = int(squad_row["element"])
        except (KeyError, TypeError, ValueError):
            continue
        projected = pmap.get(element)
        if not projected:
            continue
        merged.append({**projected, "squad_position": squad_row.get("position")})
    return merged


def optimize_lineup(team: dict[str, Any], prediction: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    players = _merged_owned_players(team, prediction)
    lineup_rules = rules.get("lineup") if isinstance(rules.get("lineup"), dict) else {}
    planning_gw = int(prediction.get("planning_gw") or 1)
    expected_size = int((rules.get("squad") or {}).get("squad_size") or 15)
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
    vice_rank = _rank((player for player in starters if int(player["element"]) != int(captain_rank[0]["element"])), planning_gw, "vice_score")
    captain = captain_rank[0]
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
    }
