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
                "tactical_role": None,
                "role_calibration_status": "NOT_ESTABLISHED",
            })
        observations.append({
            "side": "home" if field == "homeTeam" else "away",
            "official_team_id": team["official_team_id"],
            "coach": coach,
            "formation": formation,
            "provider_starter_count": len(seen),
            "verified_official_starters": mapped,
            "verified_starter_count": len(mapped),
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
