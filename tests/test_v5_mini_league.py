from src.v5.mini_league import build_tracking, collection_plan, discovered_private_league_ids


def _entry():
    return {
        "id": 42,
        "summary_event_points": 67,
        "leagues": {
            "classic": [
                {"id": 100, "name": "Private A", "entry_can_leave": True},
                {"id": 200, "name": "Overall", "entry_can_leave": False, "entry_can_admin": False, "entry_can_invite": False},
            ],
            "h2h": [{"id": 300, "name": "Private H2H", "entry_can_invite": True}],
        },
    }


def _standings():
    return {
        "league": {"name": "Private A"},
        "standings": {
            "results": [
                {"entry": 7, "entry_name": "Leader", "player_name": "A", "rank": 1, "last_rank": 1, "total": 130},
                {"entry": 42, "entry_name": "User", "player_name": "U", "rank": 2, "last_rank": 3, "total": 125},
                {"entry": 8, "entry_name": "Chaser", "player_name": "B", "rank": 3, "last_rank": 2, "total": 122},
            ]
        },
    }


def test_private_autodiscovery_excludes_system_leagues():
    entry = _entry()
    assert discovered_private_league_ids("classic", entry) == ["100"]
    assert discovered_private_league_ids("h2h", entry) == ["300"]
    plan = collection_plan(entry)
    assert plan["configured"]["classic"] == ["100"]
    assert plan["configured"]["h2h"] == ["300"]
    assert {row["route"] for row in plan["requests"]} == {"classic_league_standings", "h2h_league_standings"}


def test_tracking_computes_rank_neighbor_gaps_and_gw_points(monkeypatch):
    monkeypatch.delenv("FPL_CLASSIC_LEAGUE_IDS", raising=False)
    monkeypatch.delenv("FPL_H2H_LEAGUE_IDS", raising=False)
    entry = _entry()
    collection = {
        "generated_at": "2026-08-28T10:00:00+00:00",
        "plan": collection_plan(entry),
        "leagues": {"classic": {"100": _standings()}, "h2h": {}},
        "health": {},
    }
    tracking = build_tracking(team_id=42, entry=entry, collection=collection, previous_state={})
    current = tracking["leagues"]["classic:100"]["current"]
    assert tracking["status"] == "TRACKING"
    assert current["rank"] == 2
    assert current["rank_delta"] == 1
    assert current["points_behind_above"] == 5
    assert current["points_ahead_below"] == 3
    assert current["current_gw_points"] == 67
    assert tracking["governance"]["full_rival_picks_collected"] is False


def test_high_frequency_unchanged_refresh_does_not_erase_history(monkeypatch):
    monkeypatch.delenv("FPL_CLASSIC_LEAGUE_IDS", raising=False)
    monkeypatch.delenv("FPL_H2H_LEAGUE_IDS", raising=False)
    entry = _entry()
    plan = collection_plan(entry)
    first = build_tracking(
        team_id=42,
        entry=entry,
        collection={
            "generated_at": "2026-08-28T10:00:00+00:00",
            "plan": plan,
            "leagues": {"classic": {"100": _standings()}, "h2h": {}},
        },
        previous_state={},
    )
    second = build_tracking(
        team_id=42,
        entry=entry,
        collection={
            "generated_at": "2026-08-28T10:00:20+00:00",
            "plan": plan,
            "leagues": {"classic": {"100": _standings()}, "h2h": {}},
        },
        previous_state=first,
    )
    assert len(second["leagues"]["classic:100"]["history"]) == 1


def test_changed_gap_is_kept_even_inside_checkpoint_window(monkeypatch):
    monkeypatch.delenv("FPL_CLASSIC_LEAGUE_IDS", raising=False)
    monkeypatch.delenv("FPL_H2H_LEAGUE_IDS", raising=False)
    entry = _entry()
    plan = collection_plan(entry)
    first = build_tracking(
        team_id=42,
        entry=entry,
        collection={
            "generated_at": "2026-08-28T10:00:00+00:00",
            "plan": plan,
            "leagues": {"classic": {"100": _standings()}, "h2h": {}},
        },
        previous_state={},
    )
    changed = _standings()
    changed["standings"]["results"][0]["total"] = 132
    second = build_tracking(
        team_id=42,
        entry=entry,
        collection={
            "generated_at": "2026-08-28T10:00:20+00:00",
            "plan": plan,
            "leagues": {"classic": {"100": changed}, "h2h": {}},
        },
        previous_state=first,
    )
    row = second["leagues"]["classic:100"]
    assert len(row["history"]) == 2
    assert row["current"]["points_behind_above"] == 7
    assert row["current"]["gap_to_above_delta"] == 2
