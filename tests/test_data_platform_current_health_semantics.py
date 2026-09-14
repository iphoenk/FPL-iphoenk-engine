from __future__ import annotations

from src.runtime_v6.current_health import (
    build_current_status_view,
    current_report_semantics,
)


OBSERVED = "2026-09-14T16:31:12+07:00"


def _core_control():
    return {
        "schedule_kind": "chatgpt_scheduler",
        "report_prefetch": False,
    }


def _report_control():
    return {
        "schedule_kind": "report_prefetch",
        "report_prefetch": True,
    }


def _historical_stale_prefetch():
    return {
        "generated_at": "2026-09-14T05:31:56+00:00",
        "prefetch_status": "STALE",
        "strict_prefetch_status": "STALE",
        "public_core_status": "STALE",
        "public_core_complete": True,
        "fresh_for_target_report": False,
    }


def test_normal_core_ignores_historical_stale_report_prefetch():
    result = current_report_semantics(
        runtime_control=_core_control(),
        prefetch_health=_historical_stale_prefetch(),
    )
    assert result["report_prefetch"] == "N/A"
    assert result["target_report_freshness"] == "N/A"
    assert result["report_delivery"] == "N/A"
    assert result["report_mode"] == "NORMAL"
    assert result["historical_prefetch_ignored"] is True
    assert result["historical_prefetch_status"] == "STALE"


def test_build_current_status_view_cannot_leak_old_stale_state_into_core():
    view = build_current_status_view(
        runtime_control=_core_control(),
        prefetch_health=_historical_stale_prefetch(),
        observed_at=OBSERVED,
        core_transport="PASS",
        acquisition="PASS",
        publish_integrity="PASS",
        publish_validation="PASS",
        new_publication="PROMOTED",
        last_good_state="AVAILABLE",
        last_good_generated_at="2026-09-14T16:31:00+07:00",
        scheduler_proof_state="CURRENT",
        scheduler_proof_at="2026-09-14T16:30:00+07:00",
        report_prefetch="STALE",
        target_report_freshness="STALE",
        auth="NOT REQUESTED",
        report_delivery="DEGRADED",
    )
    assert view["REPORT PREFETCH"]["state"] == "N/A"
    assert view["TARGET REPORT FRESHNESS"]["state"] == "N/A"
    assert view["REPORT DELIVERY"]["state"] == "N/A"
    assert view["CORE TRANSPORT"]["state"] == "PASS"


def test_current_report_fresh_public_scope_is_complete_even_if_strict_auth_is_amber():
    result = current_report_semantics(
        runtime_control=_report_control(),
        prefetch_health={
            "prefetch_status": "AMBER",
            "strict_prefetch_status": "AMBER",
            "public_core_status": "GREEN",
            "public_core_complete": True,
            "fresh_for_target_report": True,
            "authenticated_personal_deferred": True,
        },
    )
    assert result["report_prefetch"] == "PASS"
    assert result["target_report_freshness"] == "COMPLETE"
    assert result["report_delivery"] == "PASS | FRESH V6"
    assert result["report_mode"] == "NORMAL"
    assert result["strict_prefetch_status"] == "AMBER"


def test_optional_provider_amber_is_warning_only_not_aggregate_degradation():
    result = current_report_semantics(
        runtime_control=_report_control(),
        prefetch_health={
            "public_core_status": "GREEN",
            "public_core_complete": True,
            "fresh_for_target_report": True,
        },
        optional_scope_states={"understat": "AMBER"},
    )
    assert result["report_mode"] == "NORMAL"
    assert result["report_prefetch"] == "PASS"
    assert result["optional_scope_warnings"] == {"understat": "AMBER"}


def test_genuinely_stale_current_report_input_degrades_only_report_layer():
    result = current_report_semantics(
        runtime_control=_report_control(),
        prefetch_health={
            "public_core_status": "STALE",
            "public_core_complete": True,
            "fresh_for_target_report": False,
        },
    )
    assert result["report_prefetch"] == "STALE"
    assert result["target_report_freshness"] == "STALE"
    assert result["report_mode"] == "DEGRADED"
    assert result["report_delivery"] == "DEGRADED | CURRENT REPORT INPUT STALE"


def test_required_scope_failure_degrades_current_report_but_not_optional_scope():
    result = current_report_semantics(
        runtime_control=_report_control(),
        prefetch_health={
            "public_core_status": "GREEN",
            "public_core_complete": True,
            "fresh_for_target_report": True,
        },
        required_scope_states={"icon_standings": "STALE"},
        optional_scope_states={"understat": "AMBER"},
    )
    assert result["report_mode"] == "DEGRADED"
    assert result["required_scope_failures"] == {"icon_standings": "STALE"}
    assert result["optional_scope_warnings"] == {"understat": "AMBER"}


def test_late_but_fresh_report_is_not_stale_when_prefetch_health_is_green():
    result = current_report_semantics(
        runtime_control=_report_control(),
        prefetch_health={
            "public_core_status": "GREEN",
            "public_core_complete": True,
            "fresh_for_target_report": True,
            "generated_at": "2026-09-14T05:31:56+00:00",
        },
    )
    assert result["report_prefetch"] == "PASS"
    assert result["target_report_freshness"] == "COMPLETE"
    assert result["report_mode"] == "NORMAL"
