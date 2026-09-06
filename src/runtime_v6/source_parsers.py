from __future__ import annotations

import csv
import io
from typing import Any, Callable

PARSER_VERSION = "v6-source-native-1"


def _request(source: dict[str, Any], request_id: str) -> dict[str, Any]:
    return dict(((source.get("data") or {}).get(request_id)) or {})


def _json(source: dict[str, Any], request_id: str) -> Any:
    return _request(source, request_id).get("json")


def _csv_rows(source: dict[str, Any], request_id: str) -> list[dict[str, str]]:
    body = _request(source, request_id).get("body")
    if not isinstance(body, str) or not body.strip():
        return []
    try:
        return [dict(row) for row in csv.DictReader(io.StringIO(body))]
    except (csv.Error, TypeError):
        return []


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _snapshot_ids(source: dict[str, Any]) -> list[str]:
    source_id = str(source.get("source_id") or "")
    out: list[str] = []
    for request_id, row in (source.get("data") or {}).items():
        if not isinstance(row, dict):
            continue
        digest = row.get("sha256")
        if digest:
            out.append(f"{source_id}:{request_id}:{digest}")
    return sorted(out)


def _base(source: dict[str, Any], *, semantic_class: str = "NORMALIZED_FACT") -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "canonical": True,
        "semantic_class": semantic_class,
        "source_id": source.get("source_id"),
        "source_name": source.get("source_name"),
        "parser_version": PARSER_VERSION,
        "normalization_version": PARSER_VERSION,
        "generated_at": source.get("checked_at"),
        "effective_at": source.get("checked_at"),
        "freshness_class": source.get("effective_state"),
        "current_run_action": source.get("current_run_action"),
        "source_snapshot_ids": _snapshot_ids(source),
        "players": [],
        "teams": [],
        "fixtures": [],
        "events": [],
        "governance": {
            "data_only": True,
            "source_native_fields_preserved": True,
            "fuzzy_identity_matching": False,
            "cross_source_aggregation": False,
            "decision_authority": "NONE",
            "prediction_authority": "NONE",
            "optimizer_authority": "NONE",
        },
    }
    if semantic_class == "UPSTREAM_MODEL_SIGNAL":
        payload.update(
            {
                "model_author": source.get("model_author") or source.get("source_name") or source.get("source_id"),
                "v6_computation": "NONE",
                "v6_transformation": "SOURCE_NATIVE_FIELD_NORMALIZATION",
            }
        )
    return payload


def _finalize(payload: dict[str, Any], *, status: str = "PARSED") -> dict[str, Any]:
    counts = {
        "players": len(payload.get("players") or []),
        "teams": len(payload.get("teams") or []),
        "fixtures": len(payload.get("fixtures") or []),
        "events": len(payload.get("events") or []),
    }
    payload["record_counts"] = counts
    payload["record_count"] = sum(counts.values())
    payload["parser_status"] = status
    return payload


def parse_fotmob(source: dict[str, Any]) -> dict[str, Any]:
    payload = _base(source)
    raw = _json(source, "league")
    if not isinstance(raw, dict):
        return _finalize(payload, status="NO_USABLE_SOURCE_JSON")

    seen: set[int] = set()
    for block in raw.get("table") or []:
        if not isinstance(block, dict):
            continue
        data = block.get("data") or {}
        table = data.get("table") or {}
        for row in table.get("all") or []:
            if not isinstance(row, dict):
                continue
            native_id = _int(row.get("id"))
            if native_id is None or native_id in seen:
                continue
            seen.add(native_id)
            payload["teams"].append(
                {
                    "source_native_id": native_id,
                    "identity_status": "UNMAPPED",
                    "official_fpl_team_id": None,
                    "canonical_team_id": None,
                    "name": row.get("name"),
                    "short_name": row.get("shortName"),
                    "source_fields": dict(row),
                }
            )
    return _finalize(payload, status="PARSED" if seen else "NO_STABLE_NATIVE_TEAM_RECORDS")


def parse_espn(source: dict[str, Any]) -> dict[str, Any]:
    payload = _base(source)
    raw = _json(source, "scoreboard")
    if not isinstance(raw, dict):
        return _finalize(payload, status="NO_USABLE_SOURCE_JSON")

    teams: dict[int, dict[str, Any]] = {}
    for event in raw.get("events") or []:
        if not isinstance(event, dict):
            continue
        competition = next((row for row in event.get("competitions") or [] if isinstance(row, dict)), {})
        home_id = away_id = None
        for competitor in competition.get("competitors") or []:
            if not isinstance(competitor, dict):
                continue
            team = competitor.get("team") or {}
            native_id = _int(team.get("id") or competitor.get("id"))
            if native_id is None:
                continue
            teams[native_id] = {
                "source_native_id": native_id,
                "identity_status": "UNMAPPED",
                "official_fpl_team_id": None,
                "canonical_team_id": None,
                "name": team.get("displayName") or team.get("name"),
                "short_name": team.get("abbreviation"),
                "source_fields": {
                    "team": dict(team),
                    "homeAway": competitor.get("homeAway"),
                },
            }
            if competitor.get("homeAway") == "home":
                home_id = native_id
            elif competitor.get("homeAway") == "away":
                away_id = native_id
        event_id = event.get("id") or competition.get("id")
        if event_id is not None:
            payload["fixtures"].append(
                {
                    "source_native_id": str(event_id),
                    "identity_status": "UNMAPPED",
                    "official_fpl_fixture_id": None,
                    "canonical_fixture_id": None,
                    "kickoff_time": event.get("date") or competition.get("date"),
                    "home_source_native_team_id": home_id,
                    "away_source_native_team_id": away_id,
                    "source_fields": {
                        "status": competition.get("status") or event.get("status"),
                        "name": event.get("name"),
                        "shortName": event.get("shortName"),
                    },
                }
            )
    payload["teams"] = [teams[key] for key in sorted(teams)]
    return _finalize(payload, status="PARSED" if payload["fixtures"] or payload["teams"] else "NO_STABLE_NATIVE_RECORDS")


def parse_vaastav(source: dict[str, Any]) -> dict[str, Any]:
    payload = _base(source)
    for row in _csv_rows(source, "players_raw"):
        native_id = _int(row.get("id"))
        if native_id is None:
            continue
        payload["players"].append(
            {
                "source_native_id": native_id,
                "identity_status": "UNMAPPED",
                "official_fpl_element_id": None,
                "canonical_player_id": None,
                "provider_code": _int(row.get("code")),
                "first_name": row.get("first_name"),
                "second_name": row.get("second_name"),
                "source_fields": row,
            }
        )

    for row in _csv_rows(source, "fixtures"):
        native_id = _int(row.get("id"))
        if native_id is None:
            continue
        payload["fixtures"].append(
            {
                "source_native_id": native_id,
                "identity_status": "UNMAPPED",
                "official_fpl_fixture_id": None,
                "canonical_fixture_id": None,
                "event": _int(row.get("event")),
                "kickoff_time": row.get("kickoff_time"),
                "home_official_team_id_candidate": _int(row.get("team_h")),
                "away_official_team_id_candidate": _int(row.get("team_a")),
                "finished": _bool(row.get("finished")),
                "started": _bool(row.get("started")),
                "source_fields": row,
            }
        )
    return _finalize(payload, status="PARSED" if payload["players"] or payload["fixtures"] else "NO_STABLE_NATIVE_RECORDS")


def parse_solio(source: dict[str, Any]) -> dict[str, Any]:
    payload = _base(source, semantic_class="UPSTREAM_MODEL_SIGNAL")
    raw = _json(source, "latest")
    if not isinstance(raw, dict):
        return _finalize(payload, status="NO_USABLE_SOURCE_JSON")
    gameweek = raw.get("gameweek")
    for row in raw.get("topProjected") or []:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        team = row.get("team")
        position = row.get("position")
        payload["players"].append(
            {
                "source_native_id": None,
                "source_record_key": f"gw:{gameweek}|{team}|{position}|{name}",
                "identity_status": "UNMAPPED",
                "official_fpl_element_id": None,
                "canonical_player_id": None,
                "source_fields": dict(row),
            }
        )
    payload["source_model_generated_at"] = raw.get("generatedAt")
    payload["source_model_gameweek"] = gameweek
    payload["source_model_deadline"] = raw.get("deadlineIso")
    return _finalize(payload, status="PARSED" if payload["players"] else "NO_SOURCE_MODEL_ROWS")


_PARSERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "fotmob": parse_fotmob,
    "espn": parse_espn,
    "vaastav_fpl": parse_vaastav,
    "solio_analytics": parse_solio,
}


def build_source_native_datasets(results: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for source_id, parser in _PARSERS.items():
        source = results.get(source_id)
        if not isinstance(source, dict):
            continue
        try:
            out[source_id] = parser(source)
        except Exception as exc:
            payload = _base(source, semantic_class=(
                "UPSTREAM_MODEL_SIGNAL" if source.get("semantic_class") == "UPSTREAM_MODEL_SIGNAL" else "NORMALIZED_FACT"
            ))
            payload["parser_error"] = type(exc).__name__
            out[source_id] = _finalize(payload, status="PARSER_FAILED_ISOLATED")
    return out


def supported_parser_sources() -> tuple[str, ...]:
    return tuple(sorted(_PARSERS))
