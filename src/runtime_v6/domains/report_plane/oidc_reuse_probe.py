"""Owner-only REUSE_ONLY probe: NEVER use an OIDC refresh grant.

Loads the existing encrypted access credential from the protected persistent
store in a fresh worker, then performs GET /me + /my-team without any token POST.
No credential values, HTTP bodies or headers are printed.
"""
from __future__ import annotations

import json
import os
import time
import hmac
from pathlib import Path

from src.runtime_v6.domains.acquisition.git_oidc_store import store_from_env
from src.runtime_v6.domains.acquisition.official_fpl_client import AuthMaterial, OfficialFPLClient
from src.runtime_v6.domains.acquisition.rotating_oidc import RotationBlocked
from src.runtime_v6.domains.report_plane.auth_probe import probe


def reuse_only_probe(*, store, client_factory=OfficialFPLClient, clock=time.time, entry_id: int) -> dict:
    if entry_id != 3462711:
        raise RotationBlocked("REUSE_ONLY_WRONG_EXPECTED_ENTRY")
    credential = store.load()
    if credential.phase != "READY":
        raise RotationBlocked("REUSE_ONLY_CREDENTIAL_NOT_READY")
    if not credential.access_token:
        raise RotationBlocked("REUSE_ONLY_NO_SAVED_ACCESS")
    if credential.expires_at <= clock() + 90:
        # Important: DO NOT fall through to the refresh grant.
        raise RotationBlocked("REUSE_ONLY_ACCESS_EXPIRED_OR_NEAR_EXPIRY")

    token = credential.access_token
    material = AuthMaterial(
        mode="bearer_token",
        headers={"X-API-Authorization": "Bearer " + token},
        secret_values=(token, "Bearer " + token),
    )
    report = probe(client_factory(auth_material=material), entry_id)
    after = store.load()
    unchanged = (
        after.version == credential.version
        and after.phase == "READY"
        and hmac.compare_digest(after.refresh_token, credential.refresh_token)
        and hmac.compare_digest(after.access_token, credential.access_token)
    )
    # Sanitize output. Only allowlisted, non-secret diagnostic fields.
    result = {
        "mode": "REUSE_ONLY",
        "probe_state": report["probe_state"],
        "credential_version": credential.version,
        "credential_unchanged": unchanged,
        "me_http": report["me_http"],
        "entry_match": report["entry_match"],
        "my_team_http": report["my_team_http"],
        "private_squad_15_valid": report["private_squad_15_valid"],
        "bank_available": report["bank_available"],
        "selling_prices_15_valid": report["selling_prices_15_valid"],
        "purchase_prices_15_valid": report["purchase_prices_15_valid"],
        "free_transfers_normalizable": report["free_transfers_normalizable"],
    }
    return result


def main() -> int:
    # Never let raw provider exception strings escape into GitHub logs.
    try:
        context = json.loads(Path("config/v6/consumer_context.json").read_text("utf-8"))
        entry_id = int(os.environ.get("FPL_TEAM_ID") or context["entry_id"])
        result = reuse_only_probe(store=store_from_env(), entry_id=entry_id)
    except RotationBlocked as exc:
        print("OIDC_REUSE_ONLY=BLOCKED;reason=" + str(exc))
        return 2
    except Exception:
        print("OIDC_REUSE_ONLY=FAILED_SAFE")
        return 2

    print("OIDC_REUSE_RESULT=" + json.dumps(result, sort_keys=True, separators=(",", ":")))
    success = (
        result["probe_state"] == "AUTH_AVAILABLE"
        and result["credential_unchanged"]
        and result["me_http"] == 200
        and result["my_team_http"] == 200
        and result["entry_match"] is True
        and result["private_squad_15_valid"] is True
    )
    print("OIDC_REUSE_ONLY=" + ("PASS" if success else "FAIL"))
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
