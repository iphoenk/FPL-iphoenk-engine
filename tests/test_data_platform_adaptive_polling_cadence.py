from __future__ import annotations

from datetime import datetime, timezone

from src.runtime_v6.polling import carry_forward_skipped, poll_decision


def _source(interval: int) -> dict:
    return {
        "id": "adaptive_source",
        "name": "Adaptive Source",
        "category": "reference",
        "adapter": "http",
        "critical": False,
        "poll_interval_minutes": interval,
        "requests": [{"id": "main", "url": "https://example.invalid/data"}],
    }


def _previous(polled_at: str) -> dict:
    return {
        "source_id": "adaptive_source",
        "health": "GREEN",
        "availability": "AVAILABLE",
        "checked_at": polled_at,
        "data": {"main": {"body": "last-good"}},
        "polling": {
            "last_polled_at": polled_at,
            "scheduler_slot": polled_at,
            "skipped": False,
        },
    }


def _dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 13, hour, minute, tzinfo=timezone.utc)


def test_long_interval_due_is_measured_from_actual_poll_not_skip_evaluation():
    source = _source(240)
    state = _previous("2026-09-13T00:00:00+00:00")

    for hour in (1, 2, 3):
        decision = poll_decision(source, state, now=_dt(hour), scheduler_interval_minutes=60)
        assert decision["due"] is False
        assert decision["reason"] == "NOT_DUE"
        state = carry_forward_skipped(source, state, decision)
        assert state["polling"]["last_polled_at"] == "2026-09-13T00:00:00+00:00"
        assert state["polling"]["last_evaluated_scheduler_slot"].startswith(
            f"2026-09-13T{hour:02d}:00:00"
        )

    due = poll_decision(source, state, now=_dt(4), scheduler_interval_minutes=60)
    assert due["due"] is True
    assert due["reason"] == "DUE"


def test_daily_adaptive_source_becomes_due_after_1440_minutes_despite_hourly_skips():
    source = _source(1440)
    state = _previous("2026-09-12T09:00:00+00:00")

    for hour in range(10, 24):
        decision = poll_decision(
            source,
            state,
            now=datetime(2026, 9, 12, hour, tzinfo=timezone.utc),
            scheduler_interval_minutes=60,
        )
        assert decision["due"] is False
        state = carry_forward_skipped(source, state, decision)

    for hour in range(0, 9):
        decision = poll_decision(
            source,
            state,
            now=datetime(2026, 9, 13, hour, tzinfo=timezone.utc),
            scheduler_interval_minutes=60,
        )
        assert decision["due"] is False
        state = carry_forward_skipped(source, state, decision)

    due = poll_decision(
        source,
        state,
        now=datetime(2026, 9, 13, 9, tzinfo=timezone.utc),
        scheduler_interval_minutes=60,
    )
    assert due["due"] is True
    assert state["polling"]["last_polled_at"] == "2026-09-12T09:00:00+00:00"


def test_hourly_source_still_deduplicates_same_scheduler_slot():
    source = _source(60)
    state = _previous("2026-09-13T09:00:00+00:00")

    same_slot = poll_decision(source, state, now=_dt(9, 31), scheduler_interval_minutes=60)
    assert same_slot["due"] is False
    assert same_slot["reason"] == "ALREADY_POLLED_THIS_SLOT"

    next_slot = poll_decision(source, state, now=_dt(10, 0), scheduler_interval_minutes=60)
    assert next_slot["due"] is True
    assert next_slot["reason"] == "DUE"
