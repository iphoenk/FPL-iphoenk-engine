from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/intelligence/role_intelligence.json"
POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def _cfg() -> dict[str, Any]:
    data = load_json_config(CONFIG)
    if not isinstance(data.get("position_slots"), dict):
        raise RuntimeError("invalid V5 role intelligence registry")
    return data


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _order_share(order: Any, weights: dict[str, Any], tail: float) -> float:
    try:
        rank = int(order or 0)
    except (TypeError, ValueError):
        rank = 0
    if rank <= 0:
        return 0.0
    return _clamp(_f(weights.get(str(rank)), tail))


def _set_piece_role(player: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    set_piece_cfg = cfg.get("set_pieces") or {}
    weights = set_piece_cfg.get("order_weights") or {}
    tail = _f(set_piece_cfg.get("tail_weight"), 0.08)
    corners = _order_share(player.get("corners_and_indirect_freekicks_order"), weights, tail)
    direct = _order_share(player.get("direct_freekicks_order"), weights, tail)
    share = _clamp(
        _f(set_piece_cfg.get("corners_weight"), 0.65) * corners
        + _f(set_piece_cfg.get("direct_freekicks_weight"), 0.35) * direct
    )

    penalty_cfg = cfg.get("penalties") or {}
    penalty_share = _order_share(
        player.get("penalties_order"),
        penalty_cfg.get("order_weights") or {},
        _f(penalty_cfg.get("tail_weight"), 0.02),
    )
    return {
        "set_piece_share": round(share, 4),
        "penalty_share": round(penalty_share, 4),
        "corners_order": int(player.get("corners_and_indirect_freekicks_order") or 0) or None,
        "direct_freekicks_order": int(player.get("direct_freekicks_order") or 0) or None,
        "penalties_order": int(player.get("penalties_order") or 0) or None,
        "source": "official_fpl_bootstrap_orders",
    }


def build_role_intelligence(bootstrap: dict[str, Any], team_matches: dict[int, int] | None = None) -> dict[str, Any]:
    """Build role evidence in O(players), with grouped peer aggregates rather than repeated universe scans."""
    cfg = _cfg()
    team_matches = team_matches or {}
    groups: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for player in bootstrap.get("elements") or []:
        position = POSITIONS.get(int(player.get("element_type") or 4), "FWD")
        groups[(int(player.get("team") or -1), position)].append(player)

    group_stats: dict[tuple[int, str], dict[str, Any]] = {}
    shrink = max(0.0, _f(cfg.get("start_rate_shrinkage_matches"), 4.0))
    credible_threshold = _clamp(_f(cfg.get("credible_peer_start_rate"), 0.35))
    neutral_by_position = cfg.get("neutral_role_start_probability") or {}
    for key, rows in groups.items():
        team_id, position = key
        matches = max(0, int(team_matches.get(team_id, 0)))
        neutral = _clamp(_f(neutral_by_position.get(position), 0.65), 0.01, 0.99)
        rates = {}
        for row in rows:
            starts = max(0.0, _f(row.get("starts")))
            observed = _clamp(starts / max(1, matches)) if matches else neutral
            rates[int(row["id"])] = (
                (observed * matches + neutral * shrink) / max(1e-6, matches + shrink)
                if matches
                else neutral
            )
        credible = sum(rate >= credible_threshold for rate in rates.values())
        total_rate = sum(rates.values())
        group_stats[key] = {"rates": rates, "credible": credible, "total_rate": total_rate}

    competition_cfg = cfg.get("competition") or {}
    slots_cfg = cfg.get("position_slots") or {}
    out = {}
    for key, rows in groups.items():
        team_id, position = key
        stats = group_stats[key]
        slots = max(1.0, _f(slots_cfg.get(position), 1.0))
        excess = max(0.0, _f(stats["credible"]) - slots)
        excess_pressure = _clamp(
            excess / slots * _f(competition_cfg.get("excess_peer_pressure_scale"), 0.35)
        )
        total_rate = max(1e-6, _f(stats["total_rate"]))
        for player in rows:
            element = int(player["id"])
            role_start = _clamp(_f(stats["rates"].get(element), 0.5), 0.01, 0.99)
            share = role_start / total_rate
            expected_share = min(1.0, slots / max(1.0, len(rows)))
            share_pressure = _clamp(
                max(0.0, expected_share - share)
                * _f(competition_cfg.get("share_pressure_scale"), 0.25)
            )
            rotation_risk = _clamp(
                excess_pressure + share_pressure,
                0.0,
                _f(competition_cfg.get("maximum_rotation_risk"), 0.45),
            )
            role = _set_piece_role(player, cfg)
            out[element] = {
                "model": str(cfg.get("model_id")),
                "role_start_probability": round(role_start, 4),
                "competition_pressure": round(_clamp(excess_pressure + share_pressure), 4),
                "rotation_risk": round(rotation_risk, 4),
                "credible_same_position_players": int(stats["credible"]),
                "position_slots_prior": round(slots, 2),
                **role,
            }
    return {
        "model": str(cfg.get("model_id")),
        "players": out,
        "capabilities": [str(x) for x in cfg.get("capabilities") or []],
        "non_claims": [str(x) for x in cfg.get("non_claims") or []],
        "projection_adjustment": cfg.get("projection_adjustment") or {},
    }
