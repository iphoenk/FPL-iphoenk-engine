from __future__ import annotations

from src.services.competitive_load_service import build_competitive_load


def _snapshot() -> dict:
    return {
        "phase": {"scoring_gw": 2},
        "official": {
            "bootstrap": {
                "teams": [{"id": 1, "name": "Alpha"}, {"id": 2, "name": "Beta"}],
                "elements": [
                    {"id": 10, "web_name": "Player A", "team": 1},
                    {"id": 20, "web_name": "Player B", "team": 2},
                ],
            },
            "fixtures": [
                {"id": 101, "event": 2, "team_h": 1, "team_a": 2, "kickoff_time": "2026-08-29T12:00:00Z"},
                {"id": 201, "event": 3, "team_h": 2, "team_a": 1, "kickoff_time": "2026-09-04T18:00:00Z"},
            ],
            "event_live": {
                "elements": {
                    "10": {
                        "stats": {"minutes": 90},
                        "explain": [
                            {
                                "fixture": 101,
                                "stats": [
                                    {"identifier": "minutes", "value": 90, "points": 2},
                                    {"identifier": "goals_scored", "value": 1, "points": 5},
                                ],
                            }
                        ],
                    },
                    "20": {"stats": {"minutes": 0}, "explain": []},
                }
            },
        },
    }


def test_current_gw_load_reuses_official_snapshot_without_start_inference():
    out = build_competitive_load(_snapshot())
    assert out["schema"] == "competitive_load.v1"
    assert out["scoring_gw"] == 2
    assert out["coverage"]["official_fpl_current_gw_load"] == "AVAILABLE"
    assert out["coverage"]["observed_player_fixture_rows"] == 1
    assert out["coverage"]["complete_for_visible_report"] is False

    player = next(row for row in out["players"] if row["element"] == 10)
    match = player["current_gw_matches"][0]
    assert match["minutes"] == 90
    assert match["started"] is None
    assert match["goal_or_assist"]["goals"] == 1
    assert match["travel_context"] == "HOME"
    assert match["rest_hours_to_next_fixture"] == 150.0
    assert out["guardrails"]["official_fpl_acquisition_reused_not_refetched"] is True
    assert out["guardrails"]["minutes_not_used_to_infer_started"] is True


def test_verified_press_evidence_is_ingested_but_does_not_fake_full_coverage():
    press = {
        "players": {
            "10": {
                "verified": True,
                "availability": "available",
                "rotation_hint": "none",
                "source": "official club press conference",
                "verified_at": "2026-08-29T10:00:00Z",
            }
        }
    }
    out = build_competitive_load(_snapshot(), press)
    player = next(row for row in out["players"] if row["element"] == 10)
    assert player["press_conference"]["status"] == "VERIFIED"
    assert player["press_conference"]["availability"] == "available"
    assert out["coverage"]["press_conference_verified_players"] == 1
    assert out["coverage"]["complete_for_visible_report"] is False
    assert out["coverage"]["other_competitions"] == "REQUIRES_EXTERNAL_EVIDENCE"
