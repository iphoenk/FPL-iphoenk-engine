from __future__ import annotations

from datetime import datetime
from typing import Any

from src.v5.config_cache import load_json_config

PRICE_CONFIG = "config/v5_price_trajectory_registry.json"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def prediction_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "risk_direction": row.get("risk_direction"),
        "predicted_change_deadline": row.get("predicted_change_deadline"),
        "prediction_source": row.get("prediction_source"),
        "official_projection_health": row.get("official_projection_health"),
        "urgency": row.get("urgency"),
        "official_progress_pct": row.get("official_progress_pct"),
    }


def _event_for_change(
    element: int,
    prior: dict[str, Any],
    current: dict[str, Any],
    observed_at: datetime,
) -> dict[str, Any] | None:
    prior_cost = prior.get("now_cost")
    current_cost = current.get("now_cost")
    if prior_cost is None or current_cost is None or int(prior_cost) == int(current_cost):
        return None
    realized = "RISE" if int(current_cost) > int(prior_cost) else "FALL"
    prediction = prior.get("prediction") if isinstance(prior.get("prediction"), dict) else {}
    predicted_direction = prediction.get("risk_direction")
    deadline = _parse_dt(prediction.get("predicted_change_deadline"))
    timing_error = None
    if deadline is not None:
        timing_error = round(abs((observed_at - deadline).total_seconds()) / 3600.0, 2)
    return {
        "element": int(element),
        "observed_at": observed_at.isoformat(),
        "event": "REALIZED_PRICE_CHANGE",
        "prior_cost": int(prior_cost),
        "current_cost": int(current_cost),
        "realized_direction": realized,
        "predicted_direction": predicted_direction,
        "direction_correct": predicted_direction == realized if predicted_direction in {"RISE", "FALL"} else None,
        "predicted_change_deadline": prediction.get("predicted_change_deadline"),
        "timing_error_hours_observation_bound": timing_error,
        "prediction_source": prediction.get("prediction_source"),
        "official_projection_health": prediction.get("official_projection_health"),
        "note": "Price-change time is bounded by refresh observations; observed_at is not claimed as the exact FPL change timestamp.",
    }


def _miss_event(
    element: int,
    prior: dict[str, Any],
    current: dict[str, Any],
    observed_at: datetime,
    grace_hours: float,
) -> dict[str, Any] | None:
    prior_cost = prior.get("now_cost")
    current_cost = current.get("now_cost")
    if prior_cost is None or current_cost is None or int(prior_cost) != int(current_cost):
        return None
    prediction = prior.get("prediction") if isinstance(prior.get("prediction"), dict) else {}
    predicted_direction = prediction.get("risk_direction")
    deadline = _parse_dt(prediction.get("predicted_change_deadline"))
    if predicted_direction not in {"RISE", "FALL"} or deadline is None:
        return None
    overdue = (observed_at - deadline).total_seconds() / 3600.0
    if overdue <= float(grace_hours):
        return None
    previous_miss_deadline = (prior.get("calibration") or {}).get("last_miss_deadline")
    if previous_miss_deadline == prediction.get("predicted_change_deadline"):
        return None
    return {
        "element": int(element),
        "observed_at": observed_at.isoformat(),
        "event": "PREDICTED_WINDOW_MISSED",
        "predicted_direction": predicted_direction,
        "predicted_change_deadline": prediction.get("predicted_change_deadline"),
        "hours_overdue": round(overdue, 2),
        "prediction_source": prediction.get("prediction_source"),
        "official_projection_health": prediction.get("official_projection_health"),
    }


def _summary(events: list[dict[str, Any]], current_rows: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    changes = [row for row in events if row.get("event") == "REALIZED_PRICE_CHANGE"]
    scored = [row for row in changes if row.get("direction_correct") is not None]
    correct = sum(row.get("direction_correct") is True for row in scored)
    timing = [
        float(row["timing_error_hours_observation_bound"])
        for row in changes
        if row.get("timing_error_hours_observation_bound") is not None
    ]
    misses = [row for row in events if row.get("event") == "PREDICTED_WINDOW_MISSED"]
    source_counts: dict[str, int] = {}
    for row in changes:
        source = str(row.get("prediction_source") or "NONE")
        source_counts[source] = source_counts.get(source, 0) + 1

    projection_rows = [row for row in current_rows if row.get("official_projections")]
    suspect_count = sum(row.get("official_projection_health") == "SUSPECT_STATIC_OFFSET0" for row in projection_rows)
    suspect_ratio = suspect_count / max(1, len(projection_rows))
    direction_accuracy = correct / len(scored) if scored else None
    mean_timing_error = sum(timing) / len(timing) if timing else None
    minimum = max(1, int(cfg.get("minimum_samples_for_calibrated_health") or 20))
    healthy = float(cfg.get("healthy_direction_accuracy") or 0.70)
    warning = float(cfg.get("warning_direction_accuracy") or 0.55)
    static_warning = float(cfg.get("suspect_static_ratio_warning") or 0.50)
    timing_warning = float(cfg.get("timing_error_warning_hours") or 24.0)

    if len(scored) < minimum:
        status = "WARMUP"
    elif direction_accuracy is not None and direction_accuracy < warning:
        status = "DEGRADED_DIRECTION"
    elif mean_timing_error is not None and mean_timing_error > timing_warning:
        status = "DEGRADED_TIMING"
    elif suspect_ratio >= static_warning:
        status = "DEGRADED_OFFICIAL_STATIC_FALLBACK_ACTIVE"
    elif direction_accuracy is not None and direction_accuracy >= healthy:
        status = "HEALTHY"
    else:
        status = "CALIBRATING"

    return {
        "status": status,
        "realized_change_samples": len(changes),
        "direction_samples": len(scored),
        "direction_accuracy": round(direction_accuracy, 4) if direction_accuracy is not None else None,
        "timing_samples": len(timing),
        "mean_timing_error_hours_observation_bound": round(mean_timing_error, 2) if mean_timing_error is not None else None,
        "missed_prediction_windows": len(misses),
        "source_samples": source_counts,
        "current_official_static_suspect_count": suspect_count,
        "current_projection_rows": len(projection_rows),
        "current_official_static_suspect_ratio": round(suspect_ratio, 4),
        "trajectory_fallback_operational": any(row.get("prediction_source") == "TRAJECTORY_RATE" for row in current_rows),
        "governance": {
            "direction_and_timing_are_separate": True,
            "observation_time_is_not_exact_change_time": True,
            "no_accuracy_claim_before_minimum_sample": True,
            "price_calibration_is_separate_from_prediction_calibration": True,
        },
    }


def evaluate_price_calibration(
    previous_state: dict[str, Any],
    current_rows: list[dict[str, Any]],
    observed_at: datetime,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    registry = load_json_config(PRICE_CONFIG)
    cfg = registry.get("calibration") if isinstance(registry.get("calibration"), dict) else {}
    prior_players = previous_state.get("players") if isinstance(previous_state.get("players"), dict) else {}
    prior_calibration = previous_state.get("calibration") if isinstance(previous_state.get("calibration"), dict) else {}
    events = list(prior_calibration.get("events") or [])
    grace = float(cfg.get("miss_grace_hours") or 12.0)
    patches: dict[str, dict[str, Any]] = {}

    for current in current_rows:
        if current.get("element") is None:
            continue
        element = int(current["element"])
        key = str(element)
        prior = prior_players.get(key) if isinstance(prior_players.get(key), dict) else {}
        event = _event_for_change(element, prior, current, observed_at)
        miss = None if event is not None else _miss_event(element, prior, current, observed_at, grace)
        if event is not None:
            events.append(event)
        elif miss is not None:
            events.append(miss)
        last_miss = (prior.get("calibration") or {}).get("last_miss_deadline")
        if miss is not None:
            last_miss = miss.get("predicted_change_deadline")
        patches[key] = {
            "prediction": prediction_snapshot(current),
            "calibration": {"last_miss_deadline": last_miss},
        }

    max_events = max(1, int(cfg.get("max_events") or 250))
    events = events[-max_events:]
    return (
        {
            "schema_version": 1,
            "model": "v5_price_predictor_health_v1",
            "owner": "price",
            "updated_at": observed_at.isoformat(),
            "max_events": max_events,
            "events": events,
            "summary": _summary(events, current_rows, cfg),
        },
        patches,
    )
