from __future__ import annotations

from src.services import architecture_guard_service as guard


def test_probe_final_architecture_fingerprint() -> None:
    result = guard.run(force_full_scan=True)
    assert result.get("status") == "PASS", result
    fingerprint = guard.repository_fingerprint()
    raise AssertionError(f"NEW_V4_ARCHITECTURE_FINGERPRINT={fingerprint}")
