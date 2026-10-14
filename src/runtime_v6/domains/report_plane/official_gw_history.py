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
        },
        "players": players,
    }
