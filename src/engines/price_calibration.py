from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils import ROOT, atomic_json, read_json

CONFIG_PATH = ROOT / "config" / "intelligence" / "price_radar.json"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def capture_previous_state(root: Path) -> dict[str, Any]:
    path = root / "price_trajectory.json"
    payload = read_json(path, {})
    return copy.deepcopy(payload) if isinstance(payload, dict) else {}


def _prediction_snapshot(row: dict[str, Any]) -> dict[str, Any]:
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
    prediction = prior.get("prediction") or {}
    predicted_direction = prediction.get("risk_direction")
    deadline = _parse_dt(prediction.get("predicted_change_deadline"))
    timing_error = None
    if deadline is not None:
        timing_error = round(abs((observed_at - deadline).total_seconds()) / 3600.0, 2)
    return {
        "element": element,
        "observed_at": observed_at.isoformat(),
        "prior_cost": prior_cost,
        "current_cost": current_cost,
        "realized_direction": realized,
        "predicted_direction": predicted_direction,
        "direction_correct": predicted_direction == realized if predicted_direction in {"RISE", "FALL"} else None,
        "predicted_change_deadline": prediction.get("predicted_change_deadline"),
        "timing_error_hours_observation_bound": timing_error,
        "prediction_source": prediction.get("prediction_source"),
        "official_projection_health": prediction.get("official_projection_health"),
        "note": "change time is bounded by collector observations; observed_at is not the exact FPL price-change timestamp",
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
    prediction = prior.get("prediction") or {}
    predicted_direction = prediction.get("risk_direction")
    deadline = _parse_dt(prediction.get("predicted_change_deadline"))
    if predicted_direction not in {"RISE", "FALL"} or deadline is None:
        return None
    overdue = (observed_at - deadline).total_seconds() / 3600.0
    if overdue <= grace_hours:
        return None
    previous_miss_deadline = (prior.get("calibration") or {}).get("last_miss_deadline")
    if previous_miss_deadline == prediction.get("predicted_change_deadline"):
        return None
    return {
        "element": element,
        "observed_at": observed_at.isoformat(),
        "event": "PREDICTED_WINDOW_MISSED",
        "predicted_direction": predicted_direction,
        "predicted_change_deadline": prediction.get("predicted_change_deadline"),
        "hours_overdue": round(overdue, 2),
        "prediction_source": prediction.get("prediction_source"),
        "official_projection_health": prediction.get("official_projection_health"),
    }


def _summary(events: list[dict[str, Any]], current_rows: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    changes = [e for e in events if e.get("realized_direction") in {"RISE", "FALL"}]
    scored_direction = [e for e in changes if e.get("direction_correct") is not None]
    direction_correct = sum(e.get("direction_correct") is True for e in scored_direction)
    timing = [float(e["timing_error_hours_observation_bound"]) for e in changes if e.get("timing_error_hours_observation_bound") is not None]
    misses = [e for e in events if e.get("event") == "PREDICTED_WINDOW_MISSED"]
    source_counts: dict[str, int] = {}
    for event in changes:
        source = str(event.get("prediction_source") or "NONE")
        source_counts[source] = source_counts.get(source, 0) + 1

    suspect_count = sum(row.get("official_projection_health") == "SUSPECT_STATIC_OFFSET0" for row in current_rows)
    with_projection = sum(bool(row.get("official_projections")) for row in current_rows)
    suspect_ratio = suspect_count / max(1, with_projection)
    direction_accuracy = direction_correct / len(scored_direction) if scored_direction else None
    mean_timing_error = sum(timing) / len(timing) if timing else None
    minimum = int(cfg.get("minimum_samples_for_calibrated_health") or 20)
    healthy = float(cfg.get("healthy_direction_accuracy") or 0.70)
    warning = float(cfg.get("warning_direction_accuracy") or 0.55)
    static_warning = float(cfg.get("suspect_static_ratio_warning") or 0.50)
    timing_warning = float(cfg.get("timing_error_warning_hours") or 24.0)

    if len(scored_direction) < minimum:
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
        "direction_samples": len(scored_direction),
        "direction_accuracy": round(direction_accuracy, 4) if direction_accuracy is not None else None,
        "timing_samples": len(timing),
        "mean_timing_error_hours_observation_bound": round(mean_timing_error, 2) if mean_timing_error is not None else None,
        "missed_prediction_windows": len(misses),
        "source_samples": source_counts,
        "current_official_static_suspect_count": suspect_count,
        "current_projection_rows": with_projection,
        "current_official_static_suspect_ratio": round(suspect_ratio, 4),
        "trajectory_fallback_operational": any(row.get("prediction_source") == "TRAJECTORY_RATE" for row in current_rows),
        "governance": {
            "direction_and_timing_are_separate": True,
            "observation_time_is_not_exact_change_time": True,
            "no_accuracy_claim_before_minimum_sample": True,
        },
    }


def patch_files(root: Path, previous_state: dict[str, Any] | None = None) -> dict[str, Any]:
    previous_state = previous_state or {}
    config = _config()
    cal_cfg = config.get("calibration") or {}
    trajectory_path = root / "price_trajectory.json"
    prices_path = root / "prices.json"
    latest_path = root / "latest.json"
    if not trajectory_path.exists() or not prices_path.exists():
        return {}

    trajectory = read_json(trajectory_path, {})
    prices = read_json(prices_path, {})
    current_rows = list(prices.get("players") or [])
    current_map = {str(row.get("element")): row for row in current_rows if row.get("element") is not None}
    prior_players = previous_state.get("players") or {}
    observed_at = datetime.now(timezone.utc)
    events = list((previous_state.get("calibration") or {}).get("events") or [])
    grace = float(cal_cfg.get("miss_grace_hours") or 12.0)

    for key, current in current_map.items():
        prior = prior_players.get(key) or {}
        event = _event_for_change(int(key), prior, current, observed_at)
        if event:
            events.append(event)
        else:
            miss = _miss_event(int(key), prior, current, observed_at, grace)
            if miss:
                events.append(miss)
        state_row = (trajectory.setdefault("players", {})).setdefault(key, {})
        state_row["prediction"] = _prediction_snapshot(current)
        state_row["calibration"] = {
            "last_miss_deadline": (
                (prior.get("prediction") or {}).get("predicted_change_deadline")
                if events and events[-1].get("element") == int(key) and events[-1].get("event") == "PREDICTED_WINDOW_MISSED"
                else (prior.get("calibration") or {}).get("last_miss_deadline")
            )
        }

    max_events = max(1, int(cal_cfg.get("max_events") or 250))
    events = events[-max_events:]
    summary = _summary(events, current_rows, cal_cfg)
    trajectory["calibration"] = {
        "model": "price_predictor_health_v1",
        "updated_at": observed_at.isoformat(),
        "max_events": max_events,
        "events": events,
        "summary": summary,
    }
    atomic_json(trajectory_path, trajectory)

    if latest_path.exists():
        latest = read_json(latest_path, {})
        latest["price_model_health"] = summary
        atomic_json(latest_path, latest)
    return summary
