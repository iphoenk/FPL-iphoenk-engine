from __future__ import annotations

"""Normalize completed-GW Official FPL event-live facts for V12 consumers.

This is a V6 factual normalization helper. It creates no prediction, tactical
inference, player identity heuristic, fixture guess, or decision authority.
"""

from datetime import datetime, timezone
from typing import Any, Mapping


def _int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _position_map(bootstrap: Mapping[str, Any]) -> dict[int, str]:
    return {
        int(row["id"]): (
            "GK"
            if str(row.get("singular_name_short") or "").upper() in {"GKP", "GK"}
            else str(row.get("singular_name_short") or "").upper()
        )
        for row in bootstrap.get("element_types") or []
        if isinstance(row, Mapping) and row.get("id") is not None
    }


def _iso_max(values: list[str]) -> str | None:
    parsed: list[tuple[datetime, str]] = []
    for raw in values:
        try:
            value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        parsed.append((value.astimezone(timezone.utc), str(raw)))
    return max(parsed)[1] if parsed else None


def build_official_match_history(
    client: Any,
    *,
    bootstrap_result: Mapping[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    bootstrap = (
        bootstrap_result.get("payload")
        if bootstrap_result.get("status") == "LIVE"
        else None
    )
    if not isinstance(bootstrap, Mapping):
        return {
            "schema_version": 1,
            "normalization_version": "V6_OFFICIAL_MATCH_HISTORY_1",
            "source_id": "official_fpl",
            "generated_at": generated_at,
            "effective_at": None,
            "source_health": "RED",
            "normalization_status": "BLOCKED",
            "status": "BLOCKED",
            "completed_gws_expected": [],
            "completed_gws_available": [],
            "missing_gws": [],
            "ambiguous_fixture_rows": 0,
            "record_count": 0,
            "record_groups": {"player_matches": []},
            "blockers": ["OFFICIAL_BOOTSTRAP_UNAVAILABLE"],
        }

    completed_gws = sorted(
        int(row["id"])
        for row in bootstrap.get("events") or []
        if isinstance(row, Mapping)
        and row.get("id") is not None
        and row.get("finished") is True
    )
    if not completed_gws:
        return {
            "schema_version": 1,
            "normalization_version": "V6_OFFICIAL_MATCH_HISTORY_1",
            "source_id": "official_fpl",
            "generated_at": generated_at,
            "effective_at": bootstrap_result.get("checked_at"),
            "source_health": "GREEN",
            "normalization_status": "NORMALIZED",
            "status": "COMPLETE",
            "completed_gws_expected": [],
            "completed_gws_available": [],
            "missing_gws": [],
            "ambiguous_fixture_rows": 0,
            "record_count": 0,
            "record_groups": {"player_matches": []},
            "blockers": [],
            "governance": {
                "data_only": True,
                "official_ids_are_canonical": True,
                "fixture_guessing": False,
                "cross_source_synthesis": False,
                "decision_authority": "NONE",
            },
        }

    fixtures_result = client.fixtures()
    fixtures_payload = (
        fixtures_result.get("payload")
        if fixtures_result.get("status") == "LIVE"
        else None
    )
    if not isinstance(fixtures_payload, list):
        return {
            "schema_version": 1,
            "normalization_version": "V6_OFFICIAL_MATCH_HISTORY_1",
            "source_id": "official_fpl",
            "generated_at": generated_at,
            "effective_at": bootstrap_result.get("checked_at"),
            "source_health": "RED",
            "normalization_status": "BLOCKED",
            "status": "BLOCKED",
            "completed_gws_expected": completed_gws,
            "completed_gws_available": [],
            "missing_gws": completed_gws,
            "ambiguous_fixture_rows": 0,
            "record_count": 0,
            "record_groups": {"player_matches": []},
            "blockers": ["OFFICIAL_FIXTURES_UNAVAILABLE"],
        }

    elements = {
        int(row["id"]): dict(row)
        for row in bootstrap.get("elements") or []
        if isinstance(row, Mapping) and row.get("id") is not None
    }
    positions = _position_map(bootstrap)
    fixtures_by_gw_team: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for raw in fixtures_payload:
        if not isinstance(raw, Mapping):
            continue
        gw = _int(raw.get("event"))
        team_h = _int(raw.get("team_h"))
        team_a = _int(raw.get("team_a"))
        if gw not in completed_gws or team_h is None or team_a is None:
            continue
        row = dict(raw)
        fixtures_by_gw_team.setdefault((gw, team_h), []).append(row)
        fixtures_by_gw_team.setdefault((gw, team_a), []).append(row)

    player_matches: list[dict[str, Any]] = []
    missing_gws: list[int] = []
    ambiguous = 0
    checked_at_values = [
        str(bootstrap_result.get("checked_at") or ""),
        str(fixtures_result.get("checked_at") or ""),
    ]
    live_lineage: list[dict[str, Any]] = []

    required_stats = ("minutes", "starts", "total_points")
    for gw in completed_gws:
        live_result = client.event_live(gw)
        if live_result.get("status") != "LIVE":
            missing_gws.append(gw)
            live_lineage.append(
                {
                    "gw": gw,
                    "status": live_result.get("status"),
                    "checked_at": live_result.get("checked_at"),
                    "payload_digest": live_result.get("payload_digest"),
                }
            )
            continue
        checked_at_values.append(str(live_result.get("checked_at") or ""))
        payload = live_result.get("payload") or {}
        raw_elements = payload.get("elements")
        if not isinstance(raw_elements, list):
            missing_gws.append(gw)
            continue
        live_lineage.append(
            {
                "gw": gw,
                "status": "LIVE",
                "checked_at": live_result.get("checked_at"),
                "payload_digest": live_result.get("payload_digest"),
            }
        )
        gw_rows_before = len(player_matches)
        for raw in raw_elements:
            if not isinstance(raw, Mapping):
                continue
            element_id = _int(raw.get("id"))
            player = elements.get(element_id or -1)
            stats = raw.get("stats")
            if not player or not isinstance(stats, Mapping):
                continue
            if any(stats.get(field) is None for field in required_stats):
                continue
            team_id = _int(player.get("team"))
            if team_id is None:
                continue
            candidates = fixtures_by_gw_team.get((gw, team_id), [])
            if len(candidates) != 1:
                ambiguous += 1
                continue
            fixture = candidates[0]
            fixture_id = _int(fixture.get("id"))
            team_h = _int(fixture.get("team_h"))
            team_a = _int(fixture.get("team_a"))
            if fixture_id is None or team_h is None or team_a is None:
                continue
            home = team_id == team_h
            opponent_id = team_a if home else team_h
            starts = _int(stats.get("starts"))
            if starts is None:
                continue
            player_matches.append(
                {
                    "source_native_player_id": element_id,
                    "source_native_fixture_id": fixture_id,
                    "source_native_opponent_team_id": opponent_id,
                    "official_element_id": element_id,
                    "identity_status": "EXACT",
                    "official_fixture_id": fixture_id,
                    "fixture_identity_status": "EXACT",
                    "official_opponent_team_id": opponent_id,
                    "opponent_identity_status": "EXACT",
                    "gw": gw,
                    "position": positions.get(_int(player.get("element_type")) or -1),
                    "team": team_id,
                    "minutes": _int(stats.get("minutes")),
                    "starts": starts,
                    "starter": starts > 0,
                    "home": home,
                    "kickoff_time": fixture.get("kickoff_time"),
                    "team_h_score": _int(fixture.get("team_h_score")),
                    "team_a_score": _int(fixture.get("team_a_score")),
                    "goals": _int(stats.get("goals_scored")),
                    "assists": _int(stats.get("assists")),
                    "xg": _float(stats.get("expected_goals")),
                    "xa": _float(stats.get("expected_assists")),
                    "xgi": _float(stats.get("expected_goal_involvements")),
                    "xgc": _float(stats.get("expected_goals_conceded")),
                    "clean_sheets": _int(stats.get("clean_sheets")),
                    "goals_conceded": _int(stats.get("goals_conceded")),
                    "saves": _int(stats.get("saves")),
                    "penalties_saved": _int(stats.get("penalties_saved")),
                    "penalties_missed": _int(stats.get("penalties_missed")),
                    "yellow_cards": _int(stats.get("yellow_cards")),
                    "red_cards": _int(stats.get("red_cards")),
                    "bonus": _int(stats.get("bonus")),
                    "bps": _int(stats.get("bps")),
                    "defensive": _float(stats.get("defensive_contribution")),
                    "clearances_blocks_interceptions": _float(
                        stats.get("clearances_blocks_interceptions")
                    ),
                    "recoveries": _float(stats.get("recoveries")),
                    "tackles": _float(stats.get("tackles")),
                    "creativity": _float(stats.get("creativity")),
                    "influence": _float(stats.get("influence")),
                    "threat": _float(stats.get("threat")),
                    "fpl_points": _int(stats.get("total_points")),
                    "source": "official_fpl",
                    "dataset": "event_live",
                    "source_checked_at": live_result.get("checked_at"),
                }
            )
        if len(player_matches) == gw_rows_before:
            missing_gws.append(gw)

    available_gws = sorted(
        {int(row["gw"]) for row in player_matches if row.get("gw") is not None}
    )
    missing_gws = sorted(set(completed_gws) - set(available_gws) | set(missing_gws))
    blockers: list[str] = []
    if missing_gws:
        blockers.append(
            "OFFICIAL_EVENT_LIVE_MISSING_GWS=" + ",".join(map(str, missing_gws))
        )
    if ambiguous:
        blockers.append(f"AMBIGUOUS_MULTI_FIXTURE_PLAYER_ROWS={ambiguous}")
    status = "COMPLETE" if not blockers else "PARTIAL"
    return {
        "schema_version": 1,
        "normalization_version": "V6_OFFICIAL_MATCH_HISTORY_1",
        "source_id": "official_fpl",
        "generated_at": generated_at,
        "effective_at": _iso_max(checked_at_values),
        "source_health": "GREEN" if not missing_gws else "AMBER",
        "normalization_status": "NORMALIZED" if player_matches else "BLOCKED",
        "status": status,
        "completed_gws_expected": completed_gws,
        "completed_gws_available": available_gws,
        "missing_gws": missing_gws,
        "ambiguous_fixture_rows": ambiguous,
        "record_count": len(player_matches),
        "record_groups": {"player_matches": player_matches},
        "lineage": {
            "bootstrap": {
                "checked_at": bootstrap_result.get("checked_at"),
                "payload_digest": bootstrap_result.get("payload_digest"),
            },
            "fixtures": {
                "checked_at": fixtures_result.get("checked_at"),
                "payload_digest": fixtures_result.get("payload_digest"),
            },
            "event_live": live_lineage,
        },
        "blockers": blockers,
        "governance": {
            "data_only": True,
            "authority": "OFFICIAL_FPL",
            "official_ids_are_canonical": True,
            "fixture_guessing": False,
            "ambiguous_multi_fixture_rows_rejected": True,
            "missing_stats_not_inferred": True,
            "cross_source_synthesis": False,
            "decision_authority": "NONE",
            "prediction_authority": "NONE",
        },
    }
