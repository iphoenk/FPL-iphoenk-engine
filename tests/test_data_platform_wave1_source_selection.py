from __future__ import annotations

from src.runtime_v6.report_contract import choose_report_source, report_delivery_status


def test_healthy_v6_truncated_retrieval_blocks_delivery_for_same_v6_recovery():
    assert choose_report_source(
        fresh_v6_available=True,
        direct_fresh_available=True,
        last_good_available=True,
        field_is_volatile=False,
        v6_scope_state="CURRENT",
        retrieval_state="CONNECTOR_TRUNCATED",
    ) == "V6_RETRIEVAL_RECOVERY"
    assert report_delivery_status(
        due=True,
        fresh_v6_available=True,
        direct_fresh_available=True,
        last_good_nonvolatile_available=True,
        v6_scope_state="CURRENT",
        retrieval_state="FIRST_READ_PARTIAL",
    ) == "BLOCKED | SAME V6 RETRIEVAL RECOVERY"


def test_direct_fresh_is_only_selected_for_real_v6_scope_failure():
    assert choose_report_source(
        fresh_v6_available=False,
        direct_fresh_available=True,
        last_good_available=True,
        field_is_volatile=False,
        v6_scope_state="V6_SCOPE_STALE",
    ) == "DIRECT_FRESH"
