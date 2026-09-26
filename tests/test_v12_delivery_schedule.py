from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.engines.v12_delivery_schedule import (
    deadline_checkpoints,
    is_price_checkpoint,
    precompute_window,
    price_checkpoint_for_london_date,
    resolve_delivery_decision,
)


WIB = ZoneInfo("Asia/Jakarta")
LONDON = ZoneInfo("Europe/London")


def test_fixed_deep_slots_and_silent_other_half_hours():
    for hour in (4, 12, 21):
        got = resolve_delivery_decision(datetime(2026, 9, 27, hour, 30, tzinfo=WIB))
        assert got.visible is True
        assert "DEEP" in got.obligations
        assert got.single_visible_report is True

    silent = resolve_delivery_decision(datetime(2026, 9, 27, 10, 30, tzinfo=WIB))
    assert silent.visible is False
    assert silent.obligations == ()


def test_price_is_2330_london_and_moves_from_0530_to_0630_wib_across_dst():
    bst = price_checkpoint_for_london_date(datetime(2026, 10, 24, tzinfo=LONDON).date())
    gmt = price_checkpoint_for_london_date(datetime(2026, 10, 25, tzinfo=LONDON).date())
    next_gmt = price_checkpoint_for_london_date(datetime(2026, 10, 26, tzinfo=LONDON).date())

    assert bst.isoformat() == "2026-10-25T05:30:00+07:00"
    assert gmt.isoformat() == "2026-10-26T06:30:00+07:00"
    assert next_gmt.isoformat() == "2026-10-27T06:30:00+07:00"
    assert is_price_checkpoint(bst)
    assert is_price_checkpoint(gmt)
    assert is_price_checkpoint(next_gmt)


def test_dst_window_has_exactly_one_price_publication_per_london_day():
    for london_day in (
        datetime(2026, 10, 24, tzinfo=LONDON).date(),
        datetime(2026, 10, 25, tzinfo=LONDON).date(),
        datetime(2026, 10, 26, tzinfo=LONDON).date(),
    ):
        target = price_checkpoint_for_london_date(london_day)
        local_day = target.date()
        candidates = [
            datetime(local_day.year, local_day.month, local_day.day, 5, 30, tzinfo=WIB),
            datetime(local_day.year, local_day.month, local_day.day, 6, 30, tzinfo=WIB),
        ]
        assert sum(is_price_checkpoint(row) for row in candidates) == 1


def test_deadline_matrix_is_exact_and_ordered():
    deadline = datetime(2026, 10, 10, 17, 0, tzinfo=WIB)
    rows = deadline_checkpoints(deadline)
    assert [row.key for row in rows] == [
        "T-24H", "T-12H", "T-6H", "T-3H", "T-2H",
        "T-1H", "T-30M", "T-15M", "T-5M",
    ]
    assert [row.contract for row in rows] == [
        "DEEP", "DEEP", "DEEP", "DEEP", "DELTA",
        "DELTA_EXECUTION", "FINAL_REVIEW", "GO_NO_GO", "FINAL_CONFIRMATION",
    ]
    assert rows[-1].at == datetime(2026, 10, 10, 16, 55, tzinfo=WIB)


def test_deadline_checkpoint_matches_by_absolute_instant():
    deadline = datetime(2026, 10, 10, 17, 0, tzinfo=WIB)
    t15 = datetime(2026, 10, 10, 16, 45, tzinfo=WIB)
    got = resolve_delivery_decision(t15, official_deadline=deadline)
    assert got.visible is True
    assert got.deadline_checkpoint == "T-15M"
    assert got.primary_mode == "DEADLINE:GO_NO_GO"


def test_pre_t3_deadline_checkpoint_does_not_break_quiet_hours():
    deadline = datetime(2026, 9, 28, 1, 0, tzinfo=WIB)
    t24 = datetime(2026, 9, 27, 1, 0, tzinfo=WIB)
    got = resolve_delivery_decision(t24, official_deadline=deadline)
    assert got.deadline_checkpoint == "T-24H"
    assert got.quiet_window is True
    assert got.quiet_suppressed is True
    assert got.visible is False


def test_quiet_match_is_suppressed_but_owner_and_t3_deadline_are_visible():
    quiet = datetime(2026, 9, 27, 1, 30, tzinfo=WIB)
    match = resolve_delivery_decision(quiet, match_live=True)
    assert match.quiet_window is True
    assert match.quiet_suppressed is True
    assert match.visible is False

    owner = resolve_delivery_decision(quiet, owner_adhoc=True)
    assert owner.visible is True
    assert owner.quiet_suppressed is False

    deadline = datetime(2026, 9, 27, 4, 0, tzinfo=WIB)
    t3 = datetime(2026, 9, 27, 1, 0, tzinfo=WIB)
    deadline_mode = resolve_delivery_decision(t3, official_deadline=deadline)
    assert deadline_mode.visible is True
    assert deadline_mode.deadline_checkpoint == "T-3H"


def test_overlap_is_one_report_with_all_obligations():
    observed = datetime(2026, 9, 27, 12, 30, tzinfo=WIB)
    deadline = datetime(2026, 9, 28, 12, 30, tzinfo=WIB)
    got = resolve_delivery_decision(
        observed,
        official_deadline=deadline,
        match_live=True,
    )
    assert got.visible is True
    assert got.single_visible_report is True
    assert set(got.obligations) == {"DEEP", "MATCH", "DEADLINE:DEEP"}
    assert got.primary_mode == "DEADLINE:DEEP"


def test_precompute_window_is_t15_to_t10():
    slot = datetime(2026, 9, 27, 12, 30, tzinfo=WIB)
    start, freeze_target = precompute_window(slot)
    assert start == datetime(2026, 9, 27, 12, 15, tzinfo=WIB)
    assert freeze_target == datetime(2026, 9, 27, 12, 20, tzinfo=WIB)
