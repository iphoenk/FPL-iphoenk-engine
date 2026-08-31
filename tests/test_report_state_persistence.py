from datetime import datetime, timezone

from src.engines import report_architecture
from src.engines.report_user_presentation import resolve_report_checkpoint


def _recovered_state() -> dict:
    return {
        "generated_at": "2026-08-31T01:53:00+00:00",
        "fingerprint": "old",
        "state": {"squad": "HOLD"},
        "last_report_mode": "FULL_OR_DELTA",
        "last_decision": {"overall": "REVIEW"},
        "checkpoint_history": [
            {
                "slot_id": "DAILY_DEEP",
                "label": "Review pagi 04:30 WIB",
                "local_date": "2026-08-31",
                "scheduled_local": "2026-08-31T04:30:00+07:00",
                "generated_at_utc": "2026-08-31T01:53:00+00:00",
                "generated_local": "2026-08-31T08:53:00+07:00",
                "status": "LATE_RECOVERED",
                "timeliness": "LATE_RECOVERED",
            }
        ],
        "last_checkpoint": {"completeness": "RECOVERED"},
        "operational_health": {"overall": "AMBER", "checkpoint": "AMBER"},
        "obsolete_extension": {"must_not_survive": True},
    }


def test_report_state_persistence_policy_is_whitelist_owned():
    policy = report_architecture.load_policy()["state_persistence"]
    assert policy["preserve_across_rebuild"] == [
        "checkpoint_history",
        "last_checkpoint",
        "operational_health",
    ]
    assert policy["unknown_extension_policy"] == "DROP"
    assert policy["core_state_is_rebuilt_each_report"] is True


def test_report_architecture_build_preserves_checkpoint_extensions(monkeypatch):
    previous = _recovered_state()

    def fake_read_json(path, default):
        if path == report_architecture.STATE_OUT:
            return previous
        return {}

    monkeypatch.setattr(report_architecture, "read_json", fake_read_json)
    _, _, rebuilt = report_architecture.build()

    assert rebuilt["checkpoint_history"] == previous["checkpoint_history"]
    assert rebuilt["last_checkpoint"] == previous["last_checkpoint"]
    assert rebuilt["operational_health"] == previous["operational_health"]
    assert "obsolete_extension" not in rebuilt
    assert rebuilt["fingerprint"] != "old"
    assert rebuilt["state"] != previous["state"]


def test_recovered_checkpoint_stays_completed_after_routine_rebuild(monkeypatch):
    previous = _recovered_state()

    def fake_read_json(path, default):
        if path == report_architecture.STATE_OUT:
            return previous
        return {}

    monkeypatch.setattr(report_architecture, "read_json", fake_read_json)
    _, _, rebuilt = report_architecture.build()

    checkpoint, updated = resolve_report_checkpoint(
        datetime(2026, 8, 31, 1, 59, tzinfo=timezone.utc),
        rebuilt,
    )

    assert checkpoint["missed_due"] == []
    assert checkpoint["today"][0]["state"] == "LATE_RECOVERED"
    assert updated["checkpoint_history"][0]["status"] == "LATE_RECOVERED"
    assert len(updated["checkpoint_history"]) == 1
