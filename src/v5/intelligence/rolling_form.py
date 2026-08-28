from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _i(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _load(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"status": "UNAVAILABLE", "path": path, "rows": []}
    with p.open(encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise RuntimeError(f"invalid rolling-form artifact: {path}")
    return payload


def _artifact_is_valid(payload: dict[str, Any], expected_gw: int) -> bool:
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    artifact_gw = _i(payload.get("gw"))
    dataset = str(payload.get("dataset") or "")
    return bool(rows) and artifact_gw == expected_gw and dataset == "playermatchstats"


def build_rolling_form(
    *,
    planning_gw: int | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    cfg = config if isinstance(config, dict) else {}
    model = str(cfg.get("model") or "recency_weighted_playermatchstats_v1")
    if planning_gw is None:
        return {
            "status": "UNAVAILABLE_NO_PLANNING_GW",
            "model": model,
            "source": "FPL-Core-Insights/playermatchstats",
            "planning_gw": None,
            "expected_completed_gw": None,
            "authoritative_eligible": False,
            "players": {},
            "reason": "planning_gw is required for point-in-time rolling form",
        }

    planning = int(planning_gw)
    offset = int(cfg.get("expected_completed_gw_offset_from_planning_gw") or -1)
    expected = max(0, planning + offset)
    window = max(1, int(cfg.get("window_gameweeks") or 4))
    minimum_completed = max(1, int(cfg.get("minimum_completed_gameweeks") or 2))
    minimum_player_gws = max(1, int(cfg.get("minimum_player_gameweeks_with_minutes") or 2))
    minimum_minutes = max(0.0, _f(cfg.get("minimum_evidence_minutes"), 90.0))
    decay = _f(cfg.get("decay_per_gw"), 0.72)
    if not 0.0 < decay <= 1.0:
        raise RuntimeError("current_form.decay_per_gw must be in (0, 1]")

    template = str(cfg.get("artifact_path_template") or "data/stats/playermatchstats_gw{gw}.json")
    start = max(1, expected - window + 1)
    requested_gws = list(range(start, expected + 1)) if expected > 0 else []
    artifacts: dict[int, dict[str, Any]] = {}
    artifact_status: list[dict[str, Any]] = []
    for gw in requested_gws:
        path = template.format(gw=gw)
        payload = _load(path)
        valid = _artifact_is_valid(payload, gw)
        artifact_status.append(
            {
                "gw": gw,
                "path": path,
                "available": bool(payload.get("rows")),
                "valid": valid,
                "artifact_gw": _i(payload.get("gw")),
                "dataset": payload.get("dataset"),
                "fetched_at": payload.get("fetched_at"),
            }
        )
        if valid:
            artifacts[gw] = payload

    valid_gws = sorted(artifacts)
    latest_completed_available = expected in artifacts if expected > 0 else False
    global_eligible = latest_completed_available and len(valid_gws) >= minimum_completed

    accum: dict[str, dict[str, Any]] = {}
    fields = (
        "xg",
        "xa",
        "total_shots",
        "shots_on_target",
        "touches_opposition_box",
        "chances_created",
    )
    for gw in valid_gws:
        age = max(0, expected - gw)
        recency_weight = decay ** age
        seen_player_minutes: set[str] = set()
        for item in artifacts[gw].get("rows") or []:
            if not isinstance(item, dict):
                continue
            eid = _i(item.get("player_id"))
            if eid is None:
                continue
            key = str(eid)
            target = accum.setdefault(
                key,
                {
                    "weighted_minutes": 0.0,
                    "raw_minutes": 0.0,
                    "weighted": {field: 0.0 for field in fields},
                    "raw": {field: 0.0 for field in fields},
                    "gameweeks_with_minutes": set(),
                    "matches_with_minutes": 0,
                },
            )
            minutes = max(0.0, _f(item.get("minutes_played")))
            target["weighted_minutes"] += minutes * recency_weight
            target["raw_minutes"] += minutes
            if minutes > 0:
                target["matches_with_minutes"] += 1
                seen_player_minutes.add(key)
            for field in fields:
                value = max(0.0, _f(item.get(field)))
                target["weighted"][field] += value * recency_weight
                target["raw"][field] += value
        for key in seen_player_minutes:
            accum[key]["gameweeks_with_minutes"].add(gw)

    players: dict[str, Any] = {}
    authoritative_players = 0
    for key, row in accum.items():
        weighted_minutes = max(0.0, _f(row.get("weighted_minutes")))
        raw_minutes = max(0.0, _f(row.get("raw_minutes")))
        gws_with_minutes = sorted(int(gw) for gw in row.get("gameweeks_with_minutes") or [])
        player_eligible = (
            global_eligible
            and weighted_minutes >= minimum_minutes
            and len(gws_with_minutes) >= minimum_player_gws
        )
        authoritative_players += int(player_eligible)
        weighted = row.get("weighted") if isinstance(row.get("weighted"), dict) else {}
        xg90 = _f(weighted.get("xg")) * 90.0 / weighted_minutes if weighted_minutes > 0 else None
        xa90 = _f(weighted.get("xa")) * 90.0 / weighted_minutes if weighted_minutes > 0 else None
        players[key] = {
            "status": "AUTHORITATIVE_ELIGIBLE" if player_eligible else "AVAILABLE_NOT_AUTHORITATIVE",
            "authoritative_eligible": player_eligible,
            "gameweeks_with_minutes": gws_with_minutes,
            "matches_with_minutes": int(row.get("matches_with_minutes") or 0),
            "weighted_minutes": round(weighted_minutes, 3),
            "raw_minutes": round(raw_minutes, 1),
            "weighted_xg": round(_f(weighted.get("xg")), 6),
            "weighted_xa": round(_f(weighted.get("xa")), 6),
            "xg90": round(xg90, 6) if xg90 is not None else None,
            "xa90": round(xa90, 6) if xa90 is not None else None,
            "weighted_total_shots": round(_f(weighted.get("total_shots")), 4),
            "weighted_shots_on_target": round(_f(weighted.get("shots_on_target")), 4),
            "weighted_box_touches": round(_f(weighted.get("touches_opposition_box")), 4),
            "weighted_chances_created": round(_f(weighted.get("chances_created")), 4),
            "minimum_evidence_minutes": minimum_minutes,
            "minimum_player_gameweeks_with_minutes": minimum_player_gws,
        }

    if not requested_gws:
        status = "UNAVAILABLE_NO_COMPLETED_GW"
        reason = "no completed gameweek exists before planning point"
    elif not latest_completed_available:
        status = "DEGRADED_LATEST_GW_MISSING"
        reason = "latest completed gameweek artifact is missing or invalid"
    elif len(valid_gws) < minimum_completed:
        status = "DEVELOPING_WINDOW"
        reason = "rolling form requires more completed gameweeks before authoritative use"
    else:
        status = "ACTIVE"
        reason = None

    return {
        "status": status,
        "model": model,
        "source": "FPL-Core-Insights/playermatchstats",
        "planning_gw": planning,
        "expected_completed_gw": expected,
        "window_gameweeks": window,
        "requested_gws": requested_gws,
        "valid_gws": valid_gws,
        "latest_completed_gw_available": latest_completed_available,
        "minimum_completed_gameweeks": minimum_completed,
        "minimum_player_gameweeks_with_minutes": minimum_player_gws,
        "minimum_evidence_minutes": minimum_minutes,
        "decay_per_gw": decay,
        "authoritative_eligible": global_eligible,
        "authoritative_players": authoritative_players,
        "artifact_status": artifact_status,
        "players": players,
        "reason": reason,
        "governance": {
            "point_in_time_only": True,
            "future_gameweeks_never_loaded": True,
            "latest_completed_gameweek_required": True,
            "minimum_multi_gw_window_required": True,
            "zero_or_missing_minutes_do_not_create_rate_evidence": True,
            "rolling_form_supersedes_latest_gw_attack_overlay_when_authoritative": True,
        },
    }
