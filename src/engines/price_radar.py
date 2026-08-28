from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from src.settings import PRICE_PRESSURE_LIST_SIZE, PRICE_SUMMARY_LIST_SIZE
from src.utils import ROOT

CONFIG_PATH = ROOT / "config" / "intelligence" / "price_radar.json"


@lru_cache(maxsize=1)
def load_policy() -> dict:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload.get("model_id"):
        raise RuntimeError("price radar policy must be a configured JSON object")
    return payload


_POLICY = load_policy()
_MARKET = _POLICY.get("market_filter") or {}
_TRAJECTORY = _POLICY.get("trajectory") or {}
_URGENCY = _POLICY.get("urgency") or {}
_SERVING = _POLICY.get("serving") or {}

MIN_OWNERSHIP_PCT = float(_MARKET["minimum_ownership_pct"])
MIN_ABS_NET = int(_MARKET["minimum_abs_net_transfers"])
HIGH_NET = int(_MARKET["high_confidence_abs_net_transfers"])
MAX_MARKET_WATCH = int(_SERVING["market_watch_capacity"])
ALERT_SUMMARY_SIZE = int(_SERVING["alert_summary_size"])
DEADLINE_TIMEZONE = str(_POLICY["deadline_timezone"])
UK = ZoneInfo(DEADLINE_TIMEZONE)
MINIMUM_RATE = float(_TRAJECTORY["minimum_rate_pct_per_hour"])
RISK_PROGRESS_FLOOR = float(_TRAJECTORY["risk_progress_floor_pct"])
MAXIMUM_ETA_HOURS = float(_TRAJECTORY["maximum_eta_hours"])
TREND_DELTA = float(_TRAJECTORY["trend_delta_pct_per_hour"])
STATIC_PROJECTION_MIN_RATE = float(_TRAJECTORY["static_projection_min_rate_pct_per_hour"])
STATIC_PROJECTION_MIN_HOURS = float(_TRAJECTORY["static_projection_min_hours_to_deadline"])
STATIC_PROJECTION_TOLERANCE = float(_TRAJECTORY["static_projection_tolerance_pct"])
CRITICAL_PROGRESS = float(_URGENCY["critical_progress_pct"])
HIGH_PROGRESS = float(_URGENCY["high_progress_pct"])
MEDIUM_PROGRESS = float(_URGENCY["medium_progress_pct"])
CRITICAL_HOURS = float(_URGENCY["critical_hours"])
HIGH_HOURS = float(_URGENCY["high_hours"])
MEDIUM_HOURS = float(_URGENCY["medium_hours"])
ACTIONABLE_PROGRESS = float(_URGENCY["actionable_progress_pct"])
ALERT_LEVELS = frozenset(str(x) for x in _URGENCY["alert_levels"])

LIKELIHOOD_LABELS = {
    -5: "VERY_LIKELY_DROP",
    -4: "DROP_SIGNAL_LEVEL_4",
    -3: "DROP_SIGNAL_LEVEL_3",
    -2: "DROP_SIGNAL_LEVEL_2",
    -1: "DROP_SIGNAL_LEVEL_1",
    0: "STABLE",
    1: "RISE_SIGNAL_LEVEL_1",
    2: "RISE_SIGNAL_LEVEL_2",
    3: "RISE_SIGNAL_LEVEL_3",
    4: "RISE_SIGNAL_LEVEL_4",
    5: "VERY_LIKELY_RISE",
}


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


def _next_uk_midnight(now: datetime) -> datetime:
    local = now.astimezone(UK)
    tomorrow = local.date() + timedelta(days=1)
    return datetime.combine(tomorrow, datetime.min.time(), tzinfo=UK).astimezone(timezone.utc)


def _deadline_for_crossing(crossing: datetime) -> datetime:
    local = crossing.astimezone(UK)
    deadline = datetime.combine(local.date(), datetime.min.time(), tzinfo=UK)
    if local > deadline:
        deadline += timedelta(days=1)
    return deadline.astimezone(timezone.utc)


def _normalise_projections(raw) -> list[dict]:
    out = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        projected = _float(item.get("projected_percent"))
        likelihood = _int(item.get("likelihood"))
        offset = _int(item.get("offset"))
        out.append({
            "offset": offset,
            "projected_percent": projected,
            "likelihood": likelihood,
            "likelihood_label": LIKELIHOOD_LABELS.get(likelihood, "UNKNOWN"),
        })
    return out


def classify(net_transfers: int, ownership_pct: float, estimated_owners: int) -> dict:
    ratio = net_transfers / max(estimated_owners, 1)
    actionable = ownership_pct >= MIN_OWNERSHIP_PCT and abs(net_transfers) >= MIN_ABS_NET
    confidence = "HIGH" if actionable and abs(net_transfers) >= HIGH_NET else "MEDIUM" if actionable else "NOISE"
    return {
        "momentum": ratio,
        "actionable": actionable,
        "confidence": confidence,
        "market_noise": not actionable,
        "min_ownership_pct": MIN_OWNERSHIP_PCT,
        "min_abs_net": MIN_ABS_NET,
    }


def classify_row(row: dict) -> dict:
    own = float(row.get("ownership_pct") or 0.0)
    net = int(row.get("net_transfers") or 0)
    meta = classify(net, own, 1)
    return {**row, "actionable": meta["actionable"], "confidence": meta["confidence"], "market_noise": meta["market_noise"]}


def filtered_pressure(rows: Iterable[dict], direction: str, limit: int | None = None) -> tuple[list[dict], list[dict]]:
    limit = PRICE_PRESSURE_LIST_SIZE if limit is None else int(limit)
    classified = [classify_row(r) for r in rows]
    actionable = [r for r in classified if r["actionable"]]
    noise = [r for r in classified if not r["actionable"]]
    if direction == "buy":
        actionable.sort(key=lambda r: (float(r.get("momentum") or 0), abs(int(r.get("net_transfers") or 0))), reverse=True)
    else:
        actionable.sort(key=lambda r: (float(r.get("momentum") or 0), -abs(int(r.get("net_transfers") or 0))))
    noise.sort(key=lambda r: abs(int(r.get("net_transfers") or 0)), reverse=True)
    return actionable[:limit], noise[:limit]


def _official_projection_health(progress, rate, projections, hours_to_deadline):
    if progress is None:
        return "UNAVAILABLE"
    if not projections:
        return "PROGRESS_ONLY"
    p0 = next((x for x in projections if x.get("offset") == 0), projections[0])
    p0v = p0.get("projected_percent")
    if (
        p0v is not None
        and rate is not None
        and abs(rate) >= STATIC_PROJECTION_MIN_RATE
        and hours_to_deadline >= STATIC_PROJECTION_MIN_HOURS
        and abs(p0v - progress) < STATIC_PROJECTION_TOLERANCE
    ):
        return "SUSPECT_STATIC_OFFSET0"
    return "LIVE"


def _trend(current_rate, previous_rate, elapsed_hours):
    if current_rate is None or previous_rate is None or not elapsed_hours or elapsed_hours <= 0:
        return "NEW", None
    acceleration = (current_rate - previous_rate) / elapsed_hours
    if current_rate * previous_rate < 0:
        label = "REVERSING"
    elif abs(current_rate) > abs(previous_rate) + TREND_DELTA:
        label = "ACCELERATING"
    elif abs(current_rate) < max(0.0, abs(previous_rate) - TREND_DELTA):
        label = "DECELERATING"
    else:
        label = "STEADY"
    return label, round(acceleration, 3)


def _trajectory_eta(now, progress, rate):
    if progress is None or rate is None or abs(rate) < MINIMUM_RATE:
        return None, None
    if abs(progress) >= RISK_PROGRESS_FLOOR:
        target = 100.0 if progress > 0 else -100.0
        if (target - progress) * rate <= 0:
            return None, None
    else:
        target = 100.0 if rate > 0 else -100.0
    remaining = target - progress
    eta = remaining / rate
    if eta < 0 or eta > MAXIMUM_ETA_HOURS:
        return None, None
    crossing = now + timedelta(hours=eta)
    return round(eta, 2), _deadline_for_crossing(crossing).isoformat()


def _official_deadline(now, projections):
    next_deadline = _next_uk_midnight(now)
    for item in sorted(projections, key=lambda x: x.get("offset") if x.get("offset") is not None else 99):
        projected = item.get("projected_percent")
        offset = item.get("offset")
        if projected is None or offset is None:
            continue
        if abs(projected) >= 100:
            return (next_deadline + timedelta(days=offset)).isoformat()
    return None


def _urgency(progress, predicted_deadline, now):
    abs_progress = abs(progress) if progress is not None else 0.0
    deadline = _parse_dt(predicted_deadline)
    hours = (deadline - now).total_seconds() / 3600 if deadline else None
    if abs_progress >= CRITICAL_PROGRESS or (hours is not None and hours <= CRITICAL_HOURS and abs_progress >= HIGH_PROGRESS):
        return "CRITICAL"
    if abs_progress >= HIGH_PROGRESS or (hours is not None and hours <= HIGH_HOURS):
        return "HIGH"
    if abs_progress >= MEDIUM_PROGRESS or (hours is not None and hours <= MEDIUM_HOURS):
        return "MEDIUM"
    return "LOW"


def _risk_direction(progress, rate):
    if progress is not None and abs(progress) >= RISK_PROGRESS_FLOOR:
        return "RISE" if progress > 0 else "FALL"
    if rate is None or abs(rate) < MINIMUM_RATE:
        return "STABLE"
    return "RISE" if rate > 0 else "FALL"


def _price_row(player: dict, total_players: int) -> dict:
    own = float(player.get("selected_by_percent") or 0.0)
    estimated_owners = max(1, int(total_players * own / 100))
    net = int(player.get("transfers_in_event") or 0) - int(player.get("transfers_out_event") or 0)
    raw_rate = _float(player.get("price_change_hourly_rate"))
    hourly_rate = round(raw_rate / 100.0, 3) if raw_rate is not None else None
    projections = _normalise_projections(player.get("price_change_projections"))
    return {
        "element": player["id"],
        "name": player.get("web_name"),
        "team_id": player.get("team"),
        "element_type": player.get("element_type"),
        "now_cost": player.get("now_cost"),
        "ownership_pct": own,
        "net_transfers": net,
        "momentum": net / estimated_owners,
        "official_progress_pct": _float(player.get("price_change_percent")),
        "official_hourly_rate_raw": raw_rate,
        "official_hourly_rate_pct": hourly_rate,
        "official_projections": projections,
        "official_locked_until": player.get("price_change_locked_until"),
        "official_calibrating": player.get("price_change_calibrating"),
    }


def build_trajectory(players: list[dict], previous_state: dict, now: datetime) -> tuple[list[dict], dict]:
    prior = (previous_state or {}).get("players", {})
    next_deadline = _next_uk_midnight(now)
    hours_to_deadline = max(0.0, (next_deadline - now).total_seconds() / 3600)
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
        trend, acceleration = _trend(rate, previous_rate, elapsed)
        observed_velocity = None
        if progress is not None and previous_progress is not None and elapsed and elapsed > 0:
            observed_velocity = round((progress - previous_progress) / elapsed, 3)

        projection_health = _official_projection_health(progress, rate, row.get("official_projections", []), hours_to_deadline)
        official_deadline = _official_deadline(now, row.get("official_projections", []))
        eta_hours, trajectory_deadline = _trajectory_eta(now, progress, rate)

        if official_deadline and projection_health == "LIVE":
            predicted_deadline = official_deadline
            prediction_source = "OFFICIAL_PROJECTION"
        else:
            predicted_deadline = trajectory_deadline
            prediction_source = "TRAJECTORY_RATE" if trajectory_deadline else None

        risk = _risk_direction(progress, rate)
        urgency = _urgency(progress, predicted_deadline, now)
        price_actionable = urgency in {"CRITICAL", "HIGH", "MEDIUM"} or abs(progress or 0) >= ACTIONABLE_PROGRESS
        item = {
            **row,
            "risk_direction": risk,
            "official_projection_health": projection_health,
            "hours_to_next_price_deadline": round(hours_to_deadline, 2),
            "observed_progress_velocity_pct_per_hour": observed_velocity,
            "acceleration_pct_per_hour2": acceleration,
            "trajectory": trend,
            "trajectory_eta_hours": eta_hours,
            "official_predicted_change_deadline": official_deadline,
            "trajectory_predicted_change_deadline": trajectory_deadline,
            "predicted_change_deadline": predicted_deadline,
            "prediction_source": prediction_source,
            "urgency": urgency,
            "price_actionable": price_actionable,
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


def _risk_sort(row: dict):
    urgency_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(row.get("urgency"), 0)
    return (urgency_rank, abs(float(row.get("official_progress_pct") or 0)), abs(float(row.get("official_hourly_rate_pct") or 0)))


def _alerts(rows: list[dict], owned_ids: set[int]) -> list[dict]:
    alerts = []
    for row in rows:
        if row.get("urgency") not in ALERT_LEVELS:
            continue
        alerts.append({
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
        })
    alerts.sort(key=_risk_sort, reverse=True)
    return alerts


def apply_to_payload(prices: dict) -> dict:
    buys, buy_noise = filtered_pressure(prices.get("top_buy_pressure", []), "buy")
    sells, sell_noise = filtered_pressure(prices.get("top_sell_pressure", []), "sell")
    return {
        **prices,
        "filter_policy": {
            "model_id": _POLICY.get("model_id"),
            "min_ownership_pct": MIN_OWNERSHIP_PCT,
            "min_abs_net_transfers": MIN_ABS_NET,
            "purpose": "suppress tiny-denominator transfer-momentum noise; Official price progress is evaluated separately",
        },
        "top_buy_pressure": buys,
        "top_sell_pressure": sells,
        "market_noise": {"buy": buy_noise, "sell": sell_noise},
    }


def patch_files(data_dir: str | Path = "data") -> None:
    root = Path(data_dir)
    market_prices_path = root / "market_prices.json"
    official_path = root / "official_snapshot.json"
    prices_path = root / "prices.json"
    latest_path = root / "latest.json"
    trajectory_path = root / "price_trajectory.json"
    alerts_path = root / "price_alerts.json"

    if not market_prices_path.exists():
        raise RuntimeError("market_prices.json missing for canonical price materialization")
    if not official_path.exists():
        raise RuntimeError("official_snapshot.json missing for canonical price materialization")
    prices = json.loads(market_prices_path.read_text(encoding="utf-8"))
    official = json.loads(official_path.read_text(encoding="utf-8"))
    bootstrap = official.get("bootstrap") or {}
    if not bootstrap:
        raise RuntimeError("official_snapshot bootstrap missing for price radar")
    official_health = (official.get("endpoint_health") or {}).get("bootstrap") or {}
    now = datetime.now(timezone.utc)

    trajectory_state = json.loads(trajectory_path.read_text(encoding="utf-8")) if trajectory_path.exists() else {}
    total_players = int(bootstrap.get("total_players") or 0)
    raw_rows = [_price_row(p, total_players) for p in bootstrap.get("elements", [])]
    enriched, new_state = build_trajectory(raw_rows, trajectory_state, now)

    rising = sorted((r for r in enriched if r.get("risk_direction") == "RISE"), key=_risk_sort, reverse=True)
    falling = sorted((r for r in enriched if r.get("risk_direction") == "FALL"), key=_risk_sort, reverse=True)
    by_momentum = sorted(enriched, key=lambda r: float(r.get("momentum") or 0), reverse=True)
    prices.update({
        "contract": "CANONICAL_PRICE_RADAR_V1",
        "authority": "Official FPL snapshot",
        "players": enriched,
        "top_buy_pressure": by_momentum[:PRICE_PRESSURE_LIST_SIZE],
        "top_sell_pressure": list(reversed(by_momentum[-PRICE_PRESSURE_LIST_SIZE:])),
        "top_rise_risk": rising[:PRICE_PRESSURE_LIST_SIZE],
        "top_fall_risk": falling[:PRICE_PRESSURE_LIST_SIZE],
        "official_price_predictor_health": official_health,
        "official_price_fields": {
            "progress": "price_change_percent",
            "hourly_rate": "price_change_hourly_rate / 100",
            "projections": "price_change_projections",
            "price_deadline": f"00:00 {DEADLINE_TIMEZONE}",
            "authority": "Official FPL bootstrap native fields from official_snapshot.json",
        },
    })

    filtered = apply_to_payload(prices)
    prices_path.write_text(json.dumps(filtered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    trajectory_path.write_text(json.dumps(new_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    team_path = root / "team.json"
    owned_ids = set()
    if team_path.exists():
        team = json.loads(team_path.read_text(encoding="utf-8"))
        owned_ids = {int(x["element"]) for x in team.get("squad", []) if x.get("element") is not None}

    all_rows = filtered.get("players", [])
    alerts = _alerts(all_rows, owned_ids)
    external_watch = [
        r for r in sorted(all_rows, key=_risk_sort, reverse=True)
        if r.get("element") not in owned_ids
    ][:MAX_MARKET_WATCH]
    alert_payload = {
        "generated_at": now.isoformat(),
        "policy": {
            "model_id": _POLICY.get("model_id"),
            "watch_capacity": MAX_MARKET_WATCH,
            "push_semantics": "consumer should notify only when alert intersects OWNED or a DSS-approved external watchlist and the move is decision-relevant",
            "price_signal_is_overlay": True,
        },
        "alerts": alerts,
        "market_watch_candidates": external_watch,
    }
    alerts_path.write_text(json.dumps(alert_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if latest_path.exists():
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        latest["price_summary"] = {
            "confirmed_changes": filtered.get("confirmed_changes", []),
            "top_buy_pressure": filtered.get("top_buy_pressure", [])[:PRICE_SUMMARY_LIST_SIZE],
            "top_sell_pressure": filtered.get("top_sell_pressure", [])[:PRICE_SUMMARY_LIST_SIZE],
            "top_rise_risk": filtered.get("top_rise_risk", [])[:PRICE_SUMMARY_LIST_SIZE],
            "top_fall_risk": filtered.get("top_fall_risk", [])[:PRICE_SUMMARY_LIST_SIZE],
            "alerts": alerts[:ALERT_SUMMARY_SIZE],
            "official_price_predictor_health": filtered.get("official_price_predictor_health", {}),
            "filter_policy": filtered.get("filter_policy", {}),
            "market_noise_count": {
                "buy": len(filtered.get("market_noise", {}).get("buy", [])),
                "sell": len(filtered.get("market_noise", {}).get("sell", [])),
            },
            "trajectory_features": {
                "predicted_change_date": True,
                "official_hourly_movement": True,
                "observed_progress_velocity": True,
                "acceleration_deceleration": True,
                "official_projection_health_guard": True,
                "market_watch_capacity": MAX_MARKET_WATCH,
            },
        }
        latest.setdefault("files", {})["prices"] = "data/prices.json"
        latest.setdefault("files", {})["price_trajectory"] = "data/price_trajectory.json"
        latest.setdefault("files", {})["price_alerts"] = "data/price_alerts.json"
        latest_path.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    patch_files()
