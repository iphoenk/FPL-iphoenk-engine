from __future__ import annotations

import json


def test_emit_refreshed_architecture_attestation_for_pr_repair():
    from src.services import architecture_guard_service as guard
    from src.utils import atomic_json

    result = guard.run(force_full_scan=True)
    fingerprint = guard.repository_fingerprint()
    payload = {
        "schema_version": guard.ATTESTATION_SCHEMA_VERSION,
        "fingerprint": fingerprint,
        "release": result.get("release"),
        "guard_schema_version": result.get("schema_version"),
        "result": result,
    }
    atomic_json(guard.ATTESTATION_PATH, payload)
    print("ATTJSON=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    assert False, "ATTTEST_EMIT"
