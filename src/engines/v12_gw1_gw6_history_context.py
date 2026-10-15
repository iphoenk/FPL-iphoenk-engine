from __future__ import annotations

"""Six-GW evidence bridge, not a second fantasy scorer or source collector.

Official FPL remains authoritative for points and gameweek settlement. Only
pre-verified, source-native IDs can enrich the retrospective six-GW player and
fixture context. A provider FT observation never upgrades provisional FPL
points into FINAL, and season totals are never mislabelled per-match evidence.
"""

from collections import Counter
from datetime import datetime, timezone
import math
import re
from typing import Any, Mapping, Sequence

CONTRACT = "V12_GW1_GW6_RETROSPECTIVE_CONTEXT_V1"
POSITION = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
FIELDS_BY_POSITION = {
    "GK": ("minutes", "saves", "goals_prevented", "clean_sheets", "goals_conceded", "total_points"),
    "DEF": ("minutes", "clean_sheets", "defensive_contribution", "goals_scored", "assists", "total_points"),
    "MID": ("minutes", "goals_scored", "assists", "expected_goals", "expected_assists", "defensive_contribution", "total_points"),
    "FWD": ("minutes", "goals_scored", "assists", "expected_goals", "expected_assists", "total_points"),
}
_SCORES = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")
_VERIFIED = {"VERIFIED_MANUAL", "EXACT", "VERIFIED"}


def _n(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def _id(value: Any) -> int | None:
    number = _n(value)
    if number is None or number <= 0 or not number.is_integer():
        return None
    return int(number)


def _aware(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.astimezone(timezone.utc) if result.tzinfo else None


def _source_is_eligible(source: Mapping[str, Any] | None, as_of: str | None) -> bool:
    if not isinstance(source, Mapping):
        return False
    if source.get("source_health") != "GREEN" or source.get("normalization_status") != "NORMALIZED":
        return False
    observed = _aware(source.get("effective_at"))
    cutoff = _aware(as_of)
    return observed is not None and (cutoff is None or observed <= cutoff)


def _source_gate_reason(source: Mapping[str, Any] | None, as_of: str | None) -> str:
    """Explain admission failure without changing the strict as-of contract."""
    if not isinstance(source, Mapping):
        return "SOURCE_NOT_PRESENT"
    if source.get("source_health") != "GREEN":
        return "SOURCE_NOT_GREEN"
    if source.get("normalization_status") != "NORMALIZED":
        return "SOURCE_NOT_NORMALIZED"
    observed, cutoff = _aware(source.get("effective_at")), _aware(as_of)
    if observed is None:
        return "SOURCE_EFFECTIVE_AT_UNVERIFIED"
    if cutoff is None:
        return "REPORT_CUTOFF_UNVERIFIED"
    if observed > cutoff:
        return "SOURCE_AFTER_REPORT_CUTOFF"
    return "PASS"


def _official_player_rows(
    bootstrap: Mapping[str, Any],
    history: Mapping[str, Any],
    historical_gws: Sequence[int],
) -> tuple[list[dict[str, Any]], int]:
    elements = [p for p in bootstrap.get("elements") or [] if isinstance(p, Mapping)]
    histories = history.get("players") or {}
    rows: list[dict[str, Any]] = []
    available = 0
    for element in elements:
        player_id = _id(element.get("id"))
        if player_id is None:
            continue
        role = POSITION.get(_id(element.get("element_type")), "UNKNOWN")
        player_history = (histories.get(str(player_id)) or {}).get("history") or {}
        gw_rows = []
        sums: dict[str, float] = {}
        for gw in historical_gws:
            slot = player_history.get(str(gw)) or {}
            status = str(slot.get("status") or "UNAVAILABLE").upper()
            metrics = dict(slot.get("aggregate") or {})
            if status != "UNAVAILABLE":
                available += 1
            # Pending fixture statistics may be seen but cannot count as FINAL.
            if status in {"FINAL", "DNP", "BLANK"}:
                for metric in FIELDS_BY_POSITION.get(role, ()):
                    value = _n(metrics.get(metric))
                    if value is not None:
                        sums[metric] = sums.get(metric, 0.0) + value
            gw_rows.append({
                "gw": gw, "official_status": status,
                "fixture_count": slot.get("fixture_count"),
                "metrics": {key: metrics[key] for key in FIELDS_BY_POSITION.get(role, ()) if key in metrics},
            })
        rows.append({
            "official_element_id": player_id,
            "name": element.get("web_name"),
            "team_id": _id(element.get("team")),
            "position": role,
            "historical_gws": gw_rows,
            "finalized_only_totals": {k: round(v, 4) for k, v in sorted(sums.items())},
            "provider_skill_observation": {"status": "UNAVAILABLE"},
            "formation_fit": {"status": "UNAVAILABLE", "reason": "MATCH_LEVEL_ROLE_AND_COACH_EVIDENCE_REQUIRED"},
            "coach_fit": {"status": "UNAVAILABLE", "reason": "NO_CAUSAL_COACH_FIT_CALIBRATION"},
        })
    return rows, available


def _attach_understat(
    player_rows: list[dict[str, Any]],
    understat: Mapping[str, Any] | None,
    as_of: str | None,
) -> dict[str, Any]:
    raw = ((understat or {}).get("record_groups") or {}).get("players") or []
    raw = raw if isinstance(raw, list) else []
    eligible = _source_is_eligible(understat, as_of)
    verified = sum(isinstance(p, Mapping) and _id(p.get("official_element_id")) is not None
                   and p.get("identity_status") in _VERIFIED for p in raw)
    gate = _source_gate_reason(understat, as_of)
    summary = {
        "source": "understat", "status": "AVAILABLE" if eligible else "UNAVAILABLE",
        "source_records": len(raw), "verified_source_identity_rows": verified,
        "eligible_verified_rows": verified if eligible else 0,
        "consumed_rows": 0, "verified_join_count": 0,
        "unmapped_provider_count": 0, "season_aggregate_only": True,
        "source_gate": gate, "source_effective_at": (understat or {}).get("effective_at"),
        "report_cutoff_at": as_of, "rejected_reasons": {},
        "decision_influence": "ADVISORY_ONLY",
    }
    if not eligible:
        summary["rejected_reasons"][gate] = len(raw)
        return summary
    by_id: dict[int, dict[str, Any]] = {}
    for p in raw:
        if not isinstance(p, Mapping):
            continue
        eid = _id(p.get("official_element_id"))
        if eid is None or p.get("identity_status") not in _VERIFIED:
            summary["unmapped_provider_count"] += 1
            reason = "SOURCE_IDENTITY_UNVERIFIED"
            summary["rejected_reasons"][reason] = summary["rejected_reasons"].get(reason, 0) + 1
            continue
        if eid in by_id:
            # Ambiguous identity collisions are not counted as a reliable join.
            by_id[eid]["_identity_conflict"] = True
        else:
            by_id[eid] = dict(p)
    for row in player_rows:
        p = by_id.get(row["official_element_id"])
        if not p or p.get("_identity_conflict"):
            continue
        minutes = _n(p.get("time"))
        xg, xa = _n(p.get("xg")), _n(p.get("xa"))
        observations = {}
        for field in ("games", "time", "goals", "assists", "shots", "key_passes",
                      "xg", "xa", "npxg", "xg_chain", "xg_buildup"):
            numeric = _n(p.get(field))
            if numeric is not None:
                observations[field] = round(numeric, 5)
        if minutes and minutes > 0:
            for field in ("xg", "xa", "shots", "key_passes"):
                value = _n(p.get(field))
                if value is not None:
                    observations[f"{field}_per90"] = round(90 * value / minutes, 5)
            if xg is not None and xa is not None:
                observations["xgi"] = round(xg + xa, 5)
                observations["xgi_per90"] = round(90 * (xg + xa) / minutes, 5)
        source_teams = [team.strip() for team in str(p.get("team_title") or "").split(",") if team.strip()]
        mixed_team_season = len(set(source_teams)) > 1
        row["provider_skill_observation"] = {
            "status": "OBSERVED_VERIFIED_ID",
            "source_team_titles": source_teams,
            "mixed_team_season": mixed_team_season,
            "club_specific_team_fit": "UNAVAILABLE_MIXED_TEAM_SEASON" if mixed_team_season else "NOT_CALIBRATED",
            "source": "UNDERSTAT_2026_27",
            "source_native_id": p.get("source_native_id"),
            "effective_at": understat.get("effective_at"),
            "season_aggregate_only": True,
            "not_independent_of_official_points": True,
            "metrics": observations,
            "interpretation": "PROCESS_PROXY_NOT_AN_ABSOLUTE_SKILL_RATING",
        }
        summary["verified_join_count"] += 1
    summary["consumed_rows"] = summary["verified_join_count"]
    summary["rejected_reasons"]["VERIFIED_BUT_NOT_CONSUMED"] = max(
        0, verified - summary["consumed_rows"]
    )
    if not summary["rejected_reasons"]["VERIFIED_BUT_NOT_CONSUMED"]:
        del summary["rejected_reasons"]["VERIFIED_BUT_NOT_CONSUMED"]
    return summary


def _fotmob_matches(
    fotmob: Mapping[str, Any] | None,
    official_fixtures: Sequence[Mapping[str, Any]],
    historical_gws: Sequence[int],
    as_of: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    groups = (fotmob or {}).get("record_groups") or {}
    raw = groups.get("fixtures") or []
    raw = raw if isinstance(raw, list) else []
    eligible = _source_is_eligible(fotmob, as_of)
    verified = sum(isinstance(f, Mapping) and f.get("identity_status") in _VERIFIED
                   and _id(f.get("official_fixture_id")) is not None for f in raw)
    gate = _source_gate_reason(fotmob, as_of)
    status = {
        "source": "fotmob", "status": "AVAILABLE" if eligible else "UNAVAILABLE",
        "source_records": len(raw), "verified_source_identity_rows": verified,
        "eligible_verified_rows": verified if eligible else 0,
        "historical_scope_rows": 0, "consumed_rows": 0,
        "verified_match_count": 0, "rejected_or_ambiguous": 0,
        "out_of_historical_scope": 0, "source_gate": gate,
        "source_effective_at": (fotmob or {}).get("effective_at"),
        "report_cutoff_at": as_of, "rejected_reasons": {},
        "decision_influence": "ADVISORY_ONLY",
    }
    if not eligible:
        status["rejected_reasons"][gate] = len(raw)
        return [], status
    verified_teams = {}
    for p in groups.get("teams") or []:
        if isinstance(p, Mapping) and p.get("identity_status") in _VERIFIED:
            native_id, official_id = _id(p.get("source_native_id")), _id(p.get("official_team_id"))
            if native_id and official_id:
                verified_teams[native_id] = official_id
    official_by_id = {_id(f.get("id")): f for f in official_fixtures if isinstance(f, Mapping)}
    out = []
    used = set()
    for f in raw:
        if not isinstance(f, Mapping):
            continue
        event = _id(f.get("round"))
        fixture_id = _id(f.get("official_fixture_id"))
        if event not in historical_gws:
            status["out_of_historical_scope"] += 1
            continue
        status["historical_scope_rows"] += 1
        if not fixture_id:
            status["rejected_or_ambiguous"] += 1
            reason = "OFFICIAL_FIXTURE_ID_MISSING"
            status["rejected_reasons"][reason] = status["rejected_reasons"].get(reason, 0) + 1
            continue
        info = f.get("status") or {}
        score = _SCORES.fullmatch(str(info.get("scoreStr") or ""))
        home = verified_teams.get(_id((f.get("home") or {}).get("source_native_id")))
        away = verified_teams.get(_id((f.get("away") or {}).get("source_native_id")))
        official = official_by_id.get(fixture_id)
        if (f.get("identity_status") not in _VERIFIED or fixture_id in used
                or not info.get("finished") or not score or home is None or away is None
                or not official or _id(official.get("event")) != event
                or _id(official.get("team_h")) != home or _id(official.get("team_a")) != away):
            status["rejected_or_ambiguous"] += 1
            reason = ("UNVERIFIED_OR_DUPLICATE_FIXTURE" if f.get("identity_status") not in _VERIFIED or fixture_id in used
                      else "UNFINISHED_OR_INVALID_SCORE" if not info.get("finished") or not score
                      else "TEAM_IDENTITY_UNVERIFIED" if home is None or away is None
                      else "OFFICIAL_FIXTURE_NOT_FOUND" if not official
                      else "OFFICIAL_FIXTURE_GW_OR_TEAM_MISMATCH")
            status["rejected_reasons"][reason] = status["rejected_reasons"].get(reason, 0) + 1
            continue
        used.add(fixture_id)
        gh, ga = int(score.group(1)), int(score.group(2))
        # Official may still be provisional; do not rewrite its settlement.
        out.append({
            "gw": event, "official_fixture_id": fixture_id,
            "home_team_id": home, "away_team_id": away,
            "home_name": (f.get("home") or {}).get("name"),
            "away_name": (f.get("away") or {}).get("name"),
            "home_goals": gh, "away_goals": ga,
            "source": "FOTMOB_VERIFIED_FIXTURE",
            "source_native_id": f.get("source_native_id"),
            "observed_ft": True,
            "official_fpl_final": official.get("finished") is True,
            "fpl_points_settlement": "FINAL" if official.get("finished") is True else "PENDING",
        })
        status["verified_match_count"] += 1
    status["consumed_rows"] = status["verified_match_count"]
    out.sort(key=lambda f: (f["gw"], f["official_fixture_id"]))
    return out, status


def _team_form(matches: Sequence[Mapping[str, Any]], team_id: int) -> dict[str, Any]:
    results = []
    for m in matches:
        is_home = m["home_team_id"] == team_id
        if not is_home and m["away_team_id"] != team_id:
            continue
        own = m["home_goals"] if is_home else m["away_goals"]
        opp = m["away_goals"] if is_home else m["home_goals"]
        results.append({
            "gw": m["gw"], "fixture_id": m["official_fixture_id"],
            "opponent": m["away_name"] if is_home else m["home_name"],
            "opponent_team_id": m["away_team_id"] if is_home else m["home_team_id"],
            "home": is_home, "goals_for": own, "goals_against": opp,
            "result": "W" if own > opp else ("D" if own == opp else "L"),
            "fpl_points_settlement": m["fpl_points_settlement"],
        })
    results.sort(key=lambda x: x["gw"])
    counter = Counter(row["result"] for row in results)
    return {
        "observed_match_count": len(results),
        "wins": counter["W"], "draws": counter["D"], "losses": counter["L"],
        "goals_for": sum(r["goals_for"] for r in results),
        "goals_against": sum(r["goals_against"] for r in results),
        "matches": results,
        "observed_vs_opponents": True,
        "forecast_opponent_fit_inferred": False,
    }


def _verified_tactical_matches(
    fotmob: Mapping[str, Any] | None,
    official_matches: Sequence[Mapping[str, Any]],
    historical_gws: Sequence[int],
    as_of: str,
    official_player_teams: Mapping[int, int] | None = None,
) -> list[dict[str, Any]]:
    """Admit only same-source, verified match details within report cutoff.

    Tactical observations are retrospective provider claims. They do not prove
    that the information was available before an earlier FPL GW deadline.
    """
    if not _source_is_eligible(fotmob, as_of):
        return []
    ids = set((fotmob or {}).get("source_snapshot_ids") or [])
    fixtures = {m["official_fixture_id"]: m for m in official_matches}
    observed: list[dict[str, Any]] = []
    used = set()
    ambiguous = set()
    for row in ((fotmob or {}).get("record_groups") or {}).get("match_tactics") or []:
        if not isinstance(row, Mapping) or row.get("contract") != "V6_FOTMOB_MATCH_TACTICS_V1":
            continue
        native_id = _id(row.get("source_native_fixture_id"))
        fixture_id = _id(row.get("official_fixture_id"))
        match = fixtures.get(fixture_id)
        digest = str(row.get("source_snapshot_sha256") or "")
        if (not re.fullmatch(r"[0-9a-f]{64}", digest) or not match or native_id != _id(match.get("source_native_id"))
                or _id(row.get("gw")) != match.get("gw")
                or match.get("gw") not in historical_gws
                or row.get("fixture_join") != "VERIFIED_NATIVE_TO_OFFICIAL"
                or not digest or digest not in ids):
            continue
        for side in row.get("sides") or []:
            if not isinstance(side, Mapping):
                continue
            team_id = _id(side.get("official_team_id"))
            if team_id not in {match["home_team_id"], match["away_team_id"]}:
                continue
            expected_side = "home" if team_id == match["home_team_id"] else "away"
            if side.get("side") != expected_side:
                continue
            key = (fixture_id, team_id)
            if key in ambiguous:
                continue
            if key in used:
                # Permanently reject this team/fixture after any duplicate, even
                # if a third provider row repeats the same identity.
                ambiguous.add(key)
                observed = [item for item in observed if (item["fixture_id"], item["team_id"]) != key]
                continue
            used.add(key)
            coach = side.get("coach") or {}
            formation = side.get("formation")
            if not isinstance(coach, Mapping) or not isinstance(formation, str):
                continue
            if not str(coach.get("name") or "").strip() or not formation:
                continue
            seen_players = set()
            roles: dict[str, dict[str, Any]] = {}
            for p in side.get("verified_official_starters") or []:
                if not isinstance(p, Mapping) or p.get("identity_status") not in _VERIFIED:
                    continue
                pid = _id(p.get("official_element_id"))
                if (not pid or pid in seen_players or
                        (official_player_teams is not None and official_player_teams.get(pid) != team_id)):
                    continue
                seen_players.add(pid)
                roles[str(pid)] = {
                    "provider_position_id": _id(p.get("provider_position_id")),
                    "observed_pitch_layout": p.get("observed_pitch_layout")
                        if isinstance(p.get("observed_pitch_layout"), Mapping) else None,
                    "role": None, "role_semantics": "UNMAPPED_PROVIDER_POSITION_PROXY",
                }
            def verified_auxiliary(key: str) -> dict[str, dict[str, Any]]:
                joined: dict[str, dict[str, Any]] = {}
                blocked: set[int] = set()
                for item in side.get(key) or []:
                    if not isinstance(item, Mapping) or item.get("identity_status") not in _VERIFIED:
                        continue
                    pid = _id(item.get("official_element_id"))
                    if (not pid or pid in seen_players or pid in blocked or
                            (official_player_teams is not None and official_player_teams.get(pid) != team_id)):
                        continue
                    blocked.add(pid)
                    joined[str(pid)] = {
                        "selection_class": item.get("selection_class"),
                        "source_native_player_id": _id(item.get("source_native_player_id")),
                        "reported_unavailability_type": item.get("reported_unavailability_type")
                            if key == "verified_official_unavailable" else None,
                        "reported_expected_return": item.get("reported_expected_return")
                            if key == "verified_official_unavailable" else None,
                        "forecast_availability_eligible": False,
                        "historical_predeadline_asof_proven": False,
                    }
                return joined
            bench = verified_auxiliary("verified_official_bench")
            unavailable = verified_auxiliary("verified_official_unavailable")
            for pid in set(bench).intersection(unavailable):
                bench.pop(pid, None)
                unavailable.pop(pid, None)
            observed.append({
                "fixture_id": fixture_id, "gw": match["gw"],
                "team_id": team_id, "manager": coach["name"],
                "manager_native_id": coach.get("source_native_id"),
                "formation": formation,
                "verified_player_roles": roles,
                "verified_bench_players": bench,
                "verified_unavailable_players": unavailable,
                "availability_observation_status": "RETROSPECTIVE_PROVIDER_REPORTED_ONLY",
                "verified_starter_count": len(roles),
                # Immutable, occurrence-bound review candidates; no inferred
                # player ownership, role or numeric P(start) admission.
                "unverified_native_starter_ids": sorted({
                    native for raw in side.get("unverified_provider_starter_ids") or []
                    if (native := _id(raw)) is not None
                }),
                "source_snapshot_sha256": digest,
                "source_effective_at": (fotmob or {}).get("effective_at"),
                "source": "V6_FOTMOB_MATCH_DETAILS",
                "predeadline_asof_proven": False,
                "numeric_start_probability_eligible": False,
            })
    return sorted(observed, key=lambda item: (item["gw"], item["fixture_id"], item["team_id"]))



def _verified_context_ledger(
    bootstrap: Mapping[str, Any],
    official_fixtures: Sequence[Mapping[str, Any]],
    full_history: Mapping[str, Any],
    tactical_matches: Sequence[Mapping[str, Any]],
    historical_gws: Sequence[int],
    cutoff: str,
) -> dict[str, Any]:
    """Retrospective, fail-closed player/fixture ledger; never a model feature.

    The original Official player/GW fixture rows are authoritative for starts
    and minutes. FotMob may enrich coach and formation only after verified
    fixture/team/source crosswalk. Post-match evidence is not predeadline truth.
    """
    universe = {
        _id(p.get("id")): p for p in bootstrap.get("elements") or []
        if isinstance(p, Mapping) and _id(p.get("id")) is not None
    }
    fixtures = {
        _id(f.get("id")): f for f in official_fixtures
        if isinstance(f, Mapping) and _id(f.get("id")) is not None
    }
    tactics = {(t["fixture_id"], t["team_id"]): t for t in tactical_matches}
    generated = full_history.get("generated_at")
    source_time_ok = (
        _aware(generated) is not None
        and _aware(cutoff) is not None
        and _aware(generated) <= _aware(cutoff)
    )
    fixture_gate_ok = (full_history.get("coverage_gate") or {}).get("fixture_identity_status") == "PASS"
    player_history = full_history.get("players") or {}
    by_club: dict[str, Counter] = {}
    by_position: dict[str, Counter] = {}
    unresolved: set[int] = set()
    rows: list[dict[str, Any]] = []

    def record(row: dict[str, Any], position: str) -> None:
        rows.append(row)
        club = str(row.get("team_id") or "UNKNOWN")
        by_club.setdefault(club, Counter())[row["admission_status"]] += 1
        by_position.setdefault(position, Counter())[row["admission_status"]] += 1
        if row["admission_status"] != "OBSERVED_VERIFIED":
            unresolved.add(row["element_id"])

    for element_id, element in sorted(universe.items()):
        position = POSITION.get(_id(element.get("element_type")), "UNKNOWN")
        team = _id(element.get("team"))
        history = ((player_history.get(str(element_id)) or {}).get("history") or {})
        for gw in historical_gws:
            slot = history.get(str(gw)) or {}
            status = str(slot.get("status") or "UNAVAILABLE").upper()
            fixture_rows = slot.get("fixtures") or []
            if not isinstance(fixture_rows, list):
                fixture_rows = []
            if not fixture_rows:
                # A DNP or BLANK GW does not identify an individual fixture or
                # prove a benched/unused lineup; never manufacture those facts.
                record({
                    "element_id": element_id, "fixture_id": None, "gw": gw,
                    "team_id": team, "coach_id": None, "formation": None,
                    "observed_role": None, "started": None, "minutes": None,
                    "availability": "UNKNOWN", "source_id": f"OFFICIAL_FPL_ELEMENT_SUMMARY/{element_id}",
                    "observed_at": generated if source_time_ok else None,
                    "finalized_at": None, "confidence": 0.0,
                    "admission_status": "UNAVAILABLE",
                    "rejection_reason": "NO_PLAYER_FIXTURE_ROW_" + status,
                    "official_gw_status": status, "numeric_context_eligible": False,
                    "historical_predeadline_asof_proven": False,
                }, position)
                continue
            seen_fixtures: set[int] = set()
            for raw in fixture_rows:
                if not isinstance(raw, Mapping):
                    continue
                fixture_id = _id(raw.get("fixture"))
                fixture = fixtures.get(fixture_id)
                reason = None
                if fixture_id in seen_fixtures:
                    reason = "DUPLICATE_PLAYER_FIXTURE"
                elif fixture_id is None or fixture is None:
                    reason = "FIXTURE_IDENTITY_NOT_VERIFIED"
                elif _id(raw.get("round") or raw.get("event")) != gw or _id(fixture.get("event")) != gw:
                    reason = "FIXTURE_GW_MISMATCH"
                elif team not in {_id(fixture.get("team_h")), _id(fixture.get("team_a"))}:
                    reason = "PLAYER_CLUB_FIXTURE_MISMATCH"
                elif status != "FINAL" or not fixture_gate_ok or fixture.get("finished") is not True:
                    reason = "OFFICIAL_FINALITY_NOT_VERIFIED"
                elif not source_time_ok:
                    reason = "SOURCE_OBSERVED_AT_UNVERIFIED_OR_LATE"
                if fixture_id is not None:
                    seen_fixtures.add(fixture_id)

                starts = _n(raw.get("starts"))
                minutes = _n(raw.get("minutes"))
                if not reason and (starts not in (0.0, 1.0) or minutes is None or minutes < 0 or minutes > 130
                                   or (starts == 1.0 and minutes == 0)):
                    reason = "OFFICIAL_START_OR_MINUTES_UNVERIFIED"
                tactical = tactics.get((fixture_id, team)) if reason is None else None
                observed_role = None  # FotMob positionId is not a tactical role.
                record({
                    "element_id": element_id, "fixture_id": fixture_id, "gw": gw,
                    "team_id": team, "coach_id": _id((tactical or {}).get("manager_native_id")),
                    "formation": (tactical or {}).get("formation"),
                    "observed_role": observed_role,
                    "provider_position_id": ((tactical or {}).get("verified_player_roles") or {}).get(
                        str(element_id), {}
                    ).get("provider_position_id"),
                    "started": starts == 1.0 if reason is None else None,
                    "minutes": int(minutes) if reason is None else None,
                    "selection_class": (
                        "START" if starts == 1.0 else "CAMEO" if minutes > 0 else "DNP"
                    ) if reason is None else "UNAVAILABLE",
                    "availability": "UNKNOWN", "source_id": f"OFFICIAL_FPL_ELEMENT_SUMMARY/{element_id}",
                    "source_snapshot_sha256": (tactical or {}).get("source_snapshot_sha256"),
                    "observed_at": generated if source_time_ok else None,
                    "finalized_at": None,  # The original archive has no verified finalization instant.
                    "confidence": 1.0 if reason is None else 0.0,
                    "admission_status": "OBSERVED_VERIFIED" if reason is None else "REJECTED",
                    "rejection_reason": reason,
                    "official_gw_status": status, "coach_formation_admission": (
                        "ADVISORY" if tactical else "UNAVAILABLE"
                    ), "numeric_context_eligible": False,
                    "historical_predeadline_asof_proven": False,
                }, position)
    return {
        "contract": "V12_VERIFIED_PLAYER_FIXTURE_CONTEXT_LEDGER_V1",
        "observation_class": "RETROSPECTIVE_POST_DEADLINE_ONLY",
        "rows": rows,
        "row_count": len(rows),
        "admission_counts": dict(Counter(r["admission_status"] for r in rows)),
        "by_club": {k: dict(v) for k, v in sorted(by_club.items())},
        "by_position": {k: dict(v) for k, v in sorted(by_position.items())},
        "unresolved_player_count": len(unresolved),
        "unresolved_player_ids": sorted(unresolved),
        "numeric_pstart_effect": "NONE",
        "historical_predeadline_source_asof": "NOT_ATTESTED",
    }



def _official_fixture_starter_coverage(
    official_fixtures: Sequence[Mapping[str, Any]],
    context_ledger: Mapping[str, Any],
    historical_gws: Sequence[int],
) -> dict[str, Any]:
    """Independently audit all Official starting XIs without FotMob quota.

    This is a retrospective data-completeness measurement ONLY. Do not call
    it coach/formation coverage, infer the tactical role from FPL position,
    or admit post-match observations as predeadline features.
    """
    expected: dict[tuple[int, int], int] = {}
    conflicted_fixtures: set[int] = set()
    seen_fixtures: set[int] = set()
    for raw in official_fixtures:
        if not isinstance(raw, Mapping):
            continue
        fid = _id(raw.get("id"))
        gw = _id(raw.get("event"))
        home, away = _id(raw.get("team_h")), _id(raw.get("team_a"))
        if fid is None or gw not in historical_gws:
            continue
        if fid in seen_fixtures:
            conflicted_fixtures.add(fid)
        seen_fixtures.add(fid)
        if raw.get("finished") is not True or home is None or away is None or home == away:
            continue
        for team in (home, away):
            expected[(fid, team)] = gw

    starters: dict[tuple[int, int], set[int]] = {}
    conflicting_sides: set[tuple[int, int]] = set()
    for row in context_ledger.get("rows") or []:
        if not isinstance(row, Mapping):
            continue
        fid, team, player = _id(row.get("fixture_id")), _id(row.get("team_id")), _id(row.get("element_id"))
        key = (fid, team)
        if key not in expected or player is None:
            continue
        if row.get("started") is not True or row.get("admission_status") != "OBSERVED_VERIFIED":
            continue
        if _n(row.get("minutes")) is None or _n(row.get("minutes")) <= 0:
            conflicting_sides.add(key)
            continue
        players = starters.setdefault(key, set())
        if player in players:
            conflicting_sides.add(key)
        players.add(player)

    clubs: dict[int, dict[str, Any]] = {}
    complete = 0
    observations = []
    for (fid, team), gw in sorted(expected.items()):
        count = len(starters.get((fid, team), set()))
        eligible = fid not in conflicted_fixtures and (fid, team) not in conflicting_sides
        verified = eligible and count == 11
        complete += int(verified)
        entry = clubs.setdefault(team, {"team_id": team, "official_finalized_sides": 0,
                                        "complete_verified_starting_xis": 0,
                                        "missing_or_conflicted_fixture_ids": []})
        entry["official_finalized_sides"] += 1
        entry["complete_verified_starting_xis"] += int(verified)
        if not verified:
            entry["missing_or_conflicted_fixture_ids"].append(fid)
        observations.append({
            "fixture_id": fid, "gw": gw, "team_id": team,
            "verified_official_starter_count": count,
            "status": "VERIFIED_STARTING_XI" if verified else "PARTIAL_OR_UNVERIFIED",
        })

    total = len(expected)
    return {
        "contract": "V12_OFFICIAL_INDEPENDENT_STARTER_COVERAGE_V1",
        "source": "OFFICIAL_FPL_ELEMENT_SUMMARY",
        "historical_gws": list(historical_gws),
        "finalized_official_fixture_count": len({fid for fid, _ in expected}),
        "expected_finalized_team_fixture_sides": total,
        "complete_verified_starting_xis": complete,
        "incomplete_or_unverified_team_fixture_sides": total - complete,
        "coverage_status": "COMPLETE" if total > 0 and complete == total else "PARTIAL",
        "clubs": [clubs[k] for k in sorted(clubs)],
        "observations": observations,
        "fotmob_match_details_count_not_affected": True,
        "coach_formation_status": "NOT_ESTABLISHED_BY_OFFICIAL_SELECTION",
        "historical_predeadline_asof_proven": False,
        "numeric_pstart_effect": "NONE",
    }



def _focus_team_selection_shadow(
    tactical_matches: Sequence[Mapping[str, Any]], team_id: int,
) -> dict[str, Any]:
    """Describe actual selection and identical observed provider slots only.

    Same-slot rivals are not expected starters or inferred true tactical roles.
    """
    by_player: dict[str, dict[str, Any]] = {}
    by_slot: dict[tuple[str, str, int], dict[str, Any]] = {}
    unavailable: list[dict[str, Any]] = []
    bench_count = 0
    for game in tactical_matches:
        if game.get("team_id") != team_id:
            continue
        fixture = game["fixture_id"]
        manager = str(game.get("manager_native_id") or game.get("manager") or "UNKNOWN")
        formation = str(game.get("formation") or "UNKNOWN")
        for raw_id, player in (game.get("verified_player_roles") or {}).items():
            pid = _id(raw_id)
            if pid is None:
                continue
            slot = _id(player.get("provider_position_id"))
            row = by_player.setdefault(str(pid), {
                "element_id": pid, "started_verified_fixtures": [],
                "observed_provider_slot_ids": [], "observed_pitch_layouts": [],
                "reported_bench_fixture_ids": [], "reported_unavailable_fixture_ids": [],
            })
            if fixture not in row["started_verified_fixtures"]:
                row["started_verified_fixtures"].append(fixture)
            if slot is not None:
                if slot not in row["observed_provider_slot_ids"]:
                    row["observed_provider_slot_ids"].append(slot)
                key = (manager, formation, slot)
                entry = by_slot.setdefault(key, {
                    "manager_identity": manager, "formation": formation,
                    "provider_position_id": slot, "verified_element_ids": [],
                    "fixture_ids": [], "semantics": "OBSERVED_SAME_PROVIDER_SLOT_NOT_ROLE",
                })
                if pid not in entry["verified_element_ids"]:
                    entry["verified_element_ids"].append(pid)
                if fixture not in entry["fixture_ids"]:
                    entry["fixture_ids"].append(fixture)
            layout = player.get("observed_pitch_layout")
            if isinstance(layout, Mapping):
                row["observed_pitch_layouts"].append({
                    "fixture_id": fixture, "x": layout.get("x"), "y": layout.get("y"),
                    "coordinate_system": layout.get("coordinate_system"),
                })
        for raw_id in (game.get("verified_bench_players") or {}):
            pid = _id(raw_id)
            if pid is None:
                continue
            bench_count += 1
            row = by_player.setdefault(str(pid), {
                "element_id": pid, "started_verified_fixtures": [],
                "observed_provider_slot_ids": [], "observed_pitch_layouts": [],
                "reported_bench_fixture_ids": [], "reported_unavailable_fixture_ids": [],
            })
            row["reported_bench_fixture_ids"].append(fixture)
        for raw_id, note in (game.get("verified_unavailable_players") or {}).items():
            pid = _id(raw_id)
            if pid is None:
                continue
            row = by_player.setdefault(str(pid), {
                "element_id": pid, "started_verified_fixtures": [],
                "observed_provider_slot_ids": [], "observed_pitch_layouts": [],
                "reported_bench_fixture_ids": [], "reported_unavailable_fixture_ids": [],
            })
            row["reported_unavailable_fixture_ids"].append(fixture)
            unavailable.append({
                "element_id": pid, "fixture_id": fixture, "gw": game.get("gw"),
                "reported_reason": note.get("reported_unavailability_type"),
                "reported_expected_return": note.get("reported_expected_return"),
                "source_snapshot_sha256": game.get("source_snapshot_sha256"),
                "source_effective_at": game.get("source_effective_at"),
                "historical_predeadline_asof_proven": False,
                "forecast_availability_eligible": False,
            })
    contests = [row for _, row in sorted(by_slot.items())
                if len(row["verified_element_ids"]) >= 2]
    return {
        "contract": "V12_RETROSPECTIVE_PROVIDER_SELECTION_SHADOW_V1",
        "observed_team_match_count": sum(m.get("team_id") == team_id for m in tactical_matches),
        "verified_starter_observation_count": sum(len(m.get("verified_player_roles") or {})
            for m in tactical_matches if m.get("team_id") == team_id),
        "verified_provider_bench_observation_count": bench_count,
        "verified_provider_unavailable_observation_count": len(unavailable),
        "observed_same_slot_candidate_groups": contests,
        "per_player": [by_player[k] for k in sorted(by_player, key=int)],
        "reported_unavailability": unavailable,
        "semantic_tactical_roles_verified": False,
        "pregame_availability_asof_verified": False,
        "numeric_pstart_effect": "NONE",
        "source_authority": "V6_VERIFIED_ADVISORY_ONLY",
    }



def _all_clubs_tactical_coverage(
    bootstrap: Mapping[str, Any],
    official_fixtures: Sequence[Mapping[str, Any]],
    tactical_matches: Sequence[Mapping[str, Any]],
    historical_gws: Sequence[int],
) -> dict[str, Any]:
    """Full-league, read-only coach/formation/selection evidence coverage.

    Use original Official team/fixture identity for the denominator. One
    downloaded match gives two team observations, not two full fixtures.
    Neither an observed slot nor matchday injury proves predeadline ability.
    """
    team_names = {
        _id(team.get("id")): str(team.get("name") or team.get("short_name") or "")
        for team in bootstrap.get("teams") or [] if isinstance(team, Mapping)
    }
    teams = {
        _id(player.get("team")) for player in bootstrap.get("elements") or []
        if isinstance(player, Mapping)
    } | {
        _id(fixture.get(key)) for fixture in official_fixtures
        if isinstance(fixture, Mapping) for key in ("team_h", "team_a")
        if _id(fixture.get("event")) in historical_gws
    }
    teams = {team for team in teams if team is not None}
    expected: dict[int, set[int]] = {team: set() for team in teams}
    for fixture in official_fixtures:
        if (not isinstance(fixture, Mapping)
                or _id(fixture.get("event")) not in historical_gws
                or fixture.get("finished") is not True):
            continue
        fid = _id(fixture.get("id"))
        home, away = _id(fixture.get("team_h")), _id(fixture.get("team_a"))
        if fid is None or home == away:
            continue
        for team in (home, away):
            if team in expected:
                expected[team].add(fid)
    by_team: dict[int, list[Mapping[str, Any]]] = {team: [] for team in teams}
    for observation in tactical_matches:
        team = _id(observation.get("team_id"))
        fixture = _id(observation.get("fixture_id"))
        if team in by_team and fixture in expected.get(team, set()):
            by_team[team].append(observation)

    clubs = []
    for team in sorted(teams):
        games = sorted(by_team[team], key=lambda m: (m["gw"], m["fixture_id"]))
        observed_fixtures = {m["fixture_id"] for m in games}
        expected_fixtures = expected[team]
        # A source's observed XI may be incomplete because native player
        # crosswalks are deliberately strict; missing identities stay missing.
        starters = sum(len(m.get("verified_player_roles") or {}) for m in games)
        bench = sum(len(m.get("verified_bench_players") or {}) for m in games)
        unavailable = sum(len(m.get("verified_unavailable_players") or {}) for m in games)
        managers_with_native_id = sum(_id(m.get("manager_native_id")) is not None for m in games)
        slot_shadow = _focus_team_selection_shadow(tactical_matches, team)
        clubs.append({
            "team_id": team,
            "team_name": team_names.get(team) or f"Official FPL team {team}",
            "finalized_official_fixture_count": len(expected_fixtures),
            "verified_tactical_team_fixture_count": len(observed_fixtures),
            "missing_official_fixture_ids": sorted(expected_fixtures - observed_fixtures),
            "verified_native_manager_id_count": managers_with_native_id,
            "verified_mapped_starter_count": starters,
            "unmapped_expected_starter_slots": max(0, 11 * len(observed_fixtures) - starters),
            "unverified_native_starter_observation_count": sum(
                len(m.get("unverified_native_starter_ids") or []) for m in games
            ),
            "unverified_native_starter_ids": sorted({
                native for m in games for native in m.get("unverified_native_starter_ids") or []
            }),
            "unverified_starter_identity_semantics": "REVIEW_ONLY_NO_CANONICAL_ATTRIBUTION",
            "verified_provider_bench_count": bench,
            "verified_provider_unavailable_count": unavailable,
            "same_provider_slot_candidate_group_count": len(
                slot_shadow["observed_same_slot_candidate_groups"]
            ),
            "coach_formation_coverage": (
                "NO_FINALIZED_OFFICIAL_FIXTURE" if not expected_fixtures else
                "RETROSPECTIVE_COMPLETE" if observed_fixtures == expected_fixtures
                else "RETROSPECTIVE_PARTIAL"
            ),
            "timeline": [{
                "gw": m["gw"], "fixture_id": m["fixture_id"],
                "manager": m["manager"], "manager_native_id": m.get("manager_native_id"),
                "formation": m["formation"],
                "source_snapshot_sha256": m["source_snapshot_sha256"],
                "source_effective_at": m.get("source_effective_at"),
            } for m in games],
            "semantic_tactical_roles_verified": False,
            "pregame_availability_asof_verified": False,
        })
    full_count = sum(x["coach_formation_coverage"] == "RETROSPECTIVE_COMPLETE" for x in clubs)
    return {
        "contract": "V12_ALL_CLUBS_TACTICAL_COVERAGE_V1",
        "historical_gws": list(historical_gws),
        "scoped_club_count": len(clubs),
        "expected_finalized_team_fixture_observations": sum(len(x) for x in expected.values()),
        "verified_team_fixture_observations": sum(x["verified_tactical_team_fixture_count"] for x in clubs),
        "complete_coach_formation_club_count": full_count,
        "clubs": clubs,
        "role_semantics": "UNVERIFIED_POSITION_PROXY_ONLY",
        "availability_semantics": "POST_MATCH_PROVIDER_REPORT_NOT_PREDEADLINE",
        "predeadline_asof_proven": False,
        "numeric_pstart_effect": "NONE",
    }


def build_retrospective_context(
    *,
    bootstrap: Mapping[str, Any],
    official_fixtures: Sequence[Mapping[str, Any]],
    full_history: Mapping[str, Any],
    understat: Mapping[str, Any] | None,
    fotmob: Mapping[str, Any] | None,
    report_slot: str | None,
    observation_cutoff_at: str | None = None,
    focus_team_id: int = 6,
    focus_player_ids: Sequence[int] = (154, 40, 165),
    tactical_observation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Enrich GW1..6 without changing canonical projections or FPL finality."""
    if not _aware(report_slot):
        raise ValueError("report_slot must be timezone-aware to prevent future leakage")
    # Report slot identifies the immutable logical occurrence. Sources acquired
    # before that occurrence's verified prefetch completion may be later than
    # its nominal clock slot; admit them only as current-report advisory.
    if observation_cutoff_at is not None and not _aware(observation_cutoff_at):
        raise ValueError("observation_cutoff_at must be timezone-aware")
    source_cutoff = observation_cutoff_at or report_slot
    gw_ids = list(range(1, 7))
    players, available = _official_player_rows(bootstrap, full_history, gw_ids)
    understat_source = _attach_understat(players, understat, source_cutoff)
    matches, match_source = _fotmob_matches(fotmob, official_fixtures, gw_ids, source_cutoff)
    official_player_teams = {row["official_element_id"]: row["team_id"] for row in players}
    tactical_matches = _verified_tactical_matches(
        fotmob, matches, gw_ids, source_cutoff, official_player_teams
    )
    context_ledger = _verified_context_ledger(
        bootstrap, official_fixtures, full_history, tactical_matches, gw_ids, source_cutoff
    )
    by_id = {row["official_element_id"]: row for row in players}
    focused = [by_id[player_id] for player_id in focus_player_ids if player_id in by_id]
    formation = {"status": "UNAVAILABLE", "coach_fit_score": None, "formation_fit_score": None}
    focus_tactics = [row for row in tactical_matches if row["team_id"] == focus_team_id]
    if focus_tactics:
        latest = focus_tactics[-1]
        formation = {
            "status": "MATCH_SPECIFIC_OBSERVED", "fixture_id": latest["fixture_id"],
            "gw": latest["gw"], "manager": latest["manager"],
            "formation": latest["formation"], "supporting_url": None,
            "source": latest["source"],
            "verified_starter_count": latest["verified_starter_count"],
            "observed_player_roles": latest["verified_player_roles"],
            "coach_fit_score": None, "formation_fit_score": None,
            "cross_match_generalization_allowed": False,
        }
    observation = dict(tactical_observation or {})
    if (observation.get("evidence_state") == "OBSERVED"
            and _id(observation.get("fixture_id")) in {x["official_fixture_id"] for x in matches}
            and _id(observation.get("team_id")) == focus_team_id
            and _id(observation.get("gw")) in gw_ids
            and observation.get("reference_url")
            and _aware(observation.get("observed_at"))
            and _aware(observation.get("observed_at")) <= _aware(report_slot)):
        formation = {
            "status": "MATCH_SPECIFIC_OBSERVED",
            "fixture_id": observation["fixture_id"],
            "gw": observation["gw"],
            "manager": observation.get("manager"),
            "formation": observation.get("formation"),
            "supporting_url": observation["reference_url"],
            "observed_player_roles": observation.get("player_roles") or {},
            "coach_fit_score": None,
            "formation_fit_score": None,
            "cross_match_generalization_allowed": False,
        }
    by_position = Counter(row["position"] for row in players)
    return {
        "contract": CONTRACT,
        "planning_target": "GW7",
        "historical_gws": gw_ids,
        "official_status": (full_history.get("coverage_gate") or {}).get("status", "UNAVAILABLE"),
        "official_players_in_universe": len(players),
        "official_gw_slots_present": available,
        "expected_official_gw_slots": len(players) * len(gw_ids),
        "official_points_finalized": (full_history.get("coverage_gate") or {}).get("all_historical_gws_finalized") is True,
        "player_position_counts": dict(by_position),
        "source_health": {"understat": understat_source, "fotmob": match_source},
        "match_tactics_verified_team_observations": len(tactical_matches),
        "all_clubs_tactical_coverage": _all_clubs_tactical_coverage(
            bootstrap, official_fixtures, tactical_matches, gw_ids
        ),
        "verified_context_ledger": context_ledger,
        "official_independent_starter_coverage": _official_fixture_starter_coverage(
            official_fixtures, context_ledger, gw_ids
        ),
        "players": players,
        "focus_players": focused,
        "focus_team": {
            "team_id": focus_team_id,
            "form_gw1_gw6": _team_form(matches, focus_team_id),
            "tactical_observation": formation,
            "verified_tactical_match_history": [row for row in tactical_matches if row["team_id"] == focus_team_id],
            "verified_selection_and_rotation_shadow": _focus_team_selection_shadow(tactical_matches, focus_team_id),
        },
        "effect_on_projection": "NONE_ADVISORY_ONLY",
        "effect_on_fpl_finality": "NONE",
        "identity_matching": "VERIFIED_SOURCE_NATIVE_IDS_ONLY",
        "season_stats_are_not_match_stats": True,
        "coach_fit_requires_multiple_observed_role_and_manager_matches": True,
        "opponent_fit_is_retrospective_not_forward_forecast": True,
        "source_cutoff_at": source_cutoff,
        "report_logical_slot": report_slot,
        "observation_cutoff_mode": (
            "OCCURRENCE_BOUND_PREFETCH_GENERATED_AT"
            if observation_cutoff_at is not None else "LOGICAL_SLOT"
        ),
        "historical_predeadline_source_asof_admission": "NOT_ASSERTED",
    }
