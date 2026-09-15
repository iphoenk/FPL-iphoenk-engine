from __future__ import annotations

from src.runtime_v6 import delivery_integrity


def _require_callable(name: str):
    value = getattr(delivery_integrity, name, None)
    assert callable(value), f"missing Wave 2 production function: {name}"
    return value


def test_report_slot_id_is_independent_and_deterministic():
    build_report_slot_id = _require_callable("build_report_slot_id")

    assert (
        build_report_slot_id(
            logical_slot="2026-09-16T04:30:00+07:00",
            report_type="deep",
        )
        == "2026-09-16T04:30+07:00|DEEP"
    )
    assert (
        build_report_slot_id(
            logical_slot="2026-09-16T05:30:00+07:00",
            report_type="price",
        )
        == "2026-09-16T05:30+07:00|PRICE"
    )


def test_already_published_v6_does_not_satisfy_undelivered_report_slot():
    resolve_report_slot_decision = _require_callable("resolve_report_slot_decision")

    decision = resolve_report_slot_decision(
        logical_slot="2026-09-16T04:30:00+07:00",
        report_type="DEEP",
        report_state="NOT_STARTED",
        v6_already_published=True,
        delivered_report_slot_id=None,
        delivery_proof_valid=False,
    )

    assert decision["report_slot_id"] == "2026-09-16T04:30+07:00|DEEP"
    assert decision["report_state"] == "NOT_STARTED"
    assert decision["report_delivered"] is False
    assert decision["report_required"] is True
    assert decision["start_build"] is True
    assert decision["duplicate"] is False
    assert decision["reason"] == "DUE_REPORT"


def test_qa_failed_same_slot_requires_recovery():
    resolve_report_slot_decision = _require_callable("resolve_report_slot_decision")

    decision = resolve_report_slot_decision(
        logical_slot="2026-09-16T04:30:00+07:00",
        report_type="DEEP",
        report_state="QA_FAILED",
        v6_already_published=True,
        delivered_report_slot_id=None,
        delivery_proof_valid=False,
    )

    assert decision["report_required"] is True
    assert decision["start_build"] is True
    assert decision["duplicate"] is False
    assert decision["reason"] == "SAME_SLOT_RECOVERY"


def test_same_report_slot_is_duplicate_only_with_valid_delivery_proof():
    resolve_report_slot_decision = _require_callable("resolve_report_slot_decision")
    slot = "2026-09-16T04:30+07:00|DEEP"

    decision = resolve_report_slot_decision(
        logical_slot="2026-09-16T04:30:00+07:00",
        report_type="DEEP",
        report_state="DELIVERED",
        v6_already_published=True,
        delivered_report_slot_id=slot,
        delivery_proof_valid=True,
    )

    assert decision["report_delivered"] is True
    assert decision["report_required"] is False
    assert decision["start_build"] is False
    assert decision["duplicate"] is True
    assert decision["reason"] == "SAME_SLOT_ALREADY_DELIVERED"


def test_delivered_state_without_valid_same_slot_proof_requires_recovery():
    resolve_report_slot_decision = _require_callable("resolve_report_slot_decision")

    invalid = resolve_report_slot_decision(
        logical_slot="2026-09-16T04:30:00+07:00",
        report_type="DEEP",
        report_state="DELIVERED",
        v6_already_published=True,
        delivered_report_slot_id="2026-09-16T04:30+07:00|DEEP",
        delivery_proof_valid=False,
    )
    wrong_slot = resolve_report_slot_decision(
        logical_slot="2026-09-16T04:30:00+07:00",
        report_type="DEEP",
        report_state="DELIVERED",
        v6_already_published=True,
        delivered_report_slot_id="2026-09-16T05:30+07:00|PRICE",
        delivery_proof_valid=True,
    )

    for decision in (invalid, wrong_slot):
        assert decision["report_delivered"] is False
        assert decision["report_required"] is True
        assert decision["start_build"] is True
        assert decision["duplicate"] is False
        assert decision["reason"] == "DELIVERY_PROOF_RECOVERY"


def test_building_slot_remains_required_but_does_not_start_parallel_build():
    resolve_report_slot_decision = _require_callable("resolve_report_slot_decision")

    decision = resolve_report_slot_decision(
        logical_slot="2026-09-16T04:30:00+07:00",
        report_type="DEEP",
        report_state="BUILDING",
        v6_already_published=True,
        delivered_report_slot_id=None,
        delivery_proof_valid=False,
    )

    assert decision["report_delivered"] is False
    assert decision["report_required"] is True
    assert decision["start_build"] is False
    assert decision["duplicate"] is False
    assert decision["reason"] == "SAME_SLOT_BUILD_IN_PROGRESS"
