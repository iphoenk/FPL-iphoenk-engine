from __future__ import annotations

from typing import Any


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation == "status":
        return {
            "status": "ACTIVE_ALPHA_BRIDGE",
            "note": "V5 service boundary is active; full DSS/optimizer service migration remains in progress.",
        }
    if operation != "summarize":
        raise KeyError(f"unsupported decision operation: {operation}")
    truth = payload.get("truth") if isinstance(payload.get("truth"), dict) else {}
    prediction = payload.get("prediction") if isinstance(payload.get("prediction"), dict) else {}
    price = payload.get("price") if isinstance(payload.get("price"), dict) else {}
    return {
        "status": "BRIDGE_ONLY_NO_PRODUCTION_RECOMMENDATION",
        "team_authority": (truth.get("team") or {}).get("authority"),
        "prediction_model": prediction.get("model_version"),
        "prediction_player_count": len(prediction.get("players", []) or []),
        "price_alert_count": len((price.get("alerts") or {}).get("alerts", []) or []),
        "production_recommendation": None,
    }
