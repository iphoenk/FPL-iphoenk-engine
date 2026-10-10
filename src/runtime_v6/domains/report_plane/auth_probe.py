"""Read-only, redacted FPL private authentication diagnostic.

Only tests /me and, after identity verification, /my-team/{entry_id}.
Does not write report artifacts, publish finance, or print credentials/payloads.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import time
from pathlib import Path
from typing import Any

from src.runtime_v6.domains.acquisition.official_fpl_client import OfficialFPLClient
from src.runtime_v6.domains.report_plane.personal_prefetch import verified_auth_entry


def _http(result: dict[str, Any] | None) -> int | None:
    code = (result or {}).get("http_status")
    return int(code) if isinstance(code, int) and 100 <= code <= 599 else None


def _outcome(result: dict[str, Any] | None) -> str:
    """Never return error text, response headers, cookies or response body."""
    code = _http(result)
    if code == 401:
        return "HTTP_401_UNAUTHORIZED"
    if code == 403:
        return "HTTP_403_FORBIDDEN"
    if code is not None and 300 <= code < 400:
        return "HTTP_3XX_REDIRECT"
    if code == 200 and (result or {}).get("status") == "LIVE":
        return "HTTP_200_OK"
    if code is not None:
        return "HTTP_OTHER"
    status = str((result or {}).get("status") or "").upper()
    if status == "AUTH_UNAVAILABLE":
        return "NOT_CONFIGURED"
    return "REQUEST_FAILED"


def _jwt_claims_health(mode: str, environ: dict[str, str] | None = None) -> dict[str, Any]:
    """Unverified expiry hint only: claims are NOT evidence of accepted auth."""
    env = environ if environ is not None else os.environ
    output: dict[str, Any] = {
        "bearer_has_duplicate_prefix": None,
        "jwt_expiry_state": "NOT_APPLICABLE",
        "jwt_remaining_minutes": None,
    }
    if mode != "bearer_token":
        return output
    raw = str(env.get("FPL_ACCESS_TOKEN") or "").strip()
    output["bearer_has_duplicate_prefix"] = raw.lower().startswith("bearer ")
    parts = raw.split(".")
    if len(parts) != 3:
        output["jwt_expiry_state"] = "UNPARSEABLE"
        return output
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        if not isinstance(payload, dict):
            output["jwt_expiry_state"] = "UNPARSEABLE"
            return output
        exp = payload.get("exp")
        if isinstance(exp, bool) or not isinstance(exp, (int, float)):
            output["jwt_expiry_state"] = "NO_EXP_CLAIM"
            return output
        remaining = float(exp) - time.time()
        output["jwt_remaining_minutes"] = round(remaining / 60)
        output["jwt_expiry_state"] = "EXPIRED_BY_CLAIM" if remaining <= 0 else "NOT_EXPIRED_BY_CLAIM"
    except (ValueError, UnicodeError, KeyError, TypeError, OverflowError, binascii.Error):
        output["jwt_expiry_state"] = "UNPARSEABLE"
    return output


def probe(client: Any, expected_entry_id: int, *, environ: dict[str, str] | None = None) -> dict[str, Any]:
    """Pure diagnostic return schema with approved, non-secret fields only."""
    config = str(getattr(client, "auth_configuration_state", "UNAVAILABLE")).upper()
    material = getattr(client, "auth_material", None)
    mode = str(getattr(material, "mode", "disabled")) if material is not None else "disabled"
    result: dict[str, Any] = {
        "probe_state": "AUTH_UNAVAILABLE",
        "auth_configuration": config if config in {"CONFIGURED", "INVALID", "UNAVAILABLE"} else "UNKNOWN",
        "auth_mode": mode if mode in {"bearer_token", "session_cookie"} else "disabled",
        "me_http": None,
        "me_result": "NOT_CALLED",
        "entry_match": None,
        "my_team_http": None,
        "my_team_result": "NOT_CALLED",
        "private_squad_15_valid": False,
        "bank_available": False,
        "selling_prices_15_valid": False,
        "purchase_prices_15_valid": False,
        "free_transfers_field_available": False,
    }
    result.update(_jwt_claims_health(result["auth_mode"], environ))
    if config != "CONFIGURED" or not getattr(client, "auth_available", False):
        result["probe_state"] = "AUTH_CONFIGURATION_INVALID" if config == "INVALID" else "AUTH_UNAVAILABLE"
        return result
    me = client.me()
    result["me_http"] = _http(me)
    result["me_result"] = _outcome(me)
    if result["me_result"] != "HTTP_200_OK":
        result["probe_state"] = "AUTH_ME_" + result["me_result"]
        return result
    try:
        verified = verified_auth_entry(me.get("payload") or {})
    except (ValueError, TypeError, KeyError):
        verified = None
    result["entry_match"] = verified == expected_entry_id if verified is not None else None
    if verified is None:
        result["probe_state"] = "AUTH_IDENTITY_UNVERIFIED"
        return result
    if verified != expected_entry_id:
        result["probe_state"] = "AUTH_ENTRY_MISMATCH"
        return result
    team = client.my_team(expected_entry_id)
    result["my_team_http"] = _http(team)
    result["my_team_result"] = _outcome(team)
    if result["my_team_result"] != "HTTP_200_OK":
        result["probe_state"] = "AUTH_TEAM_" + result["my_team_result"]
        return result
    payload = team.get("payload") or {}
    picks = payload.get("picks") if isinstance(payload, dict) else None
    if not isinstance(picks, list):
        result["probe_state"] = "AUTH_TEAM_INVALID_PAYLOAD"
        return result
    ids = [p.get("element") for p in picks if isinstance(p, dict)]
    result["private_squad_15_valid"] = len(ids) == 15 and len(set(ids)) == 15 and all(isinstance(e, int) and e > 0 for e in ids)
    result["selling_prices_15_valid"] = result["private_squad_15_valid"] and all(isinstance(p.get("selling_price"), int) for p in picks)
    result["purchase_prices_15_valid"] = result["private_squad_15_valid"] and all(isinstance(p.get("purchase_price"), int) for p in picks)
    transfers = payload.get("transfers") if isinstance(payload.get("transfers"), dict) else {}
    result["bank_available"] = isinstance(transfers.get("bank"), int)
    result["free_transfers_field_available"] = isinstance(transfers.get("free_transfers"), int)
    result["probe_state"] = "AUTH_AVAILABLE" if result["private_squad_15_valid"] else "AUTH_TEAM_INVALID_PAYLOAD"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only FPL auth HTTP and JWT-expiry diagnostic")
    parser.add_argument("--consumer-context", default="config/v6/consumer_context.json")
    args = parser.parse_args()
    cfg = json.loads(Path(args.consumer_context).read_text(encoding="utf-8"))
    entry_id = int(os.environ.get("FPL_TEAM_ID") or cfg["entry_id"])
    if entry_id <= 0:
        raise SystemExit("AUTH_PROBE_INVALID_TEAM_ID")
    result = probe(OfficialFPLClient(), entry_id)
    print("AUTH_PROBE_RESULT=" + json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["probe_state"] == "AUTH_AVAILABLE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
