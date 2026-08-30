from __future__ import annotations

import json
from datetime import datetime, timezone

from src.utils import CONFIG, DATA, atomic_json, parse_dt, read_json

SNAPSHOT = DATA / "runtime" / "snapshot.v1.json"
OUT = DATA / "competitive_load_v4.json"
POLICY = CONFIG / "recent_competitive_load.json"
PRESS_EVIDENCE = DATA / "press_conference_evidence.json"
EXTERNAL_COMPETITIVE_EVIDENCE = DATA / "evidence" / "competitive_load_v4.json"
EXTERNAL_TYPES = {"EUROPEAN", "DOMESTIC_CUP", "INTERNATIONAL"}


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def _rest_hours(kickoff: datetime | None, team_id: int, fixtures: list[dict]) -> float | None:
    if kickoff is None:
        return None
    future = []
    for fixture in fixtures:
        if int(fixture.get("team_h") or 0) != team_id and int(fixture.get("team_a") or 0) != team_id:
            continue
        nxt = parse_dt(fixture.get("kickoff_time"))
        if nxt and nxt > kickoff:
            future.append(nxt)
    if not future:
        return None
    return round((min(future) - kickoff).total_seconds() / 3600.0, 1)


def _fixture_context(fixture_id: int, team_id: int, fixtures_by_id: dict[int, dict]) -> dict:
    fixture = fixtures_by_id.get(fixture_id) or {}
    kickoff = parse_dt(fixture.get("kickoff_time"))
    home = int(fixture.get("team_h") or 0) == team_id
    away = int(fixture.get("team_a") or 0) == team_id
    return {
        "fixture_id": fixture_id,
        "match_time": _iso(kickoff),
        "travel_context": "HOME" if home else "AWAY" if away else "UNKNOWN",
        "kickoff": kickoff,
    }


def _live_map(event_live: dict) -> dict[int, dict]:
    elements = event_live.get("elements") or {}
    if isinstance(elements, dict):
        return {int(key): value or {} for key, value in elements.items()}
    if isinstance(elements, list):
        return {int(row.get("id") or 0): row for row in elements if row.get("id") is not None}
    return {}


def _explain_stats(explain_row: dict) -> dict:
    values: dict[str, float] = {}
    for row in explain_row.get("stats") or []:
        identifier = str(row.get("identifier") or "")
        try:
            values[identifier] = values.get(identifier, 0.0) + float(row.get("value") or 0)
        except (TypeError, ValueError):
            continue
    return values


def _verified_external_matches(payload: dict, snapshot_at: datetime | None) -> tuple[list[dict], int]:
    rows = list(payload.get("player_matches") or []) if isinstance(payload, dict) else []
    verified: list[dict] = []
    rejected = 0
    for row in rows:
        if not isinstance(row, dict) or row.get("verified") is not True:
            rejected += 1
            continue
        try:
            element = int(row.get("element"))
            minutes = int(row.get("minutes") or 0)
            extra_time = int(row.get("extra_time_minutes") or 0)
        except (TypeError, ValueError):
            rejected += 1
            continue
        competition_type = str(row.get("competition_type") or "").upper()
        match_time = parse_dt(row.get("match_time"))
        verified_at = parse_dt(row.get("verified_at"))
        started = row.get("started")
        if (
            element <= 0
            or competition_type not in EXTERNAL_TYPES
            or match_time is None
            or verified_at is None
            or not row.get("source")
            or minutes < 0
            or minutes > 130
            or extra_time < 0
            or extra_time > 30
            or started not in {True, False, None}
            or (snapshot_at is not None and (match_time > snapshot_at or verified_at > snapshot_at))
        ):
            rejected += 1
            continue
        verified.append({
            "element": element,
            "competition_type": competition_type,
            "competition": row.get("competition") or competition_type,
            "fixture_id": row.get("fixture_id"),
            "match_time": _iso(match_time),
            "started": started,
            "minutes": minutes,
            "sub_on_minute": row.get("sub_on_minute"),
            "sub_off_minute": row.get("sub_off_minute"),
            "position_or_role": row.get("position_or_role"),
            "goal_or_assist": row.get("goal_or_assist") or {"goals": 0, "assists": 0},
            "set_piece_or_penalty_role_if_observed": row.get("set_piece_or_penalty_role_if_observed"),
            "knock_or_injury_signal": row.get("knock_or_injury_signal"),
            "extra_time_minutes": extra_time,
            "travel_context": row.get("travel_context") or "UNKNOWN",
            "source": row.get("source"),
            "source_quality": "VERIFIED_EXTERNAL_OFFICIAL",
            "verified_at": _iso(verified_at),
        })
    return verified, rejected


def build_competitive_load(
    snapshot: dict,
    press_evidence: dict | None = None,
    external_evidence: dict | None = None,
) -> dict:
    official = snapshot.get("official") or {}
    bootstrap = official.get("bootstrap") or {}
    event_live = official.get("event_live") or {}
    fixtures = official.get("fixtures") or []
    phase = snapshot.get("phase") or {}
    players = bootstrap.get("elements") or []
    players_by_id = {int(row.get("id") or 0): row for row in players}
    teams = {int(row.get("id") or 0): row.get("name") for row in bootstrap.get("teams") or []}
    fixtures_by_id = {int(row.get("id") or 0): row for row in fixtures if row.get("id") is not None}
    live_by_id = _live_map(event_live)
    press_evidence = press_evidence or {}
    press_teams = press_evidence.get("teams") or {}
    press_players = press_evidence.get("players") or {}

    snapshot_at = parse_dt(snapshot.get("generated_at"))
    verified_external, rejected_external = _verified_external_matches(external_evidence or {}, snapshot_at)
    external_by_element: dict[int, list[dict]] = {}
    unknown_elements = 0
    for row in verified_external:
        player = players_by_id.get(int(row["element"]))
        if player is None:
            unknown_elements += 1
            continue
        team_id = int(player.get("team") or 0)
        match_time = parse_dt(row.get("match_time"))
        normalized = {
            **row,
            "team_id": team_id,
            "rest_hours_to_next_fixture": _rest_hours(match_time, team_id, fixtures),
        }
        external_by_element.setdefault(int(row["element"]), []).append(normalized)

    rows = []
    observed_matches = 0
    for player in players:
        element = int(player.get("id") or 0)
        team_id = int(player.get("team") or 0)
        live = live_by_id.get(element) or {}
        matches = []
        for explain in live.get("explain") or []:
            fixture_id = int(explain.get("fixture") or 0)
            context = _fixture_context(fixture_id, team_id, fixtures_by_id)
            stats = _explain_stats(explain)
            minutes = int(stats.get("minutes") or 0)
            if minutes <= 0 and not any(stats.values()):
                continue
            observed_matches += 1
            matches.append({
                "competition_type": "PREMIER_LEAGUE",
                "competition": "Premier League",
                "fixture_id": fixture_id,
                "match_time": context["match_time"],
                "started": None,
                "minutes": minutes,
                "sub_on_minute": None,
                "sub_off_minute": None,
                "position_or_role": None,
                "goal_or_assist": {
                    "goals": int(stats.get("goals_scored") or 0),
                    "assists": int(stats.get("assists") or 0),
                },
                "set_piece_or_penalty_role_if_observed": None,
                "knock_or_injury_signal": None,
                "extra_time_minutes": 0,
                "travel_context": context["travel_context"],
                "rest_hours_to_next_fixture": _rest_hours(context["kickoff"], team_id, fixtures),
                "source": "raw_snapshot.official.event_live.explain",
                "source_quality": "OFFICIAL_FPL",
            })
        matches.extend(external_by_element.get(element) or [])
        matches.sort(key=lambda row: row.get("match_time") or "")

        team_name = teams.get(team_id) or str(team_id)
        press = (
            press_players.get(str(element))
            or press_players.get(element)
            or press_teams.get(team_name)
            or press_teams.get(str(team_id))
            or {}
        )
        press_status = "VERIFIED" if press.get("verified") is True else "UNVERIFIED"
        rows.append({
            "element": element,
            "name": player.get("web_name"),
            "team_id": team_id,
            "team": team_name,
            "current_gw_matches": matches,
            "press_conference": {
                "status": press_status,
                "manager_quote_or_official_team_news": press.get("manager_quote_or_official_team_news"),
                "availability": press.get("availability"),
                "rotation_hint": press.get("rotation_hint"),
                "fitness_or_knock": press.get("fitness_or_knock"),
                "role_or_position_hint": press.get("role_or_position_hint"),
                "expected_return_timing_if_relevant": press.get("expected_return_timing_if_relevant"),
                "source": press.get("source"),
                "verified_at": press.get("verified_at"),
            },
        })

    external_counts = {
        kind: sum(
            match.get("competition_type") == kind
            for row in rows for match in row.get("current_gw_matches") or []
        )
        for kind in EXTERNAL_TYPES
    }
    live_available = bool(live_by_id)
    verified_press = sum(row["press_conference"]["status"] == "VERIFIED" for row in rows)
    verified_press_teams = len({row["team_id"] for row in rows if row["press_conference"]["status"] == "VERIFIED"})
    return {
        "schema": "competitive_load.v1",
        "schema_version": 497,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scoring_gw": phase.get("scoring_gw"),
        "coverage": {
            "players": len(rows),
            "official_fpl_current_gw_load": "AVAILABLE" if live_available else "UNAVAILABLE",
            "observed_player_fixture_rows": observed_matches,
            "other_competitions": "VERIFIED_PARTIAL" if sum(external_counts.values()) else "REQUIRES_EXTERNAL_EVIDENCE",
            "external_evidence_state": "VERIFIED" if sum(external_counts.values()) else "EVIDENCE_GATED",
            "external_verified_player_fixture_rows": sum(external_counts.values()),
            "external_rejected_rows": rejected_external + unknown_elements,
            "european_verified_player_fixture_rows": external_counts["EUROPEAN"],
            "domestic_cup_verified_player_fixture_rows": external_counts["DOMESTIC_CUP"],
            "international_verified_player_fixture_rows": external_counts["INTERNATIONAL"],
            "press_conference_collection": "EXTERNAL_EVIDENCE_REQUIRED",
            "press_conference_verified_players": verified_press,
            "press_conference_verified_teams": verified_press_teams,
            "complete_for_visible_report": False,
            "completion_reason": "Premier League load is Official-automated; verified optional external evidence is consumed when materialized and otherwise remains evidence-gated",
            "implemented_dimensions": [
                "EUROPEAN",
                "DOMESTIC_CUP",
                "INTERNATIONAL",
                "REST_RECOVERY",
            ],
        },
        "guardrails": {
            "official_fpl_acquisition_reused_not_refetched": True,
            "minutes_not_used_to_infer_started": True,
            "press_conference_fabrication_forbidden": True,
            "verified_external_competitive_intake_wired": True,
            "external_competition_types": sorted(EXTERNAL_TYPES),
            "unverified_external_competitive_signal_is_zero": True,
            "missing_external_evidence_reported_explicitly": True,
            "recent_match_load_is_xmins_evidence_not_direct_points_evidence": True,
        },
        "players": rows,
    }


def run() -> dict:
    snapshot = read_json(SNAPSHOT, {})
    if not snapshot:
        raise RuntimeError("competitive load requires raw snapshot contract")
    policy = read_json(POLICY, {})
    if policy.get("contract") != "RECENT_COMPETITIVE_LOAD_V2":
        raise RuntimeError("recent competitive load policy missing or incompatible")
    press_evidence = read_json(PRESS_EVIDENCE, {})
    external_evidence = read_json(EXTERNAL_COMPETITIVE_EVIDENCE, {})
    out = build_competitive_load(snapshot, press_evidence, external_evidence)
    atomic_json(OUT, out)
    print(json.dumps({
        "service": "competitive_load",
        "status": "PASS",
        "players": out["coverage"]["players"],
        "observed_player_fixture_rows": out["coverage"]["observed_player_fixture_rows"],
        "external_verified_player_fixture_rows": out["coverage"]["external_verified_player_fixture_rows"],
        "press_conference_verified_players": out["coverage"]["press_conference_verified_players"],
        "complete_for_visible_report": out["coverage"]["complete_for_visible_report"],
    }, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
