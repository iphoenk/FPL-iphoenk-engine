from src.runtime_v6.report_contract import build_status_view


def test_scheduler_proof_and_last_good_age_are_explicit_at_observation_time():
    view = build_status_view(
        observed_at="2026-09-14T12:31:00+07:00",
        core_transport="PASS",
        acquisition="PASS",
        publish_integrity="PASS",
        publish_validation="PASS",
        new_publication="PROMOTED",
        last_good_state="AVAILABLE",
        last_good_generated_at="2026-09-14T11:31:00+07:00",
        scheduler_proof_state="CURRENT",
        scheduler_proof_at="2026-09-14T12:00:00+07:00",
        report_prefetch="PASS",
        target_report_freshness="COMPLETE",
        auth="NOT REQUESTED",
        report_delivery="PASS | FRESH V6",
    )

    assert view["LAST-GOOD"]["last_good_age_seconds"] == 3600.0
    assert view["SCHEDULER PROOF"]["scheduler_proof_age_seconds"] == 1860.0
    assert view["SCHEDULER PROOF"]["observed_at"] == "2026-09-14T05:31:00+00:00"
    assert view["SCHEDULER PROOF"]["source_at"] == "2026-09-14T05:00:00+00:00"
