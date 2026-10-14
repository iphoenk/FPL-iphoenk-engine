from __future__ import annotations

"""Fail-closed FotMob match-level coach/formation/starter evidence.

Observations are ADVISORY ONLY, never a numeric P(start) feature. Fixture and
team identity must already be verified by the governed V6 crosswalk. A native
player ID is never matched to Official FPL using names or shirt numbers.
"""

import re
from typing import Any, Mapping

FORMATION = re.compile(r"^[1-9](?:-[1-9]){2,4}$")


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
        return result if result > 0 and str(value).strip() == str(result) else None
    except (ValueError, TypeError):
        return None


def _coach(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        name = str(value.get("name") or "").strip()
        native_id = _positive_int(value.get("id"))
    elif isinstance(value, str):
        name, native_id = value.strip(), None
    else:
        return None
    return {"name": name, "source_native_id": native_id} if name else None


def _layout(item: Mapping[str, Any]) -> dict[str, Any] | None:
    """Expose provider-observed pitch coordinates, NOT a tactical role label."""
    import math

    raw = item.get("horizontalLayout")
    if not isinstance(raw, Mapping):
        return None
    x, y = raw.get("x"), raw.get("y")
    if (not isinstance(x, (int, float)) or isinstance(x, bool)
            or not isinstance(y, (int, float)) or isinstance(y, bool)
            or not math.isfinite(x) or not math.isfinite(y)
            or not 0.0 <= float(x) <= 1.0 or not 0.0 <= float(y) <= 1.0):
        return None
    return {
        "x": float(x), "y": float(y),
        "coordinate_system": "FOTMOB_HORIZONTAL_LAYOUT",
        "semantic_role": None,
        "role_calibration_status": "NOT_ESTABLISHED",
    }


def _verified_auxiliary(
    items: Any,
    verified_player_ids: Mapping[str, tuple[int, str]],
    *,
    kind: str,
    excluded_native_ids: set[int],
) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(items, list):
        return [], 0
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    conflicts = 0
    for item in items:
        if not isinstance(item, Mapping):
            continue
        native = _positive_int(item.get("id"))
        if native is None:
            continue
        if native in excluded_native_ids or native in seen:
            conflicts += 1
            continue
        seen.add(native)
        link = verified_player_ids.get(str(native))
        if not link or link[1] not in {"EXACT", "VERIFIED_MANUAL"}:
            continue
        obs = {
            "source_native_player_id": native,
            "official_element_id": link[0],
            "identity_status": link[1],
            "selection_class": kind,
            "numeric_pstart_eligible": False,
            "historical_predeadline_asof_proven": False,
        }
        if kind == "PROVIDER_REPORTED_UNAVAILABLE":
            info = item.get("unavailability") or {}
            info = info if isinstance(info, Mapping) else {}
            reason = str(info.get("type") or "").strip().lower()
            obs["reported_unavailability_type"] = (
                reason if reason in {"injury", "suspension"} else "UNSPECIFIED"
            )
            obs["reported_expected_return"] = info.get("expectedReturnDate")
            obs["forecast_availability_eligible"] = False
        out.append(obs)
    return out, conflicts


def normalize_match_details(
    raw: Mapping[str, Any],
    fixture: Mapping[str, Any],
    verified_player_ids: Mapping[str, tuple[int, str]],
) -> dict[str, Any] | None:
    """Admit a match only if native fixture and team identities match V6.

    Report cutoff/source-effective-at checks remain mandatory in the downstream
    occurrence-bound consumer, not in this source-native normalizer.
    """
    if fixture.get("identity_status") not in {"EXACT", "VERIFIED_MANUAL"}:
        return None
    general = raw.get("general") or {}
    content = raw.get("content") or {}
    if not isinstance(general, Mapping) or not isinstance(content, Mapping):
        return None
    native = _positive_int(general.get("matchId"))
    if native is None or native != _positive_int(fixture.get("source_native_id")):
        return None
    if _positive_int(general.get("leagueId")) != 47:
        return None
    home, away = general.get("homeTeam") or {}, general.get("awayTeam") or {}
    if not isinstance(home, Mapping) or not isinstance(away, Mapping):
        return None
    expected = [fixture.get("home") or {}, fixture.get("away") or {}]
    if any(side.get("identity_status") not in {"EXACT", "VERIFIED_MANUAL"}
           or _positive_int(side.get("official_team_id")) is None
           for side in expected):
        return None
    if (_positive_int(home.get("id")) != _positive_int(expected[0].get("source_native_id"))
            or _positive_int(away.get("id")) != _positive_int(expected[1].get("source_native_id"))):
        return None
    lineup = content.get("lineup") or {}
    if not isinstance(lineup, Mapping):
        return None
    observations = []
    for field, team in (("homeTeam", expected[0]), ("awayTeam", expected[1])):
        side = lineup.get(field) or {}
        if not isinstance(side, Mapping) or _positive_int(side.get("id")) != _positive_int(team.get("source_native_id")):
            return None
        formation = str(side.get("formation") or "").strip()
        # Provider field is tactical shape, not an FPL fantasy formation.
        if not FORMATION.fullmatch(formation) or sum(map(int, formation.split("-"))) != 10:
            formation = None
        coach = _coach(side.get("coach"))
        starters = side.get("starters") or []
        if not isinstance(starters, list):
            starters = []
        seen = set()
        mapped = []
        for item in starters:
            if not isinstance(item, Mapping):
                continue
            player_id = _positive_int(item.get("id"))
            if player_id is None or player_id in seen:
                continue
            seen.add(player_id)
            link = verified_player_ids.get(str(player_id))
            if not link or link[1] not in {"EXACT", "VERIFIED_MANUAL"}:
                continue
            mapped.append({
                "source_native_player_id": player_id,
                "official_element_id": link[0],
                "identity_status": link[1],
                "provider_position_id": _positive_int(item.get("positionId")),
                "observed_pitch_layout": _layout(item),
                "tactical_role": None,
                "role_calibration_status": "NOT_ESTABLISHED",
            })
        bench, bench_conflicts = _verified_auxiliary(
            side.get("subs"), verified_player_ids,
            kind="PROVIDER_REPORTED_MATCHDAY_BENCH", excluded_native_ids=seen,
        )
        bench_ids = {int(p["source_native_player_id"]) for p in bench}
        unavailable, unavailable_conflicts = _verified_auxiliary(
            side.get("unavailable"), verified_player_ids,
            kind="PROVIDER_REPORTED_UNAVAILABLE",
            excluded_native_ids=seen | bench_ids,
        )
        observations.append({
            "side": "home" if field == "homeTeam" else "away",
            "official_team_id": team["official_team_id"],
            "coach": coach,
            "formation": formation,
            "provider_starter_count": len(seen),
            "verified_official_starters": mapped,
            "verified_starter_count": len(mapped),
            "verified_official_bench": bench,
            "verified_official_unavailable": unavailable,
            "auxiliary_selection_conflict_count": bench_conflicts + unavailable_conflicts,
            "availability_observation_status": "RETROSPECTIVE_PROVIDER_REPORTED_ONLY",
            "unverified_players_remain_unknown": True,
            "starting_xi_complete": len(seen) == 11,
            "role_is_position_proxy_only": True,
        })
    return {
        "contract": "V6_FOTMOB_MATCH_TACTICS_V1",
        "official_fixture_id": fixture["official_fixture_id"],
        "source_native_fixture_id": native,
        "kickoff_utc": general.get("matchTimeUTCDate"),
        "gw": fixture.get("round"),
        "sides": observations,
        "fixture_join": "VERIFIED_NATIVE_TO_OFFICIAL",
        "source": "FOTMOB_MATCH_DETAILS",
        "decision_influence": "ADVISORY_ONLY",
        "pstart_probability_applied": False,
        "asof_predeadline_proven": False,
    }
