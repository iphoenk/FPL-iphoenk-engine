from __future__ import annotations

from datetime import datetime, timezone

from src.v5.report_checkpoint import resolve_report_checkpoint


CFG = {
    "enabled": True,
    "timezone": "Asia/Jakarta",
    "grace_minutes": 60,
    "history_days": 14,
    "silent_missing_forbidden": True,
    "slots": [
        {"id": "DAILY_DEEP", "time": "04:30", "label": "Review pagi 04:30 WIB"},
        {"id": "MIDDAY_CATCHUP", "time": "12:30", "label": "Catch-up 12:30 WIB"},
        {"id": "EVENING_CHECK", "time": "21:30", "label": "Review malam 21:30 WIB"},
    ],
}


def _utc(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_morning_checkpoint_is_completed_inside_grace_window() -> None:
    # 2026-08-28 04:45 WIB == 2026-08-27 21:45 UTC.
    checkpoint, state = resolve_report_checkpoint(_utc(2026, 8, 27, 21, 45), {}, CFG)
    assert checkpoint["current"]["id"] == "DAILY_DEEP"
    assert checkpoint["completeness"] == "OK"
    assert checkpoint["missed_due"] == []
    assert len(state["checkpoint_history"]) == 1
    assert state["checkpoint_history"][0]["status"] == "COMPLETED"


def test_missed_checkpoint_is_explicit_after_grace_window() -> None:
    # 06:00 WIB: morning slot is already 30 minutes beyond its 60-minute grace.
    checkpoint, _ = resolve_report_checkpoint(_utc(2026, 8, 27, 23, 0), {}, CFG)
    assert checkpoint["completeness"] == "ATTENTION_REQUIRED"
    assert [row["id"] for row in checkpoint["missed_due"]] == ["DAILY_DEEP"]
    assert checkpoint["silent_missing_forbidden"] is True


def test_midday_checkpoint_respects_completed_morning_history() -> None:
    state = {
        "checkpoint_history": [
            {
                "slot_id": "DAILY_DEEP",
                "local_date": "2026-08-28",
                "status": "COMPLETED",
            }
        ]
    }
    # 12:45 WIB == 05:45 UTC.
    checkpoint, updated = resolve_report_checkpoint(_utc(2026, 8, 28, 5, 45), state, CFG)
    assert checkpoint["current"]["id"] == "MIDDAY_CATCHUP"
    assert checkpoint["missed_due"] == []
    assert {row["slot_id"] for row in updated["checkpoint_history"]} == {"DAILY_DEEP", "MIDDAY_CATCHUP"}


def test_routine_before_first_slot_does_not_invent_a_miss() -> None:
    # 03:00 WIB == 20:00 previous UTC.
    checkpoint, state = resolve_report_checkpoint(_utc(2026, 8, 27, 20, 0), {}, CFG)
    assert checkpoint["current"]["kind"] == "ROUTINE"
    assert checkpoint["missed_due"] == []
    assert checkpoint["completeness"] == "OK"
    assert state.get("checkpoint_history") == []


def test_repeated_refresh_does_not_duplicate_checkpoint_history() -> None:
    first, state = resolve_report_checkpoint(_utc(2026, 8, 27, 21, 45), {}, CFG)
    assert first["current"]["id"] == "DAILY_DEEP"
    second, updated = resolve_report_checkpoint(_utc(2026, 8, 27, 21, 50), state, CFG)
    assert second["missed_due"] == []
    assert len(updated["checkpoint_history"]) == 1
