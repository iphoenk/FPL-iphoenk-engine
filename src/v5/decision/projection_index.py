from __future__ import annotations

from typing import Any, Iterable

INDEX_KEY = "_v5_xpts_by_gw_index"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def index_player(player: dict[str, Any]) -> dict[str, Any]:
    """Attach an in-process O(1) GW projection index without changing network contracts."""
    existing = player.get(INDEX_KEY)
    if isinstance(existing, dict):
        return player
    index: dict[int, dict[str, float]] = {}
    for row in player.get("xpts_by_gw") or []:
        if not isinstance(row, dict) or row.get("gw") is None:
            continue
        try:
            gw = int(row["gw"])
        except (TypeError, ValueError):
            continue
        index[gw] = {"mean": _f(row.get("mean")), "std": _f(row.get("std"))}
    player[INDEX_KEY] = index
    return player


def index_players(players: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [index_player(player) for player in players]


def gw_projection(player: dict[str, Any], gw: int) -> dict[str, float]:
    index_player(player)
    index = player.get(INDEX_KEY)
    if not isinstance(index, dict):
        return {"mean": 0.0, "std": 0.0}
    return index.get(int(gw), {"mean": 0.0, "std": 0.0})


def strip_internal_index(player: dict[str, Any]) -> dict[str, Any]:
    if INDEX_KEY not in player:
        return player
    return {key: value for key, value in player.items() if key != INDEX_KEY}
