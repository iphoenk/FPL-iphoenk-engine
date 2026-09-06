from __future__ import annotations

import json

from src.runtime_v6.identity import build_player_identity_map
from src.runtime_v6.source_native import build_source_native_datasets
from src.runtime_v6.verified_bridges import enrich_shared_identity_bridges


def _official() -> dict:
    return {
        "official": {
            "bootstrap": {
                "elements": [
                    {"id": 1, "code": 1001, "web_name": "Alpha", "team": 1},
                    {"id": 2, "code": 1002, "web_name": "Beta", "team": 2},
                ],
                "teams": [
                    {"id": 1, "name": "Alpha FC", "short_name": "ALP"},
                    {"id": 2, "name": "Beta FC", "short_name": "BET"},
                ],
            },
            "fixtures": [
                {
                    "id": 10,
                    "event": 4,
                    "kickoff_time": "2026-09-12T14:00:00Z",
                    "team_h": 1,
                    "team_a": 2,
                }
            ],
        }
    }


def _understat_body() -> str:
    players = [
        {
            "id": "700",
            "player_name": "External Alpha",
            "team_title": "Alpha FC",
            "position": "M",
            "games": "3",
            "time": "250",
            "goals": "2",
            "assists": "1",
            "shots": "8",
            "key_passes": "5",
            "xG": "1.75",
            "xA": "0.84",
            "npxG": "1.75",
            "xGChain": "2.30",
            "xGBuildup": "0.90",
        }
    ]
    fixtures = [
        {
            "id": "900",
            "datetime": "2026-09-12 14:00:00",
            "isResult": False,
            "h": {"id": "81", "title": "Alpha FC"},
            "a": {"id": "82", "title": "Beta FC"},
            "goals": {"h": None, "a": None},
            "xG": {"h": "1.20", "a": "0.85"},
        }
    ]
    return (
        "<script>"
        f"var playersData = JSON.parse('{json.dumps(players)}');"
        f"var datesData = JSON.parse('{json.dumps(fixtures)}');"
        "</script>"
    )


def _results(*, fixture_kickoff: str = "2026-09-12T14:00:00Z") -> dict:
    return {
        "vaastav_fpl": {
            "source_id": "vaastav_fpl",
            "health": "GREEN",
            "effective_state": "LIVE_CHANGED",
            "checked_at": "2026-09-06T16:00:00Z",
            "current_run_action": "FETCHED",
            "data": {
                "players_raw": {
                    "sha256": "players-sha",
                    "body": (
                        "id,code,first_name,second_name,web_name,team,element_type,status,now_cost,total_points,minutes,starts,goals_scored,assists,clean_sheets,expected_goals,expected_assists,expected_goal_involvements\r\n"
                        "1,1001,A,One,Alpha,1,3,a,75,20,250,3,2,1,1,1.75,0.84,2.59\r\n"
                        "2,1002,B,Two,Beta,2,4,a,80,18,245,3,2,0,0,1.40,0.20,1.60\r\n"
                    ),
                },
                "fixtures": {
                    "sha256": "fixtures-sha",
                    "body": (
                        "id,event,kickoff_time,team_h,team_a,team_h_score,team_a_score,finished\r\n"
                        f"10,4,{fixture_kickoff},1,2,,,False\r\n"
                    ),
                },
            },
        },
        "understat": {
            "source_id": "understat",
            "health": "GREEN",
            "effective_state": "LIVE_CHANGED",
            "checked_at": "2026-09-06T16:00:00Z",
            "current_run_action": "FETCHED",
            "data": {"epl_2026": {"sha256": "understat-sha", "body": _understat_body()}},
        },
        "fotmob": {
            "source_id": "fotmob",
            "health": "GREEN",
            "effective_state": "LIVE_CHANGED",
            "checked_at": "2026-09-06T16:00:00Z",
            "current_run_action": "FETCHED",
            "data": {
                "league": {
                    "sha256": "fotmob-sha",
                    "json": {
                        "details": {"id": 47, "name": "Premier League", "selectedSeason": "2026/2027"},
                        "matches": {
                            "allMatches": [
                                {
                                    "id": 123456,
                                    "round": 4,
                                    "status": {"finished": False},
                                    "utcTime": "2026-09-12T14:00:00.000Z",
                                    "home": {"id": 501, "name": "Alpha FC", "score": None},
                                    "away": {"id": 502, "name": "Beta FC", "score": None},
                                }
                            ]
                        },
                    },
                }
            },
        },
    }


def _identity(results: dict) -> dict:
    source_ids = ["official_fpl", "vaastav_fpl", "understat", "fotmob"]
    base = build_player_identity_map(_official(), results, source_ids)
    return enrich_shared_identity_bridges(base, _official(), results)


def test_vaastav_shared_team_and_fixture_ids_require_cross_field_proof():
    results = _results()
    identity = _identity(results)

    team = identity["entity_bridges"]["team"]
    fixture = identity["entity_bridges"]["fixture"]
    assert team["coverage"]["vaastav_fpl"]["identity_health"] == "GREEN"
    assert fixture["coverage"]["vaastav_fpl"]["identity_health"] == "GREEN"
    assert team["mappings"]["1"]["links"]["vaastav_fpl"]["status"] == "EXACT"
    assert fixture["mappings"]["10"]["links"]["vaastav_fpl"]["status"] == "EXACT"
    assert identity["governance"]["name_only_bridge_allowed"] is False


def test_vaastav_fixture_mismatch_fails_closed_instead_of_force_joining():
    results = _results(fixture_kickoff="2026-09-12T15:00:00Z")
    identity = _identity(results)

    fixture = identity["entity_bridges"]["fixture"]
    assert fixture["coverage"]["vaastav_fpl"]["mapped_fixture_count"] == 0
    assert fixture["mappings"]["10"]["links"].get("vaastav_fpl") is None


def test_source_specific_normalizers_publish_typed_source_native_records():
    results = _results()
    identity = _identity(results)
    datasets = build_source_native_datasets(results, identity)

    vaastav = datasets["vaastav_fpl"]
    assert vaastav["semantic_class"] == "NORMALIZED_FACT"
    assert vaastav["normalization_status"] == "NORMALIZED"
    assert vaastav["record_groups"]["players"][0]["official_element_id"] == 1
    assert vaastav["record_groups"]["players"][0]["identity_status"] == "EXACT"
    assert vaastav["record_groups"]["fixtures"][0]["official_fixture_id"] == 10

    understat = datasets["understat"]
    assert understat["semantic_class"] == "UPSTREAM_MODEL_SIGNAL"
    assert understat["model_author"] == "UNDERSTAT"
    assert understat["v6_computation"] == "NONE"
    assert understat["record_groups"]["players"][0]["source_native_id"] == 700
    assert understat["record_groups"]["players"][0]["official_element_id"] is None
    assert understat["record_groups"]["players"][0]["identity_status"] == "UNMAPPED"

    fotmob = datasets["fotmob"]
    assert fotmob["semantic_class"] == "NORMALIZED_FACT"
    assert fotmob["record_groups"]["teams"][0]["official_team_id"] is None
    assert fotmob["record_groups"]["teams"][0]["identity_status"] == "UNMAPPED"
    assert fotmob["governance"]["cross_source_synthesis"] is False


def test_no_name_matching_turns_understat_or_fotmob_green():
    datasets = build_source_native_datasets(_results(), _identity(_results()))

    assert datasets["understat"]["record_groups"]["players"][0]["identity_status"] == "UNMAPPED"
    assert all(row["identity_status"] == "UNMAPPED" for row in datasets["fotmob"]["record_groups"]["teams"])
