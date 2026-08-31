from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from src.engines import price_radar as canonical


# Compatibility facade only. Raw Official predictor parsing, clock reconstruction,
# threshold interpretation, calibration/lock handling and provenance are owned by
# src.engines.price_radar so V3/V4/V5 cannot drift into independent semantics.
REGISTRY_CONFIG = "config/intelligence/price_radar.json"


def _cfg() -> dict[str, Any]:
    return canonical.load_policy()


def _market_tz():
    return canonical.UK


def _float(value: Any):
    return canonical._float(value)


def _int(value: Any):
    return canonical._int(value)


def _parse_dt(value: Any):
    if isinstance(value, datetime):
        return value
    return canonical._parse_dt(value)


def next_price_deadline(now: datetime) -> datetime:
    return canonical._next_uk_midnight(now)


def crossing_deadline(crossing: datetime) -> datetime:
    # Kept for callers that only need the next governed update boundary. It must
    # never be fed by extrapolated threshold-crossing logic.
    return canonical._next_uk_midnight(crossing)


def normalise_projections(raw: Any) -> list[dict[str, Any]]:
    rows, _errors = canonical._normalise_projections(raw)
    return rows


def classify(net_transfers: int, ownership_pct: float, estimated_owners: int) -> dict[str, Any]:
    return canonical.classify(net_transfers, ownership_pct, estimated_owners)


def classify_row(row: dict[str, Any]) -> dict[str, Any]:
    ownership = canonical._float(row.get("ownership_pct"))
    net = canonical._int(row.get("net_transfers"))
    owners = canonical._int(row.get("estimated_owners")) or 1
    meta = canonical.classify(net, ownership, owners)
    return {**row, "actionable": meta["actionable"], "confidence": meta["confidence"], "market_noise": meta["market_noise"]}


def filtered_pressure(rows: Iterable[dict[str, Any]], direction: str, limit: int | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if direction not in {"buy", "sell"}:
        raise ValueError("direction must be buy or sell")
    cap = canonical.MAX_MARKET_WATCH if limit is None else int(limit)
    classified = [classify_row(row) for row in rows]
    actionable = [row for row in classified if row["actionable"]]
    noise = [row for row in classified if row["market_noise"]]
    actionable.sort(
        key=lambda row: (float(row.get("momentum") or 0), abs(int(row.get("net_transfers") or 0))),
        reverse=direction == "buy",
    )
    noise.sort(key=lambda row: abs(int(row.get("net_transfers") or 0)), reverse=True)
    return actionable[:cap], noise[:cap]


def projection_health(progress: Any, rate: Any, projections: list[dict[str, Any]], hours_to_deadline: Any) -> str:
    return canonical._official_projection_health(progress, rate, projections, hours_to_deadline)


def trend(current_rate: Any, previous_rate: Any, elapsed_hours: Any):
    return canonical._trend(current_rate, previous_rate, elapsed_hours)


def trajectory_eta(now: datetime, progress: Any, rate: Any) -> tuple[None, None]:
    # Exact intra-cycle crossing ETA is intentionally forbidden by the governed
    # Official predictor contract.
    return canonical._trajectory_eta(now, progress, rate)


def official_deadline(now: datetime, projections: list[dict[str, Any]]) -> str | None:
    cycle, predicted = canonical._prediction_cycle(projections, now, None)
    del cycle
    return predicted.isoformat() if predicted is not None else None


def urgency(progress: Any, predicted_deadline: str | None, now: datetime) -> str:
    predicted = _parse_dt(predicted_deadline)
    cycle = "NONE"
    if predicted is not None:
        next_update = canonical._projection_timestamp(now, 0)
        delta_days = round((predicted - next_update).total_seconds() / 86400)
        cycle = {0: "NEXT_UPDATE", 1: "PLUS_1_UPDATE", 2: "PLUS_2_UPDATE"}.get(delta_days, "NONE")
    return canonical._urgency(canonical._float(progress), None, cycle)


def risk_direction(progress: Any, rate: Any):
    return canonical._risk_direction(canonical._float(progress), canonical._float(rate))


def price_row(player: dict[str, Any], total_players: int) -> dict[str, Any]:
    row = canonical._price_row(player, total_players)
    ownership = canonical._float(row.get("ownership_pct")) or 0.0
    row["estimated_owners"] = max(1, int(int(total_players or 0) * ownership / 100.0))
    if row.get("net_transfers") is not None:
        row["momentum"] = int(row["net_transfers"]) / row["estimated_owners"]
    return row


def build_trajectory(players: list[dict[str, Any]], previous_state: dict[str, Any], now: datetime) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return canonical.build_trajectory(players, previous_state, now)


def risk_sort_key(row: dict[str, Any]):
    return canonical._risk_sort(row)


def alerts(rows: list[dict[str, Any]], owned_ids: set[int]) -> list[dict[str, Any]]:
    result = [
        {
            **canonical._served_evidence(row, owned=int(row.get("element_id") or row.get("element") or -1) in owned_ids),
            "risk_direction": row.get("direction") or row.get("risk_direction"),
            "urgency": row.get("model_urgency") or row.get("urgency"),
        }
        for row in rows
        if str(row.get("model_urgency") or row.get("urgency")) in canonical.ALERT_LEVELS
    ]
    result.sort(key=canonical._risk_sort, reverse=True)
    return result


def market_watch_capacity() -> int:
    return canonical.MAX_MARKET_WATCH
