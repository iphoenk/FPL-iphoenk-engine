from src.engines import official_expansion as oe


def test_league_snapshot_tracks_rank_gap_and_delta(monkeypatch):
    monkeypatch.setattr(oe, "TEAM_ID", 42)
    payload = {
        "league": {"name": "Test League"},
        "standings": {"results": [
            {"entry": 1, "rank": 1, "last_rank": 1, "total": 110, "entry_name": "Above"},
            {"entry": 42, "rank": 2, "last_rank": 3, "total": 100, "entry_name": "Mine"},
            {"entry": 3, "rank": 3, "last_rank": 2, "total": 95, "entry_name": "Below"},
        ]},
    }
    previous = {"current": {"total_points": 98, "points_behind_above": 12}}
    snap = oe._league_snapshot("classic", "99", payload, previous, 7)
    assert snap["status"] == "TRACKING"
    assert snap["rank"] == 2
    assert snap["rank_delta"] == 1
    assert snap["points_behind_above"] == 10
    assert snap["points_ahead_below"] == 5
    assert snap["points_delta_since_last_refresh"] == 2
    assert snap["gap_to_above_delta"] == -2
    assert snap["current_gw_points"] == 7


def test_tracking_requires_explicit_config(monkeypatch):
    monkeypatch.setattr(oe, "_configured_league_ids", lambda kind: [])
    monkeypatch.setattr(oe, "_mini_league_config", lambda: {"model_id": "mini_league_tracking_v1"})
    out = oe._mini_league_tracking({"classic": {}, "h2h": {}}, {}, {})
    assert out["status"] == "CONFIG_REQUIRED"
    assert out["leagues"] == {}
    assert "no rival state is inferred" in out["note"]


def test_tracking_history_is_bounded(monkeypatch):
    monkeypatch.setattr(oe, "TEAM_ID", 42)
    monkeypatch.setattr(oe, "_configured_league_ids", lambda kind: ["99"] if kind == "classic" else [])
    monkeypatch.setattr(oe, "_mini_league_config", lambda: {
        "model_id": "mini_league_tracking_v1",
        "history_limit": 2,
        "governance": {"full_rival_picks_not_collected": True},
    })
    payload = {
        "league": {"name": "Test League"},
        "standings": {"results": [
            {"entry": 42, "rank": 1, "last_rank": 1, "total": 100, "entry_name": "Mine"},
            {"entry": 3, "rank": 2, "last_rank": 2, "total": 90, "entry_name": "Below"},
        ]},
    }
    previous = {"mini_league_tracking": {"leagues": {
        "classic:99": {"current": {"total_points": 99}, "history": [{"rank": 3}, {"rank": 2}]}
    }}}
    out = oe._mini_league_tracking({"classic": {"99": payload}, "h2h": {}}, previous, {"entry": {"summary_event_points": 7}})
    assert out["status"] == "TRACKING"
    assert out["tracking_count"] == 1
    history = out["leagues"]["classic:99"]["history"]
    assert len(history) == 2
    assert history[-1]["rank"] == 1
