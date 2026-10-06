from datetime import datetime, timezone

from ops.render_external_clock import resolve_tick


def test_render_clock_resolves_hourly_core_without_report():
    row = resolve_tick(datetime(2026, 10, 6, 8, 28, tzinfo=timezone.utc))
    assert row["logical_slot"] == "2026-10-06T15:00:00+07:00"
    assert row["report_mode"] == "NONE"
    assert row["report_slot"] == ""


def test_render_clock_prefires_deep_two_minutes_before_checkpoint():
    row = resolve_tick(datetime(2026, 10, 6, 14, 28, tzinfo=timezone.utc))
    assert row["logical_slot"] == "2026-10-06T21:00:00+07:00"
    assert row["report_mode"] == "DEEP"
    assert row["report_slot"] == "2026-10-06T21:30:00+07:00"
    assert row["checkpoint_time"] == "21:30"


def test_render_clock_routes_bst_price_checkpoint():
    row = resolve_tick(datetime(2026, 10, 5, 22, 28, tzinfo=timezone.utc))
    assert row["logical_slot"] == "2026-10-06T05:00:00+07:00"
    assert row["report_mode"] == "PRICE"
    assert row["report_slot"] == "2026-10-06T05:30:00+07:00"
    assert row["checkpoint_time"] == "05:30"


def test_render_clock_routes_gmt_price_checkpoint():
    row = resolve_tick(datetime(2026, 11, 5, 23, 28, tzinfo=timezone.utc))
    assert row["logical_slot"] == "2026-11-06T06:00:00+07:00"
    assert row["report_mode"] == "PRICE"
    assert row["report_slot"] == "2026-11-06T06:30:00+07:00"
    assert row["checkpoint_time"] == "06:30"


def test_render_clock_accepts_bounded_late_visible_recovery():
    row = resolve_tick(datetime(2026, 10, 6, 14, 45, tzinfo=timezone.utc))
    assert row["report_mode"] == "DEEP"
    assert row["report_slot"] == "2026-10-06T21:30:00+07:00"
