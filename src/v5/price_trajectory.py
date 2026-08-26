from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Iterable, Any
from zoneinfo import ZoneInfo

from src.v5.config_cache import load_json_config

REGISTRY_CONFIG = "config/v5_price_trajectory_registry.json"


@lru_cache(maxsize=1)
def _cfg() -> dict[str, Any]:
    return load_json_config(REGISTRY_CONFIG)


@lru_cache(maxsize=1)
def _market_tz() -> ZoneInfo:
    return ZoneInfo(str(_cfg()["timezone"]))


def _float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def next_price_deadline(now: datetime) -> datetime:
    local = now.astimezone(_market_tz())
    tomorrow = local.date() + timedelta(days=1)
    return datetime.combine(tomorrow, datetime.min.time(), tzinfo=_market_tz()).astimezone(timezone.utc)


def crossing_deadline(crossing: datetime) -> datetime:
    local = crossing.astimezone(_market_tz())
    deadline = datetime.combine(local.date(), datetime.min.time(), tzinfo=_market_tz())
    if local > deadline:
        deadline += timedelta(days=1)
    return deadline.astimezone(timezone.utc)


def normalise_projections(raw) -> list[dict]:
    labels = _cfg()["likelihood_labels"]
    out = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        likelihood = _int(item.get("likelihood"))
        out.append({
            "offset": _int(item.get("offset")),
            "projected_percent": _float(item.get("projected_percent")),
            "likelihood": likelihood,
            "likelihood_label": labels.get(str(likelihood), "UNKNOWN"),
        })
    return out


def classify(net_transfers: int, ownership_pct: float, estimated_owners: int) -> dict:
    filters = _cfg()["filters"]
    ratio = int(net_transfers) / max(int(estimated_owners), 1)
    actionable = (
        float(ownership_pct) >= float(filters["min_ownership_pct"])
        and abs(int(net_transfers)) >= int(filters["min_abs_net_transfers"])
    )
    confidence = (
        "HIGH"
        if actionable and abs(int(net_transfers)) >= int(filters["high_net_transfers"])
        else "MEDIUM" if actionable else "NOISE"
    )
    return {
        "momentum": ratio,
        "actionable": actionable,
        "confidence": confidence,
        "market_noise": not actionable,
        "min_ownership_pct": float(filters["min_ownership_pct"]),
        "min_abs_net": int(filters["min_abs_net_transfers"]),
    }


def classify_row(row: dict) -> dict:
    own = float(row.get("ownership_pct") or 0.0)
    net = int(row.get("net_transfers") or 0)
    estimated_owners = int(row.get("estimated_owners") or 1)
    meta = classify(net, own, estimated_owners)
    return {**row, "actionable": meta["actionable"], "confidence": meta["confidence"], "market_noise": meta["market_noise"]}


def filtered_pressure(rows: Iterable[dict], direction: str, limit: int | None = None) -> tuple[list[dict], list[dict]]:
    if direction not in {"buy", "sell"}:
        raise ValueError("direction must be buy or sell")
    cap = int(limit if limit is not None else _cfg()["filters"]["top_pressure_limit"])
    classified = [classify_row(r) for r in rows]
    actionable = [r for r in classified if r["actionable"]]
    noise = [r for r in classified if not r["actionable"]]
    reverse = direction == "buy"
    actionable.sort(
        key=lambda r: (float(r.get("momentum") or 0), abs(int(r.get("net_transfers") or 0))),
        reverse=reverse,
    )
    noise.sort(key=lambda r: abs(int(r.get("net_transfers") or 0)), reverse=True)
    return actionable[:cap], noise[:cap]


def projection_health(progress, rate, projections, hours_to_deadline):
    health = _cfg()["projection_health"]
    if progress is None:
        return "UNAVAILABLE"
    if not projections:
        return "PROGRESS_ONLY"
    p0 = next((x for x in projections if x.get("offset") == 0), projections[0])
    p0v = p0.get("projected_percent")
    if (
        p0v is not None
        and rate is not None
        and abs(rate) >= float(health["min_abs_hourly_rate_pct"])
        and hours_to_deadline >= float(health["min_hours_to_deadline"])
        and abs(p0v - progress) < float(health["max_static_delta_pct"])
    ):
        return "SUSPECT_STATIC_OFFSET0"
    return "LIVE"


def trend(current_rate, previous_rate, elapsed_hours):
    if current_rate is None or previous_rate is None or not elapsed_hours or elapsed_hours <= 0:
        return "NEW", None
    delta = float(_cfg()["trend"]["material_rate_delta_pct_per_hour"])
    acceleration = (current_rate - previous_rate) / elapsed_hours
    if current_rate * previous_rate < 0:
        label = "REVERSING"
    elif abs(current_rate) > abs(previous_rate) + delta:
        label = "ACCELERATING"
    elif abs(current_rate) < max(0.0, abs(previous_rate) - delta):
        label = "DECELERATING"
    else:
        label = "STEADY"
    return label, round(acceleration, 3)


def trajectory_eta(now, progress, rate):
    trajectory = _cfg()["trajectory"]
    threshold = float(_cfg()["threshold_percent"])
    min_rate = float(trajectory["min_abs_rate_pct_per_hour"])
    directional_min = float(trajectory["directional_progress_min_abs_pct"])
    if progress is None or rate is None or abs(rate) < min_rate:
        return None, None
    if abs(progress) >= directional_min:
        target = threshold if progress > 0 else -threshold
        if (target - progress) * rate <= 0:
            return None, None
    else:
        target = threshold if rate > 0 else -threshold
    eta = (target - progress) / rate
    if eta < 0 or eta > float(trajectory["max_eta_hours"]):
        return None, None
    crossing = now + timedelta(hours=eta)
    return round(eta, 2), crossing_deadline(crossing).isoformat()


def official_deadline(now, projections):
    threshold = float(_cfg()["threshold_percent"])
    next_deadline = next_price_deadline(now)
    for item in sorted(projections, key=lambda x: x.get("offset") if x.get("offset") is not None else 999):
        projected = item.get("projected_percent")
        offset = item.get("offset")
        if projected is None or offset is None:
            continue
        if abs(projected) >= threshold:
            return (next_deadline + timedelta(days=offset)).isoformat()
    return None


def urgency(progress, predicted_deadline, now):
    policy = _cfg()["urgency"]
    abs_progress = abs(progress) if progress is not None else 0.0
    deadline = _parse_dt(predicted_deadline)
    hours = (deadline - now).total_seconds() / 3600 if deadline else None
    if abs_progress >= float(policy["critical_progress_pct"]) or (
        hours is not None
        and hours <= float(policy["critical_hours"])
        and abs_progress >= float(policy["critical_near_deadline_progress_pct"])
    ):
        return "CRITICAL"
    if abs_progress >= float(policy["high_progress_pct"]) or (
        hours is not None and hours <= float(policy["high_hours"])
    ):
        return "HIGH"
    if abs_progress >= float(policy["medium_progress_pct"]) or (
        hours is not None and hours <= float(policy["medium_hours"])
    ):
        return "MEDIUM"
    return "LOW"


def risk_direction(progress, rate):
    trajectory = _cfg()["trajectory"]
    directional_min = float(trajectory["directional_progress_min_abs_pct"])
    min_rate = float(trajectory["min_abs_rate_pct_per_hour"])
    if progress is not None and abs(progress) >= directional_min:
        return "RISE" if progress > 0 else "FALL"
    if rate is None or abs(rate) < min_rate:
        return "STABLE"
    return "RISE" if rate > 0 else "FALL"


def price_row(player: dict, total_players: int) -> dict:
    own = float(player.get("selected_by_percent") or 0.0)
    estimated_owners = max(1, int(total_players * own / 100))
    net = int(player.get("transfers_in_event") or 0) - int(player.get("transfers_out_event") or 0)
    raw_rate = _float(player.get("price_change_hourly_rate"))
    hourly_rate = round(raw_rate / 100.0, 3) if raw_rate is not None else None
    return {
        "element": int(player["id"]),
        "name": player.get("web_name"),
        "team_id": player.get("team"),
        "element_type": player.get("element_type"),
        "now_cost": player.get("now_cost"),
        "ownership_pct": own,
        "estimated_owners": estimated_owners,
        "net_transfers": net,
        "momentum": net / estimated_owners,
        "official_progress_pct": _float(player.get("price_change_percent")),
        "official_hourly_rate_raw": raw_rate,
        "official_hourly_rate_pct": hourly_rate,
        "official_projections": normalise_projections(player.get("price_change_projections")),
        "official_locked_until": player.get("price_change_locked_until"),
        "official_calibrating": player.get("price_change_calibrating"),
    }


def build_trajectory(players: list[dict], previous_state: dict, now: datetime) -> tuple[list[dict], dict]:
    prior = (previous_state or {}).get("players", {})
    next_deadline = next_price_deadline(now)
    hours_to_deadline = max(0.0, (next_deadline - now).total_seconds() / 3600)
    actionable_levels = set(_cfg()["urgency"]["actionable_levels"])
    enriched = []
    new_state = {"generated_at": now.isoformat(), "players": {}}

    for row in players:
        key = str(row["element"])
        prev = prior.get(key) or {}
        prev_ts = _parse_dt(prev.get("timestamp"))
        elapsed = (now - prev_ts).total_seconds() / 3600 if prev_ts else None
        rate = row.get("official_hourly_rate_pct")
        progress = row.get("official_progress_pct")
        previous_rate = _float(prev.get("official_hourly_rate_pct"))
        previous_progress = _float(prev.get("official_progress_pct"))
        trajectory_label, acceleration = trend(rate, previous_rate, elapsed)
        observed_velocity = None
        if progress is not None and previous_progress is not None and elapsed and elapsed > 0:
            observed_velocity = round((progress - previous_progress) / elapsed, 3)
        health = projection_health(progress, rate, row.get("official_projections", []), hours_to_deadline)
        official_eta = official_deadline(now, row.get("official_projections", []))
        eta_hours, trajectory_deadline = trajectory_eta(now, progress, rate)
        if official_eta and health == "LIVE":
            predicted_deadline = official_eta
            prediction_source = "OFFICIAL_PROJECTION"
        else:
            predicted_deadline = trajectory_deadline
            prediction_source = "TRAJECTORY_RATE" if trajectory_deadline else None
        level = urgency(progress, predicted_deadline, now)
        item = {
            **row,
            "risk_direction": risk_direction(progress, rate),
            "official_projection_health": health,
            "hours_to_next_price_deadline": round(hours_to_deadline, 2),
            "observed_progress_velocity_pct_per_hour": observed_velocity,
            "acceleration_pct_per_hour2": acceleration,
            "trajectory": trajectory_label,
            "trajectory_eta_hours": eta_hours,
            "official_predicted_change_deadline": official_eta,
            "trajectory_predicted_change_deadline": trajectory_deadline,
            "predicted_change_deadline": predicted_deadline,
            "prediction_source": prediction_source,
            "urgency": level,
            "price_actionable": level in actionable_levels,
        }
        enriched.append(item)
        new_state["players"][key] = {
            "timestamp": now.isoformat(),
            "now_cost": row.get("now_cost"),
            "official_progress_pct": progress,
            "official_hourly_rate_pct": rate,
            "net_transfers": row.get("net_transfers"),
        }
    return enriched, new_state


def risk_sort_key(row: dict):
    rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(row.get("urgency"), 0)
    return (
        rank,
        abs(float(row.get("official_progress_pct") or 0)),
        abs(float(row.get("official_hourly_rate_pct") or 0)),
    )


def alerts(rows: list[dict], owned_ids: set[int]) -> list[dict]:
    alert_levels = set(_cfg()["urgency"]["alert_levels"])
    result = [
        {
            "element": row.get("element"),
            "name": row.get("name"),
            "owned": row.get("element") in owned_ids,
            "risk_direction": row.get("risk_direction"),
            "urgency": row.get("urgency"),
            "official_progress_pct": row.get("official_progress_pct"),
            "official_hourly_rate_pct": row.get("official_hourly_rate_pct"),
            "trajectory": row.get("trajectory"),
            "predicted_change_deadline": row.get("predicted_change_deadline"),
            "prediction_source": row.get("prediction_source"),
            "official_projection_health": row.get("official_projection_health"),
        }
        for row in rows
        if row.get("urgency") in alert_levels
    ]
    result.sort(key=risk_sort_key, reverse=True)
    return result


def market_watch_capacity() -> int:
    return int(_cfg()["filters"]["market_watch_capacity"])
