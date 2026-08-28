from __future__ import annotations

from src.models import tactical_matchup as tm


def _prediction() -> dict:
    return {
        "players": [
            {
                "element": 10,
                "team_id": 1,
                "priors": {"tactical_role": "advanced creator"},
                "fixtures": [{"event": 2, "opponent": 2, "xpts": 5.0}],
            }
        ]
    }


def test_v4_tactical_layer_is_advisory(monkeypatch):
    artifacts = {
        "team_profiles": {"teams": {"1": {"coach": "A", "base_formation": "4-2-3-1"}, "2": {"coach": "B", "base_formation": "4-4-2", "pressing": "high press"}}},
        "recent_form": {"teams": {"2": [{"gw": 1, "notes": "space behind first press"}]}},
        "player_roles": {},
    }
    monkeypatch.setattr(tm, "_artifact", lambda name: artifacts.get(name, {}))
    source = _prediction()
    before = source["players"][0]["fixtures"][0]["xpts"]
    out = tm.attach_tactical_matchups(source, 2)
    row = out["players"][0]
    assert row["tactical_matchup"]["status"] == "READY"
    assert row["tactical_matchup"]["advisory_only"] is True
    assert row["tactical_matchup"]["xpts_mutated"] is False
    assert row["fixtures"][0]["xpts"] == before
    assert out["governance"]["tactical_matchup"]["never_directly_mutate_xpts"] is True


def test_v4_tactical_layer_fails_soft_without_context(monkeypatch):
    monkeypatch.setattr(tm, "_artifact", lambda name: {})
    out = tm.attach_tactical_matchups(_prediction(), 2)
    assert out["players"][0]["tactical_matchup"]["status"] in {"PARTIAL", "UNAVAILABLE"}
    assert out["players"][0]["tactical_matchup"]["xpts_mutated"] is False
