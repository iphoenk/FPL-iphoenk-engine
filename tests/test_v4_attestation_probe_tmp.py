from __future__ import annotations

import json


def test_emit_architecture_attestation_probe():
    from src.services import architecture_guard_service as guard

    result = guard.run(force_full_scan=True)
    fingerprint = guard.repository_fingerprint()
    print("ARCH_ATTEST_FINGERPRINT=" + fingerprint)
    print("ARCH_ATTEST_RESULT=" + json.dumps(result, sort_keys=True, separators=(",", ":")))
    raise AssertionError("TEMP_ATTESTATION_PROBE_COMPLETE")
