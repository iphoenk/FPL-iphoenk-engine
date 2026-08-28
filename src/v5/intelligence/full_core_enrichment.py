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
    "player_defensive_contribution_evidence",
    "european_congestion",
    "domestic_cup_congestion",
    "international_load",
    "rest_days",
    "preseason_prior",
    "current_form",
    "source_fusion",
    "advanced_stats_point_in_time_freshness",
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


def _norm(value: Any) -> str:
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


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


def _dc_sample_quality(minutes: float) -> str:
    if minutes <= 0:
        return "NO_ADVANCED_EVIDENCE"
    if minutes < 270:
        return "LIMITED"
    if minutes < 450:
        return "DEVELOPING"
    return "ESTABLISHED"


def _advanced_freshness(
    cfg: dict[str, Any],
    shots: dict[str, Any],
    match: dict[str, Any],
    planning_gw: int | None,
) -> dict[str, Any]:
    policy = cfg.get("authoritative_freshness") if isinstance(cfg.get("authoritative_freshness"), dict) else {}
    shots_gw = _i(shots.get("gw"))
    match_gw = _i(match.get("gw"))
    require_match = bool(policy.get("require_shots_and_match_gw_match", True))
    maximum_lag = max(0, int(policy.get("maximum_gw_lag") or 0))
    offset = int(policy.get("expected_completed_gw_offset_from_planning_gw") or -1)
    base = {
        "planning_gw": int(planning_gw) if planning_gw is not None else None,
        "shots_gw": shots_gw,
        "match_stats_gw": match_gw,
        "shots_fetched_at": shots.get("fetched_at"),
        "match_stats_fetched_at": match.get("fetched_at"),
        "maximum_gw_lag": maximum_lag,
        "future_gw_forbidden": bool(policy.get("future_gw_forbidden", True)),
        "require_shots_and_match_gw_match": require_match,
    }
    if planning_gw is None:
        return {
            **base,
            "status": "UNKNOWN_NO_PLANNING_GW",
            "authoritative_eligible": False,
            "expected_completed_gw": None,
            "artifact_gw": match_gw if match_gw is not None else shots_gw,
            "gw_lag": None,
            "reason": "planning_gw is required for point-in-time authority",
        }
    expected = max(0, int(planning_gw) + offset)
    if shots_gw is None or match_gw is None:
        return {
            **base,
            "status": "MISSING_ARTIFACT_GW",
            "authoritative_eligible": False,
            "expected_completed_gw": expected,
            "artifact_gw": match_gw if match_gw is not None else shots_gw,
            "gw_lag": None,
            "reason": "advanced artifact gameweek metadata is required for authoritative use",
        }
    if require_match and shots_gw != match_gw:
        return {
            **base,
            "status": "ARTIFACT_GW_MISMATCH",
            "authoritative_eligible": False,
            "expected_completed_gw": expected,
            "artifact_gw": None,
            "gw_lag": None,
            "reason": "shots and player-match-stat artifacts refer to different gameweeks",
        }
    artifact_gw = match_gw
    if bool(policy.get("future_gw_forbidden", True)) and artifact_gw > expected:
        return {
            **base,
            "status": "FUTURE_DATA_BLOCKED",
            "authoritative_eligible": False,
            "expected_completed_gw": expected,
            "artifact_gw": artifact_gw,
            "gw_lag": expected - artifact_gw,
            "reason": "advanced artifact is newer than the last completed gameweek for this planning point",
        }
    lag = expected - artifact_gw
    if lag > maximum_lag:
        return {
            **base,
            "status": "STALE_GW",
            "authoritative_eligible": False,
            "expected_completed_gw": expected,
            "artifact_gw": artifact_gw,
            "gw_lag": lag,
            "reason": "advanced artifact is older than the configured authoritative gameweek lag",
        }
    return {
        **base,
        "status": "CURRENT_COMPLETED_GW",
        "authoritative_eligible": True,
        "expected_completed_gw": expected,
        "artifact_gw": artifact_gw,
        "gw_lag": lag,
        "reason": None,
    }


def _advanced_stats(
    bootstrap: dict[str, Any],
    source_fusion: dict[str, Any],
    planning_gw: int | None = None,
) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)["advanced_stats"]
    shots = _load_artifact(str(cfg["shots_path"]))
    match = _load_artifact(str(cfg["player_match_stats_path"]))
    freshness = _advanced_freshness(cfg, shots, match, planning_gw)
    shot_rows = shots.get("rows") if isinstance(shots.get("rows"), list) else []
    match_rows = match.get("rows") if isinstance(match.get("rows"), list) else []
    players: dict[int, dict[str, float]] = {}
    element_types = {
        int(p["id"]): int(p.get("element_type") or 4)
        for p in bootstrap.get("elements") or []
        if isinstance(p, dict) and p.get("id") is not None
    }

    def row(eid: int) -> dict[str, float]:
        return players.setdefault(
            eid,
            {
                "shots": 0.0,
                "shot_xg": 0.0,
                "shots_on_target": 0.0,
                "box_touches": 0.0,
                "chances_created": 0.0,
                "xg": 0.0,
                "xa": 0.0,
                "minutes": 0.0,
                "clearances": 0.0,
                "blocks": 0.0,
                "interceptions": 0.0,
                "tackles": 0.0,
                "recoveries": 0.0,
            },
        )

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
        target["clearances"] += _f(item.get("clearances"))
        target["blocks"] += _f(item.get("blocks"))
        target["interceptions"] += _f(item.get("interceptions"))
        target["tackles"] += _f(item.get("tackles"))
        target["recoveries"] += _f(item.get("recoveries"))
        if target["shots"] <= 0:
            target["shots"] += _f(item.get("total_shots"))

    normalized_players: dict[str, dict[str, Any]] = {}
    dc_covered = 0
    for eid, values in players.items():
        minutes = max(0.0, _f(values.get("minutes")))
        element_type = int(element_types.get(eid, 4))
        cbit = sum(_f(values.get(k)) for k in ("clearances", "blocks", "interceptions", "tackles"))
        cbirt = cbit + _f(values.get("recoveries"))
        dc_total = 0.0 if element_type == 1 else (cbit if element_type == 2 else cbirt)
        dc_per90 = round(dc_total * 90.0 / minutes, 4) if minutes > 0 and element_type != 1 else None
        dc_covered += int(dc_per90 is not None)
        normalized_players[str(eid)] = {
            **{name: round(value, 4) for name, value in values.items()},
            "dc_reconstructed_total": round(dc_total, 4),
            "dc_reconstructed_per90": dc_per90,
            "dc_evidence_minutes": round(minutes, 1),
            "dc_sample_quality": "INELIGIBLE" if element_type == 1 else _dc_sample_quality(minutes),
            "dc_metric_family": "NONE" if element_type == 1 else ("CBIT" if element_type == 2 else "CBIRT"),
        }

    sources = source_fusion.get("sources") if isinstance(source_fusion.get("sources"), dict) else {}
    understat = sources.get("understat") if isinstance(sources.get("understat"), dict) else {}
    understat_rows = understat.get("players") if isinstance(understat.get("players"), list) else []
    understat_by_name = {_norm(item.get("player_name")): item for item in understat_rows if isinstance(item, dict) and item.get("player_name")}
    matched = 0
    crosschecks: dict[str, Any] = {}
    for p in bootstrap.get("elements") or []:
        if not isinstance(p, dict) or p.get("id") is None:
            continue
        names = [p.get("web_name"), f"{p.get('first_name') or ''} {p.get('second_name') or ''}".strip()]
        candidate = next((understat_by_name.get(_norm(name)) for name in names if _norm(name) in understat_by_name), None)
        if candidate:
            matched += 1
            crosschecks[str(int(p["id"]))] = {
                "shots": _f(candidate.get("shots")),
                "xg": _f(candidate.get("xg")),
                "xa": _f(candidate.get("xa")),
                "key_passes": _f(candidate.get("key_passes")),
                "source": "understat",
            }

    return {
        "status": "ACTIVE" if shot_rows and match_rows else "DEGRADED",
        "source": cfg.get("source"),
        "shots_rows": len(shot_rows),
        "match_rows": len(match_rows),
        "coverage_players": len(players),
        "defensive_contribution_coverage_players": dc_covered,
        "players": normalized_players,
        "missing_player_behavior": cfg.get("missing_player_behavior"),
        "understat_status": understat.get("status"),
        "understat_players": len(understat_rows),
        "understat_identity_matches": matched,
        "understat_crosschecks": crosschecks,
        "artifact_gw": freshness.get("artifact_gw"),
        "authoritative_eligible": bool(freshness.get("authoritative_eligible")),
        "freshness": freshness,
        "governance": {
            "fpl_core_insights_primary": True,
            "understat_challenger_only": True,
            "shot_in_box_is_not_box_touch": True,
            "defensive_contribution_metrics_follow_official_position_rules": True,
            "missing_defensive_evidence_is_unavailable_not_zero": True,
            "point_in_time_freshness_gates_authoritative_feature_fusion": True,
            "stale_or_future_evidence_remains_visible_but_non_authoritative": True,
        },
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


def _cross_competition_rest_days(fixtures: list[dict[str, Any]], api_fixtures: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    by_team: dict[int, list[tuple[datetime, str]]] = {}
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            continue
        kickoff = _parse_dt(fixture.get("kickoff_time"))
        if kickoff is None:
            continue
        for key in ("team_h", "team_a"):
            if fixture.get(key) is not None:
                by_team.setdefault(int(fixture[key]), []).append((kickoff, "PREMIER_LEAGUE"))
    for item in api_fixtures:
        if not isinstance(item, dict) or item.get("fpl_team_id") is None:
            continue
        kickoff = _parse_dt(item.get("kickoff_time"))
        if kickoff is None:
            continue
        by_team.setdefault(int(item["fpl_team_id"]), []).append((kickoff, str(item.get("competition_class") or "OTHER")))
    result: dict[int, dict[str, Any]] = {}
    for team_id, events in by_team.items():
        ordered = sorted(events, key=lambda item: item[0])
        gaps = [round((ordered[i][0] - ordered[i - 1][0]).total_seconds() / 86400.0, 2) for i in range(1, len(ordered))]
        result[team_id] = {
            "minimum_cross_competition_rest_days": min(gaps) if gaps else None,
            "next_cross_competition_rest_gaps": gaps[:10],
            "event_classes": [kind for _, kind in ordered[:12]],
            "event_count": len(ordered),
            "source": "official_fpl+api_football",
        }
    return result


def _schedule_context(bootstrap: dict[str, Any], fixtures: list[dict[str, Any]], source_fusion: dict[str, Any]) -> dict[str, Any]:
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
    sources = source_fusion.get("sources") if isinstance(source_fusion.get("sources"), dict) else {}
    api_football = sources.get("api_football") if isinstance(sources.get("api_football"), dict) else {}
    api_fixtures = api_football.get("fixtures") if isinstance(api_football.get("fixtures"), list) else []
    return {
        "status": "ACTIVE",
        "league_rest_days": {str(k): v for k, v in _league_rest_days(fixtures).items()},
        "cross_competition_rest_days": {str(k): v for k, v in _cross_competition_rest_days(fixtures, api_fixtures).items()},
        "cross_competition_fixtures": api_fixtures,
        "european": european,
        "domestic_cup": cfg.get("domestic_cup") or {},
        "international": {
            **(cfg.get("international") or {}),
            "api_football": api_football.get("international"),
        },
        "api_football": {
            "status": api_football.get("status"),
            "resolved_competitions": api_football.get("resolved_competitions"),
            "failures": api_football.get("failures"),
        },
        "governance": {
            "missing_specific_match_or_callup_is_unavailable_not_zero": True,
            "calendar_windows_are_risk_context_not_claimed_minutes": True,
            "actual_cross_competition_fixtures_override_calendar_windows_when_available": True,
        },
    }


def _preseason(source_fusion: dict[str, Any]) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)["preseason"]
    artifact = _load_artifact(str(cfg["artifact_path"]))
    rows = artifact.get("rows") if isinstance(artifact.get("rows"), list) else []
    sources = source_fusion.get("sources") if isinstance(source_fusion.get("sources"), dict) else {}
    api_football = sources.get("api_football") if isinstance(sources.get("api_football"), dict) else {}
    friendlies = [row for row in (api_football.get("fixtures") or []) if isinstance(row, dict) and row.get("competition_class") == "FRIENDLY"]
    available = bool(rows or friendlies)
    return {
        "status": "ACTIVE",
        "evidence_status": "AVAILABLE" if available else "UNAVAILABLE",
        "row_count": len(rows),
        "friendly_fixture_count": len(friendlies),
        "source_policy": cfg.get("source_policy") or [],
        "fallback": "historical_role_prior" if not available else None,
        "never_fabricate_minutes_or_roles": bool(cfg.get("never_fabricate_minutes_or_roles", True)),
    }


def _current_form(bootstrap: dict[str, Any], advanced: dict[str, Any]) -> dict[str, Any]:
    advanced_players = advanced.get("players") if isinstance(advanced.get("players"), dict) else {}
    understat = advanced.get("understat_crosschecks") if isinstance(advanced.get("understat_crosschecks"), dict) else {}
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
            "understat_challenger": understat.get(str(eid)),
        }
    return {
        "status": "ACTIVE",
        "source": "official_fpl+fpl_core_insights+understat_challenger",
        "players": rows,
        "advanced_artifact_freshness": advanced.get("freshness"),
        "authoritative_mean_adjustment": False,
    }


def build_full_core_enrichment(
    bootstrap: dict[str, Any],
    fixtures: list[dict[str, Any]],
    source_fusion: dict[str, Any] | None = None,
    *,
    planning_gw: int | None = None,
) -> dict[str, Any]:
    fusion = source_fusion if isinstance(source_fusion, dict) else {"status": "UNAVAILABLE", "sources": {}}
    advanced = _advanced_stats(bootstrap, fusion, planning_gw=planning_gw)
    schedule = _schedule_context(bootstrap, fixtures, fusion)
    preseason = _preseason(fusion)
    current_form = _current_form(bootstrap, advanced)
    capabilities = list(CAPABILITIES)
    return {
        "schema_version": 4,
        "model": load_json_config(CONFIG).get("model_id"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "planning_gw": int(planning_gw) if planning_gw is not None else None,
        "status": "ACTIVE",
        "capabilities": capabilities,
        "advanced_stats": advanced,
        "schedule": schedule,
        "preseason": preseason,
        "current_form": current_form,
        "source_fusion": fusion,
        "governance": {
            "module_active_does_not_mean_every_player_has_evidence": True,
            "missing_external_evidence_is_unavailable_not_zero": True,
            "no_claimed_minutes_without_source": True,
            "official_fpl_identity_price_rules_never_overridden": True,
            "authoritative_advanced_evidence_requires_point_in_time_freshness": True,
        },
    }
