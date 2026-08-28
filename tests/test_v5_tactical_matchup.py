from __future__ import annotations

from src.v5.intelligence.tactical_matchup import attach_tactical_matchups


def _prediction() -> dict:
    return {
        "players": [
            {
                "element": 10,
                "team_id": 1,
                "role": {"set_piece_share": 0.5, "penalty_share": 1.0},
                "xpts_by_gw": [{"gw": 2, "mean": 5.0, "fixtures": [{"opponent": 2, "mean": 5.0}]}],
            }
        ]
    }


def test_v5_tactical_context_attaches_without_xpts_mutation():
    source = _prediction()
    before = source["players"][0]["xpts_by_gw"][0]["mean"]
    context = {
        "team_profiles": {
            "teams": {
                "1": {"coach": "A", "base_formation": "4-2-3-1"},
                "2": {"coach": "B", "base_formation": "4-4-2", "pressing": "high press", "vulnerabilities": ["central pocket"]},
            }
        },
        "player_roles": {"players": {"10": {"role": "advanced creator", "return_routes": ["central pocket"], "progression_route": "central pocket"}}},
        "recent_form": {"teams": {"2": [{"gw": 1, "notes": "space behind first press"}]}},
    }
    out = attach_tactical_matchups(source, 2, context)
    row = out["players"][0]
    assert row["tactical_matchup"]["status"] == "READY"
    assert row["tactical_matchup"]["highlights"]
    assert row["tactical_matchup"]["xpts_mutated"] is False
    assert row["xpts_by_gw"][0]["mean"] == before


def test_v5_tactical_context_missing_fails_neutral():
    out = attach_tactical_matchups(_prediction(), 2, None)
    row = out["players"][0]
    assert row["tactical_matchup"]["status"] in {"PARTIAL", "UNAVAILABLE"}
    assert row["tactical_matchup"]["highlights"] == []
    assert out["governance"]["tactical_matchup"]["missing_evidence_is_never_fabricated"] is True
