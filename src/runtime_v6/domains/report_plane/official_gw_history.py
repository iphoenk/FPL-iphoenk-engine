"""Deterministic, factual Official FPL GW history partitions.

These are retrospective post-settlement Official element-summary facts, never
witnesses of the original *predeadline* model input or natural scheduler runs.
The canonical V6 acquisition remains the sole source of player-match facts.
"""
from __future__ import annotations

from typing import Any, Mapping


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
    historical_gws = {int(x) for x in as_of.get("historical_gws") or []}
    final_gws = {int(x) for x in coverage.get("finalized_historical_gws") or []}
    raw_players = dict(full_history.get("players") or {})
    expected = int(universe.get("expected_players") or 0)
    players: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    if gw in historical_gws:
        for element_id, player in sorted(raw_players.items(), key=lambda kv: int(kv[0])):
            if not isinstance(player, Mapping):
                missing.append(str(element_id))
                continue
            record = (player.get("history") or {}).get(str(gw))
            if not isinstance(record, Mapping):
                missing.append(str(element_id))
                continue
            players[str(element_id)] = {
                "element_id": int(player.get("element_id") or element_id),
                "team": player.get("team"),
                "position": player.get("position"),
                "status": record.get("status"),
                "fixture_count": record.get("fixture_count"),
                "aggregate": dict(record.get("aggregate") or {}),
                "fixtures": list(record.get("fixtures") or []),
            }
    complete = (
        gw in historical_gws
        and gw in final_gws
        and coverage.get("fixture_identity_status") == "PASS"
        and expected > 0
        and len(players) == expected
        and not missing
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
