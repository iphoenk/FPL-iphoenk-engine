from __future__ import annotations

import base64
import json

from src.services import architecture_guard_service as guard


def test_emit_governed_attestation_candidate_fail_closed():
    """Temporary diagnostic only: emit exact governed attestation, never green the PR."""
    result = guard.run(force_full_scan=True)
    fingerprint = guard.repository_fingerprint()
    payload = {
        "schema_version": guard.ATTESTATION_SCHEMA_VERSION,
        "fingerprint": fingerprint,
        "release": result.get("release"),
        "guard_schema_version": result.get("schema_version"),
        "result": result,
    }
    encoded = base64.b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    print(f"V4_ATTESTATION_CANDIDATE_B64={encoded}")
    raise AssertionError("TEMP_ATTESTATION_BUILDER_FAIL_CLOSED")
