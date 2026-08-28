from __future__ import annotations

import json
from typing import Any

from src.engines.tactical_decision_consumption import apply_watchlist_overlay
from src.utils import DATA, atomic_json, read_json

WATCHLIST_OUT = DATA / "dss_watchlist.json"

PUBLIC_FIELDS = {
    "element", "name", "team", "team_id", "position", "now_cost", "price", "status",
    "ownership_pct", "projection_confidence", "xmins", "horizons", "direct_replacement_context",
    "evidence_coverage", "critical_dimension_score", "dss_score", "rank", "lifecycle",
    "reasons", "risks", "action", "tactical_matchup",
}


def _safe_price_context(price: dict[str, Any]) -> dict[str, Any]:
    source = dict(price or {})
    health = str(source.pop("official_projection_health", "") or "")
    out = {
        key: source.get(key)
        for key in (
            "official_progress_pct", "official_hourly_rate_pct", "risk_direction", "urgency",
            "predicted_change_deadline",
        )
        if source.get(key) is not None
    }
    if health == "SUSPECT_STATIC_OFFSET0":
        out["projection_confidence_note"] = "proyeksi waktu perubahan harga belum cukup yakin"
    elif source.get("prediction_source") == "TRAJECTORY_RATE":
        out["projection_confidence_note"] = "arah tekanan harga jelas, waktu perubahan masih estimasi"
    elif out:
        out["projection_confidence_note"] = "sinyal harga tersedia"
    return out


def _public_underlying(source: dict[str, Any]) -> dict[str, Any]:
    raw = source.get("underlying") or {}
    return {
        key: raw.get(key)
        for key in ("xg90", "xa90", "bonus90", "dc90", "saves90")
        if raw.get(key) is not None
    }


def _public_row(source: dict[str, Any]) -> dict[str, Any]:
    row = {key: source.get(key) for key in PUBLIC_FIELDS if key in source}
    underlying = _public_underlying(source)
    if underlying:
        row["underlying"] = underlying
    row["price_risk"] = _safe_price_context(source.get("price_risk") or {})
    return row


def sanitize(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload or {})
    positions = {}
    candidate_audit = dict(result.get("candidate_audit") or {})
    for position, rows in (result.get("positions") or {}).items():
        clean_rows = []
        for source in rows or []:
            element = str(int(source.get("element") or -1))
            # Preserve the complete screening evidence outside the USER_REPORT-facing rows.
            # This remains auditable without leaking implementation jargon into the report.
            candidate_audit[element] = dict(source)
            clean_rows.append(_public_row(source))
        positions[str(position)] = clean_rows
    result["positions"] = positions
    result["candidate_audit"] = candidate_audit

    # FULL_DSS_SCREEN_V1 is an admission contract, not merely a file-format label.
    # A blocked/incomplete screen must never make downstream reporting claim READY.
    if result.get("status") != "READY" and result.get("screening_contract") == "FULL_DSS_SCREEN_V1":
        result["screening_contract"] = "FULL_DSS_SCREEN_INCOMPLETE_V1"

    result.setdefault("public_contract", {}).update({
        "technical_price_health_codes_removed": True,
        "technical_candidate_evidence_moved_to_candidate_audit": True,
        "natural_language_price_confidence": True,
        "ready_contract_requires_ready_status": True,
        "user_report_positions_are_public_safe": True,
        "tactical_context_is_projection_owned_and_public_safe": True,
        "tactical_membership_promotion_forbidden": True,
    })
    return result


def run() -> dict[str, Any]:
    payload = read_json(WATCHLIST_OUT, {})
    if not payload:
        raise RuntimeError("dss_watchlist.json unavailable for public sanitization")
    # Reuse projection-owned tactical evidence. It may rerank only already-published
    # close DSS candidates; it can never promote a new member into the top 20.
    payload = apply_watchlist_overlay(payload)
    clean = sanitize(payload)
    atomic_json(WATCHLIST_OUT, clean)

    latest = read_json(DATA / "latest.json", {})
    summary = latest.get("dss_watchlist_summary") or {}
    summary["screening_contract"] = clean.get("screening_contract")
    summary["status"] = clean.get("status")
    summary["public_sanitized"] = True
    summary["tactical_close_call_consumed"] = True
    latest["dss_watchlist_summary"] = summary
    atomic_json(DATA / "latest.json", latest)
    return clean


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "status": result.get("status"),
        "screening_contract": result.get("screening_contract"),
        "public_contract": result.get("public_contract"),
        "candidate_audit_count": len(result.get("candidate_audit") or {}),
        "tactical_reranked_position_count": ((result.get("governance") or {}).get("tactical_reranked_position_count")),
    }, ensure_ascii=False))
