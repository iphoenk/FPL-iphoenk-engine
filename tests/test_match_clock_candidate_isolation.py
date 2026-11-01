"""MATCH gate regression: one scoring GW remains active with a fixture outstanding."""
from datetime import datetime, timezone
from unittest.mock import patch

from ops.match_clock_facts import public_kickoff_match_candidate


def test_same_gw_second_owner_fixture_survives_first_materiality_rejection():
    # GW9 is still current: two fixtures at the same kickoff, one remains
    # reportable even if the first candidate fails the materiality policy.
    now = datetime(2026, 11, 1, 20, 35, tzinfo=timezone.utc)
    fixtures = [
        {"id": fid, "event": 9, "team_h": team, "team_a": 2,
         "started": True, "finished": False, "finished_provisional": False,
         "kickoff_time": "2026-11-01T20:00:00Z"}
        for fid, team in [(101, 1), (102, 3)]
    ] + [
        {"id": 103, "event": 9, "team_h": 4, "team_a": 5,
         "started": False, "finished": False, "finished_provisional": False,
         "kickoff_time": "2026-11-02T20:00:00Z"},
    ]
    picks = [
        {"element": i, "position": i, "multiplier": 1 if i <= 11 else 0,
         "is_captain": i == 1, "is_vice_captain": i == 2}
        for i in range(1, 16)
    ]
    bootstrap = {
        "events": [{"id": 9, "is_current": True,
                    "deadline_time": "2026-11-01T18:00:00Z"},
                   {"id": 10, "is_current": False,
                    "deadline_time": "2026-11-08T18:00:00Z"}],
        "elements": [{"id": i, "team": 1 if i == 1 else 3}
                     for i in range(1, 16)],
    }
    def fetch(path):
        if path == "fixtures/":
            return fixtures
        if path == "bootstrap-static/":
            return bootstrap
        if path == "entry/3462711/event/9/picks/":
            return {"picks": picks}
        raise AssertionError(path)

    seen = []
    def materiality(proof, *, observed_at):
        seen.append(proof["official_fixture_id"])
        return {"eligible": len(seen) == 2,
                "event_key": "verified-second-fixture"}

    with patch("ops.match_clock_facts.assess_verified_match_materiality",
               side_effect=materiality):
        result = public_kickoff_match_candidate(now, fetch=fetch)
    assert seen == [101, 102]
    assert result is not None
    assert result["report_mode"] == "MATCH"
    assert result["match_gw"] == "9"
    assert result["match_fixture_id"] == "102"
    assert result["match_event_key"] == "verified-second-fixture"


def test_unstarted_final_fixture_is_not_reported_as_live():
    now = datetime(2026, 11, 1, 20, 35, tzinfo=timezone.utc)
    def fetch(path):
        assert path == "fixtures/"
        return [{"id": 103, "event": 9, "team_h": 1, "team_a": 2,
                 "started": False, "finished": False,
                 "finished_provisional": False,
                 "kickoff_time": "2026-11-02T20:00:00Z"}]
    assert public_kickoff_match_candidate(now, fetch=fetch) is None

def test_first_checkpoint_does_not_replay_at_next_hour():
    # Same LIVE fixture at a later hourly tick is not a new kickoff.
    now = datetime(2026, 11, 1, 21, 35, tzinfo=timezone.utc)
    def fetch(path):
        assert path == "fixtures/"
        return [{"id": 102, "event": 9, "team_h": 3, "team_a": 4,
                 "started": True, "finished": False,
                 "finished_provisional": False,
                 "kickoff_time": "2026-11-01T20:00:00Z"}]
    assert public_kickoff_match_candidate(now, fetch=fetch) is None
