from datetime import datetime, timedelta, timezone

from src.engines.collector_gate import deadline_intensive, fixture_match_window, should_collect


def utc(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def test_hourly_primary_always_collects():
    collect, reason = should_collect("schedule", "55 * * * *", utc(2026, 8, 25, 18), None, False)
    assert collect is True
    assert reason == "hourly_primary"


def test_adaptive_slot_skips_normal_day():
    collect, reason = should_collect("schedule", "*/15 * * * *", utc(2026, 8, 25, 18), utc(2026, 8, 28, 17, 30), False)
    assert collect is False
    assert reason == "adaptive_slot_not_needed"


def test_adaptive_slot_runs_within_24h_deadline():
    now = utc(2026, 8, 27, 18)
    deadline = utc(2026, 8, 28, 17, 30)
    assert deadline_intensive(now, deadline) is True
    collect, reason = should_collect("schedule", "*/15 * * * *", now, deadline, False)
    assert collect is True
    assert reason == "adaptive_deadline_window"


def test_adaptive_slot_runs_during_match_window():
    now = utc(2026, 8, 25, 18)
    collect, reason = should_collect("schedule", "*/15 * * * *", now, utc(2026, 8, 29, 18), True)
    assert collect is True
    assert reason == "adaptive_match_window"


def test_fixture_window_excludes_finished_matches():
    now = utc(2026, 8, 25, 18)
    fixtures = [
        {"kickoff_time": (now - timedelta(minutes=30)).isoformat(), "finished": True},
        {"kickoff_time": (now + timedelta(hours=5)).isoformat(), "finished": False},
    ]
    assert fixture_match_window(now, fixtures) is False


def test_fixture_window_detects_live_or_imminent_match():
    now = utc(2026, 8, 25, 18)
    fixtures = [{"kickoff_time": (now - timedelta(minutes=45)).isoformat(), "finished": False}]
    assert fixture_match_window(now, fixtures) is True


def test_push_and_manual_dispatch_always_collect():
    for event in ("push", "workflow_dispatch"):
        collect, _ = should_collect(event, None, utc(2026, 8, 25, 18), None, False)
        assert collect is True
