from __future__ import annotations

import pytest

from src.runtime_v6.report_contract import (
    REPORT_MODES,
    build_status_view,
    choose_report_source,
    map_auth_status,
    report_delivery_status,
)
from src.runtime_v6.wave2_control_plane import (
    WAVE2_FAILURE_MAPPINGS,
    WAVE2_REPORT_MODES,
    advance_report_slot_ledger,
    control_plane_state_from_ledger,
    price_checkpoint_contract,
    safety_net_from_ledger,
)


def _core_ledger():
    return {
        "schema_version": 4,
        "slots": [
            {
                "slot": "2026-09-14T06:00:00+00:00",
                "fulfilled_by": "CHATGPT",
                "fulfilled": True,
                "observed_at": "2026-09-14T06:31:00+00:00",
                "run_id": "1001",
                "schedule_kind": "chatgpt_scheduler",
                "core_slot_key": "chatgpt_scheduler|2026-09-14T06:00:00+00:00",
                "publication_generation_id": "publication-1001",
            }
        ],
        "auxiliary_operational_slots": [
            {
                "slot": "2026-09-14T06:30:00+00:00",
                "fulfilled_by": "MASTER_AUXILIARY",
                "fulfilled": True,
                "observed_at": "2026-09-14T06:32:00+00:00",
                "schedule_kind": "report_prefetch",
            }
        ],
    }


def test_wave2_report_mode_matrix_is_complete():
    assert tuple(sorted(REPORT_MODES)) == tuple(sorted(WAVE2_REPORT_MODES))
    assert set(WAVE2_FAILURE_MAPPINGS) == {
        "provider_amber",
        "auth_unavailable",
        "auth_expired",
        "stale_predictor",
        "duplicate_prefetch",
        "delayed_execution",
        "corrupt_candidate",
    }


@pytest.mark.parametrize("mode", WAVE2_REPORT_MODES)
def test_every_wave2_report_mode_keeps_full_visible_status_contract(mode):
    view = build_status_view(
        observed_at="2026-09-14T12:31:00+07:00",
        core_transport="PASS",
        acquisition="PASS",
        publish_integrity="PASS",
        publish_validation="PASS",
        new_publication="PROMOTED",
        last_good_state="AVAILABLE",
        last_good_generated_at="2026-09-14T12:30:30+07:00",
        scheduler_proof_state="CURRENT",
        scheduler_proof_at="2026-09-14T12:00:00+07:00",
        report_prefetch="PASS" if mode != "normal_hourly" else "N/A",
        target_report_freshness="COMPLETE" if mode != "normal_hourly" else "N/A",
        auth="NOT REQUESTED",
        report_delivery="PASS | FRESH V6" if mode != "normal_hourly" else "N/A",
    )
    assert list(view) == [
        "CORE TRANSPORT",
        "ACQUISITION",
        "PUBLISH_INTEGRITY",
        "PUBLISH VALIDATION",
        "NEW PUBLICATION",
        "LAST-GOOD",
        "SCHEDULER PROOF",
        "REPORT PREFETCH",
        "TARGET REPORT FRESHNESS",
        "AUTH",
        "REPORT DELIVERY",
    ]
    assert view["SCHEDULER PROOF"]["scheduler_proof_at"] == "2026-09-14T12:00:00+07:00"
    assert view["LAST-GOOD"]["generated_at"] == "2026-09-14T12:30:30+07:00"


def test_prefetch_does_not_advance_core_scheduler_proof():
    state = control_plane_state_from_ledger(
        _core_ledger(), observed_at="2026-09-14T06:40:00+00:00"
    )
    assert state["last_chatgpt_scheduler_cycle_at"] == "2026-09-14T06:31:00+00:00"
    assert state["last_authoritative_cycle_at"] == "2026-09-14T06:31:00+00:00"
    assert state["last_operational_cycle_at"] == "2026-09-14T06:32:00+00:00"
    assert state["last_processed_logical_slot"] == "2026-09-14T06:00:00+00:00"
    assert state["next_expected_logical_slot"] == "2026-09-14T07:00:00+00:00"
    assert state["scheduler_proof_age_seconds"] == 540.0
    assert state["run_provenance"]["slot_key"] == "chatgpt_scheduler|2026-09-14T06:00:00+00:00"


def test_report_slot_first_owner_wins_and_safety_net_noops_after_prefetch():
    ledger = advance_report_slot_ledger(
        None,
        report_kind="12:30_deep",
        logical_slot="2026-09-14T12:30:00+07:00",
        observed_at="2026-09-14T12:01:00+07:00",
        owner="FPL_MASTER_MONITOR",
        prefetched=True,
    )
    decision = safety_net_from_ledger(
        ledger,
        report_kind="12:30_deep",
        logical_slot="2026-09-14T12:30:00+07:00",
    )
    assert decision["action"] == "NO_OP"
    assert decision["deduplicated"] is True

    second = advance_report_slot_ledger(
        ledger,
        report_kind="12:30_deep",
        logical_slot="2026-09-14T12:30:00+07:00",
        observed_at="2026-09-14T12:38:00+07:00",
        owner="FPL_REPORT_SAFETY_NET",
        delivered=True,
    )
    row = second["slots"][0]
    assert row["owner"] == "FPL_MASTER_MONITOR"
    assert row["ownership_conflict"] is True
    assert row["delivered"] is False


def test_safety_net_recovers_only_unowned_unprefetched_undelivered_slot():
    decision = safety_net_from_ledger(
        None,
        report_kind="05:30_price",
        logical_slot="2026-09-14T05:30:00+07:00",
    )
    assert decision["action"] == "RECOVER"
    assert decision["deduplicated"] is False


def test_price_contract_never_promotes_legacy_id_to_official_predictor():
    contract = price_checkpoint_contract(
        official_price_fact_count=658,
        predictor={
            "source_id": "official_price_predictor",
            "availability": "AVAILABLE",
            "semantic_class": "DERIVED_MARKET_SIGNAL",
            "provenance_label": "V6_DERIVED_FROM_OFFICIAL_FPL_BOOTSTRAP",
            "predictor_official_status": "UNVERIFIED_NOT_OFFICIAL",
            "independent_official_product_evidence": False,
        },
        mini_league_status="AVAILABLE",
        target_frontier_available=True,
        auth_requested=False,
    )
    assert contract["status"] == "PASS"
    assert contract["predictor_may_be_called_official"] is False
    assert contract["auth"] == "NOT REQUESTED"


def test_price_contract_is_partial_not_report_failure_when_predictor_stale_or_missing():
    contract = price_checkpoint_contract(
        official_price_fact_count=658,
        predictor=None,
        mini_league_status="PARTIAL",
        target_frontier_available=True,
        auth_requested=False,
    )
    assert contract["status"] == "PARTIAL"
    assert "PREDICTOR_UNAVAILABLE" in contract["reasons"]
    assert contract["report_delivery_required_even_if_partial"] is True


def test_auth_mapping_keeps_not_requested_distinct_from_expired():
    assert map_auth_status(requested=False, raw_state="AUTH_EXPIRED") == "NOT REQUESTED"
    assert map_auth_status(requested=True, raw_state="AUTH_EXPIRED") == "EXPIRED"
    assert map_auth_status(requested=True, raw_state="AUTH_UNAVAILABLE") == "FAILED"


def test_provider_amber_and_stale_predictor_remain_local_not_whole_system_stale():
    view = build_status_view(
        observed_at="2026-09-14T12:31:00+07:00",
        core_transport="PASS",
        acquisition="AMBER | OPTIONAL PROVIDER",
        publish_integrity="PASS",
        publish_validation="PASS",
        new_publication="PROMOTED",
        last_good_state="AVAILABLE",
        last_good_generated_at="2026-09-14T12:30:30+07:00",
        scheduler_proof_state="CURRENT",
        scheduler_proof_at="2026-09-14T12:00:00+07:00",
        report_prefetch="PASS",
        target_report_freshness="PARTIAL | PREDICTOR STALE",
        auth="NOT REQUESTED",
        report_delivery="PASS | FRESH V6",
    )
    assert view["ACQUISITION"]["state"].startswith("AMBER")
    assert view["TARGET REPORT FRESHNESS"]["state"].startswith("PARTIAL")
    assert view["PUBLISH VALIDATION"]["state"] == "PASS"
    assert view["REPORT DELIVERY"]["state"] == "PASS | FRESH V6"


def test_v6_failure_does_not_cancel_due_report_when_scoped_direct_fresh_exists():
    assert report_delivery_status(
        due=True,
        fresh_v6_available=False,
        direct_fresh_available=True,
        last_good_nonvolatile_available=True,
    ) == "PASS | DIRECT FRESH FALLBACK"


def test_corrupt_candidate_keeps_last_good_and_allows_due_report_direct_fresh():
    source = choose_report_source(
        fresh_v6_available=False,
        direct_fresh_available=True,
        last_good_available=True,
        field_is_volatile=False,
        v6_scope_state="PUBLICATION_CORRUPT",
    )
    assert source == "DIRECT_FRESH"
