from __future__ import annotations

from pathlib import Path
from typing import Any

from src.engines.fpl_rules_2026 import POSITION_BY_TYPE
from src.utils import DATA, read_json

DEADLINE_ROOT = DATA / "validation" / "deadline"
CONTRACT = "MATCH_MODE_LIVE_SCORE_V1"


def _fixture_status(fixtures: list[dict[str, Any]], team_id: int | None, scoring_gw: int | None) -> str:
    if team_id is None or scoring_gw is None:
        return "NOT_STARTED"
    rows = [
        row for row in fixtures
        if int(row.get("event") or -1) == int(scoring_gw)
        and team_id in {int(row.get("team_h") or -1), int(row.get("team_a") or -1)}
    ]
    if any(row.get("started") is True and row.get("finished") is not True for row in rows):
        return "LIVE"
    if rows and all(row.get("finished") is True for row in rows):
        return "FT"
    return "NOT_STARTED"


def _deadline_prediction_map(scoring_gw: int | None, deadline_root: Path) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    if not scoring_gw:
        return {}, {"status": "UNAVAILABLE", "gw": scoring_gw, "source": None}
    path = deadline_root / f"gw{int(scoring_gw):02d}.json"
    payload = read_json(path, {}) if path.exists() else {}
    if payload.get("immutable") is not True or int(payload.get("gw") or 0) != int(scoring_gw):
        return {}, {"status": "UNAVAILABLE", "gw": scoring_gw, "source": None}
    out: dict[int, dict[str, Any]] = {}
    for row in payload.get("players") or []:
        element = row.get("element")
        if element is None:
            continue
        fixture = next((item for item in row.get("fixtures") or [] if int(item.get("event") or 0) == int(scoring_gw)), {})
        if fixture:
            out[int(element)] = fixture
    return out, {
        "status": "AVAILABLE" if out else "UNAVAILABLE",
        "gw": scoring_gw,
        "source": f"data/validation/deadline/gw{int(scoring_gw):02d}.json" if out else None,
        "generated_at": payload.get("prediction_generated_at") or payload.get("generated_at"),
        "immutable": bool(payload.get("immutable")),
    }


def build_match_mode_scorecard(raw: dict, *, deadline_root: Path = DEADLINE_ROOT) -> dict:
    phase = raw.get("phase") or {}
    official = raw.get("official") or {}
    scoring_gw = int(phase.get("scoring_gw") or 0) or None
    active = bool(phase.get("is_live_match"))
    picks = list((official.get("picks") or {}).get("picks") or [])
    event_live = list((official.get("event_live") or {}).get("elements") or [])
    fixtures = list(official.get("fixtures") or [])

    base = {
        "contract": CONTRACT,
        "match_mode_active": active,
        "scoring_gw": scoring_gw,
        "submitted_picks_status": "AVAILABLE" if picks else "SUBMITTED PICKS UNAVAILABLE",
        "event_live_status": "AVAILABLE" if event_live else "UNAVAILABLE",
        "coverage": {"owned": 0, "expected_owned": 15, "complete": False},
        "players": [],
        "personalized_live_score": None,
        "prediction_snapshot": {"status": "UNAVAILABLE", "gw": scoring_gw, "source": None},
    }
    if not active:
        return {**base, "status": "IDLE"}
    if not picks or not event_live:
        return {**base, "status": "PARTIAL"}

    unique = {int(row.get("element") or 0) for row in picks if row.get("element") is not None}
    if len(picks) != 15 or len(unique) != 15:
        raise RuntimeError(f"Match Mode publication blocked: ALL15 submitted-pick coverage required, got {len(unique)}/15")

    bootstrap = official.get("bootstrap") or {}
    players_by_id = {int(row["id"]): row for row in bootstrap.get("elements") or []}
    teams = {int(row["id"]): row.get("name") for row in bootstrap.get("teams") or []}
    live_by_id = {int(row["id"]): row for row in event_live if row.get("id") is not None}
    predictions, prediction_meta = _deadline_prediction_map(scoring_gw, deadline_root)

    detail: list[dict[str, Any]] = []
    effective_xi = 0
    bench_points = 0
    provisional_bonus = 0
    status_counts = {"FT": 0, "LIVE": 0, "NOT_STARTED": 0}
    captain_raw = 0
    captain_effective = 0
    potential_out: list[str] = []
    bench_candidates: list[str] = []

    for pick in sorted(picks, key=lambda row: int(row.get("position") or 99)):
        element = int(pick["element"])
        player = players_by_id.get(element) or {}
        stats = (live_by_id.get(element) or {}).get("stats") or {}
        raw_points = int(stats.get("total_points") or 0)
        multiplier = max(0, int(pick.get("multiplier") or 0))
        effective_points = raw_points * multiplier if multiplier > 0 else 0
        pick_position = int(pick.get("position") or 0)
        bench_order = pick_position - 11 if pick_position > 11 else None
        team_id = int(player.get("team")) if player.get("team") is not None else None
        fixture_status = _fixture_status(fixtures, team_id, scoring_gw)
        status_counts[fixture_status] += 1
        pred = predictions.get(element) or {}
        xpts = pred.get("xpts")
        xmins = pred.get("xmins") or {}
        delta = round(raw_points - float(xpts), 3) if isinstance(xpts, (int, float)) else None
        name = player.get("web_name") or str(element)

        if multiplier > 0:
            effective_xi += effective_points
            if fixture_status == "FT" and int(stats.get("minutes") or 0) == 0:
                potential_out.append(name)
        else:
            bench_points += raw_points
            if raw_points > 0:
                bench_candidates.append(name)
        provisional_bonus += int(stats.get("bonus") or 0)
        if pick.get("is_captain"):
            captain_raw = raw_points
            captain_effective = effective_points

        detail.append({
            "element": element,
            "name": name,
            "team": teams.get(team_id),
            "team_id": team_id,
            "position": POSITION_BY_TYPE.get(player.get("element_type")),
            "fixture_status": fixture_status,
            "pick_position": pick_position,
            "bench_order": bench_order,
            "multiplier": multiplier,
            "captain": bool(pick.get("is_captain")),
            "vice_captain": bool(pick.get("is_vice_captain")),
            "raw_points": raw_points,
            "effective_points": effective_points,
            "minutes": int(stats.get("minutes") or 0),
            "goals": int(stats.get("goals_scored") or 0),
            "assists": int(stats.get("assists") or 0),
            "clean_sheets": int(stats.get("clean_sheets") or 0),
            "saves": int(stats.get("saves") or 0),
            "yellow_cards": int(stats.get("yellow_cards") or 0),
            "red_cards": int(stats.get("red_cards") or 0),
            "bonus": int(stats.get("bonus") or 0),
            "bps": int(stats.get("bps") or 0),
            "pre_match_prediction": {
                "xpts": xpts,
                "xmins": xmins.get("expected_minutes"),
                "start_probability": xmins.get("start_probability"),
                "source": prediction_meta.get("source"),
            },
            "actual_vs_predicted": {"raw_points_minus_xpts": delta, "diagnostic_only": True},
        })

    hit = int(((official.get("picks") or {}).get("entry_history") or {}).get("event_transfers_cost") or 0)
    personalized = {
        "status": "PROVISIONAL",
        "effective_xi_points": effective_xi,
        "bench_points": bench_points,
        "captain_raw_points": captain_raw,
        "captain_effective_contribution": captain_effective,
        "players_ft": status_counts["FT"],
        "players_live": status_counts["LIVE"],
        "players_not_started": status_counts["NOT_STARTED"],
        "provisional_bonus_total": provisional_bonus,
        "hit": hit,
        "current_effective_total": effective_xi,
        "current_net_total": effective_xi - hit,
        "autosub_implications": {
            "status": "PROVISIONAL",
            "potential_out": potential_out,
            "bench_candidates": bench_candidates,
            "note": "Official finalization remains authoritative; autosubs are not inferred into the current total.",
        },
    }
    return {
        **base,
        "status": "PROVISIONAL",
        "coverage": {"owned": 15, "expected_owned": 15, "complete": True},
        "players": detail,
        "personalized_live_score": personalized,
        "prediction_snapshot": prediction_meta,
        "guardrails": {
            "submitted_picks_are_scoring_authority": True,
            "planning_xi_cannot_replace_submitted_picks": True,
            "actual_vs_predicted_is_diagnostic_only": True,
            "single_match_performance_cannot_authorize_transfer": True,
            "autosub_not_inferred_before_official_finalization": True,
        },
    }
