from __future__ import annotations

from src.runtime_v6.player_observation import augment_source_native_datasets


def test_fotmob_nonpositive_native_rows_are_not_player_entities():
    results = {
        "fotmob": {
            "checked_at": "2026-09-13T14:00:00+00:00",
            "health": "GREEN",
            "effective_state": "LIVE_CHANGED",
            "current_run_action": "FETCHED",
            "data": {
                "league": {
                    "sha256": "a" * 64,
                    "json": {
                        "stats": {
                            "players": [
                                {
                                    "title": "Some aggregate table",
                                    "topThree": [
                                        {
                                            "id": 0,
                                            "name": "Manchester City",
                                            "teamId": 9826,
                                            "value": 1,
                                        },
                                        {
                                            "id": -1,
                                            "name": "Another non-player aggregate",
                                            "teamId": 9827,
                                            "value": 2,
                                        },
                                        {
                                            "id": 815006,
                                            "name": "Display name is diagnostic only",
                                            "teamId": 8456,
                                            "value": 3,
                                        },
                                    ],
                                }
                            ]
                        }
                    },
                }
            },
        }
    }

    datasets = augment_source_native_datasets(results, {"mappings": {}}, {})
    players = datasets["fotmob"]["record_groups"]["players"]

    assert [row["source_native_id"] for row in players] == [815006]
    assert players[0]["official_element_id"] is None
    assert players[0]["identity_status"] == "UNMAPPED"
    assert players[0]["join_ready"] is False
    assert datasets["fotmob"]["governance"]["player_identity_is_provider_native_only"] is True
