from __future__ import annotations

import json

from src.services import architecture_guard_service as guard
from src.utils import atomic_json


def main() -> None:
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
    print(json.dumps({
        "service": "architecture_guard_attestation_builder",
        "status": "PASS",
        "fingerprint": fingerprint,
        "checks": len(result.get("checks") or {}),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
