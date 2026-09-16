from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from src.runtime_v6.report_delivery import should_continue_report_processing
from src.runtime_v6.scheduled_report_slot import resolve_scheduled_report_slot


def test_early_dispatch_maps_to_intended_half_hour_slot_without_rewriting_observed_at():
    observed_at = datetime.fromisoformat("2026-09-16T12:29:02+07:00")

    result = resolve_scheduled_report_slot(
        observed_at,
        timezone_name="Asia/Jakarta",
        physical_minute=30,
        tolerance_seconds=90,
    )

    assert result.within_tolerance is True
    assert result.observed_at == observed_at
    assert result.intended_report_slot.isoformat() == "2026-09-16T12:30:00+07:00"
    assert result.delta_seconds == -58.0


def test_utc_dispatch_is_resolved_against_jakarta_scheduled_occurrence():
    observed_at = datetime.fromisoformat("2026-09-16T05:29:02+00:00")

    result = resolve_scheduled_report_slot(
        observed_at,
        timezone_name="Asia/Jakarta",
        physical_minute=30,
        tolerance_seconds=90,
    )

    assert result.within_tolerance is True
    assert result.observed_at == observed_at
    assert result.intended_report_slot.isoformat() == "2026-09-16T12:30:00+07:00"
    assert result.delta_seconds == -58.0


def test_dispatch_tolerance_boundary_is_inclusive():
    result = resolve_scheduled_report_slot(
        datetime.fromisoformat("2026-09-16T12:31:30+07:00"),
        timezone_name="Asia/Jakarta",
        physical_minute=30,
        tolerance_seconds=90,
    )

    assert result.within_tolerance is True
    assert result.intended_report_slot.isoformat() == "2026-09-16T12:30:00+07:00"
    assert result.delta_seconds == 90.0


def test_dispatch_outside_tolerance_is_not_silently_coerced():
    result = resolve_scheduled_report_slot(
        datetime.fromisoformat("2026-09-16T12:31:31+07:00"),
        timezone_name="Asia/Jakarta",
        physical_minute=30,
        tolerance_seconds=90,
    )

    assert result.within_tolerance is False
    assert result.intended_report_slot is None
    assert result.delta_seconds == 91.0


def test_naive_observed_timestamp_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        resolve_scheduled_report_slot(
            datetime(2026, 9, 16, 12, 29, 2),
            timezone_name="Asia/Jakarta",
            physical_minute=30,
            tolerance_seconds=90,
        )


def test_already_published_data_slot_does_not_close_due_report_slot():
    assert should_continue_report_processing(
        data_slot_status="ALREADY_PUBLISHED",
        report_due=True,
        report_slot_status=None,
    ) is True


def test_schedule_policy_matches_canonical_half_hour_and_declares_tolerance():
    policy = json.loads(Path("config/v6/schedule_policy.json").read_text(encoding="utf-8"))
    scheduler = policy["scheduler_authority"]

    assert scheduler["physical_minute"] == 30
    assert scheduler["scheduled_dispatch_tolerance_seconds"] == 90
