from __future__ import annotations

"""Read-only ESPN-to-Official-FPL fixture crosscheck through verified V6 FotMob.

FotMob LEAGUE fixture IDs/crosswalks, not FotMob matchDetails, are used for
exact fixture identity. ESPN remains a separate provider, and no player, role,
coach or numeric starting-probability authority is inferred from a scoreboard.
"""
from datetime import datetime, timezone
from collections import Counter
from typing import Any, Mapping
import re

_HEX = re.compile(r"^[a-f0-9]{64}$")


def _date(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return date.astimezone(timezone.utc) if date.tzinfo is not None else None


def _int(value: Any) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 and str(value) == str(n) else None


def crosscheck_espn_historical_fixtures(
    espn: Mapping[str, Any],
    fotmob: Mapping[str, Any],
    *,
    source_cutoff: str,
) -> dict[str, Any]:
    """No fuzzy matching. Require unique teams, fixture pair, UTC time, FT score.

    A verified bridge means fixture identity only. Its scoreboard/summary still
    does not certify individual player lineup or past predeadline availability.
    """
    result: dict[str, Any] = {
        "contract": "V12_ESPN_DUAL_PROVIDER_FIXTURE_CROSSCHECK_V1",
        "status": "SOURCE_UNAVAILABLE", "verified_fixture_count": 0,
        "matched_missing_fotmob_detail_fixtures": 0,
        "fotmob_matchdetails_retrieval_promoted": False,
        "lineup_or_tactical_role_admitted": False,
        "manager_effect_calibrated": False,
        "historical_predeadline_asof_proven": False,
        "numeric_pstart_effect": "NONE", "matches": [],
    }
    cutoff, es_at, fm_at = _date(source_cutoff), _date(espn.get("checked_at")), _date(fotmob.get("effective_at"))
    if (cutoff is None or es_at is None or fm_at is None or es_at > cutoff or fm_at > cutoff
            or espn.get("source_id") != "espn" or fotmob.get("source_id") != "fotmob"):
        result["reason"] = "SOURCE_ASOF_OR_IDENTITY_NOT_BOUND"
        return result
    groups = fotmob.get("record_groups") or {}
    teams = groups.get("teams") or []
    fixtures = groups.get("fixtures") or []
    if not isinstance(teams, list) or not isinstance(fixtures, list):
        result["reason"] = "SOURCE_SCHEMA_MISMATCH"
        return result
    verified_team_name: dict[int, str] = {}
    team_ids = set()
    for row in teams:
        if not isinstance(row, Mapping) or row.get("identity_status") not in {"EXACT", "VERIFIED_MANUAL"}:
            continue
        tid, oid, name = _int(row.get("source_native_id")), _int(row.get("official_team_id")), row.get("name")
        if tid is None or oid is None or not isinstance(name, str) or not name.strip():
            continue
        if tid in verified_team_name or oid in team_ids or name in verified_team_name.values():
            result["reason"] = "AMBIGUOUS_VERIFIED_TEAM_CROSSWALK"
            return result
        verified_team_name[tid] = name
        team_ids.add(oid)
    fixture_index: dict[tuple[str, str, datetime, str], list[dict[str, Any]]] = {}
    for row in fixtures:
        if not isinstance(row, Mapping) or row.get("identity_status") not in {"EXACT", "VERIFIED_MANUAL"}:
            continue
        fid = _int(row.get("official_fixture_id"))
        status = row.get("status") or {}
        h, a = row.get("home") or {}, row.get("away") or {}
        if not isinstance(status, Mapping) or not isinstance(h, Mapping) or not isinstance(a, Mapping):
            continue
        home, away = verified_team_name.get(_int(h.get("source_native_id"))), verified_team_name.get(_int(a.get("source_native_id")))
        kickoff, score = _date(status.get("utcTime")), str(status.get("scoreStr") or "").replace(" ", "")
        if fid and home and away and kickoff and re.fullmatch(r"\d+-\d+", score) and status.get("finished") is True:
            fixture_index.setdefault((home, away, kickoff, score), []).append({
                "official_fixture_id": fid,
                "fotmob_native_fixture_id": row.get("source_native_id"),
                "gw": row.get("round"),
            })
    espn_data = espn.get("data") or {}
    if not isinstance(espn_data, Mapping):
        result["reason"] = "ESPN_DATA_SCHEMA_MISMATCH"
        return result
    candidates: dict[int, list[dict[str, Any]]] = {}
    for key, snapshot in espn_data.items():
        if not str(key).startswith("history_scoreboard_") or not isinstance(snapshot, Mapping):
            continue
        digest = snapshot.get("sha256")
        day = str(key).removeprefix("history_scoreboard_")
        payload = snapshot.get("json") or {}
        if (snapshot.get("status") != "AVAILABLE" or not isinstance(digest, str)
                or not _HEX.fullmatch(digest) or not isinstance(payload, Mapping)
                or not isinstance(payload.get("events"), list)):
            continue
        for event in payload["events"]:
            if not isinstance(event, Mapping):
                continue
            eid = _int(event.get("id"))
            kickoff = _date(event.get("date"))
            comps = event.get("competitions") or []
            if not eid or not kickoff or kickoff.strftime("%Y%m%d") != day or not isinstance(comps, list) or len(comps) != 1:
                continue
            cmp = comps[0]
            if not isinstance(cmp, Mapping) or _int(cmp.get("id")) != eid:
                continue
            st = (cmp.get("status") or {}).get("type") or {}
            if st.get("completed") is not True or st.get("state") != "post":
                continue
            players = cmp.get("competitors") or []
            home = [c for c in players if isinstance(c, Mapping) and c.get("homeAway") == "home"]
            away = [c for c in players if isinstance(c, Mapping) and c.get("homeAway") == "away"]
            if len(home) != 1 or len(away) != 1:
                continue
            hn = (home[0].get("team") or {}).get("displayName")
            an = (away[0].get("team") or {}).get("displayName")
            hs, a_s = home[0].get("score"), away[0].get("score")
            if not isinstance(hn, str) or not isinstance(an, str) or not str(hs).isdigit() or not str(a_s).isdigit():
                continue
            fk = (hn, an, kickoff, f"{hs}-{a_s}")
            possible = fixture_index.get(fk) or []
            if len(possible) != 1:
                continue
            candidates.setdefault(eid, []).append({
                **possible[0], "espn_native_event_id": eid,
                "espn_scoreboard_sha256": digest,
                "join_evidence": "EXACT_HOME_AWAY_UTC_KICKOFF_FULLTIME_SCORE",
                "identity_join": "VERIFIED_INDEPENDENT_ESPN_TO_V6_OFFICIAL_FIXTURE",
                "role_semantics": "NOT_ESTABLISHED",
                "coach_observation": "NOT_ESTABLISHED",
                "source_effect": "RETROSPECTIVE_FIXTURE_ONLY",
            })
    matches = [rows[0] for eid, rows in candidates.items() if len(rows) == 1]
    duplicates = Counter(row["official_fixture_id"] for row in matches)
    matches = [row for row in matches if duplicates[row["official_fixture_id"]] == 1]
    matches.sort(key=lambda row: row["official_fixture_id"])
    tactics = groups.get("match_tactics") or []
    detailed = {
        _int(row.get("official_fixture_id")) for row in tactics
        if isinstance(row, Mapping) and _HEX.fullmatch(str(row.get("source_snapshot_sha256") or ""))
    }
    result.update({
        "status": "VERIFIED_FIXTURE_ONLY" if matches else "PARTIAL",
        "verified_fixture_count": len(matches),
        "matched_missing_fotmob_detail_fixtures": sum(
            row["official_fixture_id"] not in detailed for row in matches
        ),
        "fotmob_match_details_verified_original_count": len(detailed),
        "matches": matches,
        "reason": None if matches else "NO_EXACT_PROVIDER_CROSSCHECK",
    })
    return result
