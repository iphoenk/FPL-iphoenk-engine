from __future__ import annotations

import json
from collections import Counter, defaultdict
from functools import lru_cache
from typing import Any

from src.utils import ROOT

CONFIG_PATH = ROOT / "config" / "intelligence" / "tactical_observed_context.json"


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if payload.get("contract") != "TACTICAL_OBSERVED_CONTEXT_V1":
        raise RuntimeError("unexpected observed tactical context contract")
    return payload


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value in {None, ""}:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _i(value: Any, default: int = -1) -> int:
    try:
        if value in {None, ""}:
            return int(default)
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _b(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _percentile(value: float, universe: list[float]) -> float:
    """Midrank percentile so tied zero values never become false 100th-percentile signals."""
    values = sorted(float(x) for x in universe)
    if not values:
        return 0.0
    less = sum(1 for x in values if x < value)
    equal = sum(1 for x in values if x == value)
    return round((less + 0.5 * equal) / len(values), 4)


def _sample_confidence(matches: int, cfg: dict[str, Any]) -> str:
    mapping = (cfg.get("classification") or {}).get("confidence_by_matches") or {}
    thresholds = sorted((int(k), str(v)) for k, v in mapping.items())
    label = "NONE"
    for minimum, candidate in thresholds:
        if matches >= minimum:
            label = candidate
    return label


def _shot_zone(row: dict[str, Any], cfg: dict[str, Any]) -> str | None:
    x = row.get("start_x")
    y = row.get("start_y")
    if x in {None, ""} or y in {None, ""}:
        return None
    x_f = _f(x)
    y_f = _f(y)
    zone_cfg = cfg.get("shot_zones") or {}
    close_max = _f(zone_cfg.get("close_distance_max"), 12.0)
    box_max = _f(zone_cfg.get("box_distance_max"), 18.0)
    central_min = _f(zone_cfg.get("central_y_min"), 35.0)
    central_max = _f(zone_cfg.get("central_y_max"), 65.0)
    lateral = "central" if central_min <= y_f <= central_max else ("left" if y_f < central_min else "right")
    if x_f <= close_max:
        return f"close_{lateral}"
    if x_f <= box_max:
        return f"box_{lateral}"
    return "long_range"


def _player_team_map(elements: list[dict[str, Any]]) -> dict[int, int]:
    out: dict[int, int] = {}
    for player in elements:
        element = _i(player.get("id"))
        team_id = _i(player.get("team"))
        if element > 0 and team_id > 0:
            out[element] = team_id
    return out


def _aggregate_match_rows(
    elements: list[dict[str, Any]],
    match_rows: list[dict[str, Any]],
    shot_rows: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> dict[tuple[str, int], dict[str, Any]]:
    player_team = _player_team_map(elements)
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    match_teams: dict[str, set[int]] = defaultdict(set)
    for row in match_rows:
        match_id = str(row.get("match_id") or "").strip()
        team_id = player_team.get(_i(row.get("player_id")))
        if not match_id or not team_id:
            continue
        grouped[(match_id, team_id)].append(row)
        match_teams[match_id].add(team_id)

    home_away: dict[str, dict[bool, int]] = defaultdict(dict)
    for row in shot_rows:
        match_id = str(row.get("match_id") or "").strip()
        team_id = player_team.get(_i(row.get("player_id")))
        if match_id and team_id:
            home_away[match_id][_b(row.get("is_home"))] = team_id
    for match_id, teams in match_teams.items():
        if len(teams) != 2:
            continue
        known = home_away.get(match_id) or {}
        if True in known and False not in known:
            other = next(iter(teams - {known[True]}), None)
            if other:
                home_away[match_id][False] = other
        if False in known and True not in known:
            other = next(iter(teams - {known[False]}), None)
            if other:
                home_away[match_id][True] = other

    shots_by_key: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in shot_rows:
        match_id = str(row.get("match_id") or "").strip()
        if not match_id:
            continue
        team_id = player_team.get(_i(row.get("player_id")))
        if not team_id:
            team_id = (home_away.get(match_id) or {}).get(_b(row.get("is_home")))
        if team_id:
            shots_by_key[(match_id, team_id)].append(row)

    metric_fields = {
        "xg": "xg",
        "xa": "xa",
        "shots": "total_shots",
        "shots_on_target": "shots_on_target",
        "box_touches": "touches_opposition_box",
        "chances_created": "chances_created",
        "final_third_passes": "final_third_passes",
        "accurate_crosses": "accurate_crosses",
        "corners": "corners",
        "successful_dribbles": "successful_dribbles",
        "recoveries": "recoveries",
        "tackles": "tackles",
        "interceptions": "interceptions",
        "clearances": "clearances",
        "dispossessed": "dispossessed",
        "accurate_long_balls": "accurate_long_balls",
        "accurate_passes": "accurate_passes",
        "touches": "touches",
    }
    out: dict[tuple[str, int], dict[str, Any]] = {}
    for key, rows in grouped.items():
        match_id, team_id = key
        metrics = {name: round(sum(_f(row.get(field)) for row in rows), 4) for name, field in metric_fields.items()}
        metrics["defensive_activity"] = round(metrics["recoveries"] + metrics["tackles"] + metrics["interceptions"], 4)
        shot_rows_team = shots_by_key.get(key) or []
        zones = Counter(filter(None, (_shot_zone(row, cfg) for row in shot_rows_team)))
        situations = Counter(str(row.get("situation") or "").strip().lower() for row in shot_rows_team if row.get("situation"))
        metrics["fast_break_shots"] = int(situations.get("fast-break", 0))
        metrics["set_piece_shots"] = int(sum(situations.get(name, 0) for name in ("corner", "free-kick", "penalty")))
        teams = match_teams.get(match_id) or set()
        opponent = next(iter(teams - {team_id}), None) if len(teams) == 2 else None
        home_flag = None
        if (home_away.get(match_id) or {}).get(True) == team_id:
            home_flag = True
        elif (home_away.get(match_id) or {}).get(False) == team_id:
            home_flag = False
        out[key] = {
            "match_id": match_id,
            "team_id": team_id,
            "opponent_team_id": opponent,
            "home": home_flag,
            "metrics": metrics,
            "shot_zones": dict(zones),
            "shot_team_attribution_count": len(shot_rows_team),
        }
    return out


def _signal_rows(match_agg: dict[tuple[str, int], dict[str, Any]], cfg: dict[str, Any]) -> dict[tuple[str, int], dict[str, Any]]:
    metric_map = {
        "box_pressure": "box_touches",
        "shot_volume": "shots",
        "chance_creation": "chances_created",
        "final_third_progression": "final_third_passes",
        "wide_delivery": "accurate_crosses",
        "set_piece_activity": "set_piece_shots",
        "transition_threat": "fast_break_shots",
        "defensive_activity_proxy": "defensive_activity",
    }
    universes = {
        metric: [float(row["metrics"].get(metric, 0.0)) for row in match_agg.values()]
        for metric in set(metric_map.values())
    }
    high = _f((cfg.get("classification") or {}).get("high_percentile"), 0.75)
    maximum = int((cfg.get("classification") or {}).get("maximum_team_signals") or 3)
    out: dict[tuple[str, int], dict[str, Any]] = {}
    for key, row in match_agg.items():
        percentiles = {
            signal: _percentile(float(row["metrics"].get(metric, 0.0)), universes.get(metric) or [])
            for signal, metric in metric_map.items()
        }
        ranked = sorted(percentiles.items(), key=lambda item: item[1], reverse=True)
        strengths = [
            signal for signal, pct in ranked
            if pct >= high
            and signal != "defensive_activity_proxy"
            and _f(row["metrics"].get(metric_map[signal])) > 0
        ][:maximum]
        style_proxies = [
            {"signal": signal, "percentile": pct, "observed_value": row["metrics"].get(metric_map[signal], 0.0)}
            for signal, pct in ranked
            if _f(row["metrics"].get(metric_map[signal])) > 0
        ][:maximum]
        out[key] = {**row, "percentiles": percentiles, "strengths": strengths, "observed_style_proxies": style_proxies}

    for key, row in out.items():
        opponent_id = row.get("opponent_team_id")
        opponent_key = (row["match_id"], int(opponent_id)) if opponent_id else None
        opponent = out.get(opponent_key) if opponent_key else None
        vulnerabilities: list[str] = []
        concession_percentiles: dict[str, float] = {}
        if opponent:
            for signal, metric in metric_map.items():
                if signal == "defensive_activity_proxy":
                    continue
                value = float(opponent["metrics"].get(metric, 0.0))
                pct = _percentile(value, universes.get(metric) or [])
                concession_percentiles[signal] = pct
            vulnerabilities = [
                signal for signal, pct in sorted(concession_percentiles.items(), key=lambda item: item[1], reverse=True)
                if pct >= high and _f(opponent["metrics"].get(metric_map[signal])) > 0
            ][:maximum]
        row["vulnerabilities"] = vulnerabilities
        row["concession_percentiles"] = concession_percentiles
    return out


def _top_zones(zones: dict[str, Any], maximum: int) -> list[str]:
    ranked = sorted(((str(zone), _f(count)) for zone, count in zones.items()), key=lambda item: item[1], reverse=True)
    return [zone for zone, count in ranked[:maximum] if count > 0]


def build_current_recent_rows(
    elements: list[dict[str, Any]],
    match_payload: dict[str, Any],
    shots_payload: dict[str, Any],
    team_system_context: dict[str, Any],
    cfg: dict[str, Any] | None = None,
) -> dict[int, list[dict[str, Any]]]:
    cfg = cfg or load_config()
    match_rows = [row for row in (match_payload.get("rows") or []) if isinstance(row, dict)]
    shot_rows = [row for row in (shots_payload.get("rows") or []) if isinstance(row, dict)]
    gw = _i(match_payload.get("gw"), 0)
    if gw <= 0 or not match_rows:
        return {}
    aggregates = _signal_rows(_aggregate_match_rows(elements, match_rows, shot_rows, cfg), cfg)
    max_zones = int((cfg.get("classification") or {}).get("maximum_zone_signals") or 2)
    shape_by_match_team: dict[tuple[str, int], str | None] = {}
    for team_key, system in (team_system_context or {}).items():
        team_id = _i(team_key)
        for row in system.get("matches") or []:
            match_id = str(row.get("match_id") or "").strip()
            if match_id:
                shape_by_match_team[(match_id, team_id)] = row.get("fpl_position_shape") if row.get("valid") else None

    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for key, row in aggregates.items():
        match_id, team_id = key
        opponent_id = row.get("opponent_team_id")
        opponent = aggregates.get((match_id, int(opponent_id))) if opponent_id else None
        creation_zones = _top_zones(row.get("shot_zones") or {}, max_zones)
        concession_zones = _top_zones((opponent or {}).get("shot_zones") or {}, max_zones)
        strengths = list(row.get("strengths") or [])
        vulnerabilities = list(row.get("vulnerabilities") or [])
        notes: list[str] = []
        if strengths:
            notes.append("observed strengths: " + ", ".join(strengths[:2]))
        if vulnerabilities:
            notes.append("observed concessions: " + ", ".join(vulnerabilities[:2]))
        out[team_id].append({
            "gw": gw,
            "match_id": match_id,
            "opponent_team_id": opponent_id,
            "home": row.get("home"),
            "formation": shape_by_match_team.get((match_id, team_id)),
            "possession_pattern": None,
            "pressing_pattern": None,
            "chance_creation_zones": creation_zones,
            "chance_concession_zones": concession_zones,
            "role_changes": [],
            "notes": "; ".join(notes) if notes else None,
            "strengths": strengths,
            "vulnerabilities": vulnerabilities,
            "observed_style_proxies": row.get("observed_style_proxies") or [],
            "observed_metrics": row.get("metrics") or {},
            "concession_percentiles": row.get("concession_percentiles") or {},
            "confidence": "LOW",
            "evidence": {
                "class": "OBSERVED_MATCH_EVENT_AGGREGATE",
                "source": match_payload.get("source") or "FPL-Core-Insights",
                "dataset": match_payload.get("dataset"),
                "fetched_at": match_payload.get("fetched_at"),
                "shots_dataset": shots_payload.get("dataset") if shot_rows else None,
                "shots_fetched_at": shots_payload.get("fetched_at") if shot_rows else None,
                "true_pressing_not_inferred": True,
                "true_possession_not_inferred": True,
            },
        })
    return dict(out)


def merge_recent_history(
    previous: dict[str, Any] | None,
    current: dict[int, list[dict[str, Any]]],
    team_ids: list[int],
    cfg: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    cfg = cfg or load_config()
    window = int(cfg.get("recent_gw_window") or 5)
    previous_teams = ((previous or {}).get("teams") or {}) if isinstance(previous, dict) else {}
    out: dict[str, list[dict[str, Any]]] = {}
    for team_id in team_ids:
        rows = []
        for row in previous_teams.get(str(team_id), []) or []:
            if isinstance(row, dict):
                rows.append(dict(row))
        rows.extend(dict(row) for row in current.get(team_id, []) if isinstance(row, dict))
        dedup: dict[tuple[int, str, int], dict[str, Any]] = {}
        for row in rows:
            key = (_i(row.get("gw"), 0), str(row.get("match_id") or ""), _i(row.get("opponent_team_id"), -1))
            dedup[key] = row
        ordered = sorted(dedup.values(), key=lambda row: (_i(row.get("gw"), 0), str(row.get("match_id") or "")), reverse=True)
        out[str(team_id)] = ordered[:window]
    return out


def summarize_team_history(rows: list[dict[str, Any]], cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    valid = [row for row in rows if isinstance(row, dict)]
    strengths = Counter(signal for row in valid for signal in (row.get("strengths") or []))
    vulnerabilities = Counter(signal for row in valid for signal in (row.get("vulnerabilities") or []))
    shapes = Counter(str(row.get("formation")) for row in valid if row.get("formation"))
    style = Counter(
        str(item.get("signal"))
        for row in valid
        for item in (row.get("observed_style_proxies") or [])
        if isinstance(item, dict) and item.get("signal")
    )
    maximum = int((cfg.get("classification") or {}).get("maximum_team_signals") or 3)
    return {
        "matches": len(valid),
        "confidence": _sample_confidence(len(valid), cfg),
        "dominant_shape": shapes.most_common(1)[0][0] if shapes else None,
        "formation_variants": [shape for shape, _ in shapes.most_common()],
        "strengths": [signal for signal, _ in strengths.most_common(maximum)],
        "vulnerabilities": [signal for signal, _ in vulnerabilities.most_common(maximum)],
        "observed_style_proxies": [signal for signal, _ in style.most_common(maximum)],
    }


def player_return_routes(player_feature: dict[str, Any]) -> dict[str, Any]:
    advanced = player_feature.get("advanced_current") or {}
    totals = advanced.get("totals") or {}
    routes: list[str] = []
    zones: list[str] = []
    if _f(totals.get("touches_opposition_box")) > 0:
        routes.append("box_pressure")
        zones.append("box_involvement")
    if _f(totals.get("total_shots")) > 0 or _f(totals.get("xg")) > 0:
        routes.append("shot_volume")
    if _f(totals.get("chances_created")) > 0 or _f(totals.get("xa")) > 0:
        routes.append("chance_creation")
        zones.append("chance_creation")
    if _f(totals.get("corners")) > 0:
        routes.append("set_piece_activity")
    penalty_events = _f(totals.get("penalties_scored")) + _f(totals.get("penalties_missed"))
    if penalty_events > 0:
        routes.append("penalty_route")
    routes = list(dict.fromkeys(routes))
    priority = ["box_pressure", "shot_volume", "chance_creation", "set_piece_activity", "penalty_route"]
    progression = next((route for route in priority if route in routes), None)
    return {
        "zones": list(dict.fromkeys(zones)),
        "set_pieces": "CORNERS_OBSERVED" if "set_piece_activity" in routes else None,
        "penalties": "PENALTY_EVENT_OBSERVED" if "penalty_route" in routes else None,
        "progression_route": progression,
        "return_routes": routes,
    }
