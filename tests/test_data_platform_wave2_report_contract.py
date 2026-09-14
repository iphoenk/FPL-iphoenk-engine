from __future__ import annotations

from src.runtime_v6.report_contract import (
    REPORT_MODES,
    VISIBLE_STATUS_LAYERS,
    build_status_view,
    choose_report_source,
    core_slot_key,
    map_auth_status,
    report_delivery_status,
    safety_net_decision,
)


OBSERVED = "2026-09-14T12:31:00+07:00"
LOGICAL = "2026-09-14T12:30:00+07:00"


def test_all_wave2_report_modes_are_explicitly_regressed():
    assert REPORT_MODES == {
        "normal_hourly",
        "04:30_deep",
        "05:30_price",
        "12:30_deep",
        "21:30_deep",
        "match_mode",
        "deadline_mode",
        "ad_hoc_deep",
    }


def test_core_slot_idempotency_key_includes_schedule_kind_and_logical_slot():
    assert core_slot_key("chatgpt_scheduler", LOGICAL) == f"chatgpt_scheduler|{LOGICAL}"
    assert core_slot_key("report_prefetch", LOGICAL) != core_slot_key("chatgpt_scheduler", LOGICAL)


def test_safety_net_is_noop_when_primary_owns_slot():
    decision = safety_net_decision(
        logical_slot=LOGICAL,
        primary_owned=True,
        prefetched=False,
        delivered=False,
    )
    assert decision["action"] == "NO_OP"
    assert decision["deduplicated"] is True
    assert "PRIMARY_OWNS_SLOT" in decision["reason"]


def test_safety_net_is_noop_when_slot_was_prefetched_or_delivered():
    prefetched = safety_net_decision(
        logical_slot=LOGICAL,
        primary_owned=False,
        prefetched=True,
        delivered=False,
    )
    delivered = safety_net_decision(
        logical_slot=LOGICAL,
        primary_owned=False,
        prefetched=False,
        delivered=True,
    )
    assert prefetched["action"] == "NO_OP"
    assert delivered["action"] == "NO_OP"


def test_safety_net_recovers_only_unowned_unprefetched_undelivered_slot():
    decision = safety_net_decision(
        logical_slot=LOGICAL,
        primary_owned=False,
        prefetched=False,
        delivered=False,
    )
    assert decision == {
        "logical_slot": LOGICAL,
        "action": "RECOVER",
        "reason": "UNOWNED_UNPREFETCHED_UNDELIVERED_SLOT",
        "deduplicated": False,
    }


def test_report_fallback_order_is_fresh_v6_then_direct_then_last_good_then_unavailable():
    assert choose_report_source(
        fresh_v6_available=True,
        direct_fresh_available=True,
        last_good_available=True,
        field_is_volatile=False,
    ) == "FRESH_V6"
    assert choose_report_source(
        fresh_v6_available=False,
        direct_fresh_available=True,
        last_good_available=True,
        field_is_volatile=False,
    ) == "DIRECT_FRESH"
    assert choose_report_source(
        fresh_v6_available=False,
        direct_fresh_available=False,
        last_good_available=True,
        field_is_volatile=False,
    ) == "LAST_GOOD_NONVOLATILE"
    assert choose_report_source(
        fresh_v6_available=False,
        direct_fresh_available=False,
        last_good_available=True,
        field_is_volatile=True,
    ) == "UNAVAILABLE"


def test_v6_failure_does_not_fail_due_report_when_direct_fresh_fallback_exists():
    assert report_delivery_status(
        due=True,
        fresh_v6_available=False,
        direct_fresh_available=True,
        last_good_nonvolatile_available=True,
    ) == "PASS | DIRECT FRESH FALLBACK"


def test_due_report_is_still_delivered_with_explicit_unavailable_fields_when_no_source_exists():
    assert report_delivery_status(
        due=True,
        fresh_v6_available=False,
        direct_fresh_available=False,
        last_good_nonvolatile_available=False,
    ) == "PASS | UNAVAILABLE FIELDS DISCLOSED"


def test_auth_not_requested_is_not_misreported_as_expired():
    assert map_auth_status(requested=False, raw_state="AUTH_EXPIRED") == "NOT REQUESTED"
    assert map_auth_status(requested=True, raw_state="AUTH_EXPIRED") == "EXPIRED"
    assert map_auth_status(requested=True, raw_state="AUTH_AVAILABLE") == "OK"


def test_local_publish_failure_remains_granular_and_report_delivery_can_pass():
    view = build_status_view(
        observed_at=OBSERVED,
        core_transport="PASS",
        acquisition="PASS",
        publish_integrity="FAIL",
        publish_validation="FAIL",
        new_publication="NOT PROMOTED",
        last_good_state="AVAILABLE",
        last_good_generated_at="2026-09-14T11:31:00+07:00",
        scheduler_proof_state="CURRENT",
        scheduler_proof_at="2026-09-14T12:00:00+07:00",
        report_prefetch="PASS",
        target_report_freshness="COMPLETE",
        auth="NOT REQUESTED",
        report_delivery="PASS | DIRECT FRESH FALLBACK",
    )
    assert tuple(view) == VISIBLE_STATUS_LAYERS
    assert view["PUBLISH VALIDATION"]["state"] == "FAIL"
    assert view["NEW PUBLICATION"]["state"] == "NOT PROMOTED"
    assert view["LAST-GOOD"]["state"] == "AVAILABLE"
    assert view["LAST-GOOD"]["age_seconds"] == 3600.0
    assert view["SCHEDULER PROOF"]["age_seconds"] == 1860.0
    assert view["REPORT DELIVERY"]["state"] == "PASS | DIRECT FRESH FALLBACK"


def test_stale_optional_component_does_not_force_whole_status_to_failed():
    view = build_status_view(
        observed_at=OBSERVED,
        core_transport="PASS",
        acquisition="PASS",
        publish_integrity="PASS",
        publish_validation="PASS",
        new_publication="PROMOTED",
        last_good_state="AVAILABLE",
        last_good_generated_at="2026-09-14T12:30:30+07:00",
        scheduler_proof_state="CURRENT",
        scheduler_proof_at="2026-09-14T12:00:00+07:00",
        report_prefetch="PASS",
        target_report_freshness="PARTIAL | PREDICTOR STALE",
        auth="OK",
        report_delivery="PASS | FRESH V6",
    )
    assert view["TARGET REPORT FRESHNESS"]["state"] == "PARTIAL | PREDICTOR STALE"
    assert view["CORE TRANSPORT"]["state"] == "PASS"
    assert view["ACQUISITION"]["state"] == "PASS"
    assert view["REPORT DELIVERY"]["state"] == "PASS | FRESH V6"


def test_observed_time_is_distinct_from_logical_slot():
    view = build_status_view(
        observed_at=OBSERVED,
        core_transport="PASS",
        acquisition="PASS",
        publish_integrity="PASS",
        publish_validation="PASS",
        new_publication="PROMOTED",
        last_good_state="AVAILABLE",
        last_good_generated_at="2026-09-14T12:30:45+07:00",
        scheduler_proof_state="CURRENT",
        scheduler_proof_at=LOGICAL,
        report_prefetch="N/A",
        target_report_freshness="N/A",
        auth="NOT REQUESTED",
        report_delivery="N/A",
    )
    assert view["CORE TRANSPORT"]["observed_at"] == "2026-09-14T05:31:00+00:00"
    assert view["SCHEDULER PROOF"]["source_at"] == "2026-09-14T05:30:00+00:00"
    assert view["SCHEDULER PROOF"]["age_seconds"] == 60.0
