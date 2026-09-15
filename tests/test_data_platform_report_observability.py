from __future__ import annotations

import pytest

from src.runtime_v6.delivery_integrity import DeliveryIntegrityError
from src.runtime_v6.report_observability import build_report_observability


SLOT = "2026-09-16T04:30+07:00|DEEP"
TIMESTAMPS = {
    "data_plane": "2026-09-16T04:28:00+07:00",
    "retrieval": "2026-09-16T04:29:00+07:00",
    "compute": "2026-09-16T04:30:05+07:00",
    "pre_render_qa": "2026-09-16T04:30:10+07:00",
    "post_render_qa": "2026-09-16T04:30:20+07:00",
    "delivery": "2026-09-16T04:30:30+07:00",
    "recovery": "2026-09-16T04:31:00+07:00",
}


def _snapshot(**overrides):
    values = {
        "report_slot_id": SLOT,
        "data_plane": {"status": "GREEN", "generated_at": "2026-09-16T04:28:00+07:00"},
        "retrieval": {
            "v6_scope_id": "bootstrap",
            "v6_scope_state": "CURRENT",
            "retrieval_state": "COMPLETE",
            "action": "READ_V6_ONLY",
            "legacy_fallback_allowed": False,
        },
        "compute": {
            "status": "PASS",
            "compute_ready": True,
            "next_action": "PRE_RENDER_QA",
            "legacy_fallback_allowed": False,
        },
        "pre_render_qa": {
            "status": "PASS",
            "qa_stage": "PRE_RENDER",
            "qa_passed": True,
            "report_state": "BUILDING",
            "next_action": "RENDER_REPORT",
            "legacy_fallback_allowed": False,
        },
        "post_render_qa": {
            "status": "PASS",
            "qa_stage": "POST_RENDER",
            "qa_passed": True,
            "report_state": "BUILDING",
            "next_action": "BUILD_DELIVERY_PROOF",
            "legacy_fallback_allowed": False,
        },
        "delivery": {
            "status": "PASS",
            "delivery_proof_valid": True,
            "report_delivered": True,
            "report_state": "DELIVERED",
            "report_slot_id": SLOT,
            "delivered_report_slot_id": SLOT,
            "delivered_at": "2026-09-16T04:30:29+07:00",
            "next_action": "NONE",
            "legacy_fallback_allowed": False,
        },
        "recovery": None,
        "stage_timestamps": dict(TIMESTAMPS),
    }
    values.update(overrides)
    return build_report_observability(**values)


def test_v6_green_never_implies_report_green_when_delivery_failed():
    result = _snapshot(
        delivery={
            "status": "FAIL",
            "delivery_proof_valid": False,
            "report_delivered": False,
            "report_state": "BUILDING",
            "next_action": "DELIVERY_PROOF_RECOVERY",
            "legacy_fallback_allowed": False,
        }
    )

    assert result["data_plane"]["status"] == "GREEN"
    assert result["report_plane"]["status"] == "DELIVERY_FAILED"
    assert result["report_plane"]["delivered"] is False
    assert result["invariants"]["v6_green_implies_report_green"] is False


def test_v6_failure_does_not_override_valid_report_delivery_evidence():
    result = _snapshot(data_plane={"status": "RED", "reason": "PUBLICATION_STALE"})

    assert result["data_plane"]["status"] == "RED"
    assert result["report_plane"]["status"] == "DELIVERED"
    assert result["report_plane"]["delivered"] is True
    assert result["invariants"]["v6_failure_implies_report_failure"] is False


def test_retrieval_transport_partial_is_recovery_required_not_source_failed():
    result = _snapshot(
        retrieval={
            "v6_scope_id": "bootstrap",
            "v6_scope_state": "CURRENT",
            "retrieval_state": "CONNECTOR_TRUNCATED",
            "action": "SAME_V6_RETRIEVAL_RECOVERY",
            "scope_lock_required": True,
            "direct_fresh_allowed": False,
            "legacy_fallback_allowed": False,
        },
        compute=None,
        pre_render_qa=None,
        post_render_qa=None,
        delivery=None,
    )

    retrieval = result["report_plane"]["stages"]["retrieval"]
    assert retrieval["status"] == "RECOVERY_REQUIRED"
    assert retrieval["source_failed"] is False
    assert retrieval["action"] == "SAME_V6_RETRIEVAL_RECOVERY"
    assert result["report_plane"]["status"] == "RETRIEVAL_RECOVERY"
    assert result["invariants"]["retrieval_truncated_implies_source_failed"] is False


def test_stage_timestamps_are_independent_and_preserved_exactly():
    result = _snapshot()
    stages = result["report_plane"]["stages"]

    assert result["data_plane"]["observed_at"] == TIMESTAMPS["data_plane"]
    assert stages["retrieval"]["observed_at"] == TIMESTAMPS["retrieval"]
    assert stages["compute"]["observed_at"] == TIMESTAMPS["compute"]
    assert stages["pre_render_qa"]["observed_at"] == TIMESTAMPS["pre_render_qa"]
    assert stages["post_render_qa"]["observed_at"] == TIMESTAMPS["post_render_qa"]
    assert stages["delivery"]["observed_at"] == TIMESTAMPS["delivery"]
    assert stages["recovery"]["observed_at"] == TIMESTAMPS["recovery"]


def test_pre_render_and_post_render_qa_remain_separate_observability_stages():
    result = _snapshot(
        post_render_qa={
            "status": "FAIL",
            "qa_stage": "POST_RENDER",
            "qa_passed": False,
            "report_state": "QA_FAILED",
            "next_action": "RENDER_RECOVERY",
            "legacy_fallback_allowed": False,
        },
        delivery=None,
    )
    stages = result["report_plane"]["stages"]

    assert stages["pre_render_qa"]["status"] == "PASS"
    assert stages["post_render_qa"]["status"] == "FAIL"
    assert result["report_plane"]["status"] == "QA_FAILED"


def test_delivery_is_delivered_only_with_valid_same_slot_receipt_evidence():
    result = _snapshot(
        delivery={
            "status": "PASS",
            "delivery_proof_valid": True,
            "report_delivered": True,
            "report_state": "DELIVERED",
            "report_slot_id": "2026-09-16T12:30+07:00|DEEP",
            "delivered_report_slot_id": "2026-09-16T12:30+07:00|DEEP",
            "next_action": "NONE",
            "legacy_fallback_allowed": False,
        }
    )

    assert result["report_plane"]["delivered"] is False
    assert result["report_plane"]["status"] == "DELIVERY_FAILED"
    assert result["report_plane"]["stages"]["delivery"]["same_slot_receipt"] is False


def test_recovery_is_visible_without_overwriting_delivery_truth():
    result = _snapshot(
        delivery={
            "status": "FAIL",
            "delivery_proof_valid": False,
            "report_delivered": False,
            "report_state": "BUILDING",
            "next_action": "DELIVERY_PROOF_RECOVERY",
            "legacy_fallback_allowed": False,
        },
        recovery={
            "recovery_mode": "SAME_RUN",
            "retry_now": True,
            "retry_exhausted": False,
            "next_action": "DELIVERY_PROOF_RECOVERY",
            "report_delivered": False,
            "legacy_fallback_allowed": False,
            "v6_data_plane_mutation_allowed": False,
        },
    )

    assert result["report_plane"]["stages"]["recovery"]["status"] == "ACTIVE"
    assert result["report_plane"]["stages"]["recovery"]["mode"] == "SAME_RUN"
    assert result["report_plane"]["delivered"] is False
    assert result["report_plane"]["status"] == "RECOVERY_REQUIRED"


def test_missing_stage_evidence_is_unknown_not_assumed_pass():
    result = _snapshot(
        retrieval=None,
        compute=None,
        pre_render_qa=None,
        post_render_qa=None,
        delivery=None,
        recovery=None,
    )

    stages = result["report_plane"]["stages"]
    assert stages["retrieval"]["status"] == "UNKNOWN"
    assert stages["compute"]["status"] == "UNKNOWN"
    assert stages["pre_render_qa"]["status"] == "UNKNOWN"
    assert stages["post_render_qa"]["status"] == "UNKNOWN"
    assert stages["delivery"]["status"] == "UNKNOWN"
    assert stages["recovery"]["status"] == "UNKNOWN"
    assert result["report_plane"]["status"] == "UNKNOWN"


def test_report_evidence_never_synthesizes_v6_data_plane_state():
    result = _snapshot(data_plane=None)

    assert result["data_plane"]["status"] == "UNKNOWN"
    assert result["data_plane"]["observed_at"] == TIMESTAMPS["data_plane"]
    assert "v6_already_published" not in result["data_plane"]
    assert result["report_plane"]["status"] == "DELIVERED"


def test_all_planes_keep_legacy_fallback_forbidden():
    result = _snapshot()

    assert result["legacy_fallback_allowed"] is False
    assert result["data_plane"]["legacy_fallback_allowed"] is False
    assert result["report_plane"]["legacy_fallback_allowed"] is False
    for stage in result["report_plane"]["stages"].values():
        assert stage["legacy_fallback_allowed"] is False


def test_timestamp_must_be_timezone_aware_iso8601_when_supplied():
    invalid = dict(TIMESTAMPS)
    invalid["compute"] = "2026-09-16T04:30:05"

    with pytest.raises(DeliveryIntegrityError):
        _snapshot(stage_timestamps=invalid)
