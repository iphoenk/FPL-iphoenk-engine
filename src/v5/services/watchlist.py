from __future__ import annotations

from typing import Any

from src.v5.decision.watchlist import build_watchlist
from src.v5.decision.tactical_consumption import close_group_sort, compact_tactical, watchlist_gap


def _tactical_overlay(payload: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    pmap = {
        int(row["element"]): row
        for row in prediction.get("players") or []
        if isinstance(row, dict) and row.get("element") is not None
    }
    positions = {}
    reranked = 0
    for position, raw_rows in (payload.get("positions") or {}).items():
        rows = [dict(row) for row in raw_rows or [] if isinstance(row, dict)]
        before = [int(row.get("element") or -1) for row in rows]
        rows = close_group_sort(
            rows,
            score=lambda row: float(row.get("score") or 0),
            player=lambda row: pmap.get(int(row.get("element") or -1), {}),
            gap=watchlist_gap(),
        )
        after = [int(row.get("element") or -1) for row in rows]
        if before != after:
            reranked += 1
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
            player = pmap.get(int(row.get("element") or -1), {})
            row["tactical_matchup"] = compact_tactical(player)
        positions[str(position)] = rows
    return {
        **payload,
        "positions": positions,
        "governance": {
            **(payload.get("governance") or {}),
            "tactical_consumption_contract": "TACTICAL_DECISION_CONSUMPTION_V1",
            "tactical_tiebreak_close_screened_pool_only": True,
            "tactical_membership_promotion_forbidden": True,
            "tactical_reranked_position_count": reranked,
            "price_business_logic_imported": False,
            "price_evidence_binding_owned_by_price_service": True,
        },
    }


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation == "status":
        return {
            "status": "ACTIVE",
            "model": "full_dss_watchlist_v5_v3_tactical_consumption",
            "operations": ["build"],
            "tactical_consumption": "CLOSE_CALL_ONLY",
            "price_evidence": "BOUND_BY_PRICE_SERVICE_AFTER_SELECTION",
        }
    if operation != "build":
        raise KeyError(f"unsupported watchlist operation: {operation}")
    prediction = payload.get("prediction") if isinstance(payload.get("prediction"), dict) else {}
    truth = payload.get("truth") if isinstance(payload.get("truth"), dict) else {}
    team = truth.get("team") if isinstance(truth.get("team"), dict) else {}
    dss = payload.get("dss") if isinstance(payload.get("dss"), dict) else {}
    if not prediction or not team:
        raise ValueError("watchlist service requires prediction and truth team")
    base = build_watchlist(prediction, team, dss)
    return _tactical_overlay(base, prediction)
