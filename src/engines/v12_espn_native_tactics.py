from __future__ import annotations

"""Exact source-bound ESPN starting-XI/formation observations, NEVER FotMob.

Read-only V12 projection of data already acquired and SHA-bound by governed
V6. No network access, no Official FPL athlete-ID inference or P(start) effect.
"""
from collections import Counter
import re
from typing import Any, Mapping

from src.engines.v12_espn_fixture_crosscheck import (
    _date, _int, _HEX, crosscheck_espn_historical_fixtures,
)

_FORMATION = re.compile(r"^[1-9](?:-[1-9]){2,4}$")


def _validated_rosters(
    summary: Mapping[str, Any], scoreboard: Mapping[str, Any], eid: int,
) -> list[dict[str, Any]] | None:
    """Require same ESPN native match, teams, scores and 22 unique starters."""
    header = summary.get("header") or {}
    if not isinstance(header, Mapping):
        return None
    rosters = summary.get("rosters") or []
    comps = header.get("competitions") or []
    if (_int(header.get("id")) != eid or not isinstance(comps, list)
            or len(comps) != 1 or not isinstance(rosters, list) or len(rosters) != 2):
        return None
    comp = comps[0]
    if not isinstance(comp, Mapping) or _int(comp.get("id")) != eid:
        return None
    status = comp.get("status") or {}
    state = status.get("type") or {} if isinstance(status, Mapping) else {}
    event_time = _date(scoreboard.get("date"))
    if (not isinstance(state, Mapping) or state.get("completed") is not True
            or state.get("state") != "post"
            or event_time is None or _date(comp.get("date")) != event_time):
        return None
    s_comps = scoreboard.get("competitions") or []
    if not isinstance(s_comps, list) or len(s_comps) != 1:
        return None
    sb_comp = s_comps[0]
    if not isinstance(sb_comp, Mapping):
        return None
    def _competitors(row: Mapping[str, Any]) -> dict[str, Mapping[str, Any]] | None:
        items = row.get("competitors") or []
        if not isinstance(items, list) or len(items) != 2:
            return None
        output: dict[str, Mapping[str, Any]] = {}
        for item in items:
            if not isinstance(item, Mapping) or item.get("homeAway") not in ("home", "away"):
                return None
            key = item["homeAway"]
            if key in output:
                return None
            output[key] = item
        return output if set(output) == {"home", "away"} else None

    header_sides, board_sides = _competitors(comp), _competitors(sb_comp)
    if header_sides is None or board_sides is None:
        return None
    result = []
    seen_players: set[int] = set()
    seen_sides: set[str] = set()
    for row in rosters:
        if not isinstance(row, Mapping) or row.get("homeAway") not in {"home", "away"}:
            return None
        side = row["homeAway"]
        if side in seen_sides:
            return None
        seen_sides.add(side)
        team = row.get("team") or {}
        if not isinstance(team, Mapping):
            return None
        header_team = header_sides[side].get("team") or {}
        board_team = board_sides[side].get("team") or {}
        native_id = _int(team.get("id"))
        if (native_id is None or native_id != _int(header_team.get("id"))
                or native_id != _int(board_team.get("id"))
                or not isinstance(team.get("displayName"), str)
                or team["displayName"] != header_team.get("displayName")
                or team["displayName"] != board_team.get("displayName")
                or str(header_sides[side].get("score")) != str(board_sides[side].get("score"))):
            return None
        formation = row.get("formation")
        if (not isinstance(formation, str) or not _FORMATION.fullmatch(formation)
                or sum(int(x) for x in formation.split("-")) != 10):
            return None
        players = row.get("roster") or []
        if not isinstance(players, list):
            return None
        starters = [p for p in players if isinstance(p, Mapping) and p.get("starter") is True]
        if len(starters) != 11:
            return None
        native_players = []
        positions = []
        for player in starters:
            athlete = player.get("athlete") or {}
            if not isinstance(athlete, Mapping):
                return None
            pid = _int(athlete.get("id"))
            if pid is None or pid in seen_players:
                return None
            seen_players.add(pid)
            native_players.append(pid)
            pos = player.get("position") or {}
            positions.append(str(pos.get("displayName") or "") if isinstance(pos, Mapping) else "")
        result.append({
            "side": side,
            "espn_native_team_id": native_id,
            "team_name": team["displayName"],
            "formation": formation,
            "verified_source_native_starter_count": 11,
            "espn_native_starter_ids": native_players,
            "source_native_reported_positions": positions,
            "official_fpl_starter_ids": [],
            "official_fpl_player_identity_status": "UNMAPPED",
            "semantic_tactical_role_calibrated": False,
        })
    return sorted(result, key=lambda row: 0 if row["side"] == "home" else 1)


def verify_espn_native_lineup_coverage(
    espn: Mapping[str, Any], fotmob: Mapping[str, Any], *, source_cutoff: str,
) -> dict[str, Any]:
    """Never call this a FotMob detail or verified Official FPL athlete lineup."""
    result: dict[str, Any] = {
        "contract": "V12_ESPN_NATIVE_POSTMATCH_TACTICAL_EVIDENCE_V1",
        "status": "SOURCE_UNAVAILABLE",
        "native_espn_starting_xi_matches": 0,
        "native_espn_starter_observations": 0,
        "missing_fotmob_with_espn_native_xi": 0,
        "verified_fotmob_native_tactics": 0,
        "combined_distinct_tactical_fixtures": 0,
        "historical_fixture_denominator": 0,
        "still_without_tactical_source_fixture_ids": [],
        "source_native_observations": [],
        "espn_athlete_official_fpl_crosswalk": "NOT_ESTABLISHED",
        "player_role_or_manager_effect_calibrated": False,
        "historical_predeadline_asof_proven": False,
        "numeric_pstart_effect": "NONE",
        "fotmob_matchdetails_retrieval_promoted": False,
    }
    bridge = crosscheck_espn_historical_fixtures(espn, fotmob, source_cutoff=source_cutoff)
    if bridge.get("status") != "VERIFIED_FIXTURE_ONLY":
        result["reason"] = bridge.get("reason") or "FIXTURE_IDENTITY_BRIDGE_UNAVAILABLE"
        return result
    cutoff = _date(source_cutoff)
    groups = fotmob.get("record_groups") or {}
    fixtures = groups.get("fixtures") or []
    tactics = groups.get("match_tactics") or []
    if cutoff is None or not isinstance(fixtures, list) or not isinstance(tactics, list):
        result["reason"] = "SOURCE_OR_CUTOFF_SCHEMA_UNAVAILABLE"
        return result
    expected = {
        _int(row.get("official_fixture_id"))
        for row in fixtures if isinstance(row, Mapping)
        and row.get("identity_status") in {"EXACT", "VERIFIED_MANUAL"}
        and (row.get("status") or {}).get("finished") is True
        and _int(row.get("round")) in range(1, 7)
        and _int(row.get("official_fixture_id")) is not None
    }
    original = {
        _int(row.get("official_fixture_id"))
        for row in tactics if isinstance(row, Mapping)
        and row.get("fixture_join") == "VERIFIED_NATIVE_TO_OFFICIAL"
        and _HEX.fullmatch(str(row.get("source_snapshot_sha256") or ""))
        and _int(row.get("official_fixture_id")) in expected
    }
    original.discard(None)
    espn_data = espn.get("data") or {}
    if not isinstance(espn_data, Mapping):
        result["reason"] = "ESPN_SOURCE_SCHEMA_MISMATCH"
        return result
    # A duplicate event in the raw scoreboard is already rejected by the
    # exact fixture bridge. A summary must additionally match that scoreboard.
    scoreboard = {}
    for key, obs in espn_data.items():
        if not str(key).startswith("history_scoreboard_") or not isinstance(obs, Mapping):
            continue
        if obs.get("status") != "AVAILABLE" or not _HEX.fullmatch(str(obs.get("sha256") or "")):
            continue
        for event in (obs.get("json") or {}).get("events") or []:
            if not isinstance(event, Mapping):
                continue
            eid = _int(event.get("id"))
            if eid is not None:
                scoreboard.setdefault(eid, []).append(event)
    records = []
    for match in bridge.get("matches") or []:
        event_id = _int(match.get("espn_native_event_id"))
        fixture_id = _int(match.get("official_fixture_id"))
        if event_id is None or fixture_id not in expected or len(scoreboard.get(event_id, [])) != 1:
            continue
        snapshot = espn_data.get("history_summary_" + str(event_id)) or {}
        if (not isinstance(snapshot, Mapping) or snapshot.get("status") != "AVAILABLE"
                or not _HEX.fullmatch(str(snapshot.get("sha256") or ""))
                or snapshot.get("sha256_scope") not in (None, "full_body")
                or (s_at := _date(snapshot.get("checked_at"))) is None or s_at > cutoff):
            continue
        summary = snapshot.get("json") or {}
        if not isinstance(summary, Mapping):
            continue
        rosters = _validated_rosters(summary, scoreboard[event_id][0], event_id)
        if rosters is None:
            continue
        records.append({
            "official_fixture_id": fixture_id,
            "gw": match.get("gw"),
            "espn_native_event_id": event_id,
            "source_snapshot_sha256": snapshot["sha256"],
            "source_observed_at": snapshot["checked_at"],
            "observation_class": "ESPN_SOURCE_NATIVE_POSTMATCH_XI_FORMATION",
            "teams": rosters,
            "official_fpl_player_identity_status": "UNMAPPED",
            "numeric_pstart_effect": "NONE",
        })
    records.sort(key=lambda row: row["official_fixture_id"])
    counts = Counter(r["official_fixture_id"] for r in records)
    records = [r for r in records if counts[r["official_fixture_id"]] == 1]
    added = {r["official_fixture_id"] for r in records}
    independent = added - original
    result.update({
        "status": "VERIFIED_ESPN_NATIVE_XI_ONLY" if records else "PARTIAL",
        "native_espn_starting_xi_matches": len(added),
        "native_espn_starter_observations": len(added) * 22,
        "missing_fotmob_with_espn_native_xi": len(independent),
        "verified_fotmob_native_tactics": len(original),
        "combined_distinct_tactical_fixtures": len(original | added),
        "historical_fixture_denominator": len(expected),
        "still_without_tactical_source_fixture_ids": sorted(expected - (original | added)),
        "source_native_observations": records,
        "reason": None if records else "NO_VALID_SOURCE_NATIVE_ESPN_ROSTERS",
    })
    return result
