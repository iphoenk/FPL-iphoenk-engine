from datetime import datetime, timezone

from src.services.prediction_service import _chip_state_summary
from src.services.raw_snapshot_service import detect_phase


def _bootstrap():
    return {
        "events": [
            {"id": 2, "is_current": True, "is_next": False, "finished": False, "deadline_time": "2026-08-28T17:30:00Z"},
            {"id": 3, "is_current": False, "is_next": True, "finished": False, "deadline_time": "2026-09-04T17:30:00Z"},
        ]
    }


def test_match_day_can_be_active_while_no_fixture_is_live():
    fixtures = [
        {"id": 11, "event": 2, "kickoff_time": "2026-08-29T01:00:00Z", "started": True, "finished": False, "finished_provisional": True},
        {"id": 12, "event": 2, "kickoff_time": "2026-08-29T11:30:00Z", "started": False, "finished": False, "finished_provisional": False},
    ]
    phase = detect_phase(_bootstrap(), fixtures, datetime(2026, 8, 29, 5, 30, tzinfo=timezone.utc))
    assert phase["match_day_active"] is True
    assert phase["match_day_fixture_count"] == 2
    assert phase["is_live_match"] is False
    assert phase["active_live_fixture_count"] == 0


def test_live_match_requires_not_finished_and_not_finished_provisional():
    fixtures = [
        {"id": 12, "event": 2, "kickoff_time": "2026-08-29T11:30:00Z", "started": True, "finished": False, "finished_provisional": False},
    ]
    phase = detect_phase(_bootstrap(), fixtures, datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc))
    assert phase["match_day_active"] is True
    assert phase["is_live_match"] is True
    assert phase["active_live_fixture_ids"] == [12]


def test_chip_summary_separates_submitted_truth_from_future_planning_state():
    official = {
        "picks": {"active_chip": "wildcard"},
        "history": {"chips": [{"name": "bboost", "event": 1}, {"name": "wildcard", "event": 2}]},
    }
    phase = {"submitted_gw": 2, "planning_gw": 3}
    result = _chip_state_summary(official, phase)
    assert result["submitted_chip"] == "WILDCARD"
    assert result["chip_used_this_submitted_gw"] is True
    assert result["planning_chip"] == "NONE"
    assert result["submitted_gw"] == 2
    assert result["planning_gw"] == 3
