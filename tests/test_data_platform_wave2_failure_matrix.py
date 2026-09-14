from src.runtime_v6.report_contract import (
    build_status_view,
    map_auth_status,
    report_delivery_status,
    safety_net_decision,
)


OBSERVED = "2026-09-14T12:31:00+07:00"
LOGICAL = "2026-09-14T12:30:00+07:00"


def _view(**overrides):
    values = {
        "observed_at": OBSERVED,
        "core_transport": "PASS",
        "acquisition": "PASS",
        "publish_integrity": "PASS",
        "publish_validation": "PASS",
        "new_publication": "PROMOTED",
        "last_good_state": "AVAILABLE",
        "last_good_generated_at": "2026-09-14T12:30:30+07:00",
        "scheduler_proof_state": "CURRENT",
        "scheduler_proof_at": LOGICAL,
        "report_prefetch": "PASS",
        "target_report_freshness": "COMPLETE",
        "auth": "NOT REQUESTED",
        "report_delivery": "PASS | FRESH V6",
    }
    values.update(overrides)
    return build_status_view(**values)


def test_provider_amber_is_local_and_report_can_still_pass():
    view = _view(
        acquisition="AMBER | OPTIONAL PROVIDER INCOMPLETE",
        target_report_freshness="PARTIAL | OPTIONAL PROVIDER AMBER",
        report_delivery="PASS | FRESH V6",
    )
    assert view["ACQUISITION"]["state"].startswith("AMBER")
    assert view["REPORT DELIVERY"]["state"] == "PASS | FRESH V6"


def test_auth_unavailable_and_expired_are_not_conflated_with_not_requested():
    assert map_auth_status(requested=False, raw_state="AUTH_UNAVAILABLE") == "NOT REQUESTED"
    assert map_auth_status(requested=True, raw_state="AUTH_UNAVAILABLE") == "FAILED"
    assert map_auth_status(requested=True, raw_state="AUTH_EXPIRED") == "EXPIRED"


def test_stale_predictor_is_local_partial_not_whole_system_failure():
    view = _view(target_report_freshness="PARTIAL | PRICE PREDICTOR STALE")
    assert view["TARGET REPORT FRESHNESS"]["state"] == "PARTIAL | PRICE PREDICTOR STALE"
    assert view["CORE TRANSPORT"]["state"] == "PASS"
    assert view["PUBLISH VALIDATION"]["state"] == "PASS"
    assert view["REPORT DELIVERY"]["state"] == "PASS | FRESH V6"


def test_duplicate_prefetch_safety_net_is_noop():
    decision = safety_net_decision(
        logical_slot=LOGICAL,
        primary_owned=False,
        prefetched=True,
        delivered=False,
    )
    assert decision["action"] == "NO_OP"
    assert decision["deduplicated"] is True
    assert decision["reason"] == "REPORT_ALREADY_PREFETCHED"


def test_delayed_execution_keeps_logical_slot_and_observed_time_distinct():
    delayed_observed = "2026-09-14T12:57:00+07:00"
    view = build_status_view(
        observed_at=delayed_observed,
        core_transport="PASS | DELAYED",
        acquisition="PASS",
        publish_integrity="PASS",
        publish_validation="PASS",
        new_publication="PROMOTED",
        last_good_state="AVAILABLE",
        last_good_generated_at="2026-09-14T12:56:30+07:00",
        scheduler_proof_state="CURRENT | DELAYED EXECUTION",
        scheduler_proof_at=LOGICAL,
        report_prefetch="N/A",
        target_report_freshness="N/A",
        auth="NOT REQUESTED",
        report_delivery="N/A",
    )
    assert view["SCHEDULER PROOF"]["scheduler_proof_age_seconds"] == 1620.0
    assert view["SCHEDULER PROOF"]["source_at"] == "2026-09-14T05:30:00+00:00"
    assert view["SCHEDULER PROOF"]["observed_at"] == "2026-09-14T05:57:00+00:00"


def test_corrupt_candidate_blocked_publication_does_not_auto_fail_due_report():
    delivery = report_delivery_status(
        due=True,
        fresh_v6_available=False,
        direct_fresh_available=True,
        last_good_nonvolatile_available=True,
    )
    view = _view(
        publish_integrity="FAIL | CORRUPT CANDIDATE",
        publish_validation="BLOCKED",
        new_publication="NOT PROMOTED",
        report_delivery=delivery,
    )
    assert view["PUBLISH_INTEGRITY"]["state"] == "FAIL | CORRUPT CANDIDATE"
    assert view["NEW PUBLICATION"]["state"] == "NOT PROMOTED"
    assert view["LAST-GOOD"]["state"] == "AVAILABLE"
    assert view["REPORT DELIVERY"]["state"] == "PASS | DIRECT FRESH FALLBACK"
