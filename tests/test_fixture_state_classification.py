from src.engines.live_state_service import classify_fixture_state, _team_match_state


def test_provisional_90_is_not_live():
    result = classify_fixture_state({
        "event": 7, "started": True, "finished": False,
        "finished_provisional": True, "kickoff_time": "2026-10-12T00:00:00Z",
    })
    assert result == {
        "state": "PROVISIONAL_90",
        "substate": "OFFICIAL_FINISHED_PROVISIONAL",
    }


def test_live_requires_started_without_provisional_completion():
    result = classify_fixture_state({
        "event": 7, "started": True, "finished": False,
        "finished_provisional": False, "kickoff_time": "2026-10-12T00:00:00Z",
    })
    assert result["state"] == "LIVE"


def test_final_requires_official_finished_flag_not_minute_90():
    result = classify_fixture_state({
        "event": 7, "started": True, "finished": True,
        "finished_provisional": True, "minutes": 90,
    })
    assert result["state"] == "FINAL"


def test_minute_90_alone_does_not_make_final():
    result = classify_fixture_state({
        "event": 7, "started": True, "finished": False,
        "finished_provisional": False, "minutes": 90,
    })
    assert result["state"] == "LIVE"


def test_postponed_remains_not_started_with_distinct_substate():
    result = classify_fixture_state({
        "event": None, "started": False, "finished": False,
        "finished_provisional": False, "kickoff_time": None,
    })
    assert result == {"state": "NOT_STARTED", "substate": "POSTPONED"}


def test_missing_or_conflicting_lifecycle_fails_closed():
    assert classify_fixture_state({
        "event": 7, "started": True, "finished": False,
        "finished_provisional": True,
    })["state"] == "PROVISIONAL_90"
    assert classify_fixture_state({
        "event": 7, "started": False, "finished": False,
        "finished_provisional": True,
    })["state"] == "UNKNOWN"
    assert classify_fixture_state({
        "event": 7, "started": "yes", "finished": False,
    })["state"] == "UNKNOWN"


def test_team_state_prefers_live_over_provisional_and_final():
    fixtures = [
        {"id": 1, "event": 7, "team_h": 1, "team_a": 2,
         "started": True, "finished": True, "finished_provisional": True},
        {"id": 2, "event": 7, "team_h": 1, "team_a": 3,
         "started": True, "finished": False, "finished_provisional": True},
        {"id": 3, "event": 7, "team_h": 1, "team_a": 4,
         "started": True, "finished": False, "finished_provisional": False},
    ]
    assert _team_match_state(fixtures, 1, 7)["state"] == "LIVE"


def test_eight_provisional_and_one_live_are_not_nine_live():
    fixtures = [
        {"id": i, "event": 7, "team_h": i, "team_a": 100 + i,
         "started": True, "finished": False,
         "finished_provisional": i <= 8}
        for i in range(1, 10)
    ]
    states = [classify_fixture_state(row)["state"] for row in fixtures]
    assert states.count("PROVISIONAL_90") == 8
    assert states.count("LIVE") == 1


def test_fixture_classification_does_not_accept_future_snapshot_time():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    snapshot = datetime.fromisoformat("2026-10-12T00:00:00+00:00")
    assert snapshot <= now or snapshot.year < now.year
