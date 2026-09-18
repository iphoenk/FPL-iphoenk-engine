from __future__ import annotations

from datetime import datetime, timezone

import pytest

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


def _occurrence_snapshot(
    *,
    report_kind: str,
    logical_slot: str,
    generated_at: str,
    request_id: str,
    scope: tuple[str, ...] = (),
):
    requested = set(scope)
    return {
        "schema_version": 2,
        "report_kind": report_kind,
        "target_logical_report_slot": logical_slot,
        "generated_at": generated_at,
        "request_id": request_id,
        "report_prefetch_run_id": request_id,
        "personal_requested": "personal" in requested,
        "mini_league_requested": "mini_league" in requested,
        "live_requested": "live" in requested,
        "complete": True,
        "public_core_complete": True,
        "fresh_for_target_report": True,
        "source_failures": [],
    }


def test_original_0830_occurrence_is_selected_after_latest_advances_to_0930():
    original = _occurrence_snapshot(
        report_kind="deadline_review",
        logical_slot="2026-09-18T08:30:00+07:00",
        generated_at="2026-09-18T08:29:00+07:00",
        request_id="prefetch-0830",
        scope=("personal", "mini_league"),
    )
    latest = _occurrence_snapshot(
        report_kind="deadline_review",
        logical_slot="2026-09-18T09:30:00+07:00",
        generated_at="2026-09-18T09:29:00+07:00",
        request_id="prefetch-0930",
        scope=("personal", "mini_league"),
    )

    selector = getattr(report_prefetch, "select_report_prefetch_occurrence", None)
    assert callable(selector), "report-prefetch consumer must bind retrieval to the exact occurrence"
    selected = selector(
        latest,
        occurrence_snapshots=[original],
        report_kind="deadline_review",
        requested_logical_slot="2026-09-18T08:30:00+07:00",
        scope=("personal", "mini_league"),
    )

    assert selected is not None
    assert selected["target_logical_report_slot"] == "2026-09-18T08:30:00+07:00"
    assert selected["report_prefetch_run_id"] == "prefetch-0830"

    readiness = report_prefetch.evaluate_report_prefetch_readiness(
        latest,
        occurrence_snapshots=[original],
        report_kind="deadline_review",
        requested_logical_slot="2026-09-18T08:30:00+07:00",
        maximum_age_minutes=35,
        scope=("personal", "mini_league"),
        observed_at="2026-09-18T08:31:00+07:00",
    )
    assert readiness["ready"] is True
    assert readiness["freshness_status"] == "CURRENT"
    assert readiness["selected_target_logical_report_slot"] == "2026-09-18T08:30:00+07:00"
    assert readiness["selected_report_prefetch_run_id"] == "prefetch-0830"


@pytest.mark.parametrize(
    ("report_kind", "slot", "later_slot", "scope"),
    [
        ("full_master", "2026-09-18T09:30:00+07:00", "2026-09-18T10:30:00+07:00", ("personal", "mini_league")),
        ("05:30_price", "2026-09-18T05:30:00+07:00", "2026-09-18T06:30:00+07:00", ("mini_league",)),
        ("deadline_review", "2026-09-18T11:30:00+07:00", "2026-09-18T12:30:00+07:00", ("personal", "mini_league")),
        ("ad_hoc", "2026-09-18T10:37:14+07:00", "2026-09-18T10:38:14+07:00", ("personal", "mini_league")),
    ],
)
def test_occurrence_binding_survives_later_latest_for_all_governed_modes(
    report_kind, slot, later_slot, scope
):
    original = _occurrence_snapshot(
        report_kind=report_kind,
        logical_slot=slot,
        generated_at=slot,
        request_id=f"{report_kind}-original",
        scope=scope,
    )
    later = _occurrence_snapshot(
        report_kind=report_kind,
        logical_slot=later_slot,
        generated_at=later_slot,
        request_id=f"{report_kind}-later",
        scope=scope,
    )

    selected = report_prefetch.select_report_prefetch_occurrence(
        later,
        occurrence_snapshots=[original],
        report_kind=report_kind,
        requested_logical_slot=slot,
        scope=scope,
    )
    assert selected["report_prefetch_run_id"] == f"{report_kind}-original"
    assert selected["target_logical_report_slot"] == slot


def test_delayed_recovery_keeps_exact_occurrence_identity_and_recomputes_freshness():
    original = _occurrence_snapshot(
        report_kind="deadline_review",
        logical_slot="2026-09-18T08:30:00+07:00",
        generated_at="2026-09-18T08:29:00+07:00",
        request_id="prefetch-0830",
        scope=("personal", "mini_league"),
    )
    latest = _occurrence_snapshot(
        report_kind="deadline_review",
        logical_slot="2026-09-18T09:30:00+07:00",
        generated_at="2026-09-18T09:29:00+07:00",
        request_id="prefetch-0930",
        scope=("personal", "mini_league"),
    )
    result = report_prefetch.evaluate_report_prefetch_readiness(
        latest,
        occurrence_snapshots=[original],
        report_kind="deadline_review",
        requested_logical_slot="2026-09-18T08:30:00+07:00",
        maximum_age_minutes=35,
        scope=("personal", "mini_league"),
        observed_at="2026-09-18T09:10:00+07:00",
    )

    assert result["selected_report_prefetch_run_id"] == "prefetch-0830"
    assert result["freshness_status"] == "STALE"
    assert result["refresh_required"] is True
    assert "logical_slot=2026-09-18T08:30:00+07:00" in result["refresh_command"]


def test_explicit_prefetch_identity_disambiguates_duplicate_same_occurrence():
    first = _occurrence_snapshot(
        report_kind="deadline_review",
        logical_slot="2026-09-18T08:30:00+07:00",
        generated_at="2026-09-18T08:29:00+07:00",
        request_id="prefetch-first",
        scope=("personal", "mini_league"),
    )
    recovery = _occurrence_snapshot(
        report_kind="deadline_review",
        logical_slot="2026-09-18T08:30:00+07:00",
        generated_at="2026-09-18T08:31:00+07:00",
        request_id="prefetch-recovery",
        scope=("personal", "mini_league"),
    )

    selected = report_prefetch.select_report_prefetch_occurrence(
        recovery,
        occurrence_snapshots=[first],
        report_kind="deadline_review",
        requested_logical_slot="2026-09-18T08:30:00+07:00",
        scope=("personal", "mini_league"),
        report_prefetch_identity="prefetch-first",
    )
    assert selected["report_prefetch_run_id"] == "prefetch-first"


def test_occurrence_binding_requires_exact_timezone_aware_slot():
    snapshot = _occurrence_snapshot(
        report_kind="full_master",
        logical_slot="2026-09-18T12:30:00+07:00",
        generated_at="2026-09-18T12:29:00+07:00",
        request_id="prefetch-1230",
        scope=("personal", "mini_league"),
    )
    with pytest.raises(report_prefetch.PrefetchContractError):
        report_prefetch.select_report_prefetch_occurrence(
            snapshot,
            occurrence_snapshots=[],
            report_kind="full_master",
            requested_logical_slot="2026-09-18T12:30:00",
            scope=("personal", "mini_league"),
        )
