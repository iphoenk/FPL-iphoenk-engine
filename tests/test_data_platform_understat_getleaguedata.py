from __future__ import annotations

from src.runtime_v6.registry import load_registry, source_map
from src.runtime_v6.source_native import build_source_native_datasets


def test_understat_transport_uses_single_bounded_get_league_snapshot():
    registry = load_registry()
    understat = source_map(registry)["understat"]

    assert registry["policy"]["preserve_last_good_on_failure"] is True
    assert registry["policy"]["source_failures_are_isolated"] is True
    assert understat["acquisition_kind"] == "rest_json"
    assert understat["poll_interval_minutes"] == 60
    assert len(understat["requests"]) == 1

    request = understat["requests"][0]
    assert request["id"] == "players_api"
    assert request["method"] == "GET"
    assert request["url"].endswith("/getLeagueData/EPL/2026")
    assert request["expect"] == "json"
    assert set(request["validation"]["required_json_paths"]) == {"players", "dates", "teams"}


def test_understat_get_league_snapshot_normalizes_player_records_without_name_join():
    payload = {
        "understat": {
            "checked_at": "2026-09-13T09:00:00+00:00",
            "health": "GREEN",
            "effective_state": "LIVE_CHANGED",
            "current_run_action": "FETCHED",
            "data": {
                "players_api": {
                    "json": {
                        "players": [
                            {
                                "id": "20974",
                                "player_name": "Example Player",
                                "team_title": "Example Club",
                                "position": "F",
                                "games": "4",
                                "time": "340",
                                "goals": "3",
                                "assists": "1",
                                "shots": "12",
                                "key_passes": "4",
                                "xG": "2.61",
                                "xA": "0.55",
                                "npxG": "2.61",
                                "xGChain": "3.20",
                                "xGBuildup": "0.44",
                            }
                        ],
                        "dates": [],
                        "teams": [],
                    },
                    "sha256": "understat-test-snapshot",
                }
            },
        }
    }

    datasets = build_source_native_datasets(payload, {"mappings": {}})
    rows = datasets["understat"]["record_groups"]["players"]

    assert len(rows) == 1
    assert rows[0]["source_native_id"] == 20974
    assert rows[0]["xg"] == 2.61
    assert rows[0]["npxg"] == 2.61
    assert rows[0]["identity_status"] == "UNMAPPED"
    assert rows[0]["official_element_id"] is None
