from __future__ import annotations


def test_checked_in_architecture_attestation_matches_governed_bytes():
    from src.services import architecture_guard_service as guard

    attested = guard._attested_result()
    assert attested is not None
    assert attested.get("status") == "PASS"
    assert all(
        isinstance(row, dict) and row.get("pass") is True
        for row in (attested.get("checks") or {}).values()
    )
