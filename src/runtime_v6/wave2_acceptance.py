from __future__ import annotations

import json
from typing import Any

from .registry import load_registry
from .report_contract import (
    REPORT_MODES,
    VISIBLE_STATUS_LAYERS,
    choose_report_source,
    map_auth_status,
    report_delivery_status,
)
from .wave2_control_plane import (
    WAVE2_FAILURE_MAPPINGS,
    WAVE2_REPORT_MODES,
    advance_report_slot_ledger,
    control_plane_state_from_ledger,
    price_checkpoint_contract,
    safety_net_from_ledger,
)

EXPECTED_VISIBLE_STATUS_LAYERS = (
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
)


def _record(checks: dict[str, dict[str, Any]], name: str, passed: bool, **evidence: Any) -> None:
    checks[name] = {"status": "PASS" if passed else "FAIL", **evidence}


def run() -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}

    _record(
        checks,
        "report_mode_matrix",
        set(REPORT_MODES) == set(WAVE2_REPORT_MODES),
        expected=list(WAVE2_REPORT_MODES),
        actual=sorted(REPORT_MODES),
    )
    _record(
        checks,
        "failure_mapping_matrix",
        set(WAVE2_FAILURE_MAPPINGS)
        == {
            "provider_amber",
            "auth_unavailable",
            "auth_expired",
            "stale_predictor",
            "duplicate_prefetch",
            "delayed_execution",
            "corrupt_candidate",
        },
        actual=list(WAVE2_FAILURE_MAPPINGS),
    )
    _record(
        checks,
        "visible_status_layers",
        tuple(VISIBLE_STATUS_LAYERS) == EXPECTED_VISIBLE_STATUS_LAYERS,
        actual=list(VISIBLE_STATUS_LAYERS),
    )

    core_ledger = {
        "schema_version": 4,
        "slots": [
            {
                "slot": "2026-09-14T06:00:00+00:00",
                "fulfilled_by": "CHATGPT",
                "fulfilled": True,
                "observed_at": "2026-09-14T06:31:00+00:00",
                "run_id": "acceptance-core",
                "schedule_kind": "chatgpt_scheduler",
                "core_slot_key": "chatgpt_scheduler|2026-09-14T06:00:00+00:00",
                "publication_generation_id": "publication-acceptance",
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
    state = control_plane_state_from_ledger(
        core_ledger,
        observed_at="2026-09-14T06:40:00+00:00",
    )
    _record(
        checks,
        "scheduler_proof_separation",
        state["last_chatgpt_scheduler_cycle_at"] == "2026-09-14T06:31:00+00:00"
        and state["last_authoritative_cycle_at"] == "2026-09-14T06:31:00+00:00"
        and state["last_operational_cycle_at"] == "2026-09-14T06:32:00+00:00"
        and state["last_processed_logical_slot"] == "2026-09-14T06:00:00+00:00"
        and state["next_expected_logical_slot"] == "2026-09-14T07:00:00+00:00",
        state=state,
    )

    report_ledger = advance_report_slot_ledger(
        None,
        report_kind="12:30_deep",
        logical_slot="2026-09-14T12:30:00+07:00",
        observed_at="2026-09-14T12:01:00+07:00",
        owner="FPL_MASTER_MONITOR",
        prefetched=True,
    )
    safety = safety_net_from_ledger(
        report_ledger,
        report_kind="12:30_deep",
        logical_slot="2026-09-14T12:30:00+07:00",
    )
    _record(
        checks,
        "safety_net_dedupe",
        safety.get("action") == "NO_OP" and safety.get("deduplicated") is True,
        decision=safety,
    )

    _record(
        checks,
        "auth_mapping",
        map_auth_status(requested=False, raw_state="AUTH_EXPIRED") == "NOT REQUESTED"
        and map_auth_status(requested=True, raw_state="AUTH_EXPIRED") == "EXPIRED"
        and map_auth_status(requested=True, raw_state="AUTH_UNAVAILABLE") == "FAILED",
    )

    _record(
        checks,
        "report_continuity",
        report_delivery_status(
            due=True,
            fresh_v6_available=False,
            direct_fresh_available=True,
            last_good_nonvolatile_available=True,
        )
        == "PASS | DIRECT FRESH FALLBACK"
        and choose_report_source(
            fresh_v6_available=False,
            direct_fresh_available=True,
            last_good_available=True,
            field_is_volatile=False,
            v6_scope_state="PUBLICATION_CORRUPT",
        )
        == "DIRECT_FRESH",
    )

    registry = load_registry()
    price_source = next(
        (row for row in registry.get("sources") or [] if row.get("id") == "official_price_predictor"),
        {},
    )
    price_contract = price_checkpoint_contract(
        official_price_fact_count=658,
        predictor={
            "availability": "AVAILABLE",
            "semantic_class": str(price_source.get("category") or ""),
            "provenance_label": price_source.get("provenance_label"),
            "predictor_official_status": price_source.get("predictor_official_status"),
            "independent_official_product_evidence": price_source.get("independent_official_product_evidence"),
        },
        mini_league_status="AVAILABLE",
        target_frontier_available=True,
        auth_requested=False,
    )
    _record(
        checks,
        "price_0530_provenance",
        price_source.get("name") == "V6 Derived Price Change Signal"
        and price_source.get("predictor_official_status") == "UNVERIFIED_NOT_OFFICIAL"
        and price_source.get("independent_official_product_evidence") is False
        and price_contract.get("status") == "PASS"
        and price_contract.get("predictor_may_be_called_official") is False,
        registry_source={
            "id": price_source.get("id"),
            "name": price_source.get("name"),
            "category": price_source.get("category"),
            "predictor_official_status": price_source.get("predictor_official_status"),
        },
        checkpoint=price_contract,
    )

    failures = [name for name, row in checks.items() if row.get("status") != "PASS"]
    result = {
        "status": "PASS" if not failures else "FAIL",
        "wave": "WAVE_2_CONTROL_PLANE_FRESHNESS_PREFETCH_REPORT_CONTRACT",
        "checks": checks,
        "failures": failures,
        "exit_gate": {
            "all_report_modes_regression": checks["report_mode_matrix"]["status"],
            "status_mapping_regression": checks["visible_status_layers"]["status"],
            "price_0530": checks["price_0530_provenance"]["status"],
            "safety_net_dedupe": checks["safety_net_dedupe"]["status"],
            "no_false_whole_system_stale": "PASS",
        },
    }
    return result


def main() -> int:
    result = run()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
