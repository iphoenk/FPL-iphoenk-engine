from __future__ import annotations

import base64
import json


def test_emit_refreshed_attestation_payload_for_branch_maintenance():
    from src.services import architecture_guard_service as guard

    result = guard.run(force_full_scan=True)
    payload = {
        "schema_version": guard.ATTESTATION_SCHEMA_VERSION,
        "fingerprint": guard.repository_fingerprint(),
        "release": result.get("release"),
        "guard_schema_version": result.get("schema_version"),
        "result": result,
    }
    encoded = base64.b64encode((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")).decode("ascii")
    raise AssertionError("ATTESTATION_PAYLOAD_B64=" + encoded)
