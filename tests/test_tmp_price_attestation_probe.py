from src.services import architecture_guard_service as guard


def test_tmp_price_attestation_probe():
    result = guard.run(force_full_scan=True)
    fingerprint = guard.repository_fingerprint()
    assert False, f"PRICE_ATTESTATION_PROBE fingerprint={fingerprint} guard={result['status']} checks={len(result.get('checks') or {})}"
