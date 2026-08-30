from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from src.sources.official_auth import (
    AuthConfigurationError,
    AuthPolicyError,
    EXPECTED_TEAM_ID,
    auth_material_from_env,
    safe_get,
)
from src.utils import DATA, atomic_json, iso_now


def _load(name: str, default: Any):
    try:
        with open(DATA / name) as f:
            return json.load(f)
    except Exception:
        return default


def _entry_from_me(payload: dict | None) -> int | None:
    if not isinstance(payload, dict):
        return None
    player = payload.get("player")
    value = player.get("entry") if isinstance(player, dict) else payload.get("entry")
    try:
        return int(value) if value is not None else None
    except Exception:
        return None


def _authoritative_elements() -> list[int]:
    team = _load("team.json", {})
    out: list[int] = []
    for row in team.get("squad", []):
        try:
            eid = int(row["element"])
        except Exception:
            continue
        if eid not in out:
            out.append(eid)
    return out


def _draft_elements(my_team: dict | None) -> list[int]:
    out: list[int] = []
    for row in (my_team or {}).get("picks", []) or []:
        try:
            out.append(int(row["element"]))
        except Exception:
            continue
    return out


def _draft_fingerprint(elements: list[int]) -> str | None:
    if not elements:
        return None
    raw = json.dumps(sorted(elements), separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _safe_finance(my_team: dict | None, authoritative_elements: set[int]) -> dict:
    payload = my_team or {}
    transfers = payload.get("transfers") if isinstance(payload.get("transfers"), dict) else {}
    picks = payload.get("picks") if isinstance(payload.get("picks"), list) else []
    private_prices = []
    authoritative_prices = []
    for row in picks:
        try:
            eid = int(row.get("element"))
        except Exception:
            continue
        item = {"element": eid}
        for key in ("purchase_price", "selling_price"):
            if row.get(key) is not None:
                item[key] = row.get(key)
        private_prices.append(item)
        if eid in authoritative_elements:
            authoritative_prices.append(dict(item))

    expected = len(authoritative_elements)
    covered = len({x["element"] for x in authoritative_prices})
    auth_sell_complete = bool(expected) and covered == expected and all("selling_price" in x for x in authoritative_prices)
    auth_purchase_complete = bool(expected) and covered == expected and all("purchase_price" in x for x in authoritative_prices)
    private_covered = len({x["element"] for x in private_prices})
    private_sell_complete = len(picks) == 15 and private_covered == 15 and all("selling_price" in x for x in private_prices)
    private_purchase_complete = len(picks) == 15 and private_covered == 15 and all("purchase_price" in x for x in private_prices)

    return {
        "bank": transfers.get("bank"),
        "value": transfers.get("value"),
        "transfers_made": transfers.get("made"),
        "transfer_cost": transfers.get("cost"),
        "coverage": {"expected": expected, "covered": covered, "complete": auth_sell_complete},
        "exact_sell_total": sum(x["selling_price"] or 0 for x in authoritative_prices) if auth_sell_complete else None,
        "exact_purchase_total": sum(x["purchase_price"] or 0 for x in authoritative_prices) if auth_purchase_complete else None,
        "prices_for_authoritative_squad": authoritative_prices,
        "private_squad_coverage": {"expected": 15, "covered": private_covered, "complete": private_covered == 15},
        "private_exact_sell_total": sum(x["selling_price"] or 0 for x in private_prices) if private_sell_complete else None,
        "private_exact_purchase_total": sum(x["purchase_price"] or 0 for x in private_prices) if private_purchase_complete else None,
        "prices_for_private_squad": private_prices,
    }


def _safe_chip_state(my_team: dict | None) -> dict:
    chips = (my_team or {}).get("chips")
    if not isinstance(chips, list):
        return {"available": False, "chips": []}
    return {
        "available": True,
        "chips": [
            {
                "name": chip.get("name"),
                "status_for_entry": chip.get("status_for_entry"),
                "played_by_entry": chip.get("played_by_entry"),
            }
            for chip in chips if isinstance(chip, dict)
        ],
    }


def _safe_transfers_latest(payload: Any) -> dict:
    if isinstance(payload, list):
        return {"available": True, "count": len(payload)}
    if isinstance(payload, dict):
        for key in ("transfers", "results"):
            if isinstance(payload.get(key), list):
                return {"available": True, "count": len(payload[key])}
        return {"available": True, "count": None}
    return {"available": False, "count": None}


def _enhancement_health(summary: dict) -> dict:
    """Report authenticated enrichment health without gating public production."""
    if summary.get("mode") == "disabled" and summary.get("state") == "DISABLED":
        return {"required": False, "ready": True, "status": "NOT_CONFIGURED", "reasons": []}
    reasons: list[str] = []
    if summary.get("state") != "VALID":
        reasons.append(f"state={summary.get('state')}")
    if summary.get("verified_entry") != EXPECTED_TEAM_ID:
        reasons.append("entry_not_verified")
    if summary.get("raw_authenticated_payload_persisted") is not False:
        reasons.append("raw_payload_policy_violation")
    if summary.get("failure_reason"):
        reasons.append(str(summary["failure_reason"]))
    return {
        "required": False,
        "ready": not reasons,
        "status": "AVAILABLE" if not reasons else "DEGRADED",
        "reasons": reasons,
    }


def _production_readiness(summary: dict) -> dict:
    # Backward-compatible field name. Auth is never a production prerequisite;
    # public Official + target-GW-scoped user capture owns the primary path.
    return _enhancement_health(summary)


def _persist(summary: dict):
    summary["production_readiness"] = _production_readiness(summary)
    summary["enhancement_health"] = dict(summary["production_readiness"])
    atomic_json(DATA / "auth.json", summary)
    latest = _load("latest.json", {})
    latest["authenticated_official"] = summary
    latest.setdefault("files", {})["auth"] = "data/auth.json"
    atomic_json(DATA / "latest.json", latest)
    return summary


def _transport_rejected(*health_rows: dict) -> bool:
    return any(row.get("status") == "REDIRECT_REJECTED" for row in health_rows if isinstance(row, dict))


def _base_summary() -> dict:
    return {
        "checked_at": iso_now(),
        "expected_entry": EXPECTED_TEAM_ID,
        "state": "DISABLED",
        "mode": "disabled",
        "verified_entry": None,
        "endpoint_health": {},
        "safe_finance": {},
        "draft_integrity": {"count": None, "fingerprint": None, "matches_authoritative_squad": None},
        "chip_state": {"available": False, "chips": []},
        "transfers_latest": {"available": False, "count": None},
        "raw_authenticated_payload_persisted": False,
        "policy": {
            "role": "OPTIONAL_PRIVATE_ENRICHMENT",
            "primary_authority": "PUBLIC_OFFICIAL_PLUS_USER_CAPTURE",
            "resource_methods": ["GET"],
            "allowed_endpoints": ["me", "my-team", "transfers-latest"],
            "redirects_followed": False,
            "redirects_rejected": True,
            "production_blocking": False,
            "configured_mode_requires_production_validation": False,
        },
    }


def _run_once() -> dict:
    authoritative = _authoritative_elements()
    base = _base_summary()

    try:
        material = auth_material_from_env()
    except AuthConfigurationError:
        base["state"] = "MISCONFIGURED"
        base["mode"] = "configured"
        return _persist(base)
    if material is None:
        return _persist(base)
    base["mode"] = material.mode

    try:
        me, hm = safe_get("me/", material)
    except AuthPolicyError:
        base["state"] = "POLICY_BLOCKED"
        return _persist(base)
    base["endpoint_health"]["me"] = hm
    if hm.get("status") == "AUTH_REJECTED":
        base["state"] = "EXPIRED_OR_REJECTED"
        return _persist(base)
    if _transport_rejected(hm):
        base["state"] = "REDIRECT_REJECTED"
        return _persist(base)
    if not me:
        base["state"] = "UNAVAILABLE"
        return _persist(base)

    entry_id = _entry_from_me(me)
    base["verified_entry"] = entry_id
    if entry_id != EXPECTED_TEAM_ID:
        base["state"] = "ENTRY_MISMATCH"
        return _persist(base)

    my_team, ht = safe_get(f"my-team/{EXPECTED_TEAM_ID}/", material)
    base["endpoint_health"]["my_team"] = ht
    latest, hl = safe_get(f"entry/{EXPECTED_TEAM_ID}/transfers-latest/", material)
    base["endpoint_health"]["transfers_latest"] = hl

    if _transport_rejected(ht, hl):
        base["state"] = "PARTIAL_REDIRECT_REJECTED"
    elif ht.get("status") == "AUTH_REJECTED" or hl.get("status") == "AUTH_REJECTED":
        base["state"] = "PARTIAL_AUTH_REJECTED"
    elif not my_team:
        base["state"] = "PARTIAL"
    else:
        base["state"] = "VALID"

    draft = _draft_elements(my_team)
    authoritative_set = set(authoritative)
    base["safe_finance"] = _safe_finance(my_team, authoritative_set)
    base["draft_integrity"] = {
        "count": len(draft) if draft else None,
        "fingerprint": _draft_fingerprint(draft),
        "matches_authoritative_squad": set(draft) == authoritative_set if draft and authoritative_set else None,
    }
    base["chip_state"] = _safe_chip_state(my_team)
    base["transfers_latest"] = _safe_transfers_latest(latest)
    return _persist(base)


def run() -> dict:
    """Run optional private enrichment and always leave deterministic safe health.

    Known auth/transport states are handled explicitly by _run_once(). Any unexpected
    service-layer exception degrades only this optional enrichment. Error text is not
    persisted because it could contain transport internals; required public core keeps
    its independent fail-closed policy.
    """
    try:
        return _run_once()
    except Exception:
        base = _base_summary()
        mode = os.getenv("FPL_AUTH_MODE", "disabled").strip().lower() or "disabled"
        base["mode"] = mode
        base["state"] = "UNAVAILABLE"
        base["failure_reason"] = "SERVICE_FAILURE"
        return _persist(base)


if __name__ == "__main__":
    run()
