from __future__ import annotations

import pytest

from src.runtime_v6 import delivery_integrity


RECOVERY_STATES = (
    "CONNECTOR_TRUNCATED",
    "PAYLOAD_TOO_LARGE",
    "FIRST_READ_PARTIAL",
    "PAGINATION_REQUIRED",
    "PARTIAL_CHUNK",
    "RENDERING_LIMIT",
)


def _require_callable(name: str):
    value = getattr(delivery_integrity, name, None)
    assert callable(value), f"missing Wave 3 production function: {name}"
    return value


def test_truncated_healthy_v6_locks_recovery_to_exact_same_scope():
    plan_exact_scope_retrieval = _require_callable("plan_exact_scope_retrieval")

    plan = plan_exact_scope_retrieval(
        v6_scope_id="publication-20260916T0400/bootstrap",
        v6_scope_state="CURRENT",
        retrieval_state="CONNECTOR_TRUNCATED",
    )

    assert plan["v6_scope_id"] == "publication-20260916T0400/bootstrap"
    assert plan["action"] == "SAME_V6_RETRIEVAL_RECOVERY"
    assert plan["scope_lock_required"] is True
    assert plan["direct_fresh_allowed"] is False
    assert plan["legacy_fallback_allowed"] is False
    assert plan["final_unavailable_allowed"] is False
    assert plan["recovery_steps"] == [
        "CONTINUE_SAME_V6_SCOPE",
        "PAGINATE_OR_INCREASE_LIMIT",
        "CHUNK_BY_ROW_PLAYER_SECTION",
        "REASSEMBLE",
        "VALIDATE_COMPLETENESS",
    ]


@pytest.mark.parametrize("retrieval_state", RECOVERY_STATES)
def test_every_transport_retrieval_limit_preserves_v6_scope_and_forbids_fallback(
    retrieval_state,
):
    plan_exact_scope_retrieval = _require_callable("plan_exact_scope_retrieval")

    plan = plan_exact_scope_retrieval(
        v6_scope_id="generation-abc/S10-watchlist",
        v6_scope_state="PASS",
        retrieval_state=retrieval_state,
    )

    assert plan["action"] == "SAME_V6_RETRIEVAL_RECOVERY"
    assert plan["scope_lock_required"] is True
    assert plan["direct_fresh_allowed"] is False
    assert plan["legacy_fallback_allowed"] is False
    assert plan["final_unavailable_allowed"] is False


def test_complete_healthy_scope_needs_no_recovery_and_still_forbids_legacy_fallback():
    plan_exact_scope_retrieval = _require_callable("plan_exact_scope_retrieval")

    plan = plan_exact_scope_retrieval(
        v6_scope_id="generation-abc/S10-watchlist",
        v6_scope_state="CURRENT",
        retrieval_state="COMPLETE",
    )

    assert plan["action"] == "READ_V6_ONLY"
    assert plan["scope_lock_required"] is True
    assert plan["recovery_steps"] == []
    assert plan["direct_fresh_allowed"] is False
    assert plan["legacy_fallback_allowed"] is False
    assert plan["final_unavailable_allowed"] is False


def test_verified_v6_scope_failure_may_use_scoped_direct_fresh_but_never_legacy_engine():
    plan_exact_scope_retrieval = _require_callable("plan_exact_scope_retrieval")

    plan = plan_exact_scope_retrieval(
        v6_scope_id="generation-abc/S10-watchlist",
        v6_scope_state="V6_SCOPE_FAILED",
        retrieval_state="COMPLETE",
    )

    assert plan["action"] == "SCOPED_DIRECT_FRESH_ALLOWED"
    assert plan["direct_fresh_allowed"] is True
    assert plan["legacy_fallback_allowed"] is False
    assert plan["final_unavailable_allowed"] is True
    assert plan["recovery_steps"] == []


def test_reassembly_passes_only_when_expected_scope_is_complete_and_unique():
    validate_retrieval_reassembly = _require_callable("validate_retrieval_reassembly")

    result = validate_retrieval_reassembly(
        v6_scope_id="generation-abc/S10-watchlist",
        expected_ids=[101, 102, 103, 104, 105, 106],
        retrieved_chunks=[[101, 102], [103], [104, 105, 106]],
    )

    assert result["status"] == "PASS"
    assert result["complete"] is True
    assert result["expected_count"] == 6
    assert result["retrieved_unique_count"] == 6
    assert result["missing_ids"] == []
    assert result["duplicate_ids"] == []
    assert result["unexpected_ids"] == []
    assert result["reassembled_ids"] == [101, 102, 103, 104, 105, 106]
    assert result["action"] == "READ_REASSEMBLED_V6_SCOPE"


def test_missing_chunk_remains_same_scope_recovery_not_final_unavailable():
    validate_retrieval_reassembly = _require_callable("validate_retrieval_reassembly")

    result = validate_retrieval_reassembly(
        v6_scope_id="generation-abc/S10-watchlist",
        expected_ids=[101, 102, 103, 104],
        retrieved_chunks=[[101, 102], [104]],
    )

    assert result["status"] == "INCOMPLETE"
    assert result["complete"] is False
    assert result["missing_ids"] == [103]
    assert result["action"] == "SAME_V6_RETRIEVAL_RECOVERY"
    assert result["direct_fresh_allowed"] is False
    assert result["legacy_fallback_allowed"] is False
    assert result["final_unavailable_allowed"] is False


def test_duplicate_or_cross_scope_rows_cannot_be_misclassified_as_complete():
    validate_retrieval_reassembly = _require_callable("validate_retrieval_reassembly")

    result = validate_retrieval_reassembly(
        v6_scope_id="generation-abc/S11-rise20",
        expected_ids=[201, 202, 203],
        retrieved_chunks=[[201, 202], [202, 203, 999]],
    )

    assert result["status"] == "INCOMPLETE"
    assert result["complete"] is False
    assert result["duplicate_ids"] == [202]
    assert result["unexpected_ids"] == [999]
    assert result["action"] == "SAME_V6_RETRIEVAL_RECOVERY"
    assert result["final_unavailable_allowed"] is False


def test_reassembly_contract_rejects_invalid_scope_or_ambiguous_expected_identity():
    validate_retrieval_reassembly = _require_callable("validate_retrieval_reassembly")
    DeliveryIntegrityError = delivery_integrity.DeliveryIntegrityError

    with pytest.raises(DeliveryIntegrityError):
        validate_retrieval_reassembly(
            v6_scope_id="",
            expected_ids=[1, 2, 3],
            retrieved_chunks=[[1, 2, 3]],
        )

    with pytest.raises(DeliveryIntegrityError):
        validate_retrieval_reassembly(
            v6_scope_id="generation-abc/S12-fall20",
            expected_ids=[1, 1, 2],
            retrieved_chunks=[[1, 2]],
        )
