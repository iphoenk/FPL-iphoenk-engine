from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from src.utils import iso_now
from src.v5.official_auth import (
    AuthConfigurationError,
    AuthPolicyError,
    auth_material_from_env,
    expected_team_id,
    safe_get,
)


def _entry_from_me(payload: dict | None) -> int | None:
    if not isinstance(payload, dict):
        return None
    player = payload.get("player")
    value = player.get("entry") if isinstance(player, dict) else payload.get("entry")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _draft_elements(my_team: dict | None) -> list[int]:
    out = []
    for row in (my_team or {}).get("picks", []) or []:
        try:
            out.append(int(row["element"]))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _draft_fingerprint(elements: list[int]) -> str | None:
    if not elements:
        return None
    raw = json.dumps(sorted(elements), separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def safe_finance(my_team: dict | None, allowed_elements: Iterable[int]) -> dict:
    allowed = {int(x) for x in allowed_elements}
    payload = my_team or {}
    transfers = payload.get("transfers") if isinstance(payload.get("transfers"), dict) else {}
    picks = payload.get("picks") if isinstance(payload.get("picks"), list) else []
    prices = []
    for row in picks:
        try:
            eid = int(row.get("element"))
        except (TypeError, ValueError):
            continue
        if eid not in allowed:
            continue
        item = {"element": eid}
        for key in ("purchase_price", "selling_price"):
            value = row.get(key)
            if value is not None:
                item[key] = int(value)
        prices.append(item)
    expected = len(allowed)
    covered = len({x["element"] for x in prices})
    exact_complete = bool(expected) and covered == expected and all("selling_price" in x for x in prices)
    purchase_complete = bool(expected) and covered == expected and all("purchase_price" in x for x in prices)
    return {
        "bank": transfers.get("bank"),
        "value": transfers.get("value"),
        "transfers_made": transfers.get("made"),
        "transfer_cost": transfers.get("cost"),
        "coverage": {"expected": expected, "covered": covered, "complete": exact_complete},
        "exact_sell_total": sum(x["selling_price"] for x in prices) if exact_complete else None,
        "exact_purchase_total": sum(x["purchase_price"] for x in prices) if purchase_complete else None,
        "prices_for_authoritative_squad": prices,
    }


def summarize_authenticated_payloads(
    *,
    me: dict | None,
    my_team: dict | None,
    transfers_latest: Any,
    authoritative_elements: Iterable[int],
    endpoint_health: dict[str, dict] | None = None,
) -> dict:
    expected = expected_team_id()
    authoritative = {int(x) for x in authoritative_elements}
    verified = _entry_from_me(me)
    draft = _draft_elements(my_team)
    if verified is None:
        state = "UNAVAILABLE"
    elif verified != expected:
        state = "ENTRY_MISMATCH"
    elif not isinstance(my_team, dict):
        state = "PARTIAL"
    else:
        state = "VALID"
    if isinstance(transfers_latest, list):
        transfer_summary = {"available": True, "count": len(transfers_latest)}
    elif isinstance(transfers_latest, dict):
        values = next((transfers_latest.get(k) for k in ("transfers", "results") if isinstance(transfers_latest.get(k), list)), None)
        transfer_summary = {"available": True, "count": len(values) if isinstance(values, list) else None}
    else:
        transfer_summary = {"available": False, "count": None}
    return {
        "checked_at": iso_now(),
        "expected_entry": expected,
        "verified_entry": verified,
        "state": state,
        "endpoint_health": endpoint_health or {},
        "safe_finance": safe_finance(my_team, authoritative),
        "draft_integrity": {
            "count": len(draft) if draft else None,
            "fingerprint": _draft_fingerprint(draft),
            "matches_authoritative_squad": set(draft) == authoritative if draft and authoritative else None,
        },
        "transfers_latest": transfer_summary,
        "raw_authenticated_payload_persisted": False,
    }


def collect(authoritative_elements: Iterable[int]) -> dict:
    checked_at = iso_now()
    expected = expected_team_id()
    base = {
        "checked_at": checked_at,
        "expected_entry": expected,
        "state": "DISABLED",
        "verified_entry": None,
        "endpoint_health": {},
        "safe_finance": {},
        "draft_integrity": {"count": None, "fingerprint": None, "matches_authoritative_squad": None},
        "transfers_latest": {"available": False, "count": None},
        "raw_authenticated_payload_persisted": False,
    }
    try:
        material = auth_material_from_env()
    except AuthConfigurationError:
        return {**base, "state": "MISCONFIGURED"}
    if material is None:
        return base
    try:
        me, health_me = safe_get("me", material)
    except AuthPolicyError:
        return {**base, "state": "POLICY_BLOCKED"}
    health = {"me": health_me}
    if health_me.get("status") == "AUTH_REJECTED":
        return {**base, "state": "EXPIRED_OR_REJECTED", "endpoint_health": health}
    verified = _entry_from_me(me)
    if verified != expected:
        return {**base, "state": "ENTRY_MISMATCH", "verified_entry": verified, "endpoint_health": health}
    my_team, health_team = safe_get("my_team", material)
    latest, health_latest = safe_get("transfers_latest", material)
    health.update({"my_team": health_team, "transfers_latest": health_latest})
    summary = summarize_authenticated_payloads(
        me=me,
        my_team=my_team,
        transfers_latest=latest,
        authoritative_elements=authoritative_elements,
        endpoint_health=health,
    )
    if health_team.get("status") == "AUTH_REJECTED" or health_latest.get("status") == "AUTH_REJECTED":
        summary["state"] = "PARTIAL_AUTH_REJECTED"
    return summary
