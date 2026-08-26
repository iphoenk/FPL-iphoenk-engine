from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/intelligence/evidence_enrichment.json"
CAPABILITIES = [
    "advanced_stats_sync",
    "european_congestion",
    "domestic_cup_congestion",
    "international_load",
    "rest_days",
    "preseason_prior",
    "current_form",
]


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


@lru_cache(maxsize=8)
def _load_artifact(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"status": "UNAVAILABLE", "path": path, "rows": []}
    with p.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise RuntimeError(f"invalid enrichment artifact: {path}")
    return data


def _advanced_stats() -> dict[str, Any]:
    cfg = load_json_config(CONFIG)["advanced_stats"]
    shots = _load_artifact(str(cfg["shots_path"]))
    match = _load_artifact(str(cfg["player_match_stats_path"]))
    shot_rows = shots.get("rows") if isinstance(shots.get("rows"), list) else []
    match_rows = match.get("rows") if isinstance(match.get("rows"), list) else []
    players: dict[int, dict[str, float]] = {}

    def row(eid: int) -> dict[str, float]:
        return players.setdefault(eid, {"shots": 0.0, "shot_xg": 0.0, "shots_on_target": 0.0, "box_touches": 0.0, "chances_created": 0.0, "xg": 0.0, "xa": 0.0, "minutes": 0.0})

    for item in shot_rows:
        if not isinstance(item, dict):
            continue
        eid = _i(item.get("player_id"))
        if eid is None:
            continue
        target = row(eid)
        target["shots"] += 1.0
        target["shot_xg"] += _f(item.get("xg"))
    for item in match_rows:
        if not isinstance(item, dict):
            continue
        eid = _i(item.get("player_id"))
        if eid is None:
            continue
        target = row(eid)
        target["minutes"] += _f(item.get("minutes_played"))
        target["shots_on_target"] += _f(item.get("shots_on_target"))
        target["box_touches"] += _f(item.get("touches_opposition_box"))
        target["chances_created"] += _f(item.get("chances_created"))
        target["xg"] += _f(item.get("xg"))
        target["xa"] += _f(item.get("xa"))
        if target["shots"] <= 0:
            target["shots"] += _f(item.get("total_shots"))
    return {
        "status": "ACTIVE" if shot_rows and match_rows else "DEGRADED",
        "source": cfg.get("source"),
        "shots_rows": len(shot_rows),
        "match_rows": len(match_rows),
        "coverage_players": len(players),
        "players": {str(k): {name: round(value, 4) for name, value in values.items()} for k, values in players.items()},
        "missing_player_behavior": cfg.get("missing_player_behavior"),
    }


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _league_rest_days(fixtures: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    by_team: dict[int, list[datetime]] = {}
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            continue
        kickoff = _parse_dt(fixture.get("kickoff_time"))
        if kickoff is None:
            continue
        for key in ("team_h", "team_a"):
            if fixture.get(key) is not None:
                by_team.setdefault(int(fixture[key]), []).append(kickoff)
    result: dict[int, dict[str, Any]] = {}
    for team_id, dates in by_team.items():
        ordered = sorted(dates)
        gaps = [round((ordered[i] - ordered[i - 1]).total_seconds() / 86400.0, 2) for i in range(1, len(ordered))]
        result[team_id] = {
            "minimum_pl_rest_days": min(gaps) if gaps else None,
            "next_pl_rest_gaps": gaps[:6],
            "source": "official_fpl_fixtures",
        }
    return result


def _schedule_context(bootstrap: dict[str, Any], fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)["schedule"]
    teams = {int(t["id"]): str(t.get("name") or t.get("short_name") or "") for t in bootstrap.get("teams") or [] if t.get("id") is not None}
    normalized = {name.lower().replace(" ", ""): tid for tid, name in teams.items()}
    european: dict[str, Any] = {}
    club_cfg = ((cfg.get("european_calendar") or {}).get("club_competitions") or {})
    for competition, spec in club_cfg.items():
        ids = []
        for club in spec.get("english_clubs") or []:
            key = str(club).lower().replace(" ", "")
            if key in normalized:
                ids.append(normalized[key])
        european[competition] = {
            "team_ids": sorted(set(ids)),
            "match_windows": spec.get("match_windows") or [],
            "participation_state": spec.get("participation_state", "confirmed"),
        }
    return {
        "status": "ACTIVE",
        "league_rest_days": {str(k): v for k, v in _league_rest_days(fixtures).items()},
        "european": european,
        "domestic_cup": cfg.get("domestic_cup") or {},
        "international": cfg.get("international") or {},
        "governance": {
            "missing_specific_match_or_callup_is_unavailable_not_zero": True,
            "calendar_windows_are_risk_context_not_claimed_minutes": True,
        },
    }


def _preseason() -> dict[str, Any]:
    cfg = load_json_config(CONFIG)["preseason"]
    artifact = _load_artifact(str(cfg["artifact_path"]))
    rows = artifact.get("rows") if isinstance(artifact.get("rows"), list) else []
    return {
        "status": "ACTIVE",
        "evidence_status": "AVAILABLE" if rows else "UNAVAILABLE",
        "row_count": len(rows),
        "source_policy": cfg.get("source_policy") or [],
        "fallback": "historical_role_prior" if not rows else None,
        "never_fabricate_minutes_or_roles": bool(cfg.get("never_fabricate_minutes_or_roles", True)),
    }


def _current_form(bootstrap: dict[str, Any], advanced: dict[str, Any]) -> dict[str, Any]:
    advanced_players = advanced.get("players") if isinstance(advanced.get("players"), dict) else {}
    rows: dict[str, Any] = {}
    for p in bootstrap.get("elements") or []:
        if not isinstance(p, dict) or p.get("id") is None:
            continue
        eid = int(p["id"])
        adv = advanced_players.get(str(eid)) or {}
        minutes = max(0.0, _f(p.get("minutes")))
        rows[str(eid)] = {
            "official_form": _f(p.get("form")),
            "points_per_game": _f(p.get("points_per_game")),
            "total_points": _f(p.get("total_points")),
            "starts": int(p.get("starts") or 0),
            "minutes": int(minutes),
            "expected_goals": _f(p.get("expected_goals")),
            "expected_assists": _f(p.get("expected_assists")),
            "threat": _f(p.get("threat")),
            "creativity": _f(p.get("creativity")),
            "net_transfers_event": int(p.get("transfers_in_event") or 0) - int(p.get("transfers_out_event") or 0),
            "advanced": adv or None,
        }
    return {"status": "ACTIVE", "source": "official_fpl+advanced_stats", "players": rows}


def build_full_core_enrichment(bootstrap: dict[str, Any], fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    advanced = _advanced_stats()
    schedule = _schedule_context(bootstrap, fixtures)
    preseason = _preseason()
    current_form = _current_form(bootstrap, advanced)
    capabilities = list(CAPABILITIES)
    return {
        "schema_version": 1,
        "model": load_json_config(CONFIG).get("model_id"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ACTIVE",
        "capabilities": capabilities,
        "advanced_stats": advanced,
        "schedule": schedule,
        "preseason": preseason,
        "current_form": current_form,
        "governance": {
            "module_active_does_not_mean_every_player_has_evidence": True,
            "missing_external_evidence_is_unavailable_not_zero": True,
            "no_claimed_minutes_without_source": True,
        },
    }
