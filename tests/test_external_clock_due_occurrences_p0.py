from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from ops.render_external_clock import due_report_occurrences, reconcile_due_occurrences


WIB = ZoneInfo("Asia/Jakarta")


def test_delayed_clock_enumerates_multiple_due_deep_slots():
    rows = due_report_occurrences(datetime(2026, 10, 25, 23, 12, tzinfo=WIB), 24)
    deep = [row["checkpoint_time"] for row in rows if row["report_mode"] == "DEEP"]
    assert deep == ["04:30", "12:30", "21:30"]
    assert len({(row["report_mode"], row["report_slot"]) for row in rows}) == len(rows)


def test_price_london_dst_transition():
    before = due_report_occurrences(datetime(2026, 10, 25, 6, 45, tzinfo=WIB), 3)
    assert any(row["report_mode"] == "PRICE" and row["checkpoint_time"] == "05:30" for row in before)
    after = due_report_occurrences(datetime(2026, 10, 26, 7, 15, tzinfo=WIB), 3)
    assert any(row["report_mode"] == "PRICE" and row["checkpoint_time"] == "06:30" for row in after)


def test_future_occurrences_are_never_emitted():
    rows = due_report_occurrences(datetime(2026, 10, 25, 11, 0, tzinfo=WIB), 2)
    assert not any(row["checkpoint_time"] == "12:30" for row in rows)


@pytest.mark.parametrize("hours", [0, 73])
def test_bounded_horizon(hours):
    with pytest.raises(ValueError):
        due_report_occurrences(datetime(2026, 10, 25, 12, 0, tzinfo=WIB), hours)


def test_naive_time_rejected():
    with pytest.raises(ValueError):
        due_report_occurrences(datetime(2026, 10, 25, 12, 0))


def test_reconciliation_requires_verified_terminal_state():
    now = datetime(2026, 10, 25, 13, 45, tzinfo=WIB)
    due = due_report_occurrences(now, 12)
    deep = next(row for row in due if row["checkpoint_time"] == "12:30")
    key = f'DEEP|{deep["report_slot"]}'
    missing = reconcile_due_occurrences(now, set(), set(), 12)
    assert key in {row["occurrence_id"] for row in missing["missing"]}
    active = reconcile_due_occurrences(now, set(), {key}, 12)
    assert key in {row["occurrence_id"] for row in active["active"]}
    published = reconcile_due_occurrences(now, {key}, {key}, 12)
    assert key in {row["occurrence_id"] for row in published["published"]}
    assert key not in {row["occurrence_id"] for row in published["active"]}
