from __future__ import annotations

from datetime import datetime, timezone

from src.runtime_v6.domains.report_plane import report_prefetch
from src.runtime_v6.domains.control_plane.runtime_control import build_runtime_control


REQUEST_SLOT = "2026-09-18T04:30:00+07:00"


def _stale_snapshot():
    return {
        "schema_version": 2,
        "report_kind": "full_master",
        "generated_at": "2026-09-16T17:26:00+07:00",
        "complete": True,
        "public_core_complete": True,
        "fresh_for_target_report": True,
        "source_failures": [],
    }


def _evaluate(snapshot, *, refresh_attempt=0):
    evaluator = getattr(report_prefetch, "evaluate_report_prefetch_readiness", None)
    assert callable(evaluator), "IR3 requires the existing report_prefetch owner to expose read-time readiness"
    return evaluator(
        snapshot,
        report_kind="full_master",
        requested_logical_slot=REQUEST_SLOT,
        maximum_age_minutes=35,
        refresh_attempt=refresh_attempt,
        max_refresh_attempts=1,
        reason="fpl_master_report_prefetch_recovery",
    )


def test_stale_prefetch_enters_governed_refresh():
    result = _evaluate(_stale_snapshot())

    assert result["ready"] is False
    assert result["freshness_status"] == "STALE"
    assert result["next_action"] == "GOVERNED_REPORT_PREFETCH_REFRESH"
    assert result["refresh_required"] is True
    assert result["refresh_transport"] == "ISSUE_431_COMMENT"
    assert result["refresh_command"].startswith("/v6-report-prefetch ")
    assert "report_kind=full_master" in result["refresh_command"]
    assert f"logical_slot={REQUEST_SLOT}" in result["refresh_command"]
    assert "reason=fpl_master_report_prefetch_recovery" in result["refresh_command"]
    assert "force=true" in result["refresh_command"]


def test_missing_prefetch_enters_governed_refresh():
    result = _evaluate(None)

    assert result["ready"] is False
    assert result["freshness_status"] == "MISSING"
    assert result["next_action"] == "GOVERNED_REPORT_PREFETCH_REFRESH"
    assert result["refresh_required"] is True
    assert result["refresh_command"].startswith("/v6-report-prefetch ")


def test_prefetch_retry_is_bounded_and_idempotent():
    first = _evaluate(_stale_snapshot(), refresh_attempt=0)
    repeated = _evaluate(_stale_snapshot(), refresh_attempt=0)
    exhausted = _evaluate(_stale_snapshot(), refresh_attempt=1)

    assert first["refresh_command"] == repeated["refresh_command"]
    assert first["refresh_identity"] == repeated["refresh_identity"]
    assert first["max_refresh_attempts"] == 1

    assert exhausted["ready"] is False
    assert exhausted["refresh_required"] is False
    assert exhausted["next_action"] == "REPORT_PREFETCH_RECOVERY_EXHAUSTED"
    assert exhausted["refresh_command"] is None
    assert exhausted["refresh_attempt"] == 1


def test_current_prefetch_uses_derived_timestamp_not_stored_flag():
    current = {
        **_stale_snapshot(),
        "generated_at": "2026-09-18T04:10:00+07:00",
        "fresh_for_target_report": False,
    }
    result = _evaluate(current)

    assert result["ready"] is True
    assert result["freshness_status"] == "CURRENT"
    assert result["fresh_for_target_report"] is True
    assert result["next_action"] == "USE_REPORT_PREFETCH"
    assert result["refresh_required"] is False
    assert result["refresh_command"] is None


def test_report_prefetch_does_not_mutate_core_schedule():
    previous = {
        "runtime_control": {
            "last_chatgpt_scheduler_cycle_at": "2026-09-18T05:00:00+00:00",
            "last_operational_cycle_at": "2026-09-18T05:00:00+00:00",
            "last_authoritative_cycle_at": "2026-09-18T05:00:00+00:00",
        }
    }
    control = build_runtime_control(
        previous,
        now=datetime(2026, 9, 18, 5, 25, tzinfo=timezone.utc),
        event_name="issue_comment",
        schedule_kind="report_prefetch",
        run_id="ir3-report-prefetch",
    )

    assert control["report_prefetch"] is True
    assert control["counts_as_completed_report_slot"] is True
    assert control["counts_as_completed_operational_slot"] is False
    assert control["last_chatgpt_scheduler_cycle_at"] == "2026-09-18T05:00:00+00:00"
    assert control["last_operational_cycle_at"] == "2026-09-18T05:00:00+00:00"
    assert control["report_prefetch_cannot_complete_core_operational_slot"] is True
