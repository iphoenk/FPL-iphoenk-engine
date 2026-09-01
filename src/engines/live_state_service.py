from __future__ import annotations

import json
from typing import Any

from src.engines.base_state import bootstrap_maps, expanded_live
from src.utils import DATA, atomic_json, iso_now, read_json

OFFICIAL = DATA / "official_snapshot.json"
PREDICTION_LEDGER = DATA / "prediction_ledger.json"
OUT = DATA / "live.json"
MATCH_MODE_CONTRACT = "MATCH_MODE_LIVE_SCORE_V1"


def _team_match_status(fixtures: list[dict[str, Any]], team_id: int | None, scoring_gw: int | None) -> str:
    if team_id is None or scoring_gw is None:
        return "NOT_STARTED"
    team_fixtures = [
        row for row in fixtures
        if int(row.get("event") or -1) == int(scoring_gw)
        and team_id in {int(row.get("team_h") or -1), int(row.get("team_a") or -1)}
    ]
    if any(row.get("started") is True and row.get("finished") is not True for row in team_fixtures):
        return "LIVE"
    if team_fixtures and all(row.get("finished") is True for row in team_fixtures):
        return "FT"
    return "NOT_STARTED"


def _match_mode_active(fixtures: list[dict[str, Any]], scoring_gw: int | None) -> bool:
    if scoring_gw is None:
        return False
    return any(
        int(row.get("event") or -1) == int(scoring_gw)
        and row.get("started") is True
        and row.get("finished") is not True
        for row in fixtures
    )


def _prediction_map(scoring_gw: int | None) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    ledger = read_json(PREDICTION_LEDGER, {})
    record = ((ledger.get("records") or {}).get(str(scoring_gw)) or {}) if scoring_gw is not None else {}
    frozen = record.get("latest_pre_deadline_forecast") or {}
    rows = [row for row in frozen.get("players") or [] if row.get("element") is not None]
    return ({int(row["element"]): row for row in rows}, {
        "status": "AVAILABLE" if rows else "UNAVAILABLE",
        "source": "prediction_ledger.latest_pre_deadline_forecast" if rows else None,
        "generated_at": frozen.get("generated_at"),
        "gw": scoring_gw,
    })


def _empty_payload(scoring_gw: int | None, *, match_mode_active: bool, picks_available: bool, live_available: bool) -> dict[str, Any]:
    return {
        "generated_at": iso_now(),
        "contract": MATCH_MODE_CONTRACT,
        "status": "PARTIAL" if match_mode_active else "IDLE",
        "match_mode_active": match_mode_active,
        "scoring_gw": scoring_gw,
        "submitted_picks_status": "AVAILABLE" if picks_available else "SUBMITTED PICKS UNAVAILABLE",
        "event_live_status": "AVAILABLE" if live_available else "UNAVAILABLE",
        "coverage": {"owned": 0, "expected_owned": 15, "complete": False},
        "players": [],
        "personalized_live_score": None,
    }


def run() -> dict:
    official = read_json(OFFICIAL, {})
    bootstrap = official.get("bootstrap") or {}
    if not bootstrap:
        raise RuntimeError("official_snapshot missing bootstrap")
    phase = official.get("phase") or {}
    picks = official.get("picks") or {}
    event_live = official.get("event_live") or {}
    fixtures = list(official.get("fixtures") or [])
    teams, positions, by_id = bootstrap_maps(bootstrap)
    scoring_gw = phase.get("scoring_gw")
    active = _match_mode_active(fixtures, scoring_gw)
    pick_rows = list(picks.get("picks") or [])
    live_rows = list(event_live.get("elements") or [])
    payload = _empty_payload(
        scoring_gw,
        match_mode_active=active,
        picks_available=bool(pick_rows),
        live_available=bool(live_rows),
    )

    if not pick_rows or not live_rows:
        atomic_json(OUT, payload)
        return payload

    live_by = {int(row["id"]): row for row in live_rows}
    predictions, prediction_meta = _prediction_map(scoring_gw)
    detail: list[dict[str, Any]] = []
    effective_xi_points = 0
    bench_points = 0
    provisional_bonus_total = 0
    status_counts = {"FT": 0, "LIVE": 0, "NOT_STARTED": 0}
    captain_raw = 0
    captain_effective = 0
    potential_autosub_out: list[str] = []
    bench_candidates: list[str] = []

    for pick in pick_rows:
        element = int(pick["element"])
        player = by_id.get(element) or {}
        team_id = int(player.get("team")) if player.get("team") is not None else None
        stats = expanded_live(live_by.get(element) or {})
        raw_points = int(stats.get("total_points") or 0)
        multiplier = int(pick.get("multiplier") or 0)
        effective_points = raw_points * multiplier if multiplier > 0 else 0
        pick_position = int(pick.get("position") or 0)
        bench_order = pick_position - 11 if pick_position > 11 else None
        match_status = _team_match_status(fixtures, team_id, scoring_gw)
        status_counts[match_status] += 1
        predicted = predictions.get(element) or {}
        predicted_xpts = predicted.get("xpts")
        actual_delta = None
        if isinstance(predicted_xpts, (int, float)):
            actual_delta = round(float(raw_points) - float(predicted_xpts), 3)

        if multiplier > 0:
            effective_xi_points += effective_points
            if match_status == "FT" and int(stats.get("minutes") or 0) == 0:
                potential_autosub_out.append(player.get("web_name") or str(element))
        else:
            bench_points += raw_points
            if raw_points > 0:
                bench_candidates.append(player.get("web_name") or str(element))
        provisional_bonus_total += int(stats.get("bonus") or 0)
        if pick.get("is_captain"):
            captain_raw = raw_points
            captain_effective = effective_points

        detail.append({
            "element": element,
            "name": player.get("web_name"),
            "team": teams.get(player.get("team")),
            "team_id": team_id,
            "position": positions.get(player.get("element_type")),
            "fixture_status": match_status,
            "pick_position": pick_position,
            "bench_order": bench_order,
            "multiplier": multiplier,
            "effective_points": effective_points,
            "captain": bool(pick.get("is_captain")),
            "vice": bool(pick.get("is_vice_captain")),
            "pre_match_prediction": {
                "xpts": predicted_xpts,
                "xmins": predicted.get("xmins"),
                "start_probability": predicted.get("start_probability"),
                "confidence": predicted.get("projection_confidence"),
                "source": prediction_meta.get("source"),
            },
            "actual_vs_predicted": {
                "raw_points_minus_xpts": actual_delta,
                "diagnostic_only": True,
            },
            **stats,
        })

    hit = int((picks.get("entry_history") or {}).get("event_transfers_cost") or 0)
    complete = len(detail) == 15 and len({row["element"] for row in detail}) == 15
    if active and not complete:
        raise RuntimeError(f"Match Mode publication blocked: ALL15 submitted-pick coverage required, got {len(detail)}/15")

    personalized = {
        "status": "PROVISIONAL" if active else "RECONCILED_OR_IDLE",
        "effective_xi_points": effective_xi_points,
        "bench_points": bench_points,
        "captain_raw_points": captain_raw,
        "captain_effective_contribution": captain_effective,
        "players_ft": status_counts["FT"],
        "players_live": status_counts["LIVE"],
        "players_not_started": status_counts["NOT_STARTED"],
        "provisional_bonus_total": provisional_bonus_total,
        "hit": hit,
        "current_effective_total": effective_xi_points,
        "current_net_total": effective_xi_points - hit,
        "autosub_implications": {
            "status": "PROVISIONAL",
            "potential_out": potential_autosub_out,
            "bench_candidates": bench_candidates,
            "note": "Official finalization remains authoritative; no autosub is inferred into the current total.",
        },
    }
    payload = {
        "generated_at": iso_now(),
        "contract": MATCH_MODE_CONTRACT,
        "status": "PROVISIONAL" if active else "RECONCILED_OR_IDLE",
        "match_mode_active": active,
        "scoring_gw": scoring_gw,
        "submitted_picks_status": "AVAILABLE",
        "event_live_status": "AVAILABLE",
        "prediction_snapshot": prediction_meta,
        "coverage": {"owned": len(detail), "expected_owned": 15, "complete": complete},
        "gross_points": effective_xi_points,
        "hit": hit,
        "net_points": effective_xi_points - hit,
        "players": detail,
        "personalized_live_score": personalized,
        "governance": {
            "submitted_picks_are_scoring_authority": True,
            "planning_xi_cannot_replace_submitted_picks": True,
            "actual_vs_predicted_is_diagnostic_only": True,
            "single_match_performance_cannot_authorize_transfer": True,
        },
    }
    atomic_json(OUT, payload)
    return payload


if __name__ == "__main__":
    out = run()
    print(json.dumps({
        "status": out.get("status"),
        "match_mode_active": out.get("match_mode_active"),
        "scoring_gw": out.get("scoring_gw"),
        "owned": (out.get("coverage") or {}).get("owned"),
        "net_points": out.get("net_points"),
    }, ensure_ascii=False))
