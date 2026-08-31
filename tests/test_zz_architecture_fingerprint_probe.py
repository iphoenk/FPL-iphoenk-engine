from __future__ import annotations


def test_emit_final_architecture_fingerprint():
    from src.services import architecture_guard_service as guard

    result = guard.run(force_full_scan=True)
    fingerprint = guard.repository_fingerprint()
    assert result.get("status") == "PASS", result
    raise AssertionError(f"ARCHITECTURE_FINGERPRINT={fingerprint}")
