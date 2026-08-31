from __future__ import annotations

import json
from typing import Any

from src.engines.price_radar import _served_evidence
from src.engines.tactical_decision_consumption import apply_watchlist_overlay
from src.utils import DATA, atomic_json, read_json

WATCHLIST_OUT = DATA / "dss_watchlist.json"

PUBLIC_FIELDS = {
    "element", "name", "team", "team_id", "position", "now_cost", "price", "status",
    "ownership_pct", "projection_confidence", "xmins", "horizons", "direct_replacement_context",
    "evidence_coverage", "critical_dimension_score", "dss_score", "rank", "lifecycle",
    "reasons", "risks", "action", "tactical_matchup",
}


def _safe_price_context(price: dict[str, Any], official: dict[str, Any] | None = None) -> dict[str, Any]:
    """Expose governed Official price evidence without leaking unverified UI mappings.

    The full Official evidence is resolved by element id from prices.json. The older
    DSS price_risk object is retained only as a compatibility fallback when a row
    cannot be resolved, and it never overrides fresh canonical Official evidence.
    """
    if official:
        return dict(official)
    source = dict(price or {})
    out = {
        key: source.get(key)
        for key in (
            "official_progress_pct", "official_hourly_rate_pct", "risk_direction", "urgency",
            "predicted_change_deadline", "prediction_source", "official_projection_health",
        )
        if source.get(key) is not None
    }
    if out:
        out["narrative"] = "Sinyal harga tersedia sebagai fallback kompatibilitas; bukti Official lengkap tidak berhasil di-resolve untuk baris ini."
        out["source"] = "LEGACY_COMPATIBILITY_FALLBACK"
    return out


def _public_underlying(source: dict[str, Any]) -> dict[str, Any]:
    raw = source.get("underlying") or {}
    return {
        key: raw.get(key)
        for key in ("xg90", "xa90", "bonus90", "dc90", "saves90")
        if raw.get(key) is not None
    }


def _public_tactical(value: Any) -> dict[str, Any]:
    raw = dict(value or {}) if isinstance(value, dict) else {}
    if "verified_shape" in raw:
        raw["observed_shape"] = raw.pop("verified_shape")
    return raw


def _public_row(source: dict[str, Any], official_price: dict[str, Any] | None = None) -> dict[str, Any]:
    row = {key: source.get(key) for key in PUBLIC_FIELDS if key in source}
    if "tactical_matchup" in row:
        row["tactical_matchup"] = _public_tactical(row.get("tactical_matchup"))
    underlying = _public_underlying(source)
    if underlying:
        row["underlying"] = underlying
    row["price_risk"] = _safe_price_context(source.get("price_risk") or {}, official_price)
    return row


def _official_price_index(prices: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in prices.get("players") or []:
        if not isinstance(row, dict) or row.get("element_id") is None:
            continue
        element = int(row["element_id"])
        out[element] = _served_evidence(row, owned=False)
    return out


def sanitize(payload: dict[str, Any], price_index: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    result = dict(payload or {})
    price_index = price_index or {}
    positions = {}
    candidate_audit = dict(result.get("candidate_audit") or {})
    price_evidence_rows = 0
    published_rows = 0
    for position, rows in (result.get("positions") or {}).items():
        clean_rows = []
        for source in rows or []:
            element_id = int(source.get("element") or -1)
            element = str(element_id)
            published_rows += 1
            candidate_audit[element] = dict(source)
            official_price = price_index.get(element_id)
            if official_price and official_price.get("source") == "OFFICIAL_FPL":
                price_evidence_rows += 1
            clean_rows.append(_public_row(source, official_price))
        positions[str(position)] = clean_rows
    result["positions"] = positions
    result["candidate_audit"] = candidate_audit

    if result.get("status") != "READY" and result.get("screening_contract") == "FULL_DSS_SCREEN_V1":
        result["screening_contract"] = "FULL_DSS_SCREEN_INCOMPLETE_V1"

    complete = published_rows > 0 and price_evidence_rows == published_rows
    result["price_evidence_summary"] = {
        "published_watchlist_rows": published_rows,
        "official_price_evidence_rows": price_evidence_rows,
        "complete": complete,
        "required_when_published": True,
        "authority": "OFFICIAL_FPL",
    }
    result.setdefault("public_contract", {}).update({
        "technical_candidate_evidence_moved_to_candidate_audit": True,
        "natural_language_price_narrative": True,
        "full_governed_price_evidence_preserved": True,
        "official_price_evidence_resolved_by_element_id": True,
        "unverified_likelihood_wording_forbidden": True,
        "ready_contract_requires_ready_status": True,
        "user_report_positions_are_public_safe": True,
        "tactical_context_is_projection_owned_and_public_safe": True,
        "tactical_shape_is_observational_not_verified_formation": True,
        "tactical_membership_promotion_forbidden": True,
    })
    return result


def run() -> dict[str, Any]:
    payload = read_json(WATCHLIST_OUT, {})
    if not payload:
        raise RuntimeError("dss_watchlist.json unavailable for public sanitization")
    prices = read_json(DATA / "prices.json", {})
    price_index = _official_price_index(prices)
    payload = apply_watchlist_overlay(payload)
    clean = sanitize(payload, price_index)
    atomic_json(WATCHLIST_OUT, clean)

    latest = read_json(DATA / "latest.json", {})
    summary = latest.get("dss_watchlist_summary") or {}
    summary["screening_contract"] = clean.get("screening_contract")
    summary["status"] = clean.get("status")
    summary["public_sanitized"] = True
    summary["tactical_close_call_consumed"] = True
    summary["price_evidence"] = clean.get("price_evidence_summary")
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
        "price_evidence": result.get("price_evidence_summary"),
        "tactical_reranked_position_count": ((result.get("governance") or {}).get("tactical_reranked_position_count")),
    }, ensure_ascii=False))
