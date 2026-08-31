from datetime import datetime, timezone

from src.engines.report_user_presentation import _operational_health, resolve_report_checkpoint


def _policy() -> dict:
    return {
        "scheduled_report_checkpoints": {
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
    }


def _late_recovered_state() -> dict:
    return {
        "checkpoint_history": [
            {
                "slot_id": "DAILY_DEEP",
                "label": "Review pagi 04:30 WIB",
                "local_date": "2026-08-31",
                "scheduled_local": "2026-08-31T04:30:00+07:00",
                "generated_at_utc": "2026-08-31T02:09:50+00:00",
                "generated_local": "2026-08-31T09:09:50+07:00",
                "status": "LATE_RECOVERED",
                "timeliness": "LATE_RECOVERED",
            }
        ]
    }


def test_late_recovery_remains_amber_on_later_routine_run_same_day():
    checkpoint, updated = resolve_report_checkpoint(
        datetime(2026, 8, 31, 2, 10, tzinfo=timezone.utc),
        _late_recovered_state(),
        _policy(),
    )

    assert checkpoint["current"]["kind"] == "ROUTINE"
    assert checkpoint["completeness"] == "RECOVERED"
    assert checkpoint["missed_due"] == []
    assert [row["id"] for row in checkpoint["recovered_late"]] == ["DAILY_DEEP"]
    assert checkpoint["recovered_late"][0]["recovered_local"] == "2026-08-31T09:09:50+07:00"
    assert checkpoint["today"][0]["state"] == "LATE_RECOVERED"
    assert len(updated["checkpoint_history"]) == 1

    health = _operational_health(checkpoint, "GREEN")
    assert health["overall"] == "AMBER"
    assert health["engine"] == "GREEN"
    assert health["checkpoint"] == "AMBER"
    assert health["late_recovered_checkpoint_ids"] == ["DAILY_DEEP"]
    assert health["checkpoint_completeness"] == "RECOVERED"


def test_historical_late_recovery_does_not_masquerade_as_new_recovery_event():
    checkpoint, _ = resolve_report_checkpoint(
        datetime(2026, 8, 31, 2, 10, tzinfo=timezone.utc),
        _late_recovered_state(),
        _policy(),
    )

    assert checkpoint["current"].get("id") is None
    assert checkpoint["current"]["kind"] == "ROUTINE"
    assert [row["id"] for row in checkpoint["recovered_late"]] == ["DAILY_DEEP"]
