from __future__ import annotations

from pathlib import Path
from typing import Any

from src.utils import atomic_json, read_json

PRICE_MOVER_COUNT = 20
_CYCLE_RANK = {"NEXT_UPDATE": 4, "PLUS_1_UPDATE": 3, "PLUS_2_UPDATE": 2, "NONE": 1}
_URGENCY_RANK = {"CRITICAL": 4, "HIGH": 3, "WATCH": 2, "LOW": 1}


def _number(value: Any) -> float:
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _rise_key(row: dict[str, Any]) -> tuple[float, ...]:
    return (
        float(_CYCLE_RANK.get(str(row.get("predicted_change_cycle") or "NONE"), 0)),
        float(_URGENCY_RANK.get(str(row.get("model_urgency") or row.get("urgency") or "LOW"), 0)),
        _number(row.get("projection_offset_0_likelihood")),
        _number(row.get("projection_offset_0_percent")),
        _number(row.get("current_progress_percent")),
        _number(row.get("price_change_hourly_rate")),
        -_number(row.get("element_id") or row.get("element")),
    )


def _fall_key(row: dict[str, Any]) -> tuple[float, ...]:
    return (
        float(_CYCLE_RANK.get(str(row.get("predicted_change_cycle") or "NONE"), 0)),
        float(_URGENCY_RANK.get(str(row.get("model_urgency") or row.get("urgency") or "LOW"), 0)),
        -_number(row.get("projection_offset_0_likelihood")),
        -_number(row.get("projection_offset_0_percent")),
        -_number(row.get("current_progress_percent")),
        -_number(row.get("price_change_hourly_rate")),
        -_number(row.get("element_id") or row.get("element")),
    )


def _served(row: dict[str, Any], rank: int) -> dict[str, Any]:
    fields = (
        "element_id", "player_name", "team_id", "position", "current_price", "ownership_percent",
        "confirmed_price_change", "direction", "current_progress_percent", "price_change_hourly_rate",
        "projection_offset_0_percent", "projection_offset_0_likelihood", "projection_offset_0_at",
        "projection_offset_1_percent", "projection_offset_1_likelihood", "projection_offset_1_at",
        "projection_offset_2_percent", "projection_offset_2_likelihood", "projection_offset_2_at",
        "predicted_change_cycle", "predicted_change_at", "next_official_price_update_at", "eta_human",
        "model_urgency", "confidence", "freshness_state", "freshness_seconds", "evidence_state",
        "source", "provider", "observed_at", "fetched_at", "narrative",
    )
    out = {key: row.get(key) for key in fields if key in row}
    out["rank"] = rank
    out["element"] = row.get("element_id", row.get("element"))
    out["name"] = row.get("player_name", row.get("name"))
    return out


def ranked_price_movers(players: list[dict[str, Any]], limit: int = PRICE_MOVER_COUNT) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    count = int(limit)
    if count <= 0:
        raise ValueError("limit must be positive")
    rising = [row for row in players if isinstance(row, dict) and row.get("direction") == "RISE"]
    falling = [row for row in players if isinstance(row, dict) and row.get("direction") == "FALL"]
    rising.sort(key=_rise_key, reverse=True)
    falling.sort(key=_fall_key, reverse=True)
    return (
        [_served(row, rank) for rank, row in enumerate(rising[:count], start=1)],
        [_served(row, rank) for rank, row in enumerate(falling[:count], start=1)],
    )


def apply_ranked_price_movers(payload: dict[str, Any], limit: int = PRICE_MOVER_COUNT) -> dict[str, Any]:
    out = dict(payload or {})
    players = [row for row in out.get("players") or [] if isinstance(row, dict)]
    risers, fallers = ranked_price_movers(players, limit=limit)
    required = int(limit)
    complete = len(risers) == required and len(fallers) == required
    status = "PASS" if complete else "PARTIAL"
    reason = None if complete else "PRICE_MOVER_20X20_INCOMPLETE"
    contract = {
        "schema_version": 1,
        "required_count_per_direction": required,
        "ranking_basis": "OFFICIAL_FPL_PREDICTOR",
        "transfer_pressure_used_for_rank": False,
        "full_universe_player_count": len(players),
        "rise_count": len(risers),
        "fall_count": len(fallers),
        "status": status,
        "reason": reason,
        "comprehensive_price_mover_verdict_allowed": complete,
    }
    out["top_20_risers"] = risers
    out["top_20_fallers"] = fallers
    out["price_mover_serving_contract"] = contract
    return out


def patch_price_artifacts(data_dir: str | Path = "data") -> dict[str, Any]:
    root = Path(data_dir)
    prices_path = root / "prices.json"
    if not prices_path.exists():
        raise FileNotFoundError(prices_path)
    prices = read_json(prices_path, {})
    patched = apply_ranked_price_movers(prices)
    atomic_json(prices_path, patched)

    summary = {
        "top_20_risers": patched["top_20_risers"],
        "top_20_fallers": patched["top_20_fallers"],
        "price_mover_serving_contract": patched["price_mover_serving_contract"],
    }
    latest_path = root / "latest.json"
    if latest_path.exists():
        latest = read_json(latest_path, {})
        latest.setdefault("price_summary", {}).update(summary)
        atomic_json(latest_path, latest)

    alerts_path = root / "price_alerts.json"
    if alerts_path.exists():
        alerts = read_json(alerts_path, {})
        alerts.update(summary)
        atomic_json(alerts_path, alerts)
    return patched["price_mover_serving_contract"]
