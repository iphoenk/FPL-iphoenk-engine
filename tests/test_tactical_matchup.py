from __future__ import annotations

from src.models import tactical_matchup as tm


def _projection() -> dict:
    return {
        "players": [
            {
                "element": 10,
                "name": "Creator",
                "team_id": 1,
                "position": "MID",
                "xpts_by_gw": [
                    {
                        "gw": 2,
                        "fixtures": [
                            {"opponent": 2, "home": True, "mean": 5.0, "std": 2.0}
                        ],
                    }
                ],
            }
        ]
    }


def test_tactical_matchup_is_advisory_and_never_mutates_xpts(monkeypatch):
    artifacts = {
        "team_profiles": {
            "teams": {
                "1": {"coach": "Coach A", "base_formation": "4-2-3-1", "build_up": "possession"},
                "2": {
                    "coach": "Coach B",
                    "base_formation": "4-4-2",
                    "pressing": "high press",
                    "vulnerabilities": ["central pocket"],
                },
            }
        },
        "recent_form": {"teams": {"2": [{"gw": 1, "notes": "space appeared behind first press"}]}},
        "player_roles": {
            "players": {
                "10": {
                    "role": "advanced creator",
                    "progression_route": "central pocket",
                    "return_routes": ["central pocket"],
                }
            }
        },
    }
    monkeypatch.setattr(tm, "_artifact", lambda name: artifacts.get(name, {}))
    source = _projection()
    before = source["players"][0]["xpts_by_gw"][0]["fixtures"][0]["mean"]

    out = tm.attach_tactical_matchups(source, 2)

    row = out["players"][0]
    assert row["tactical_matchup"]["status"] == "READY"
    assert row["tactical_matchup"]["advisory_only"] is True
    assert row["tactical_matchup"]["xpts_mutated"] is False
    assert row["tactical_matchup"]["highlights"]
    assert row["xpts_by_gw"][0]["fixtures"][0]["mean"] == before
    assert out["governance"]["tactical_matchup"]["never_directly_mutate_xpts"] is True


def test_missing_tactical_evidence_fails_soft(monkeypatch):
    monkeypatch.setattr(tm, "_artifact", lambda name: {})
    out = tm.attach_tactical_matchups(_projection(), 2)
    row = out["players"][0]
    assert row["tactical_matchup"]["status"] == "UNAVAILABLE"
    assert row["tactical_matchup"]["highlights"] == []
    assert out["tactical_matchup_summary"]["unavailable"] == 1
