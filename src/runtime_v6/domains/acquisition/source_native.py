from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

from .http_client import utc_now
from .rotowire_normalizer import parse_rotowire_lineups

NORMALIZATION_VERSION = "V6_SOURCE_NATIVE_1"
_JOINABLE = {"EXACT", "VERIFIED_MANUAL"}
_UNDERSTAT_VAR_RE = re.compile(
    r"var\s+(?P<name>playersData|datesData)\s*=\s*JSON\.parse\('(?P<payload>.*?)'\)",
    re.DOTALL,
)


def _request(payload: dict[str, Any], request_id: str) -> dict[str, Any]:
    value = ((payload.get("data") or {}).get(request_id) or {})
    return dict(value) if isinstance(value, dict) else {}


def _csv_rows(payload: dict[str, Any], request_id: str) -> list[dict[str, str]]:
    body = _request(payload, request_id).get("body")
    if not isinstance(body, str) or not body.strip():
        return []
    try:
        return list(csv.DictReader(io.StringIO(body)))
    except (csv.Error, TypeError):
        return []


def _int(value: Any) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _source_snapshot_ids(payload: dict[str, Any]) -> list[str]:
    values: set[str] = set()
    for row in (payload.get("data") or {}).values():
        if not isinstance(row, dict):
            continue
        digest = row.get("sha256")
        if isinstance(digest, str) and digest:
            values.add(digest)
    return sorted(values)


def _reverse_links(identity_map: dict[str, Any], source_id: str, entity: str) -> dict[str, tuple[int, str]]:
    if entity == "player":
        mappings = identity_map.get("mappings") or {}
        official_key = "official_fpl_element_id"
    else:
        bridge = ((identity_map.get("entity_bridges") or {}).get(entity) or {})
        mappings = bridge.get("mappings") or {}
        official_key = f"official_fpl_{entity}_id"

    out: dict[str, tuple[int, str]] = {}
    for raw_mapping in mappings.values():
        if not isinstance(raw_mapping, dict):
            continue
        official_id = _int(raw_mapping.get(official_key))
        link = (raw_mapping.get("links") or {}).get(source_id) or {}
        status = str(link.get("status") or link.get("verification_status") or "")
        native_id = link.get("source_native_id", link.get("external_id"))
        if official_id is None or native_id is None or status not in _JOINABLE:
            continue
        out[str(native_id)] = (official_id, status)
    return out


def _identity_fields(
    reverse: dict[str, tuple[int, str]], native_id: Any, official_field: str
) -> dict[str, Any]:
    match = reverse.get(str(native_id)) if native_id is not None else None
    return {
        official_field: match[0] if match else None,
        "identity_status": match[1] if match else "UNMAPPED",
    }


def _dataset(
    *,
    source_id: str,
    payload: dict[str, Any],
    semantic_class: str,
    authority: str,
    record_groups: dict[str, list[dict[str, Any]]],
    normalization_status: str,
    model_author: str | None = None,
) -> dict[str, Any]:
    record_count = sum(len(rows) for rows in record_groups.values())
    out: dict[str, Any] = {
        "schema_version": 1,
        "normalization_version": NORMALIZATION_VERSION,
        "source_id": source_id,
        "generated_at": utc_now(),
        "effective_at": payload.get("checked_at"),
        "canonical": True,
        "semantic_class": semantic_class,
        "authority": authority,
        "source_snapshot_ids": _source_snapshot_ids(payload),
        "source_health": payload.get("health"),
        "source_effective_state": payload.get("effective_state"),
        "current_run_action": payload.get("current_run_action"),
        "normalization_status": normalization_status,
        "record_count": record_count,
        "record_groups": record_groups,
        "governance": {
            "data_only": True,
            "source_native_records_preserved": True,
            "cross_source_synthesis": False,
            "silent_fuzzy_identity_join": False,
            "decision_authority": "NONE",
            "prediction_authority": "NONE",
            "optimizer_authority": "NONE",
        },
    }
    if semantic_class == "UPSTREAM_MODEL_SIGNAL":
        out["model_author"] = model_author or authority
        out["v6_computation"] = "NONE"
        out["v6_transformation"] = "SOURCE_SPECIFIC_NORMALIZATION"
    return out


def _official_fpl(
    payload: dict[str, Any],
    identity_map: dict[str, Any],
) -> dict[str, Any]:
    del identity_map
    official = payload.get("official") or {}
    bootstrap = official.get("bootstrap")
    fixtures = official.get("fixtures")
    event_live = official.get("event_live")
    bootstrap = bootstrap if isinstance(bootstrap, dict) else {}
    fixtures = fixtures if isinstance(fixtures, list) else []
    event_live = event_live if isinstance(event_live, dict) else {}

    players = {
        int(row.get("id")): row
        for row in bootstrap.get("elements") or []
        if isinstance(row, dict) and _int(row.get("id")) is not None
    }
    fixtures_by_id = {
        int(row.get("id")): row
        for row in fixtures
        if isinstance(row, dict) and _int(row.get("id")) is not None
    }
    position_map = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    rows: list[dict[str, Any]] = []
    skipped = {
        "missing_player": 0,
        "missing_exact_fixture": 0,
        "team_not_in_fixture": 0,
    }

    for gw_text, live in sorted(
        event_live.items(),
        key=lambda item: _int(item[0]) or 0,
    ):
        gw = _int(gw_text)
        if gw is None or not isinstance(live, dict):
            continue
        for element in live.get("elements") or []:
            if not isinstance(element, dict):
                continue
            element_id = _int(element.get("id"))
            player = players.get(element_id or -1)
            if player is None:
                skipped["missing_player"] += 1
                continue
            stats = element.get("stats")
            stats = stats if isinstance(stats, dict) else {}
            fixture_ids = sorted(
                {
                    fixture_id
                    for row in element.get("explain") or []
                    if isinstance(row, dict)
                    and (fixture_id := _int(row.get("fixture"))) is not None
                }
            )
            if len(fixture_ids) != 1:
                skipped["missing_exact_fixture"] += 1
                continue
            fixture_id = fixture_ids[0]
            fixture = fixtures_by_id.get(fixture_id)
            if not isinstance(fixture, dict):
                skipped["missing_exact_fixture"] += 1
                continue

            team_id = _int(player.get("team"))
            team_h = _int(fixture.get("team_h"))
            team_a = _int(fixture.get("team_a"))
            if team_id is None or team_id not in {team_h, team_a}:
                skipped["team_not_in_fixture"] += 1
                continue
            home = team_id == team_h
            opponent = team_a if home else team_h
            if opponent is None:
                skipped["missing_exact_fixture"] += 1
                continue

            rows.append(
                {
                    "source_native_player_id": element_id,
                    "source_native_fixture_id": fixture_id,
                    "source_native_opponent_team_id": opponent,
                    "official_element_id": element_id,
                    "identity_status": "EXACT",
                    "official_fixture_id": fixture_id,
                    "fixture_identity_status": "EXACT",
                    "official_opponent_team_id": opponent,
                    "opponent_identity_status": "EXACT",
                    "gw": gw,
                    "position": position_map.get(
                        _int(player.get("element_type"))
                    ),
                    "team_id": team_id,
                    "minutes": _int(stats.get("minutes")) or 0,
                    "starts": _int(stats.get("starts")) or 0,
                    "starter": (_int(stats.get("starts")) or 0) > 0,
                    "home": home,
                    "kickoff_time": fixture.get("kickoff_time"),
                    "team_h_score": _int(fixture.get("team_h_score")),
                    "team_a_score": _int(fixture.get("team_a_score")),
                    "goals": _int(stats.get("goals_scored")) or 0,
                    "assists": _int(stats.get("assists")) or 0,
                    "xg": _float(stats.get("expected_goals")),
                    "xa": _float(stats.get("expected_assists")),
                    "xgi": _float(
                        stats.get("expected_goal_involvements")
                    ),
                    "xgc": _float(
                        stats.get("expected_goals_conceded")
                    ),
                    "clean_sheets": _int(stats.get("clean_sheets")) or 0,
                    "goals_conceded": _int(stats.get("goals_conceded")) or 0,
                    "saves": _int(stats.get("saves")) or 0,
                    "penalties_saved": _int(stats.get("penalties_saved")) or 0,
                    "penalties_missed": _int(stats.get("penalties_missed")) or 0,
                    "yellow_cards": _int(stats.get("yellow_cards")) or 0,
                    "red_cards": _int(stats.get("red_cards")) or 0,
                    "bonus": _int(stats.get("bonus")) or 0,
                    "bps": _int(stats.get("bps")) or 0,
                    "defensive": _float(
                        stats.get("defensive_contribution")
                    ),
                    "clearances_blocks_interceptions": _float(
                        stats.get("clearances_blocks_interceptions")
                    ),
                    "recoveries": _float(stats.get("recoveries")),
                    "tackles": _float(stats.get("tackles")),
                    "creativity": _float(stats.get("creativity")),
                    "influence": _float(stats.get("influence")),
                    "threat": _float(stats.get("threat")),
                    "fpl_points": _int(stats.get("total_points")) or 0,
                    "source": "official_fpl",
                    "dataset": "event_live",
                    "fixture_resolution_method": "OFFICIAL_EXPLAIN_FIXTURE",
                    "source_checked_at": payload.get("checked_at"),
                }
            )

    history = payload.get("official_history") or {}
    status = (
        "NORMALIZED"
        if rows and history.get("status") == "GREEN"
        else "PARTIAL"
        if rows
        else "EMPTY_OR_SCHEMA_UNAVAILABLE"
    )
    dataset = _dataset(
        source_id="official_fpl",
        payload=payload,
        semantic_class="NORMALIZED_FACT",
        authority="OFFICIAL_FPL",
        record_groups={"player_matches": rows},
        normalization_status=status,
    )
    dataset["history_coverage"] = {
        "finished_gws": list(history.get("finished_gws") or []),
        "available_gws": list(history.get("available_gws") or []),
        "missing_gws": list(history.get("missing_gws") or []),
        "normalized_match_rows": len(rows),
        "skipped_rows": skipped,
        "fixture_resolution": "OFFICIAL_EXPLAIN_FIXTURE_ONLY",
        "aggregate_gw_stats_split_across_dgw": False,
        "ambiguous_fixture_rows_fabricated": False,
    }
    return dataset


def _vaastav(payload: dict[str, Any], identity_map: dict[str, Any]) -> dict[str, Any]:
    player_reverse = _reverse_links(identity_map, "vaastav_fpl", "player")
    team_reverse = _reverse_links(identity_map, "vaastav_fpl", "team")
    fixture_reverse = _reverse_links(identity_map, "vaastav_fpl", "fixture")

    players: list[dict[str, Any]] = []
    for row in _csv_rows(payload, "players_raw"):
        native_id = _int(row.get("id"))
        team_id = _int(row.get("team"))
        players.append(
            {
                "source_native_id": native_id,
                "source_native_code": _int(row.get("code")),
                "first_name": row.get("first_name"),
                "second_name": row.get("second_name"),
                "web_name": row.get("web_name"),
                "source_native_team_id": team_id,
                "element_type": _int(row.get("element_type")),
                "status": row.get("status"),
                "now_cost": _int(row.get("now_cost")),
                "total_points": _int(row.get("total_points")),
                "minutes": _int(row.get("minutes")),
                "starts": _int(row.get("starts")),
                "goals_scored": _int(row.get("goals_scored")),
                "assists": _int(row.get("assists")),
                "clean_sheets": _int(row.get("clean_sheets")),
                "expected_goals": _float(row.get("expected_goals")),
                "expected_assists": _float(row.get("expected_assists")),
                "expected_goal_involvements": _float(row.get("expected_goal_involvements")),
                **_identity_fields(player_reverse, native_id, "official_element_id"),
                "team_identity": _identity_fields(team_reverse, team_id, "official_team_id"),
            }
        )

    fixtures: list[dict[str, Any]] = []
    for row in _csv_rows(payload, "fixtures"):
        native_id = _int(row.get("id"))
        team_h = _int(row.get("team_h"))
        team_a = _int(row.get("team_a"))
        fixtures.append(
            {
                "source_native_id": native_id,
                "event": _int(row.get("event")),
                "kickoff_time": row.get("kickoff_time"),
                "source_native_team_h_id": team_h,
                "source_native_team_a_id": team_a,
                "team_h_score": _int(row.get("team_h_score")),
                "team_a_score": _int(row.get("team_a_score")),
                "finished": str(row.get("finished") or "").lower() == "true",
                **_identity_fields(fixture_reverse, native_id, "official_fixture_id"),
                "home_team_identity": _identity_fields(team_reverse, team_h, "official_team_id"),
                "away_team_identity": _identity_fields(team_reverse, team_a, "official_team_id"),
            }
        )

    player_matches: list[dict[str, Any]] = []
    for row in _csv_rows(payload, "merged_gw"):
        native_player_id = _int(row.get("element"))
        native_fixture_id = _int(row.get("fixture"))
        native_opponent_team_id = _int(row.get("opponent_team"))
        player_identity = _identity_fields(
            player_reverse, native_player_id, "official_element_id"
        )
        fixture_identity = _identity_fields(
            fixture_reverse, native_fixture_id, "official_fixture_id"
        )
        opponent_identity = _identity_fields(
            team_reverse, native_opponent_team_id, "official_opponent_team_id"
        )
        player_matches.append(
            {
                "source_native_player_id": native_player_id,
                "source_native_fixture_id": native_fixture_id,
                "source_native_opponent_team_id": native_opponent_team_id,
                "official_element_id": player_identity["official_element_id"],
                "identity_status": player_identity["identity_status"],
                "official_fixture_id": fixture_identity["official_fixture_id"],
                "fixture_identity_status": fixture_identity["identity_status"],
                "official_opponent_team_id": opponent_identity[
                    "official_opponent_team_id"
                ],
                "opponent_identity_status": opponent_identity["identity_status"],
                "gw": _int(row.get("GW") or row.get("round")),
                "position": row.get("position"),
                "team": row.get("team"),
                "minutes": _int(row.get("minutes")),
                "starts": _int(row.get("starts")),
                "starter": _int(row.get("starts")) > 0,
                "home": str(row.get("was_home") or "").strip().lower()
                == "true",
                "kickoff_time": row.get("kickoff_time"),
                "team_h_score": _int(row.get("team_h_score")),
                "team_a_score": _int(row.get("team_a_score")),
                "goals": _int(row.get("goals_scored")),
                "assists": _int(row.get("assists")),
                "xg": _float(row.get("expected_goals")),
                "xa": _float(row.get("expected_assists")),
                "xgi": _float(row.get("expected_goal_involvements")),
                "xgc": _float(row.get("expected_goals_conceded")),
                "clean_sheets": _int(row.get("clean_sheets")),
                "goals_conceded": _int(row.get("goals_conceded")),
                "saves": _int(row.get("saves")),
                "penalties_saved": _int(row.get("penalties_saved")),
                "penalties_missed": _int(row.get("penalties_missed")),
                "yellow_cards": _int(row.get("yellow_cards")),
                "red_cards": _int(row.get("red_cards")),
                "bonus": _int(row.get("bonus")),
                "bps": _int(row.get("bps")),
                "defensive": _float(row.get("defensive_contribution")),
                "clearances_blocks_interceptions": _float(
                    row.get("clearances_blocks_interceptions")
                ),
                "recoveries": _float(row.get("recoveries")),
                "tackles": _float(row.get("tackles")),
                "creativity": _float(row.get("creativity")),
                "influence": _float(row.get("influence")),
                "threat": _float(row.get("threat")),
                "fpl_points": _int(row.get("total_points")),
                "source": "vaastav_fpl",
                "dataset": "merged_gw",
                "source_checked_at": payload.get("checked_at"),
            }
        )

    status = (
        "NORMALIZED"
        if players or fixtures or player_matches
        else "EMPTY_OR_SCHEMA_UNAVAILABLE"
    )
    return _dataset(
        source_id="vaastav_fpl",
        payload=payload,
        semantic_class="NORMALIZED_FACT",
        authority="VAASTAV_FPL",
        record_groups={
            "players": players,
            "fixtures": fixtures,
            "player_matches": player_matches,
        },
        normalization_status=status,
    )


def _decode_understat_embedded(body: str) -> dict[str, Any]:
    decoded: dict[str, Any] = {}
    for match in _UNDERSTAT_VAR_RE.finditer(body):
        encoded = match.group("payload")
        try:
            text = bytes(encoded, "utf-8").decode("unicode_escape")
            decoded[match.group("name")] = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            continue
    return decoded


def _understat(payload: dict[str, Any], identity_map: dict[str, Any]) -> dict[str, Any]:
    body = _request(payload, "epl_2026").get("body")
    embedded = _decode_understat_embedded(body) if isinstance(body, str) else {}
    player_reverse = _reverse_links(identity_map, "understat", "player")

    api_payload = _request(payload, "players_api").get("json")
    api_players = api_payload.get("players") if isinstance(api_payload, dict) else None
    players_raw = api_players if isinstance(api_players, list) else (embedded.get("playersData") or [])
    players: list[dict[str, Any]] = []
    if isinstance(players_raw, list):
        for row in players_raw:
            if not isinstance(row, dict):
                continue
            native_id = _int(row.get("id"))
            players.append(
                {
                    "source_native_id": native_id,
                    "player_name": row.get("player_name"),
                    "team_title": row.get("team_title"),
                    "position": row.get("position"),
                    "games": _int(row.get("games")),
                    "time": _int(row.get("time")),
                    "goals": _int(row.get("goals")),
                    "assists": _int(row.get("assists")),
                    "shots": _int(row.get("shots")),
                    "key_passes": _int(row.get("key_passes")),
                    "xg": _float(row.get("xG")),
                    "xa": _float(row.get("xA")),
                    "npxg": _float(row.get("npxG")),
                    "xg_chain": _float(row.get("xGChain")),
                    "xg_buildup": _float(row.get("xGBuildup")),
                    **_identity_fields(player_reverse, native_id, "official_element_id"),
                }
            )

    fixtures_raw = embedded.get("datesData") or []
    fixtures: list[dict[str, Any]] = []
    if isinstance(fixtures_raw, list):
        for row in fixtures_raw:
            if not isinstance(row, dict):
                continue
            home = row.get("h") if isinstance(row.get("h"), dict) else {}
            away = row.get("a") if isinstance(row.get("a"), dict) else {}
            goals = row.get("goals") if isinstance(row.get("goals"), dict) else {}
            expected = row.get("xG") if isinstance(row.get("xG"), dict) else {}
            fixtures.append(
                {
                    "source_native_id": _int(row.get("id")),
                    "datetime": row.get("datetime"),
                    "is_result": row.get("isResult"),
                    "home_team": {"source_native_id": _int(home.get("id")), "title": home.get("title")},
                    "away_team": {"source_native_id": _int(away.get("id")), "title": away.get("title")},
                    "goals": {"home": _int(goals.get("h")), "away": _int(goals.get("a"))},
                    "xg": {"home": _float(expected.get("h")), "away": _float(expected.get("a"))},
                    "identity_status": "UNMAPPED",
                    "official_fixture_id": None,
                }
            )

    status = "NORMALIZED" if players or fixtures else "EMPTY_OR_SCHEMA_UNAVAILABLE"
    return _dataset(
        source_id="understat",
        payload=payload,
        semantic_class="UPSTREAM_MODEL_SIGNAL",
        authority="UNDERSTAT",
        model_author="UNDERSTAT",
        record_groups={"players": players, "fixtures": fixtures},
        normalization_status=status,
    )


def _fotmob_table_rows(raw: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    table_sections = raw.get("table")
    if not isinstance(table_sections, list):
        return rows
    for section in table_sections:
        if not isinstance(section, dict):
            continue
        data = section.get("data") if isinstance(section.get("data"), dict) else {}
        direct_table = data.get("table") if isinstance(data.get("table"), dict) else {}
        direct_rows = direct_table.get("all")
        if isinstance(direct_rows, list):
            rows.extend(row for row in direct_rows if isinstance(row, dict))
        nested_tables = data.get("tables") if isinstance(data.get("tables"), list) else []
        for nested in nested_tables:
            nested = nested if isinstance(nested, dict) else {}
            nested_table = nested.get("table") if isinstance(nested.get("table"), dict) else {}
            nested_rows = nested_table.get("all")
            if isinstance(nested_rows, list):
                rows.extend(row for row in nested_rows if isinstance(row, dict))
    return rows


def _fotmob_match_rows(raw: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ("matches", "fixtures"):
        value = raw.get(key)
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, dict))
        elif isinstance(value, dict):
            for child_key in ("allMatches", "matches", "fixtures"):
                child = value.get(child_key)
                if isinstance(child, list):
                    rows.extend(row for row in child if isinstance(row, dict))
    table_sections = raw.get("table")
    if isinstance(table_sections, list):
        for section in table_sections:
            if not isinstance(section, dict):
                continue
            data = section.get("data") if isinstance(section.get("data"), dict) else {}
            ongoing = data.get("ongoing")
            if isinstance(ongoing, list):
                rows.extend(row for row in ongoing if isinstance(row, dict))
    deduped: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    for row in rows:
        native_id = row.get("id")
        if native_id is None:
            anonymous.append(row)
        else:
            deduped[str(native_id)] = row
    return list(deduped.values()) + anonymous


def _fotmob_team_record(row: dict[str, Any], team_reverse: dict[str, tuple[int, str]]) -> dict[str, Any] | None:
    native_id = _int(row.get("id"))
    if native_id is None:
        return None
    return {
        "source_native_id": native_id,
        "name": row.get("name"),
        "short_name": row.get("shortName"),
        "played": _int(row.get("played")),
        "wins": _int(row.get("wins")),
        "draws": _int(row.get("draws")),
        "losses": _int(row.get("losses")),
        "scores": row.get("scoresStr"),
        "goal_difference": _int(row.get("goalConDiff")),
        "points": _int(row.get("pts")),
        "table_position": _int(row.get("idx")),
        **_identity_fields(team_reverse, native_id, "official_team_id"),
    }


def _fotmob_side(row: dict[str, Any], side: str) -> dict[str, Any]:
    value = row.get(side)
    if isinstance(value, dict):
        return {
            "source_native_id": _int(value.get("id")),
            "name": value.get("name"),
            "score": value.get("score"),
        }
    prefix = "h" if side == "home" else "a"
    return {
        "source_native_id": _int(row.get(f"{prefix}Id")),
        "name": row.get(f"{prefix}Team"),
        "score": row.get(f"{prefix}Score"),
    }


def _fotmob(payload: dict[str, Any], identity_map: dict[str, Any]) -> dict[str, Any]:
    raw = _request(payload, "league").get("json")
    raw = raw if isinstance(raw, dict) else {}
    fixture_reverse = _reverse_links(identity_map, "fotmob", "fixture")
    team_reverse = _reverse_links(identity_map, "fotmob", "team")

    teams_by_id: dict[int, dict[str, Any]] = {}
    for row in _fotmob_table_rows(raw):
        team = _fotmob_team_record(row, team_reverse)
        if team is not None:
            teams_by_id[int(team["source_native_id"])] = team

    fixtures: list[dict[str, Any]] = []
    for row in _fotmob_match_rows(raw):
        home = _fotmob_side(row, "home")
        away = _fotmob_side(row, "away")
        for side in (home, away):
            team_id = _int(side.get("source_native_id"))
            if team_id is not None and team_id not in teams_by_id:
                teams_by_id[team_id] = {
                    "source_native_id": team_id,
                    "name": side.get("name"),
                    "short_name": None,
                    "played": None,
                    "wins": None,
                    "draws": None,
                    "losses": None,
                    "scores": None,
                    "goal_difference": None,
                    "points": None,
                    "table_position": None,
                    **_identity_fields(team_reverse, team_id, "official_team_id"),
                }
        native_id = _int(row.get("id"))
        fixtures.append(
            {
                "source_native_id": native_id,
                "round": row.get("round", row.get("stage")),
                "status": row.get("status"),
                "utc_time": row.get("utcTime", row.get("time")),
                "home": home,
                "away": away,
                **_identity_fields(fixture_reverse, native_id, "official_fixture_id"),
            }
        )

    details = raw.get("details") if isinstance(raw.get("details"), dict) else {}
    competition = [
        {
            "source_native_id": details.get("id"),
            "name": details.get("name"),
            "selected_season": details.get("selectedSeason"),
        }
    ] if details else []

    teams = [teams_by_id[key] for key in sorted(teams_by_id)]
    status = "NORMALIZED" if teams or fixtures or competition else "EMPTY_OR_SCHEMA_UNAVAILABLE"
    return _dataset(
        source_id="fotmob",
        payload=payload,
        semantic_class="NORMALIZED_FACT",
        authority="FOTMOB",
        record_groups={"competition": competition, "teams": teams, "fixtures": fixtures},
        normalization_status=status,
    )


def _rotowire(payload: dict[str, Any], identity_map: dict[str, Any]) -> dict[str, Any]:
    body = _request(payload, "lineups").get("body")
    parsed = parse_rotowire_lineups(body if isinstance(body, str) else "")
    player_reverse = _reverse_links(identity_map, "rotowire", "player")
    fixture_reverse = _reverse_links(identity_map, "rotowire", "fixture")

    fixtures: list[dict[str, Any]] = []
    for raw in parsed["fixtures"]:
        row = dict(raw)
        native_id = row.get("source_native_id")
        row.update(_identity_fields(fixture_reverse, native_id, "official_fixture_id"))
        fixtures.append(row)

    def player_rows(group: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for raw in parsed[group]:
            row = dict(raw)
            native_id = row.get("source_native_id")
            row.update(_identity_fields(player_reverse, native_id, "official_element_id"))
            rows.append(row)
        return rows

    lineups = player_rows("lineups")
    availability = player_rows("availability")
    status = "NORMALIZED" if fixtures or lineups or availability else "EMPTY_OR_SCHEMA_UNAVAILABLE"
    dataset = _dataset(
        source_id="rotowire",
        payload=payload,
        semantic_class="UPSTREAM_MODEL_SIGNAL",
        authority="ROTOWIRE",
        model_author="ROTOWIRE",
        record_groups={"fixtures": fixtures, "lineups": lineups, "availability": availability},
        normalization_status=status,
    )
    dataset["authority_ceiling"] = "ADVISORY"
    dataset["record_semantics"] = {
        "confirmed_lineup": "SECONDARY_REPORTED_FACT_REQUIRES_PRIMARY_CROSSCHECK",
        "predicted_lineup": "UPSTREAM_MODEL_SIGNAL",
        "availability": "SECONDARY_AVAILABILITY_SIGNAL_REQUIRES_PRIMARY_CROSSCHECK",
    }
    dataset["governance"].update(
        {
            "requires_primary_crosscheck_for_fact_promotion": True,
            "may_override_verified_facts": False,
            "consensus_vote": False,
        }
    )
    return dataset


def build_source_native_datasets(
    results: dict[str, dict[str, Any]], identity_map: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    parsers = {
        "official_fpl": _official_fpl,
        "vaastav_fpl": _vaastav,
        "understat": _understat,
        "fotmob": _fotmob,
        "rotowire": _rotowire,
    }
    datasets: dict[str, dict[str, Any]] = {}
    for source_id, parser in parsers.items():
        payload = results.get(source_id)
        if not isinstance(payload, dict):
            continue
        datasets[source_id] = parser(payload, identity_map)
    return datasets
