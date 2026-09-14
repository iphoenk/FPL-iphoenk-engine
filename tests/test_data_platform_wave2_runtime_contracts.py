from __future__ import annotations

from src.runtime_v6.adapters import collect_price_predictor
from src.runtime_v6.operational_ledger import build_operational_slots


def _core_control(*, run_id: str, observed_at: str, generation: str) -> dict:
    return {
        "counts_as_completed_operational_slot": True,
        "expected_cycle_at": "2026-09-14T06:00:00+00:00",
        "chatgpt_scheduler": True,
        "run_id": run_id,
        "cycle_observed_at": observed_at,
        "schedule_kind": "chatgpt_scheduler",
        "scheduler_interval_minutes": 60,
        "schedule_lag_seconds": 60.0,
        "publication_generation_id": generation,
        "source_commit": "a" * 40,
        "runtime_branch": "runtime-data-v6",
    }


def test_duplicate_core_trigger_preserves_first_owner_and_provenance():
    first = build_operational_slots(
        None,
        _core_control(
            run_id="1001",
            observed_at="2026-09-14T06:01:00+00:00",
            generation="publication-1001",
        ),
    )
    second = build_operational_slots(
        first,
        _core_control(
            run_id="1002",
            observed_at="2026-09-14T06:02:00+00:00",
            generation="publication-1002",
        ),
    )

    assert len(second["slots"]) == 1
    row = second["slots"][0]
    assert row["run_id"] == "1001"
    assert row["publication_generation_id"] == "publication-1001"
    assert row["duplicate_trigger_count"] == 1
    assert second["summary"]["duplicate_core_attempts"] == 1
    assert second["duplicate_core_attempts"][0]["duplicate_run_id"] == "1002"
    assert second["summary"]["last_chatgpt_scheduler_cycle_at"] == "2026-09-14T06:01:00+00:00"
    assert second["summary"]["last_processed_logical_slot"] == "2026-09-14T06:00:00+00:00"
    assert second["summary"]["next_expected_logical_slot"] == "2026-09-14T07:00:00+00:00"


def test_prefetch_auxiliary_cycle_does_not_advance_authoritative_scheduler_cycle():
    core = build_operational_slots(
        None,
        _core_control(
            run_id="1001",
            observed_at="2026-09-14T06:01:00+00:00",
            generation="publication-1001",
        ),
    )
    auxiliary = build_operational_slots(
        core,
        {
            "counts_as_completed_operational_slot": True,
            "expected_cycle_at": "2026-09-14T06:30:00+00:00",
            "chatgpt_scheduler": False,
            "run_id": "prefetch-1",
            "cycle_observed_at": "2026-09-14T06:31:00+00:00",
            "schedule_kind": "report_prefetch",
            "scheduler_interval_minutes": 60,
        },
    )
    assert auxiliary["summary"]["last_chatgpt_scheduler_cycle_at"] == "2026-09-14T06:01:00+00:00"
    assert auxiliary["summary"]["last_authoritative_cycle_at"] == "2026-09-14T06:01:00+00:00"
    assert auxiliary["summary"]["last_operational_cycle_at"] == "2026-09-14T06:31:00+00:00"


def test_legacy_price_source_id_does_not_create_official_predictor_claim():
    source = {
        "id": "official_price_predictor",
        "name": "Official FPL Price Predictor",
        "category": "market",
        "adapter": "official_price_predictor",
        "critical": True,
        "independence_group": "official_fpl",
        "derived_from": "official_fpl.bootstrap",
        "fields": [
            "id",
            "web_name",
            "now_cost",
            "selected_by_percent",
            "transfers_in_event",
            "transfers_out_event",
            "price_change_percent",
            "price_change_projections",
        ],
    }
    upstream = {
        "health": "GREEN",
        "effective_state": "LIVE_CHANGED",
        "official": {
            "bootstrap": {
                "elements": [
                    {
                        "id": 10,
                        "web_name": "Test",
                        "now_cost": 55,
                        "selected_by_percent": "10.0",
                        "transfers_in_event": 100,
                        "transfers_out_event": 20,
                        "price_change_percent": "60.0",
                        "price_change_projections": [{"offset": 0, "projected_percent": "65.0"}],
                    }
                ]
            }
        },
    }

    payload = collect_price_predictor(source, upstream)
    assert payload["source_id"] == "official_price_predictor"
    assert payload["source_name"] == "V6 Derived Price Change Signal"
    assert payload["legacy_source_name"] == "Official FPL Price Predictor"
    assert payload["semantic_class"] == "DERIVED_MARKET_SIGNAL"
    assert payload["authority_class"] == "MODEL"
    assert payload["predictor_official_status"] == "UNVERIFIED_NOT_OFFICIAL"
    assert payload["independent_official_product_evidence"] is False
    assert payload["authority"]["current_price_facts"] == "OFFICIAL_FPL_BOOTSTRAP"
    assert payload["authority"]["official_fpl_predictor_product_verified"] is False
    assert payload["governance"]["legacy_source_identifier_is_not_authority_proof"] is True
    assert payload["governance"]["may_be_described_as_official_fpl_predictor"] is False
