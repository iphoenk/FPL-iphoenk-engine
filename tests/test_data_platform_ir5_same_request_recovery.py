from __future__ import annotations

from copy import deepcopy

from src.runtime_v6.domains.report_plane import report_recovery
from test_support.report_rank20 import rank20_rows


REQUEST_ID = "adhoc-deep-20260918-100800"
LOGICAL_SLOT = "2026-09-18T10:08:00+07:00"
OBSERVED_AT = "2026-09-18T10:10:00+07:00"


def _planner(**overrides):
    planner = getattr(report_recovery, "plan_same_request_recovery_pipeline", None)
    assert callable(planner), "IR5 requires integration in the existing report_recovery owner"
    values = {
        "request_id": REQUEST_ID,
        "logical_slot": LOGICAL_SLOT,
        "report_type": "DEEP",
        "trigger_kind": "AD_HOC",
        "mode": "DEEP",
        "v6_scope_id": "generation-458a095/S11-S12-price",
        "v6_scope_state": "CURRENT",
        "retrieval_state": "CONNECTOR_TRUNCATED",
        "expected_ids": list(range(1, 41)),
        "retrieved_chunks": [list(range(1, 21)), list(range(21, 41))],
        "rise_rows": rank20_rows(1000, "RISE"),
        "fall_rows": rank20_rows(2000, "FALL"),
        "observed_at": OBSERVED_AT,
        "rank20_max_age_minutes": 35,
        "same_v6_retry_exhausted": False,
        "direct_fresh_contract_permitted": False,
    }
    for rows in (values["rise_rows"], values["fall_rows"]):
        for row in rows:
            row["observed_at"] = "2026-09-18T10:00:00+07:00"
            row["source"] = "PRICE_PROVIDER"
            row["raw_payload_hash"] = "a" * 64
    values.update(overrides)
    return planner(**values)


def test_same_request_recovery_preserves_request_and_report_identity():
    result = _planner()

    assert result["request_id"] == REQUEST_ID
    assert result["original_request_id"] == REQUEST_ID
    assert result["request_identity_preserved"] is True
    assert result["report_slot_id"] == "2026-09-18T10:08+07:00|DEEP"
    assert result["replacement_report_identity_allowed"] is False
    assert result["legacy_fallback_allowed"] is False
    assert result["v3_v4_v5_fallback_allowed"] is False


def test_same_v6_granular_reassembly_precedes_any_direct_fresh():
    incomplete = _planner(
        retrieved_chunks=[list(range(1, 20)), list(range(21, 41))],
    )

    assert incomplete["input_ready"] is False
    assert incomplete["next_action"] == "SAME_V6_RETRIEVAL_RECOVERY"
    assert incomplete["recovery_sequence"][:5] == [
        "SAME_V6_RETRY",
        "GRANULAR_RETRIEVAL",
        "REASSEMBLE",
        "VALIDATE_COMPLETENESS",
        "EXACT_SCOPE_DIRECT_FRESH_IF_PERMITTED",
    ]
    assert incomplete["direct_fresh_allowed"] is False
    assert incomplete["visible_body_allowed"] is False

    escalated = _planner(
        retrieved_chunks=[list(range(1, 20)), list(range(21, 41))],
        same_v6_retry_exhausted=True,
        direct_fresh_contract_permitted=True,
    )
    assert escalated["next_action"] == "EXACT_SCOPE_DIRECT_FRESH"
    assert escalated["direct_fresh_allowed"] is True
    assert escalated["legacy_fallback_allowed"] is False


def test_ad_hoc_uses_same_recovery_contract_and_never_emits_incomplete_placeholder():
    result = _planner(
        retrieved_chunks=[list(range(1, 20)), list(range(21, 41))],
    )

    assert result["trigger_kind"] == "AD_HOC"
    assert result["ad_hoc_bypass_allowed"] is False
    assert result["input_ready"] is False
    assert result["compute_allowed"] is False
    assert result["pre_render_qa_allowed"] is False
    assert result["render_allowed"] is False
    assert result["post_render_qa_allowed"] is False
    assert result["can_emit"] is False
    assert result["visible_emitted"] is False
    assert result["visible_placeholder_allowed"] is False


def test_rank20_recovery_requires_exact20_j1_provenance_and_currentness():
    stale_rise = deepcopy(rank20_rows(3000, "RISE"))
    for row in stale_rise:
        row["observed_at"] = "2026-09-18T08:00:00+07:00"
        row["source"] = "PRICE_PROVIDER"
        row["raw_payload_hash"] = "b" * 64

    stale = _planner(rise_rows=stale_rise)
    assert stale["RISE20"]["status"] == "FAIL"
    assert stale["RISE20"]["schema_status"] == "PASS"
    assert stale["RISE20"]["freshness_status"] == "STALE"
    assert stale["input_ready"] is False
    assert stale["can_emit"] is False

    mixed = deepcopy(rank20_rows(4000, "FALL"))
    for row in mixed:
        row["observed_at"] = "2026-09-18T10:00:00+07:00"
        row["source"] = "PRICE_PROVIDER"
        row["raw_payload_hash"] = "c" * 64
    mixed[7]["raw_payload_hash"] = "d" * 64

    incoherent = _planner(fall_rows=mixed)
    assert incoherent["FALL20"]["status"] == "FAIL"
    assert incoherent["FALL20"]["provenance_coherent"] is False
    assert incoherent["input_ready"] is False


def test_complete_reassembled_current_rank20_advances_only_to_compute_not_emit():
    result = _planner()

    assert result["retrieval_complete"] is True
    assert result["RISE20"]["status"] == "PASS"
    assert result["FALL20"]["status"] == "PASS"
    assert result["input_ready"] is True
    assert result["next_action"] == "COMPUTE"
    assert result["compute_allowed"] is True
    assert result["render_allowed"] is False
    assert result["can_emit"] is False
    assert result["visible_emitted"] is False
    assert result["pipeline"] == [
        "REQUEST",
        "RETRIEVE",
        "RECOVERY",
        "READY",
        "INPUT_READINESS",
        "COMPUTE",
        "PRE_RENDER_QA",
        "RENDER",
        "POST_RENDER_QA",
        "EMIT",
        "DELIVERY_RECEIPT",
    ]
