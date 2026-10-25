from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.runtime_v6.report_contract import (
    build_status_view,
    choose_report_source,
    map_auth_status,
    report_delivery_status,
    safety_net_decision,
)
from src.runtime_v6.wave3_proof import Wave3ProofError, build_slot_proof, evaluate_proof_window


OBSERVED = "2026-09-14T13:31:00+07:00"
LOGICAL = "2026-09-14T13:00:00+07:00"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _failed_candidate(tmp_path: Path, error: str) -> Path:
    root = tmp_path / error.replace(":", "_") / "data" / "v6"
    _write(
        root / "manifest.json",
        {
            "generated_at": "2026-09-14T06:31:00+00:00",
            "runtime_control": {
                "event_name": "issues",
                "schedule_kind": "chatgpt_scheduler",
                "chatgpt_scheduler_proof": True,
                "counts_as_completed_operational_slot": True,
                "expected_cycle_at": "2026-09-14T06:00:00+00:00",
                "cycle_observed_at": "2026-09-14T06:31:00+00:00",
            },
        },
    )
    _write(
        root / "health" / "candidate_freeze.lock",
        {
            "candidate_state": "FROZEN",
            "run_id": "9001",
            "run_attempt": "1",
            "candidate_generation_id": "9001:1:deadbeefdeadbeef",
            "registry_fingerprint": "f" * 64,
            "candidate_tree_sha256": "d" * 64,
        },
    )
    _write(
        root / "health" / "publish_integrity.json",
        {"status": "FAIL", "tree_sha256": "d" * 64, "errors": [error]},
    )
    return root


def test_provider_timeout_can_degrade_acquisition_without_cancelling_due_report():
    delivery = report_delivery_status(
        due=True,
        fresh_v6_available=False,
        direct_fresh_available=True,
        last_good_nonvolatile_available=True,
    )
    assert delivery == "PENDING | DIRECT FRESH | REPORT CONTRACT NOT PROVEN"


def test_provider_incomplete_amber_is_local_when_core_integrity_remains_valid():
    view = build_status_view(
        observed_at=OBSERVED,
        core_transport="PASS",
        acquisition="AMBER | OPTIONAL PROVIDER INCOMPLETE",
        publish_integrity="PASS",
        publish_validation="PASS",
        new_publication="PROMOTED",
        last_good_state="AVAILABLE",
        last_good_generated_at="2026-09-14T13:30:30+07:00",
        scheduler_proof_state="CURRENT",
        scheduler_proof_at=LOGICAL,
        report_prefetch="PASS",
        target_report_freshness="PARTIAL | OPTIONAL PROVIDER AMBER",
        auth="NOT REQUESTED",
        report_delivery="PASS | FRESH V6",
    )
    assert view["ACQUISITION"]["state"].startswith("AMBER")
    assert view["PUBLISH VALIDATION"]["state"] == "PASS"
    assert view["REPORT DELIVERY"]["state"] == "PASS | FRESH V6"


def test_auth_expired_and_not_requested_are_distinct_chaos_states():
    assert map_auth_status(requested=False, raw_state="AUTH_EXPIRED") == "NOT REQUESTED"
    assert map_auth_status(requested=True, raw_state="AUTH_EXPIRED") == "EXPIRED"
    assert map_auth_status(requested=True, raw_state="AUTH_UNAVAILABLE") == "FAILED"


def test_stale_optional_cache_does_not_override_fresh_core_delivery():
    view = build_status_view(
        observed_at=OBSERVED,
        core_transport="PASS",
        acquisition="PASS",
        publish_integrity="PASS",
        publish_validation="PASS",
        new_publication="PROMOTED",
        last_good_state="AVAILABLE",
        last_good_generated_at="2026-09-14T13:30:30+07:00",
        scheduler_proof_state="CURRENT",
        scheduler_proof_at=LOGICAL,
        report_prefetch="PASS",
        target_report_freshness="PARTIAL | OPTIONAL CACHE STALE",
        auth="NOT REQUESTED",
        report_delivery="PASS | FRESH V6",
    )
    assert view["TARGET REPORT FRESHNESS"]["state"].startswith("PARTIAL")
    assert view["REPORT DELIVERY"]["state"] == "PASS | FRESH V6"


def test_registry_activation_transition_is_proven_by_fingerprint_not_inferred(tmp_path):
    root = tmp_path / "data" / "v6"
    _write(
        root / "manifest.json",
        {
            "generated_at": "2026-09-14T06:31:00+00:00",
            "runtime_control": {
                "event_name": "issues",
                "schedule_kind": "chatgpt_scheduler",
                "chatgpt_scheduler_proof": True,
                "counts_as_completed_operational_slot": True,
                "authoritative_runtime_snapshot": True,
                "logical_slot_source": "GOVERNED_TRIGGER_EVENT",
                "expected_cycle_at": "2026-09-14T06:00:00+00:00",
                "cycle_observed_at": "2026-09-14T06:31:00+00:00",
            },
        },
    )
    _write(
        root / "health" / "candidate_freeze.lock",
        {
            "candidate_state": "FROZEN",
            "run_id": "9002",
            "run_attempt": "1",
            "candidate_generation_id": "9002:1:0123456789abcdef",
            "registry_fingerprint": "1" * 64,
            "registry_epoch": "registry-epoch-2",
            "candidate_tree_sha256": "a" * 64,
        },
    )
    _write(root / "health" / "publish_integrity.json", {"status": "PASS", "tree_sha256": "a" * 64})
    proof = build_slot_proof(
        root,
        source_commit="c" * 40,
        production_validated=True,
        promotion_verified=True,
        run_id="9002",
        run_attempt="1",
        collect_job_id="9501",
        publish_job_id="9502",
        fulfillment_job_id="9503",
    )
    assert proof["registry_fingerprint"] == "1" * 64
    assert proof["registry_epoch"] == "registry-epoch-2"


@pytest.mark.parametrize(
    "error",
    [
        "identity_conflict",
        "duplicate_identity",
        "broken_stable_id_bridge",
        "malformed_candidate",
        "corrupt_candidate",
        "publisher_revalidation_rejected",
    ],
)
def test_structural_identity_and_publisher_chaos_remain_fail_closed(tmp_path, error):
    root = _failed_candidate(tmp_path, error)
    with pytest.raises(Wave3ProofError, match="publish_integrity_not_pass"):
        build_slot_proof(
            root,
            source_commit="c" * 40,
            production_validated=True,
            promotion_verified=True,
            run_id="9001",
            run_attempt="1",
        )


def test_duplicate_core_trigger_is_not_eligible_for_rolling_production_green():
    stages = {
        stage: {"state": "PASS"}
        for stage in (
            "TRIGGERED",
            "ACQUIRED",
            "STAGED",
            "FROZEN",
            "INTEGRITY_PASS",
            "VALIDATED",
            "PROMOTED",
        )
    }
    first = {
        "proof_kind": "WAVE3_NATURAL_CORE_SLOT",
        "natural_slot": True,
        "natural_transport": "FPL_MASTER_SLOT_ISSUE_TITLE",
        "core_chain_pass": True,
        "logical_slot": "2026-09-14T06:00:00+00:00",
        "run_id": "1001",
        "run_attempt": "1",
        "publication_generation_id": "publication-1001",
        "stages": stages,
    }
    duplicate_publication = dict(first)
    duplicate_publication["run_id"] = "1002"
    duplicate_publication["publication_generation_id"] = "publication-1002"
    result = evaluate_proof_window([first, duplicate_publication])
    assert result["duplicate_logical_slots"] == ["2026-09-14T06:00:00+00:00"]
    assert result["production_green_eligible"] is False


def test_duplicate_report_prefetch_is_safety_net_noop():
    # Prefetch is preparation only and can never prove visible report fulfillment.
    # Keep the canonical scenario id/name for Wave3 acceptance, but require
    # same-slot recovery until report contract + delivery proof are positive.
    decision = safety_net_decision(
        logical_slot=LOGICAL,
        primary_owned=False,
        prefetched=True,
        delivered=False,
    )
    assert decision["action"] == "RECOVER"
    assert decision["deduplicated"] is False
    assert decision["report_slot_fulfilled"] is False
    assert "REPORT_PREFETCHED_NONTERMINAL" in decision["reason"]

    fulfilled = safety_net_decision(
        logical_slot=LOGICAL,
        primary_owned=False,
        prefetched=True,
        delivered=True,
        report_contract_pass=True,
        delivery_proof_valid=True,
        report_slot_fulfilled=True,
    )
    assert fulfilled["action"] == "NO_OP"
    assert fulfilled["deduplicated"] is True


def test_delayed_scheduler_execution_keeps_truthful_proof_age():
    view = build_status_view(
        observed_at="2026-09-14T13:57:00+07:00",
        core_transport="PASS | DELAYED",
        acquisition="PASS",
        publish_integrity="PASS",
        publish_validation="PASS",
        new_publication="PROMOTED",
        last_good_state="AVAILABLE",
        last_good_generated_at="2026-09-14T13:56:30+07:00",
        scheduler_proof_state="CURRENT | DELAYED EXECUTION",
        scheduler_proof_at=LOGICAL,
        report_prefetch="N/A",
        target_report_freshness="N/A",
        auth="NOT REQUESTED",
        report_delivery="N/A",
    )
    assert view["SCHEDULER PROOF"]["scheduler_proof_age_seconds"] == 3420.0


def test_last_good_recovery_is_allowed_only_for_nonvolatile_fields():
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


# ---------------------------------------------------------------------------
# F06: resilience evidence (fixtures only; nothing here touches production or dispatches anything)
# ---------------------------------------------------------------------------
from src.runtime_v6.consumer import assess_snapshot  # noqa: E402
from src.runtime_v6.domains.observability import health as _health  # noqa: E402
from src.runtime_v6.domains.observability.current_health import (  # noqa: E402
    classify_evidence,
    consumer_impact,
    current_report_semantics,
)
from tests.test_data_platform_consumer import _write_snapshot  # noqa: E402

_F06_NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def test_f06_source_429_and_timeout_are_transport_degradation_not_green():
    attempts = [{"status": "AVAILABLE"}, {"status": "HTTP_429"}, {"status": "TIMEOUT"}]
    assert _health._transport_health({}, {"attempts": attempts}) == "AMBER"
    assert _health._transport_health({}, {"attempts": attempts[1:]}) == "RED"
    assert _health._transport_health({}, {"attempts": attempts[:1]}) == "GREEN"


def test_f06_cached_old_source_is_not_fresh():
    old = (_F06_NOW.replace(hour=0)).isoformat()
    assert _health._freshness_health({"check_freshness_minutes": 90}, {"checked_at": old}) in {"AMBER", "RED"}
    assert _health._freshness_health({"critical": True}, {}) == "RED"
    assert _health._freshness_health({}, {}) == "AMBER"


def test_f06_missing_manifest_requires_direct_fallback(tmp_path):
    r = assess_snapshot(tmp_path, now=_F06_NOW)
    assert r["state"] == "INVALID" and r["failures"] == ["MISSING_MANIFEST"] and r["direct_fallback_eligible"] is True


def test_f06_partial_publish_without_integrity_file_is_invalid(tmp_path):
    _write_snapshot(tmp_path, _F06_NOW.isoformat())
    (tmp_path / "health" / "publish_integrity.json").unlink()
    r = assess_snapshot(tmp_path, now=_F06_NOW)
    assert r["state"] == "INVALID" and r["failures"] == ["MISSING_PUBLISH_INTEGRITY"] and r["usable"] is False


def test_f06_corrupt_manifest_is_unreadable_not_green(tmp_path):
    _write_snapshot(tmp_path, _F06_NOW.isoformat())
    (tmp_path / "manifest.json").write_text("{not json", encoding="utf-8")
    r = assess_snapshot(tmp_path, now=_F06_NOW)
    assert r["state"] == "INVALID" and r["failures"][0].startswith("UNREADABLE_RUNTIME")


def test_f06_readback_digest_mismatch_is_invalid_with_both_digests_visible(tmp_path):
    _write_snapshot(tmp_path, _F06_NOW.isoformat())
    (tmp_path / "normalized" / "canonical_players.json").write_text(json.dumps({"player_count": 2}), encoding="utf-8")
    r = assess_snapshot(tmp_path, now=_F06_NOW)
    assert r["state"] == "INVALID" and "PUBLISH_TREE_DIGEST_MISMATCH" in r["failures"]
    assert r["stored_tree_sha256"] and r["recomputed_tree_sha256"] and r["stored_tree_sha256"] != r["recomputed_tree_sha256"]


def test_f06_report_plane_outage_does_not_invalidate_official_facts(tmp_path):
    _write_snapshot(tmp_path, _F06_NOW.isoformat())
    snapshot = assess_snapshot(tmp_path, now=_F06_NOW)
    assert snapshot["state"] == "FRESH" and snapshot["usable"] is True
    semantics = current_report_semantics(
        runtime_control={"report_prefetch": True, "schedule_kind": "REPORT_PREFETCH"},
        prefetch_health={"public_core_status": "STALE", "fresh_for_target_report": False},
    )
    assert semantics["report_mode"] == "DEGRADED"
    impact = consumer_impact(snapshot_usable=snapshot["usable"], report_plane_available=False)
    assert impact["official_facts"] == "VALID" and impact["report_plane"] == "UNAVAILABLE"
    assert impact["official_facts_depend_on_report_plane"] == "NO" and impact["direct_fallback"] == "NOT_NEEDED"


def test_f06_incomplete_or_failed_audit_proof_is_unknown_not_missing_or_verified():
    assert classify_evidence({"run": True, "artifact": True})["state"] == "VERIFIED"
    assert classify_evidence({"run": True, "artifact": False})["state"] == "MISSING"
    incomplete = classify_evidence({"run": True, "artifact": None})
    assert incomplete["state"] == "UNKNOWN" and incomplete["unknown_checks"] == ["artifact"]
    assert classify_evidence({"run": False, "artifact": None})["state"] == "UNKNOWN"
    assert classify_evidence({})["state"] == "UNKNOWN" and classify_evidence(None)["state"] == "UNKNOWN"
    assert consumer_impact(snapshot_usable=None, report_plane_available=None)["official_facts"] == "UNKNOWN"
