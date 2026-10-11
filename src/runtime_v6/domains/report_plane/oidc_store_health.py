"""Safe read-only encrypted OIDC store diagnostics.

This module never issues a refresh grant or mutates persisted credentials.
It prints only fixed metadata, never secrets, transaction IDs or token bodies.
"""
from __future__ import annotations

import json
import time
from typing import Any

from src.runtime_v6.domains.acquisition.git_oidc_store import store_from_env
from src.runtime_v6.domains.acquisition.rotating_oidc import RotationBlocked


def inspect_store(store: Any, *, now: float | None = None) -> dict[str, Any]:
    credential = store.load()
    remaining = float(credential.expires_at or 0) - (time.time() if now is None else now)
    return {
        "credential_version": credential.version,
        "phase": credential.phase,
        "access_state": (
            "VALID_OVER_90S" if credential.access_token and remaining > 90
            else "EXPIRED_OR_UNAVAILABLE"
        ),
        "refresh_present": bool(credential.refresh_token),
        "grant_sent": False,
        "credentials_mutated": False,
    }


def main() -> int:
    try:
        result = inspect_store(store_from_env())
    except RotationBlocked as exc:
        allowed = {
            "CREDENTIAL_STORE_CHECKOUT_UNAVAILABLE",
            "CREDENTIAL_STORE_ENCRYPTION_KEY_INVALID",
            "CREDENTIAL_STORE_WRONG_REMOTE",
            "CREDENTIAL_STORE_GIT_UNAVAILABLE",
            "CREDENTIAL_STORE_GIT_OPERATION_FAILED",
            "CREDENTIAL_STORE_EMPTY_ENCRYPTED_BLOB",
            "CREDENTIAL_STORE_DECRYPTION_OR_SCHEMA_INVALID",
            "CREDENTIAL_STORE_KEY_NOT_CONFIGURED",
        }
        code = str(exc)
        print("OIDC_STORE_HEALTH=BLOCKED;reason=" + (code if code in allowed else "STORE_CHECK_FAILED_SAFE"))
        return 2
    except Exception:
        print("OIDC_STORE_HEALTH=FAILED_SAFE")
        return 2
    print("OIDC_STORE_HEALTH=PASS")
    print("OIDC_STORE_STATUS=" + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
