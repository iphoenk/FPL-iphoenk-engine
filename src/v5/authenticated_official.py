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


def _policy() -> dict[str, Any]:
    return {
        "role": "OPTIONAL_PRIVATE_ENRICHMENT",
        "primary_authority": "PUBLIC_OFFICIAL_PLUS_USER_CAPTURE",
        "resource_methods": ["GET"],
        "production_blocking": False,
        "configured_mode_requires_production_validation": False,
        "raw_authenticated_payload_persisted": False,
    }


def safe_finance(my_team: dict | None, allowed_elements: Iterable[int]) -> dict:
    allowed = {int(x) for x in allowed_elements}
    payload = my_team or {}
    transfers = payload.get("transfers") if isinstance(payload.get("transfers"), dict) else {}
    picks = payload.get("picks") if isinstance(payload.get("picks"), list) else []
    private_prices = []
    authoritative_prices = []
    for row in picks:
        try:
            eid = int(row.get("element"))
        except (TypeError, ValueError):
            continue
        item = {"element": eid}
        for key in ("purchase_price", "selling_price"):
            value = row.get(key)
            if value is not None:
                item[key] = int(value)
        private_prices.append(item)
        if eid in allowed:
            authoritative_prices.append(dict(item))

    expected = len(allowed)
    covered = len({x["element"] for x in authoritative_prices})
    exact_complete = bool(expected) and covered == expected and all("selling_price" in x for x in authoritative_prices)
    purchase_complete = bool(expected) and covered == expected and all("purchase_price" in x for x in authoritative_prices)
    private_covered = len({x["element"] for x in private_prices})
    private_sell_complete = len(picks) == 15 and private_covered == 15 and all("selling_price" in x for x in private_prices)
    private_purchase_complete = len(picks) == 15 and private_covered == 15 and all("purchase_price" in x for x in private_prices)
    return {
        "bank": transfers.get("bank"),
        "value": transfers.get("value"),
        "transfers_made": transfers.get("made"),
        "transfer_cost": transfers.get("cost"),
        "coverage": {"expected": expected, "covered": covered, "complete": exact_complete},
        "exact_sell_total": sum(x["selling_price"] for x in authoritative_prices) if exact_complete else None,
        "exact_purchase_total": sum(x["purchase_price"] for x in authoritative_prices) if purchase_complete else None,
        "prices_for_authoritative_squad": authoritative_prices,
        "private_squad_coverage": {"expected": 15, "covered": private_covered, "complete": private_covered == 15},
        "private_exact_sell_total": sum(x["selling_price"] for x in private_prices) if private_sell_complete else None,
        "private_exact_purchase_total": sum(x["purchase_price"] for x in private_prices) if private_purchase_complete else None,
        "prices_for_private_squad": private_prices,
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
        values = next(
            (transfers_latest.get(k) for k in ("transfers", "results") if isinstance(transfers_latest.get(k), list)),
            None,
        )
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
        "enhancement_health": {
            "required": False,
            "ready": state == "VALID",
            "status": "AVAILABLE" if state == "VALID" else "DEGRADED",
        },
        "policy": _policy(),
    }


def _base_summary(state: str = "DISABLED") -> dict:
    return {
        "checked_at": iso_now(),
        "expected_entry": expected_team_id(),
        "state": state,
        "verified_entry": None,
        "endpoint_health": {},
        "safe_finance": {},
        "draft_integrity": {"count": None, "fingerprint": None, "matches_authoritative_squad": None},
        "transfers_latest": {"available": False, "count": None},
        "raw_authenticated_payload_persisted": False,
        "enhancement_health": {
            "required": False,
            "ready": True,
            "status": "NOT_CONFIGURED" if state == "DISABLED" else "DEGRADED",
        },
        "policy": _policy(),
    }


def collect_runtime(authoritative_elements: Iterable[int] = ()) -> dict[str, Any]:
    """Return safe private enrichment plus in-memory payload; auth never owns production squad truth."""
    base = _base_summary()
    try:
        material = auth_material_from_env()
    except AuthConfigurationError:
        return {
            "summary": {
                **base,
                "state": "MISCONFIGURED",
                "enhancement_health": {"required": False, "ready": False, "status": "DEGRADED"},
            },
            "my_team": None,
        }
    if material is None:
        return {"summary": base, "my_team": None}
    try:
        me, health_me = safe_get("me", material)
    except AuthPolicyError:
        return {
            "summary": {
                **base,
                "state": "POLICY_BLOCKED",
                "enhancement_health": {"required": False, "ready": False, "status": "DEGRADED"},
            },
            "my_team": None,
        }
    health = {"me": health_me}
    if health_me.get("status") == "AUTH_REJECTED":
        return {
            "summary": {
                **base,
                "state": "EXPIRED_OR_REJECTED",
                "endpoint_health": health,
                "enhancement_health": {"required": False, "ready": False, "status": "DEGRADED"},
            },
            "my_team": None,
        }
    verified = _entry_from_me(me)
    if verified != expected_team_id():
        return {
            "summary": {
                **base,
                "state": "ENTRY_MISMATCH",
                "verified_entry": verified,
                "endpoint_health": health,
                "enhancement_health": {"required": False, "ready": False, "status": "DEGRADED"},
            },
            "my_team": None,
        }
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
        summary["enhancement_health"] = {"required": False, "ready": False, "status": "DEGRADED"}
    return {"summary": summary, "my_team": my_team if isinstance(my_team, dict) else None}


def collect(authoritative_elements: Iterable[int]) -> dict:
    return collect_runtime(authoritative_elements)["summary"]
