from __future__ import annotations

from typing import Any

from src.v5.price_service import build_price_snapshot
from src.v5.price_squeeze import annotate_comparator, annotate_packages, attach_watchlist_price_evidence
from src.v5.services.common import parse_datetime

# Static capability stays intentionally narrow. The Official predictor is an
# evidence contract inside price_intelligence, while transfer_momentum may only
# be advertised after runtime Official transfer-count/current-price linkage is
# proven AVAILABLE. Price squeeze is owned by this same bounded context and is
# exposed only through service operations so downstream services do not import
# price business implementation directly.
STATIC_CAPABILITIES = ["price_intelligence", "price_squeeze"]


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation == "status":
        return {
            "status": "ACTIVE",
            "capabilities": list(STATIC_CAPABILITIES),
            "operations": ["build", "bind_watchlist_evidence", "annotate_comparator", "annotate_packages"],
            "official_price_predictor": {
                "source": "OFFICIAL_FPL_BOOTSTRAP_STATIC",
                "authentication_required": False,
                "ui_scraping": False,
                "canonical_provider": "src.engines.price_radar",
                "price_decision_role": "TIMING_AFFORDABILITY_OPTIONALITY_ONLY",
            },
            "conditional_capabilities": {
                "transfer_momentum": "advertised only when Official transfer-count/current-price linkage evidence is AVAILABLE"
            },
            "governance": {
                "price_business_authority": "price",
                "cross_service_price_consumption_uses_versioned_operation_contract": True,
            },
        }
    if operation == "bind_watchlist_evidence":
        watchlist = payload.get("watchlist") if isinstance(payload.get("watchlist"), dict) else {}
        price = payload.get("price") if isinstance(payload.get("price"), dict) else {}
        return attach_watchlist_price_evidence(watchlist, price, payload.get("owned_ids") or [])
    if operation == "annotate_comparator":
        comparator = payload.get("comparator") if isinstance(payload.get("comparator"), dict) else {}
        price = payload.get("price") if isinstance(payload.get("price"), dict) else {}
        team = payload.get("team") if isinstance(payload.get("team"), dict) else {}
        return annotate_comparator(
            comparator,
            price=price,
            team=team,
            transfer_state=payload.get("transfer_state") if isinstance(payload.get("transfer_state"), dict) else None,
        )
    if operation == "annotate_packages":
        packages = payload.get("packages") if isinstance(payload.get("packages"), dict) else {}
        price = payload.get("price") if isinstance(payload.get("price"), dict) else {}
        team = payload.get("team") if isinstance(payload.get("team"), dict) else {}
        return annotate_packages(packages, price, team)
    if operation != "build":
        raise KeyError(f"unsupported price operation: {operation}")
    bootstrap = payload.get("bootstrap")
    if not isinstance(bootstrap, dict):
        raise ValueError("price service requires bootstrap")
    result = build_price_snapshot(
        bootstrap,
        previous_state=payload.get("previous_state") if isinstance(payload.get("previous_state"), dict) else {},
        owned_ids=payload.get("owned_ids") or (),
        now=parse_datetime(payload.get("now")),
        observed_at=payload.get("observed_at"),
        transport_health=payload.get("transport_health") if isinstance(payload.get("transport_health"), dict) else {},
    )
    capabilities = list(STATIC_CAPABILITIES)
    momentum = result.get("transfer_momentum") if isinstance(result.get("transfer_momentum"), dict) else {}
    if momentum.get("evidence_state") == "AVAILABLE":
        capabilities.append("transfer_momentum")
    return {**result, "capabilities": capabilities}
