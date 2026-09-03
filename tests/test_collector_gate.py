from datetime import datetime, timedelta, timezone

from src.engines.collector_gate import (
    deadline_intensive,
    direct_official_refresh_required,
    final_review_at,
    final_review_due,
    fixture_match_window,
    normal_report_mode,
    persisted_phase,
    should_collect,
    visible_report_decision,
)

ADAPTIVE_SCHEDULE = "2,7,12,17,22,27,32,37,42,47,52,57 * * * *"


def utc(y, m, d, hh, mm=0, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc)


def live_fixture(event=2, kickoff=None):
    kickoff = kickoff or utc(2026, 8, 29, 13, 0)
    return {
        "event": event,
        "kickoff_time": kickoff.isoformat(),
        "started": True,
        "finished": False,
    }


def test_hourly_primary_always_collects():
    collect, reason = should_collect("schedule", "30 * * * *", utc(2026, 8, 25, 18, 30), None, False)
    assert collect is True
    assert reason == "hourly_primary"


def test_adaptive_slot_skips_normal_day():
    collect, reason = should_collect(
        "schedule", ADAPTIVE_SCHEDULE, utc(2026, 8, 25, 18, 2), utc(2026, 8, 28, 17, 30), False
    )
    assert collect is False
    assert reason == "adaptive_slot_not_needed"


def test_deadline_day_window_is_exactly_24h_and_adaptive_only_runs_for_final_review():
    deadline = utc(2026, 8, 28, 17, 30)
    assert deadline_intensive(deadline - timedelta(hours=24), deadline) is True
    assert deadline_intensive(deadline - timedelta(hours=24, seconds=1), deadline) is False
    assert deadline_intensive(deadline + timedelta(seconds=1), deadline) is False

    ordinary_adaptive, ordinary_reason = should_collect(
        "schedule", ADAPTIVE_SCHEDULE, deadline - timedelta(hours=2), deadline, False
    )
    assert ordinary_adaptive is False
    assert ordinary_reason == "adaptive_slot_not_needed"

    daytime_deadline = utc(2026, 8, 29, 11, 30)
    final_collect, final_reason = should_collect(
        "schedule", ADAPTIVE_SCHEDULE, utc(2026, 8, 29, 10, 2), daytime_deadline, False
    )
    assert final_collect is True
    assert final_reason == "adaptive_final_review"


def test_adaptive_slot_runs_for_live_refresh_without_authorizing_match_report_by_itself():
    now = utc(2026, 8, 29, 13, 2)
    collect, reason = should_collect(
        "schedule", ADAPTIVE_SCHEDULE, now, utc(2026, 9, 5, 17, 30), True
    )
    assert collect is True
    assert reason == "adaptive_live_refresh"


def test_match_mode_requires_current_scoring_gw_started_and_unfinished():
    now = utc(2026, 8, 29, 13, 30)
    assert fixture_match_window(now, [live_fixture(event=2)], scoring_gw=2) is True
    assert fixture_match_window(now, [live_fixture(event=1)], scoring_gw=2) is False
    not_started = live_fixture(event=2)
    not_started["started"] = False
    assert fixture_match_window(now, [not_started], scoring_gw=2) is False
    finished = live_fixture(event=2)
    finished["finished"] = True
    assert fixture_match_window(now, [finished], scoring_gw=2) is False
    assert fixture_match_window(now, [live_fixture(event=2)], scoring_gw=None) is False


def test_future_kickoff_cannot_be_match_mode_even_if_started_flag_is_bad():
    now = utc(2026, 8, 29, 13, 0)
    fixture = live_fixture(event=2, kickoff=now + timedelta(minutes=30))
    assert fixture_match_window(now, [fixture], scoring_gw=2) is False


def test_normal_wib_report_checkpoints():
    assert normal_report_mode(utc(2026, 8, 28, 21, 30)) == "NORMAL_DEEP_REVIEW"
    assert normal_report_mode(utc(2026, 8, 29, 5, 30)) == "NORMAL_MIDDAY"
    assert normal_report_mode(utc(2026, 8, 29, 14, 30)) == "NORMAL_NIGHT"
    assert normal_report_mode(utc(2026, 8, 29, 8, 30)) is None


def test_normal_report_checkpoint_tolerates_delayed_primary_job():
    assert normal_report_mode(utc(2026, 8, 29, 5, 41), hourly_checkpoint=True) == "NORMAL_MIDDAY"


def test_final_review_rule_for_overnight_deadline_is_t_minus_3h():
    deadline = utc(2026, 8, 28, 17, 30)
    assert final_review_at(deadline) == utc(2026, 8, 28, 14, 30)
    assert final_review_due(utc(2026, 8, 28, 14, 30), deadline) is True


def test_final_review_rule_for_non_overnight_deadline_is_t_minus_90m():
    deadline = utc(2026, 8, 29, 11, 30)
    assert final_review_at(deadline) == utc(2026, 8, 29, 10, 0)
    decision = visible_report_decision(utc(2026, 8, 29, 10, 0), deadline, scoring_gw=1, fixtures=[], hourly_checkpoint=False)
    assert decision["visible"] is True
    assert decision["primary_mode"] == "DEADLINE_DAY_FINAL_REVIEW"


def test_final_review_grace_handles_scheduler_delay_once_inside_window():
    deadline = utc(2026, 8, 29, 11, 30)
    target = utc(2026, 8, 29, 10, 0)
    assert final_review_due(target + timedelta(minutes=10), deadline, grace_minutes=15) is True
    assert final_review_due(target + timedelta(minutes=15), deadline, grace_minutes=15) is False


def test_deadline_day_hourly_report_is_never_suppressed():
    deadline = utc(2026, 8, 28, 17, 30)
    decision = visible_report_decision(utc(2026, 8, 28, 16, 30), deadline, scoring_gw=1, fixtures=[], hourly_checkpoint=True)
    assert decision["visible"] is True
    assert decision["primary_mode"] == "DEADLINE_DAY"


def test_hourly_deadline_reports_continue_after_final_review():
    deadline = utc(2026, 8, 28, 17, 30)
    decision = visible_report_decision(utc(2026, 8, 28, 15, 30), deadline, scoring_gw=1, fixtures=[], hourly_checkpoint=True)
    assert decision["visible"] is True
    assert decision["primary_mode"] == "DEADLINE_DAY"


def test_match_mode_only_visible_at_hourly_checkpoint():
    fixture = live_fixture(event=2)
    off_checkpoint = visible_report_decision(utc(2026, 8, 29, 13, 15), utc(2026, 9, 5, 17, 30), scoring_gw=2, fixtures=[fixture], hourly_checkpoint=False)
    assert off_checkpoint["match_mode"] is True
    assert off_checkpoint["visible"] is False
    checkpoint = visible_report_decision(utc(2026, 8, 29, 13, 30), utc(2026, 9, 5, 17, 30), scoring_gw=2, fixtures=[fixture], hourly_checkpoint=True)
    assert checkpoint["visible"] is True
    assert checkpoint["primary_mode"] == "MATCH_MODE"


def test_night_and_match_collision_emits_one_match_mode_report_with_night_folded_in():
    fixture = live_fixture(event=2)
    decision = visible_report_decision(utc(2026, 8, 29, 14, 30), utc(2026, 9, 5, 17, 30), scoring_gw=2, fixtures=[fixture], hourly_checkpoint=True)
    assert decision["primary_mode"] == "MATCH_MODE"
    assert decision["included_modes"] == ["MATCH_MODE", "NORMAL_NIGHT"]


def test_deadline_final_review_collision_has_highest_priority():
    deadline = utc(2026, 8, 28, 17, 30)
    fixture = {"event": 1, "kickoff_time": utc(2026, 8, 28, 14, 0).isoformat(), "started": True, "finished": False}
    decision = visible_report_decision(utc(2026, 8, 28, 14, 30), deadline, scoring_gw=1, fixtures=[fixture], hourly_checkpoint=True)
    assert decision["primary_mode"] == "DEADLINE_DAY_FINAL_REVIEW"
    assert "NORMAL_NIGHT" in decision["included_modes"]
    assert "MATCH_MODE" in decision["included_modes"]


def test_critical_price_alert_can_break_silence_outside_normal_schedule():
    decision = visible_report_decision(utc(2026, 8, 29, 3, 0), utc(2026, 9, 5, 17, 30), scoring_gw=2, fixtures=[], hourly_checkpoint=False, critical_price_alert=True)
    assert decision["primary_mode"] == "CRITICAL_PRICE_ALERT"


def test_direct_official_refresh_threshold_and_material_override():
    now = utc(2026, 8, 29, 10, 0)
    assert direct_official_refresh_required(now - timedelta(minutes=30), now) is False
    assert direct_official_refresh_required(now - timedelta(minutes=31), now) is True
    assert direct_official_refresh_required(now - timedelta(minutes=1), now, material_native_change=True) is True
    assert direct_official_refresh_required(None, now) is True


def test_persisted_phase_reads_deadline_scoring_gw_and_generation_time(tmp_path):
    path = tmp_path / "latest.json"
    path.write_text("""{
      "generated_at": "2026-08-29T09:30:00Z",
      "phase": {"deadline_time": "2026-09-05T17:30:00Z", "scoring_gw": 2, "is_live_event": true}
    }""")
    phase = persisted_phase(path)
    assert phase["deadline"] == utc(2026, 9, 5, 17, 30)
    assert phase["scoring_gw"] == 2
    assert phase["generated_at"] == utc(2026, 8, 29, 9, 30)
    assert phase["is_live_event"] is True


def test_push_and_manual_dispatch_always_collect():
    for event in ("push", "workflow_dispatch"):
        collect, _ = should_collect(event, None, utc(2026, 8, 25, 18), None, False)
        assert collect is True
