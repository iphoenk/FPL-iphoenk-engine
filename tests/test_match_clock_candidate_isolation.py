from datetime import datetime, timezone

from ops.match_clock_facts import public_kickoff_match_candidate


def test_invalid_first_fixture_does_not_block_valid_second_owner_fixture():
    now = datetime(2026, 11, 1, 20, 35, tzinfo=timezone.utc)
    fixtures = [
        {"id": 101, "event": 9, "team_h": 1, "team_a": 2,
         "started": True, "finished": False, "finished_provisional": False,
         "kickoff_time": "2026-11-01T20:00:00Z"},
        {"id": 102, "event": 10, "team_h": 3, "team_a": 4,
         "started": True, "finished": False, "finished_provisional": False,
         "kickoff_time": "2026-11-01T20:00:00Z"},
    ]
    # Both fixtures kick off at 03:00 WIB; the first eligible HH:30 is 03:30 WIB.
    # Distinct scoring GW snapshots: invalid GW9 picks must not mask valid GW10 picks.
    picks = [
        {"element": i, "position": i, "multiplier": 1 if i <= 11 else 0,
         "is_captain": i == 1, "is_vice_captain": i == 2}
        for i in range(1, 16)
    ]
    bootstrap = {
        "events": [{"id": gw, "is_current": True,
                    "deadline_time": "2026-11-01T18:00:00Z"} for gw in (9, 10)],
        "elements": [{"id": i, "team": 3} for i in range(1, 16)],
    }
    calls = {"picks": 0}

    def fetch(path):
        if path == "fixtures/":
            return fixtures
        if path == "bootstrap-static/":
            return bootstrap
        if path == "entry/3462711/event/9/picks/":
            calls["picks"] += 1
            return {"picks": []}
        if path == "entry/3462711/event/10/picks/":
            calls["picks"] += 1
            return {"picks": picks}
        raise AssertionError(path)

    result = public_kickoff_match_candidate(now, fetch=fetch)
    assert result is not None
    assert result["report_mode"] == "MATCH"
    assert result["match_fixture_id"] == "102"
    assert calls["picks"] == 2
