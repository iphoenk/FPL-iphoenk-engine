from __future__ import annotations

import json
from typing import Any

from src.utils import DATA, atomic_json, read_json

WATCHLIST_OUT = DATA / "dss_watchlist.json"


def _safe_price_context(price: dict[str, Any]) -> dict[str, Any]:
    out = dict(price or {})
    health = str(out.pop("official_projection_health", "") or "")
    if health == "SUSPECT_STATIC_OFFSET0":
        out["projection_confidence_note"] = "proyeksi waktu perubahan harga belum cukup yakin"
    elif out.get("prediction_source") == "TRAJECTORY_RATE":
        out["projection_confidence_note"] = "arah tekanan harga jelas, waktu perubahan masih estimasi"
    elif any(out.get(key) is not None for key in ("official_progress_pct", "risk_direction", "urgency")):
        out["projection_confidence_note"] = "sinyal harga tersedia"
    return out


def sanitize(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload or {})
    positions = {}
    for position, rows in (result.get("positions") or {}).items():
        clean_rows = []
        for source in rows or []:
            row = dict(source)
            row["price_risk"] = _safe_price_context(row.get("price_risk") or {})
            clean_rows.append(row)
        positions[str(position)] = clean_rows
    result["positions"] = positions

    # The report architecture treats FULL_DSS_SCREEN_V1 as an admission contract.
    # If screening failed or evidence is insufficient, do not expose a misleading
    # contract that could make a downstream report call the watchlist READY.
    if result.get("status") != "READY" and result.get("screening_contract") == "FULL_DSS_SCREEN_V1":
        result["screening_contract"] = "FULL_DSS_SCREEN_INCOMPLETE_V1"

    result.setdefault("public_contract", {}).update({
        "technical_price_health_codes_removed": True,
        "natural_language_price_confidence": True,
        "ready_contract_requires_ready_status": True,
    })
    return result


def run() -> dict[str, Any]:
    payload = read_json(WATCHLIST_OUT, {})
    if not payload:
        raise RuntimeError("dss_watchlist.json unavailable for public sanitization")
    clean = sanitize(payload)
    atomic_json(WATCHLIST_OUT, clean)

    latest = read_json(DATA / "latest.json", {})
    summary = latest.get("dss_watchlist_summary") or {}
    summary["screening_contract"] = clean.get("screening_contract")
    summary["status"] = clean.get("status")
    summary["public_sanitized"] = True
    latest["dss_watchlist_summary"] = summary
    atomic_json(DATA / "latest.json", latest)
    return clean


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "status": result.get("status"),
        "screening_contract": result.get("screening_contract"),
        "public_contract": result.get("public_contract"),
    }, ensure_ascii=False))
