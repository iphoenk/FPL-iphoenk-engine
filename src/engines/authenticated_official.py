from __future__ import annotations

import hashlib
import json
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
    if isinstance(player, dict) and player.get("entry") is not None:
        try:
            return int(player["entry"])
        except Exception:
            return None
    if payload.get("entry") is not None:
        try:
            return int(payload["entry"])
        except Exception:
            return None
    return None


def _authoritative_elements() -> list[int]:
    team = _load("team.json", {})
    out = []
    for row in team.get("squad", []):
        try:
            eid = int(row["element"])
        except Exception:
            continue
        if eid not in out:
            out.append(eid)
    return out


def _draft_elements(my_team: dict | None) -> list[int]:
    out = []
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
    """Persist only safe private finance facts, never the raw authenticated payload.

    Exact private purchase/sell totals are computed over the current 15-player
    private squad returned by my-team. Authoritative submitted-squad coverage is
    tracked separately because a legitimate pre-deadline transfer can make the
    private squad differ from the previous submitted squad.
    """
    payload = my_team or {}
    transfers = payload.get("transfers") if isinstance(payload.get("transfers"), dict) else {}
    picks = payload.get("picks") if isinstance(payload.get("picks"), list) else []

    prices = []
    authoritative_covered: set[int] = set()
    for row in picks:
        try:
            eid = int(row.get("element"))
        except Exception:
            continue
        item = {"element": eid}
        for key in ("purchase_price", "selling_price"):
            value = row.get(key)
            if value is not None:
                item[key] = value
        prices.append(item)
        if eid in authoritative_elements:
            authoritative_covered.add(eid)

    private_expected = len(picks)
    private_covered = len({x["element"] for x in prices})
    sell_complete = (
        private_expected == 15
        and private_covered == 15
        and all("selling_price" in x for x in prices)
    )
    purchase_complete = (
        private_expected == 15
        and private_covered == 15
        and all("purchase_price" in x for x in prices)
    )

    return {
        "bank": transfers.get("bank"),
        "value": transfers.get("value"),
        "transfers_made": transfers.get("made"),
        "transfer_cost": transfers.get("cost"),
        "private_squad_coverage": {
            "expected": 15,
            "covered": private_covered,
            "complete": private_covered == 15,
        },
        "authoritative_submitted_coverage": {
            "expected": len(authoritative_elements),
            "covered": len(authoritative_covered),
            "complete": bool(authoritative_elements) and authoritative_covered == authoritative_elements,
        },
        "exact_sell_total": sum(x["selling_price"] or 0 for x in prices) if sell_complete else None,
        "exact_purchase_total": sum(x["purchase_price"] or 0 for x in prices) if purchase_complete else None,
        "prices_for_private_squad": prices,
    }


def _safe_chip_state(my_team: dict | None) -> dict:
    chips = (my_team or {}).get("chips")
    if not isinstance(chips, list):
        return {"available": False, "chips": []}
    safe = []
    for chip in chips:
        if not isinstance(chip, dict):
            continue
        safe.append({
            "name": chip.get("name"),
            "status_for_entry": chip.get("status_for_entry"),
            "played_by_entry": chip.get("played_by_entry"),
        })
    return {"available": True, "chips": safe}


def _safe_transfers_latest(payload: Any) -> dict:
    if isinstance(payload, list):
        return {"available": True, "count": len(payload)}
    if isinstance(payload, dict):
        for key in ("transfers", "results"):
            if isinstance(payload.get(key), list):
                return {"available": True, "count": len(payload[key])}
        return {"available": True, "count": None}
    return {"available": False, "count": None}


def _production_readiness(summary: dict) -> dict:
    if summary.get("mode") == "disabled":
        return {"required": False, "ready": True, "reasons": []}

    reasons: list[str] = []
    if summary.get("state") != "VALID":
        reasons.append(f"state={summary.get('state')}")
    if summary.get("verified_entry") != EXPECTED_TEAM_ID:
        reasons.append("entry_not_verified")

    health = summary.get("endpoint_health") or {}
    for key in ("me", "my_team", "transfers_latest"):
        if (health.get(key) or {}).get("status") != "LIVE":
            reasons.append(f"endpoint_{key}_not_live")

    finance = summary.get("safe_finance") or {}
    if not (finance.get("private_squad_coverage") or {}).get("complete"):
        reasons.append("private_squad_finance_incomplete")
    if finance.get("exact_sell_total") is None:
        reasons.append("exact_sell_total_unavailable")
    if finance.get("exact_purchase_total") is None:
        reasons.append("exact_purchase_total_unavailable")
    if not (summary.get("chip_state") or {}).get("available"):
        reasons.append("chip_state_unavailable")
    if not (summary.get("transfers_latest") or {}).get("available"):
        reasons.append("transfers_latest_unavailable")
    if summary.get("raw_authenticated_payload_persisted") is not False:
        reasons.append("raw_payload_policy_violation")

    return {"required": True, "ready": not reasons, "reasons": reasons}


def _persist(summary: dict):
    summary["production_readiness"] = _production_readiness(summary)
    atomic_json(DATA / "auth.json", summary)
    latest = _load("latest.json", {})
    latest["authenticated_official"] = summary
    latest.setdefault("files", {})["auth"] = "data/auth.json"
    atomic_json(DATA / "latest.json", latest)

    readiness = summary["production_readiness"]
    if readiness.get("required") and not readiness.get("ready"):
        raise RuntimeError(
            "FAIL CLOSED: configured authenticated Official FPL is not production-ready: "
            + ",".join(readiness.get("reasons") or [])
        )
    return summary


def _transport_rejected(*health_rows: dict) -> bool:
    return any(row.get("status") == "REDIRECT_REJECTED" for row in health_rows if isinstance(row, dict))


def run() -> dict:
    checked_at = iso_now()
    authoritative = _authoritative_elements()
    base = {
        "checked_at": checked_at,
        "expected_entry": EXPECTED_TEAM_ID,
        "state": "DISABLED",
        "mode": "disabled",
        "verified_entry": None,
        "endpoint_health": {},
        "safe_finance": {},
        "draft_integrity": {
            "count": None,
            "fingerprint": None,
            "matches_authoritative_squad": None,
        },
        "chip_state": {"available": False, "chips": []},
        "transfers_latest": {"available": False, "count": None},
        "raw_authenticated_payload_persisted": False,
        "policy": {
            "resource_methods": ["GET"],
            "allowed_endpoints": ["me", "my-team", "transfers-latest"],
            "redirects_followed": False,
            "redirects_rejected": True,
            "fail_soft_when_disabled": True,
            "configured_mode_requires_production_validation": True,
        },
    }

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


if __name__ == "__main__":
    run()
