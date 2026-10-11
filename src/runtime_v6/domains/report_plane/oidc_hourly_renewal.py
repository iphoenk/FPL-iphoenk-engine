"""Natural-hourly private OIDC maintenance, downstream of the ONLY ChatGPT scheduler.

No timer, no independent dispatcher, no public data mutation. The shared
encrypted Git CAS store arbitrates with the existing report-prefetch worker.
No credential or provider response content is emitted to the logs.
"""
from __future__ import annotations

import hmac
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from src.runtime_v6.domains.acquisition.git_oidc_store import CASLease, store_from_env
from src.runtime_v6.domains.acquisition.official_fpl_client import AuthMaterial, OfficialFPLClient
from src.runtime_v6.domains.acquisition.rotating_oidc import (
    RotatingCredentialManager, RotationBlocked,
)
from src.runtime_v6.domains.report_plane.auth_probe import probe


RENEW_BEFORE_SECONDS = 15 * 60


def check_hourly(
    *,
    store: Any,
    manager: RotatingCredentialManager,
    entry_id: int,
    client_factory: Callable[..., Any] = OfficialFPLClient,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Reuse healthy access, or safely attempt at most one near-expiry grant."""
    if entry_id != 3462711:
        raise RotationBlocked("OIDC_HOURLY_ENTRY_NOT_APPROVED")
    before = store.load()
    if before.phase != "READY":
        raise RotationBlocked("OIDC_ROTATION_REQUIRES_REENROLLMENT")
    if before.access_token and before.expires_at > clock() + RENEW_BEFORE_SECONDS:
        return {"state": "REUSED_FRESH", "credential_version": before.version, "grant_sent": False}

    token = manager.get_access_token(refresh_before_seconds=RENEW_BEFORE_SECONDS)
    after = store.load()
    if (after.phase != "READY" or not after.access_token
            or not hmac.compare_digest(after.access_token, token)
            or after.expires_at <= clock() + 90):
        raise RotationBlocked("OIDC_HOURLY_READBACK_UNVERIFIED")
    # A competing protected worker may have rotated first. CAS enforces at
    # most one grant per old credential, not exactly one grant per process.
    material = AuthMaterial(
        mode="bearer_token",
        headers={"X-API-Authorization": "Bearer " + token},
        secret_values=(token, "Bearer " + token),
    )
    checked = probe(client_factory(auth_material=material), entry_id)
    if not (
        checked.get("probe_state") == "AUTH_AVAILABLE"
        and checked.get("me_http") == 200
        and checked.get("my_team_http") == 200
        and checked.get("entry_match") is True
        and checked.get("private_squad_15_valid") is True
    ):
        raise RotationBlocked("OIDC_HOURLY_PRIVATE_VALIDATION_FAILED")
    return {
        "state": "VALIDATED_AFTER_RENEWAL_CHECK",
        "credential_version": after.version,
        "grant_sent": after.version > before.version,
    }


def main() -> int:
    # Explicit gate even if the YAML guard is accidentally loosened.
    if os.getenv("FPL_HOURLY_SCHEDULER_KIND") != "chatgpt_scheduler":
        print("OIDC_HOURLY_RENEWAL=SKIPPED_NOT_NATURAL")
        return 0
    if os.getenv("FPL_PRIVATE_AUTO_REFRESH_PAUSED", "").lower() == "true":
        print("OIDC_HOURLY_RENEWAL=PAUSED")
        return 0
    try:
        if os.getenv("FPL_OIDC_CONTRACT_VERIFIED") != "true":
            raise RotationBlocked("OIDC_CLIENT_CONTRACT_NOT_VERIFIED")
        store = store_from_env()
        manager = RotatingCredentialManager(
            store=store, lease=CASLease(),
            token_url="https://account.premierleague.com/as/token",
            approved_host="account.premierleague.com",
            client_id=(os.getenv("FPL_OIDC_CLIENT_ID") or "").strip(),
            contract_verified=True, permit_nonrotating=False,
        )
        # FPL_TEAM_ID is not guaranteed to be an environment variable in the
        # protected runner. Use the checked-in canonical consumer identity,
        # matching the existing REUSE_ONLY probe; check_hourly still requires
        # exactly the approved 3462711 entry before touching any credential.
        context = json.loads(Path("config/v6/consumer_context.json").read_text("utf-8"))
        configured_entry = int(context["entry_id"])
        env_entry = (os.getenv("FPL_TEAM_ID") or "").strip()
        if env_entry and int(env_entry) != configured_entry:
            raise RotationBlocked("OIDC_HOURLY_ENTRY_NOT_APPROVED")
        result = check_hourly(store=store, manager=manager, entry_id=configured_entry)
    except RotationBlocked as exc:
        allowed = {
            "OIDC_HOURLY_ENTRY_NOT_APPROVED",
            "OIDC_ROTATION_REQUIRES_REENROLLMENT",
            "OIDC_HOURLY_READBACK_UNVERIFIED",
            "OIDC_HOURLY_PRIVATE_VALIDATION_FAILED",
            "OIDC_CLIENT_CONTRACT_NOT_VERIFIED",
            "OIDC_CONTRACT_NOT_VERIFIED",
            "OIDC_GRANT_REJECTED",
            "OIDC_GRANT_RESULT_UNCERTAIN",
            "OIDC_GRANT_HTTP_UNCERTAIN",
            "OIDC_GRANT_PAYLOAD_UNCERTAIN",
            "OIDC_ROTATION_PERSISTENCE_UNVERIFIED",
            "OIDC_REPLACEMENT_REFRESH_TOKEN_ABSENT",
            "OIDC_GRANT_MARKER_PERSISTENCE_FAILED",
            "OIDC_GRANT_MARKER_PERSISTENCE_UNVERIFIED",
            "CREDENTIAL_STORE_KEY_NOT_CONFIGURED",
            "CREDENTIAL_STORE_CHECKOUT_UNAVAILABLE",
            "CREDENTIAL_STORE_WRONG_REMOTE",
            "CREDENTIAL_STORE_CAS_VERSION_CONFLICT",
            "CREDENTIAL_STORE_PERSISTENCE_UNCERTAIN",
        }
        reason = str(exc)
        print("OIDC_HOURLY_RENEWAL=BLOCKED;reason=" + (reason if reason in allowed else "REVIEW_PRIVATE_CREDENTIAL_STATE"))
        return 2
    except Exception:
        print("OIDC_HOURLY_RENEWAL=FAILED_SAFE")
        return 2

    print("OIDC_HOURLY_RENEWAL=" + result["state"])
    print("OIDC_HOURLY_CREDENTIAL_VERSION=" + str(result["credential_version"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
