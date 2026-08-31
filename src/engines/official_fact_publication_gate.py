from __future__ import annotations

import json
from typing import Any

from src.engines.official_fact_completeness import (
    PUBLIC_OFFICIAL_FACT,
    build_public_official_fact_integrity,
    require_complete_user_report,
)
from src.utils import DATA, atomic_json, read_json

REPORT_FILES = (
    DATA / "user_report.json",
    DATA / "decision_brief.json",
    DATA / "deep_review_payload.json",
    DATA / "dss_watchlist_summary.json",
)


def _fact_map(integrity: dict[str, Any]) -> dict[int, dict[str, Any]]:
    rows = [
        *((integrity.get("owned") or {}).get("rows") or []),
        *((integrity.get("watchlist") or {}).get("rows") or []),
    ]
    return {int(row["element_id"]): row for row in rows if row.get("element_id") is not None}


def _apply_fact(row: dict[str, Any], facts: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Replace public FACT fields while keeping serving provenance compact.

    Detailed source/freshness provenance is carried once at report level. Each
    player row keeps the canonical element id, authority class and snapshot ref,
    which is sufficient to audit that all 35 rows came from the same snapshot
    without duplicating verbose metadata 35 times.
    """
    if row.get("element") is None:
        return row
    element = int(row["element"])
    fact = facts.get(element)
    if not fact:
        return row
    provenance = fact.get("official_fact_provenance") or {}
    out = dict(row)
    out.update({
        "element": element,
        "element_id": element,
        "name": fact.get("name"),
        "team": fact.get("team"),
        "position": fact.get("position"),
        "price": fact.get("current_price"),
        "ownership_pct": fact.get("current_ownership_pct"),
        "status": fact.get("status"),
        "fact_authority": PUBLIC_OFFICIAL_FACT,
        "official_fact_snapshot_id": provenance.get("snapshot_id"),
    })
    return out


def _apply_position_rows(positions: dict[str, Any], facts: dict[int, dict[str, Any]]) -> dict[str, Any]:
    return {
        str(position): [_apply_fact(dict(row), facts) for row in rows if isinstance(row, dict)]
        for position, rows in positions.items()
    }


def _patch_report_payload(payload: dict[str, Any], facts: dict[int, dict[str, Any]], integrity: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    if isinstance(out.get("owned_squad"), dict):
        owned = dict(out["owned_squad"])
        owned["facts"] = [_apply_fact(dict(row), facts) for row in owned.get("facts") or [] if isinstance(row, dict)]
        owned["official_fact_completeness"] = (integrity.get("owned") or {}).get("visible_gate")
        out["owned_squad"] = owned
    if isinstance(out.get("owned_15"), list):
        out["owned_15"] = [_apply_fact(dict(row), facts) for row in out.get("owned_15") or [] if isinstance(row, dict)]
    if isinstance(out.get("external_watchlist"), dict):
        watch = dict(out["external_watchlist"])
        watch["positions"] = _apply_position_rows(watch.get("positions") or {}, facts)
        watch["official_fact_completeness"] = (integrity.get("watchlist") or {}).get("visible_gate")
        out["external_watchlist"] = watch
    if isinstance(out.get("watchlist_20"), dict):
        out["watchlist_20"] = _apply_position_rows(out.get("watchlist_20") or {}, facts)
    if isinstance(out.get("positions"), dict) and out.get("count") == 20:
        out["positions"] = _apply_position_rows(out.get("positions") or {}, facts)

    gate = integrity.get("publication_integrity") or {}
    snapshot = integrity.get("official_snapshot") or {}
    out["official_fact_integrity"] = {
        "status": gate.get("status"),
        "owned": (integrity.get("owned") or {}).get("visible_gate"),
        "watchlist": (integrity.get("watchlist") or {}).get("visible_gate"),
        "authority": PUBLIC_OFFICIAL_FACT,
        "source": snapshot.get("source"),
        "snapshot_id": snapshot.get("snapshot_id"),
        "fetched_at": snapshot.get("fetched_at"),
        "freshness_state": snapshot.get("freshness_state"),
        "fallback": snapshot.get("fallback"),
        "fallback_banner": snapshot.get("fallback_banner"),
        "last_verified_at": snapshot.get("last_verified_at"),
        "age_seconds": snapshot.get("age_seconds"),
        "confidence": snapshot.get("confidence"),
        "fact_model_separation": {
            "current_price": "FACT",
            "current_ownership": "FACT",
            "confirmed_official_change": "FACT",
            "price_prediction": "MODEL",
            "purchase_price": "PERSONAL_AUTH_FACT_OR_RECONSTRUCTED_PERSONAL_FACT",
            "exact_sell_value": "PERSONAL_AUTH_FACT_WHEN_AVAILABLE",
        },
    }
    return out


def _predictor_health(latest: dict[str, Any]) -> str:
    direct = latest.get("price_model_health") or {}
    if not direct:
        direct = ((latest.get("price_summary") or {}).get("official_price_predictor_health") or {})
    status = str(direct.get("status") or "UNAVAILABLE").upper()
    if status in {"PASS", "LIVE", "FRESH"}:
        return "PASS"
    if status in {"STALE", "PARTIAL", "CALIBRATING", "DEGRADED"}:
        return "DEGRADED"
    return "UNAVAILABLE"


def run() -> dict[str, Any]:
    snapshot = read_json(DATA / "official_snapshot.json", {})
    team = read_json(DATA / "team.json", {})
    watchlist = read_json(DATA / "dss_watchlist.json", {})
    latest = read_json(DATA / "latest.json", {})
    owned_ids = [int(row["element"]) for row in team.get("team_value_ledger") or [] if row.get("element") is not None]

    integrity = build_public_official_fact_integrity(
        snapshot,
        owned_ids,
        watchlist.get("positions") or {},
        personal_auth=latest.get("authenticated_official") or {},
    )
    integrity.setdefault("health", {})["Predictor Freshness"] = _predictor_health(latest)

    gate = integrity.get("publication_integrity") or {}
    latest["official_fact_integrity"] = {
        "status": gate.get("status"),
        "owned_expected": (integrity.get("owned") or {}).get("expected"),
        "owned_resolved": (integrity.get("owned") or {}).get("resolved"),
        "owned_official_fact_complete": (integrity.get("owned") or {}).get("official_fact_complete"),
        "watchlist_expected": (integrity.get("watchlist") or {}).get("expected"),
        "watchlist_resolved": (integrity.get("watchlist") or {}).get("resolved"),
        "watchlist_official_fact_complete": (integrity.get("watchlist") or {}).get("official_fact_complete"),
        "snapshot_id": (integrity.get("official_snapshot") or {}).get("snapshot_id"),
        "freshness_state": (integrity.get("official_snapshot") or {}).get("freshness_state"),
        "health": integrity.get("health"),
        "reasons": gate.get("reasons") or [],
    }
    latest.setdefault("report_serving", {})["official_fact_integrity"] = gate.get("status")
    latest["report_serving"]["publication_integrity_gate"] = gate.get("status")
    atomic_json(DATA / "latest.json", latest)

    require_complete_user_report(integrity)
    facts = _fact_map(integrity)
    for path in REPORT_FILES:
        payload = read_json(path, {})
        if payload:
            atomic_json(path, _patch_report_payload(payload, facts, integrity))

    return {
        "status": gate.get("status"),
        "owned": (integrity.get("owned") or {}).get("visible_gate"),
        "watchlist": (integrity.get("watchlist") or {}).get("visible_gate"),
        "snapshot_id": (integrity.get("official_snapshot") or {}).get("snapshot_id"),
        "predictor_freshness": (integrity.get("health") or {}).get("Predictor Freshness"),
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
