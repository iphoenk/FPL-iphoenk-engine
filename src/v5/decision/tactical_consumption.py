from __future__ import annotations

from typing import Any, Callable

from src.v5.config_cache import load_json_config

CONFIG = "config/v5_tactical_decision_consumption.json"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def tactical_key(player: dict[str, Any]) -> tuple[int, int, int]:
    cfg = load_json_config(CONFIG)
    matchup = player.get("tactical_matchup") if isinstance(player.get("tactical_matchup"), dict) else {}
    if str(matchup.get("status") or "") != "READY":
        return (0, 0, 0)
    routes = {str(x) for x in matchup.get("player_return_routes") or [] if x}
    vulnerabilities = {str(x) for x in matchup.get("opponent_vulnerabilities") or [] if x}
    overlap = routes & vulnerabilities
    highlights = [x for x in matchup.get("highlights") or [] if x]
    rank = cfg.get("confidence_rank") or {}
    confidence = str(matchup.get("evidence_confidence") or "NONE").upper()
    if not overlap and not highlights:
        return (0, 0, 0)
    return (len(overlap), len(highlights), int(rank.get(confidence, 0)))


def close_group_sort(
    rows: list[Any],
    *,
    score: Callable[[Any], float],
    player: Callable[[Any], dict[str, Any]],
    gap: float,
) -> list[Any]:
    """Sort only within score-close groups using tactical evidence.

    Base model score always defines group boundaries and remains unchanged.
    """
    if len(rows) < 2:
        return list(rows)
    base = sorted(rows, key=score, reverse=True)
    out: list[Any] = []
    index = 0
    while index < len(base):
        anchor = score(base[index])
        group = [base[index]]
        index += 1
        while index < len(base) and anchor - score(base[index]) <= gap + 1e-9:
            group.append(base[index])
            index += 1
        if any(tactical_key(player(item)) != (0, 0, 0) for item in group):
            group.sort(key=lambda item: (tactical_key(player(item)), score(item)), reverse=True)
        out.extend(group)
    return out


def compact_tactical(player: dict[str, Any]) -> dict[str, Any]:
    matchup = player.get("tactical_matchup") if isinstance(player.get("tactical_matchup"), dict) else {}
    return {
        "status": matchup.get("status") or "UNAVAILABLE",
        "opponent_team_id": matchup.get("opponent_team_id"),
        "player_role": matchup.get("player_role"),
        "player_return_routes": list(matchup.get("player_return_routes") or [])[:4],
        "opponent_vulnerabilities": list(matchup.get("opponent_vulnerabilities") or [])[:3],
        "opponent_strengths": list(matchup.get("opponent_strengths") or [])[:3],
        "route_vulnerability_overlap": sorted(set(matchup.get("player_return_routes") or []) & set(matchup.get("opponent_vulnerabilities") or []))[:3],
        "highlights": list(matchup.get("highlights") or [])[:2],
        "tactical_key": list(tactical_key(player)),
        "advisory_only": True,
    }
