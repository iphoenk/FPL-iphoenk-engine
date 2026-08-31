from __future__ import annotations


def test_architecture_fingerprint_probe():
    from src.services import architecture_guard_service as guard

    print(f"ARCH_FINGERPRINT={guard.repository_fingerprint()}")
    result = guard.run(force_full_scan=True)
    assert result.get("status") == "PASS"
    assert False, "TEMP_PROBE_REMOVE_AFTER_FINGERPRINT_CAPTURE"
