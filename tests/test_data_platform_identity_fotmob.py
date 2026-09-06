from __future__ import annotations

from src.runtime_v6.identity_scope import apply_entity_scope_identity_semantics
from src.runtime_v6.source_native import build_source_native_datasets


def test_official_fpl_is_exact_canonical_identity_not_external_bridge_failure():
    identity = {
        "canonical_authority": "official_fpl",
        "canonical_player_count": 2,
        "coverage": {
            "understat": {
                "identity_health": "RED",
                "deterministic_bridge": False,
                "mapped_player_count": 0,
                "canonical_player_count": 2,
                "join_allowed": False,
            }
        },
        "entity_bridges": {
            "team": {
                "canonical_team_count": 2,
                "coverage": {
                    "understat": {
                        "identity_health": "RED",
                        "deterministic_bridge": False,
                        "mapped_team_count": 0,
                        "canonical_team_count": 2,
                        "join_allowed": False,
                    }
                },
            },
            "fixture": {
                "canonical_fixture_count": 1,
                "coverage": {
                    "understat": {
                        "identity_health": "RED",
                        "deterministic_bridge": False,
                        "mapped_fixture_count": 0,
                        "canonical_fixture_count": 1,
                        "join_allowed": False,
                    }
                },
            },
        },
    }
    scopes = {
        "official_fpl": ["PLAYER", "TEAM", "FIXTURE", "EVENT"],
        "understat": ["PLAYER", "TEAM", "FIXTURE"],
    }

    out = apply_entity_scope_identity_semantics(identity, scopes)
    official = out["source_entity_identity"]["official_fpl"]

    assert official["identity_health"] == "GREEN"
    assert official["player"]["mapped_status"] == "EXACT"
    assert official["team"]["mapped_status"] == "EXACT"
    assert official["fixture"]["mapped_status"] == "EXACT"
    assert official["player"]["coverage_ratio"] == 1.0
    assert out["governance"]["canonical_source_identity_is_exact_by_definition"] is True
    assert out["governance"]["canonical_source_is_excluded_from_external_bridge_health"] is True
    assert out["identity_health"] == "RED"


def test_fotmob_current_league_table_shape_materializes_verified_teams_and_ongoing_fixture():
    identity = {
        "entity_bridges": {
            "team": {
                "mappings": {
                    "1": {
                        "official_fpl_team_id": 1,
                        "links": {
                            "fotmob": {
                                "source_native_id": 501,
                                "status": "VERIFIED_MANUAL",
                            }
                        },
                    },
                    "2": {
                        "official_fpl_team_id": 2,
                        "links": {
                            "fotmob": {
                                "source_native_id": 502,
                                "status": "VERIFIED_MANUAL",
                            }
                        },
                    },
                }
            },
            "fixture": {
                "mappings": {
                    "10": {
                        "official_fpl_fixture_id": 10,
                        "links": {
                            "fotmob": {
                                "source_native_id": 9001,
                                "status": "VERIFIED_MANUAL",
                            }
                        },
                    }
                }
            },
        }
    }
    results = {
        "fotmob": {
            "source_id": "fotmob",
            "health": "GREEN",
            "effective_state": "LIVE_CHANGED",
            "checked_at": "2026-09-07T00:00:00Z",
            "current_run_action": "FETCHED",
            "data": {
                "league": {
                    "sha256": "fotmob-current-shape",
                    "json": {
                        "details": {
                            "id": 47,
                            "name": "Premier League",
                            "selectedSeason": "2026/2027",
                        },
                        "table": [
                            {
                                "data": {
                                    "ongoing": [
                                        {
                                            "id": 9001,
                                            "hId": 501,
                                            "aId": 502,
                                            "hTeam": "Alpha FC",
                                            "aTeam": "Beta FC",
                                            "hScore": 2,
                                            "aScore": 1,
                                            "stage": "4",
                                            "time": "07.09.2026 00:00",
                                            "status": "S",
                                        }
                                    ],
                                    "table": {
                                        "all": [
                                            {
                                                "id": 501,
                                                "name": "Alpha FC",
                                                "shortName": "Alpha",
                                                "played": 4,
                                                "wins": 3,
                                                "draws": 1,
                                                "losses": 0,
                                                "scoresStr": "8-3",
                                                "goalConDiff": 5,
                                                "pts": 10,
                                                "idx": 1,
                                            },
                                            {
                                                "id": 502,
                                                "name": "Beta FC",
                                                "shortName": "Beta",
                                                "played": 4,
                                                "wins": 2,
                                                "draws": 1,
                                                "losses": 1,
                                                "scoresStr": "6-4",
                                                "goalConDiff": 2,
                                                "pts": 7,
                                                "idx": 2,
                                            },
                                        ]
                                    },
                                }
                            }
                        ],
                    },
                }
            },
        }
    }

    fotmob = build_source_native_datasets(results, identity)["fotmob"]
    teams = fotmob["record_groups"]["teams"]
    fixtures = fotmob["record_groups"]["fixtures"]

    assert fotmob["normalization_status"] == "NORMALIZED"
    assert fotmob["record_count"] == 4
    assert len(teams) == 2
    assert teams[0]["official_team_id"] == 1
    assert teams[0]["identity_status"] == "VERIFIED_MANUAL"
    assert teams[0]["table_position"] == 1
    assert teams[1]["official_team_id"] == 2
    assert len(fixtures) == 1
    assert fixtures[0]["official_fixture_id"] == 10
    assert fixtures[0]["identity_status"] == "VERIFIED_MANUAL"
    assert fixtures[0]["home"]["source_native_id"] == 501
    assert fixtures[0]["away"]["source_native_id"] == 502
    assert fotmob["governance"]["data_only"] is True
    assert fotmob["governance"]["cross_source_synthesis"] is False
