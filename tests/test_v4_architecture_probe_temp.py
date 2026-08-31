from src.services import architecture_guard_service as guard


def test_temp_architecture_probe():
    result = guard.run(force_full_scan=True)
    fingerprint = guard.repository_fingerprint()
    assert False, f"ARCH_PROBE fingerprint={fingerprint} result={result}"
