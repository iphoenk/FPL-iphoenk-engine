from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.runtime_v6.control_plane import CONTROL_PLANE
from src.runtime_v6.scheduler_recovery import DEFAULT_COOLDOWN_MINUTES, DEFAULT_SETTLE_MINUTES
from src.runtime_v6.scheduler_watchdog import DEFAULT_CRITICAL_MINUTES, DEFAULT_WARNING_MINUTES
from src.runtime_v6.temporal import (
    TemporalError,
    age_seconds,
    canonical_timestamp,
    classify_freshness,
    classify_incident,
    compare_temporal_window,
    floor_interval_slot,
    parse_timestamp,
    resolve_scheduled_report_slot,
)


def test_temporal_parser_rejects_naive_timestamp_by_default():
    with pytest.raises(TemporalError, match="timezone-aware"):
        parse_timestamp(datetime(2026, 9, 16, 12, 30), label="observed_at")


def test_temporal_parser_normalizes_utc_to_jakarta_without_changing_instant():
    parsed = parse_timestamp(
        "2026-09-16T05:29:02+00:00",
        label="observed_at",
        target_timezone="Asia/Jakarta",
    )
    assert parsed.isoformat() == "2026-09-16T12:29:02+07:00"
    assert parsed.astimezone(timezone.utc).isoformat() == "2026-09-16T05:29:02+00:00"


def test_offset_input_is_resolved_by_instant_not_raw_wall_clock():
    result = resolve_scheduled_report_slot(
        datetime.fromisoformat("2026-09-16T13:29:02+08:00"),
        timezone_name="Asia/Jakarta",
        physical_minute=30,
        tolerance_seconds=90,
    )
    assert result.within_tolerance is True
    assert result.intended_report_slot.isoformat() == "2026-09-16T12:30:00+07:00"
    assert result.delta_seconds == -58.0


def test_canonical_timestamp_preserves_microseconds_only_when_present():
    assert canonical_timestamp(
        datetime.fromisoformat("2026-09-16T12:30:00+07:00"),
        timezone_name="Asia/Jakarta",
    ) == "2026-09-16T12:30:00+07:00"
    assert canonical_timestamp(
        datetime.fromisoformat("2026-09-16T12:30:00.123456+07:00"),
        timezone_name="Asia/Jakarta",
    ) == "2026-09-16T12:30:00.123456+07:00"


def test_interval_slot_and_age_are_shared_temporal_primitives():
    observed = datetime.fromisoformat("2026-09-16T12:29:02+07:00")
    slot = floor_interval_slot(observed, cadence_minutes=60)
    assert slot.astimezone(timezone.utc).isoformat() == "2026-09-16T05:00:00+00:00"
    assert age_seconds(
        now=datetime.fromisoformat("2026-09-16T13:30:00+07:00"),
        earlier=datetime.fromisoformat("2026-09-16T12:30:00+07:00"),
    ) == 3600.0


def test_freshness_and_incident_are_independent_dimensions():
    freshness = classify_freshness(
        age_minutes=82,
        fresh_after_minutes=75,
        stale_after_minutes=135,
    )
    incident = classify_incident(
        age_minutes=82,
        warning_after_minutes=90,
        critical_after_minutes=135,
    )
    assert freshness.freshness == "LATE"
    assert freshness.health == "AMBER"
    assert incident.state == "BELOW_WARNING"


def test_temporal_window_is_explicit_and_fail_closed_at_deadline():
    inside = compare_temporal_window(
        logical_at="2026-09-16T12:30:00+07:00",
        observed_at="2026-09-16T12:45:00+07:00",
        deadline="2026-09-16T13:00:00+07:00",
    )
    outside = compare_temporal_window(
        logical_at="2026-09-16T12:30:00+07:00",
        observed_at="2026-09-16T13:01:00+07:00",
        deadline="2026-09-16T13:00:00+07:00",
    )
    assert inside.observed_before_logical is False
    assert inside.window_open is True
    assert outside.window_open is False


def test_control_plane_contract_is_single_python_owner_for_runtime_identity_and_thresholds():
    assert CONTROL_PLANE.runtime_branch == "runtime-data-v6"
    assert CONTROL_PLANE.control_issue_number == 431
    assert CONTROL_PLANE.issue_title_marker == "FPL_MASTER_SLOT"
    assert CONTROL_PLANE.required_reason == "chatgpt_hourly_master"
    assert CONTROL_PLANE.required_audit == "FPL_MASTER_HOURLY"
    assert CONTROL_PLANE.report_prefetch_command == "/v6-report-prefetch"
    assert CONTROL_PLANE.scheduler_authority_id == "CHATGPT_FPL_MASTER_MONITOR"
    assert CONTROL_PLANE.watchdog_role == "MONITORING_ONLY"
    assert CONTROL_PLANE.recovery_role == "SAFE_RECOVERY_ONLY"
    assert CONTROL_PLANE.watchdog_warning_minutes == 90
    assert CONTROL_PLANE.watchdog_critical_minutes == 135
    assert CONTROL_PLANE.recovery_cooldown_minutes == 60
    assert CONTROL_PLANE.governed_event_settle_minutes == 20
    assert DEFAULT_WARNING_MINUTES == CONTROL_PLANE.watchdog_warning_minutes
    assert DEFAULT_CRITICAL_MINUTES == CONTROL_PLANE.watchdog_critical_minutes
    assert DEFAULT_COOLDOWN_MINUTES == CONTROL_PLANE.recovery_cooldown_minutes
    assert DEFAULT_SETTLE_MINUTES == CONTROL_PLANE.governed_event_settle_minutes


def test_schedule_policy_declares_runtime_branch_for_control_plane_owner():
    import json

    policy = json.loads(Path("config/v6/schedule_policy.json").read_text(encoding="utf-8"))
    assert policy["runtime_branch"] == "runtime-data-v6"


def test_migrated_temporal_modules_do_not_own_iso_parsers_or_jakarta_zone_literals():
    migrated = (
        "src/runtime_v6/scheduled_report_slot.py",
        "src/runtime_v6/report_trigger.py",
        "src/runtime_v6/report_delivery.py",
        "src/runtime_v6/report_recovery.py",
        "src/runtime_v6/report_observability.py",
        "src/runtime_v6/delivery_integrity.py",
        "src/runtime_v6/runtime_control.py",
        "src/runtime_v6/workflow_control.py",
        "src/runtime_v6/scheduler_watchdog.py",
        "src/runtime_v6/scheduler_recovery.py",
        "src/runtime_v6/schedule_policy.py",
    )
    for path in migrated:
        text = Path(path).read_text(encoding="utf-8")
        assert "datetime.fromisoformat" not in text, path
        assert 'ZoneInfo("Asia/Jakarta")' not in text, path


def test_temporal_owner_contains_the_iso_parser_implementation():
    temporal = Path("src/runtime_v6/temporal.py").read_text(encoding="utf-8")
    assert "datetime.fromisoformat" in temporal
