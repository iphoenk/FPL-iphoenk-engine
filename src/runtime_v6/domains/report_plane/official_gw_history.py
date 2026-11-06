"""Deterministic, factual Official FPL GW history partitions.

These are retrospective post-settlement Official element-summary facts, never
witnesses of the original *predeadline* model input or natural scheduler runs.
The canonical V6 acquisition remains the sole source of player-match facts.
"""
from __future__ import annotations

from typing import Any, Mapping


def validated_finalized_historical_gws(full_history: Mapping[str, Any]) -> list[int]:
    """Return positive integer finalized GWs bound to the history range."""
    historical = {
        value for value in (full_history.get("as_of") or {}).get("historical_gws") or []
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    }
    finalized = {
        value for value in (full_history.get("coverage_gate") or {}).get("finalized_historical_gws") or []
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    }
    return sorted(historical & finalized)


def retrospective_gw_partition(
    full_history: Mapping[str, Any], gw: int
) -> dict[str, Any]:
    """Expose one GW's raw Official player-fixture rows without duplicating context.

    BLANK/DNP are source-derived states, not missing-record replacements.
    Any missing player history or unfinished event prevents PASS.
    """
    gw = int(gw)
    as_of = dict(full_history.get("as_of") or {})
    coverage = dict(full_history.get("coverage_gate") or {})
    universe = dict(full_history.get("universe") or {})
    historical_gws = {
        x for x in as_of.get("historical_gws") or []
        if isinstance(x, int) and not isinstance(x, bool) and x > 0
    }
    final_gws = set(validated_finalized_historical_gws(full_history))
    raw_players = dict(full_history.get("players") or {})
    expected = int(universe.get("expected_players") or 0)
    players: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    universe_anomalies: list[dict[str, Any]] = []
    fixture_anomalies: list[dict[str, Any]] = []
    raw_keys: set[int] = set()
    for raw_key in raw_players:
        try:
            parsed_key = int(raw_key)
        except (TypeError, ValueError):
            universe_anomalies.append({"player_key": str(raw_key), "reason": "INVALID_PLAYER_KEY"})
            continue
        if parsed_key <= 0 or str(parsed_key) != str(raw_key):
            universe_anomalies.append({"player_key": str(raw_key), "reason": "INVALID_PLAYER_KEY"})
            continue
        raw_keys.add(parsed_key)
    declared_ids = universe.get("element_ids")
    if declared_ids is not None:
        valid_declared = (
            isinstance(declared_ids, list)
            and all(isinstance(x, int) and not isinstance(x, bool) and x > 0 for x in declared_ids)
            and len(set(declared_ids)) == len(declared_ids)
        )
        expected_ids = set(declared_ids) if valid_declared else set()
        if not valid_declared:
            universe_anomalies.append({"reason": "INVALID_DECLARED_ELEMENT_IDS"})
        elif expected_ids != raw_keys:
            universe_anomalies.append({
                "reason": "BOOTSTRAP_PLAYER_ID_SET_MISMATCH",
                "missing_ids": sorted(expected_ids - raw_keys),
                "foreign_ids": sorted(raw_keys - expected_ids),
            })
        universe_identity_status = "PASS" if not universe_anomalies else "PARTIAL"
    else:
        expected_ids = raw_keys
        universe_identity_status = "PASS_INFERRED_LEGACY"
    if gw in historical_gws:
        for element_id, player in sorted(raw_players.items(), key=lambda kv: int(kv[0])):
            if not isinstance(player, Mapping):
                missing.append(str(element_id))
                continue
            try:
                payload_element_id = int(player.get("element_id"))
            except (TypeError, ValueError):
                payload_element_id = None
            if payload_element_id != int(element_id):
                universe_anomalies.append({
                    "player_key": str(element_id),
                    "element_id": player.get("element_id"),
                    "reason": "PLAYER_KEY_ELEMENT_ID_MISMATCH",
                })
            record = (player.get("history") or {}).get(str(gw))
            if not isinstance(record, Mapping):
                missing.append(str(element_id))
                continue
            fixtures = list(record.get("fixtures") or [])
            seen_fixture_ids: set[int] = set()
            for index, fixture in enumerate(fixtures):
                if not isinstance(fixture, Mapping):
                    fixture_anomalies.append({"element_id": int(element_id), "index": index, "reason": "MALFORMED_FIXTURE_ROW"})
                    continue
                fixture_id = fixture.get("fixture")
                fixture_gw = fixture.get("round") if fixture.get("round") is not None else fixture.get("event")
                if not isinstance(fixture_id, int) or isinstance(fixture_id, bool) or fixture_id <= 0:
                    fixture_anomalies.append({"element_id": int(element_id), "index": index, "reason": "INVALID_FIXTURE_ID"})
                elif fixture_id in seen_fixture_ids:
                    fixture_anomalies.append({"element_id": int(element_id), "fixture_id": fixture_id, "reason": "DUPLICATE_PLAYER_FIXTURE_ID"})
                else:
                    seen_fixture_ids.add(fixture_id)
                if fixture_gw != gw:
                    fixture_anomalies.append({"element_id": int(element_id), "fixture_id": fixture_id, "reason": "FIXTURE_GW_MISMATCH"})
            players[str(element_id)] = {
                "element_id": int(player.get("element_id") or element_id),
                "team": player.get("team"),
                "position": player.get("position"),
                "status": record.get("status"),
                "fixture_count": record.get("fixture_count"),
                "aggregate": dict(record.get("aggregate") or {}),
                "fixtures": fixtures,
            }
    if universe_anomalies:
        universe_identity_status = "PARTIAL"
    fixture_row_identity_status = "PASS" if not fixture_anomalies else "PARTIAL"
    complete = (
        gw in historical_gws
        and gw in final_gws
        and coverage.get("fixture_identity_status") == "PASS"
        and expected > 0
        and len(expected_ids) == expected
        and len(players) == expected
        and not missing
        and universe_identity_status in {"PASS", "PASS_INFERRED_LEGACY"}
        and fixture_row_identity_status == "PASS"
        and all(row["status"] in {"FINAL", "DNP", "BLANK"} for row in players.values())
    )
    return {
        "contract": "OFFICIAL_FPL_RETROSPECTIVE_GW_PARTITION_V1",
        "authority": "OFFICIAL_FPL",
        "gw": gw,
        "observation_class": "RETROSPECTIVE_POST_DEADLINE_FACTS",
        "historical_predeadline_source_asof": "NOT_ATTESTED",
        "natural_scheduler_proof": "NOT_APPLICABLE",
        "source": "V6_FULL_SEASON_OFFICIAL_ELEMENT_SUMMARY",
        "original_full_history_generated_at": full_history.get("generated_at"),
        "original_full_history_as_of": as_of,
        "coverage": {
            "status": "PASS" if complete else "PARTIAL",
            "expected_players": expected,
            "players_with_gw_record": len(players),
            "missing_player_ids": missing,
            "universe_identity_status": universe_identity_status,
            "universe_identity_anomalies": universe_anomalies,
            "fixture_row_identity_status": fixture_row_identity_status,
            "fixture_row_identity_anomalies": fixture_anomalies,
            "gw_official_finalized": gw in final_gws,
            "fixture_identity_status": coverage.get("fixture_identity_status"),
            "status_counts": {
                status: sum(row["status"] == status for row in players.values())
                for status in ("FINAL", "DNP", "BLANK")
            },
            "observed_fixture_rows": sum(len(row["fixtures"]) for row in players.values()),
        },
        "players": players,
    }


def _parse_utc(value: Any):
    from datetime import datetime, timezone

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def official_event_context(
    bootstrap_event: Mapping[str, Any] | None,
    fixtures: list[Any] | None,
    *,
    as_of: str,
) -> dict[str, Any]:
    """Facts-only gameweek context from the official event and fixture rows.

    Finality is per official flags, never inferred from kickoff times: a finished event that
    is not ``data_checked`` is PENDING_CHECK. ``fixtures=None`` means the fetch failed and is
    UNAVAILABLE; ``[]`` is a valid empty (blank) gameweek. Fixtures stay per fixture id, so a
    double gameweek yields two entries for the team. Rows that are malformed or belong to another
    event are rejected individually and never poison the rest.
    """
    event = dict(bootstrap_event or {})
    gw = event.get("id")
    as_of_utc = _parse_utc(as_of)
    deadline = _parse_utc(event.get("deadline_time"))
    if as_of_utc is None or gw is None:
        observation = "UNKNOWN"
    elif deadline is None:
        observation = "UNKNOWN"
    else:
        observation = "PROSPECTIVE_BEFORE_DEADLINE" if as_of_utc < deadline else "RETROSPECTIVE_POST_DEADLINE_FACTS"
    base = {
        "contract": "OFFICIAL_FPL_EVENT_CONTEXT_V1",
        "authority": "OFFICIAL_FPL",
        "gw": gw,
        "as_of": as_of,
        "observation_class": observation,
        "checked": bool(event.get("data_checked")) if event else None,
    }
    if fixtures is None:
        return {**base, "fixture_ids": [], "status": "UNAVAILABLE", "postponed_fixture_ids": [],
                "rejected_rows": [], "team_fixture_counts": {}, "double_gameweek_team_ids": [],
                "coverage": {"status": "FETCH_FAILED", "fixtures": None, "finished": None}}
    accepted: list[dict[str, Any]] = []
    postponed: list[int] = []
    rejected: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, row in enumerate(fixtures):
        if not isinstance(row, Mapping) or not isinstance(row.get("id"), int) or isinstance(row.get("id"), bool):
            rejected.append({"index": index, "reason": "MALFORMED_ROW"})
            continue
        fixture_id = row["id"]
        if row.get("event") is None and row.get("kickoff_time") is None:
            postponed.append(fixture_id)
            continue
        if row.get("event") != gw:
            rejected.append({"index": index, "fixture_id": fixture_id, "reason": "WRONG_EVENT"})
            continue
        if fixture_id in seen:
            rejected.append({"index": index, "fixture_id": fixture_id, "reason": "DUPLICATE_FIXTURE_ID"})
            continue
        seen.add(fixture_id)
        accepted.append(dict(row))
    accepted.sort(key=lambda r: r["id"])
    finished = [r for r in accepted if r.get("finished") is True]
    team_counts: dict[str, int] = {}
    for row in accepted:
        for side in ("team_h", "team_a"):
            if isinstance(row.get(side), int):
                team_counts[str(row[side])] = team_counts.get(str(row[side]), 0) + 1
    event_finished = bool(event.get("finished"))
    checked = bool(event.get("data_checked"))
    if not accepted:
        status = "BLANK_GAMEWEEK"
    elif event_finished and checked and len(finished) == len(accepted):
        status = "FINAL"
    elif event_finished and not checked:
        status = "PENDING_CHECK"
    elif finished and len(finished) < len(accepted):
        status = "PARTIAL_FINALITY"
    elif finished:
        status = "PENDING_CHECK"
    else:
        status = "NOT_STARTED"
    return {
        **base,
        "fixture_ids": [r["id"] for r in accepted],
        "status": status,
        "postponed_fixture_ids": sorted(postponed),
        "rejected_rows": rejected,
        "team_fixture_counts": team_counts,
        "double_gameweek_team_ids": sorted(int(t) for t, c in team_counts.items() if c > 1),
        "coverage": {"status": "PARTIAL" if rejected else "COMPLETE", "fixtures": len(accepted), "finished": len(finished)},
    }
