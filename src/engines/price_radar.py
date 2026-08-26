from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from src.sources.official_fpl import get_json

MIN_OWNERSHIP_PCT = 0.5
MIN_ABS_NET = 5_000
HIGH_NET = 25_000
MAX_MARKET_WATCH = 50
UK = ZoneInfo("Europe/London")

# The API currently exposes a signed ordinal likelihood code. Only +/-5 is
# safely interpreted here as threshold-crossing / very-likely because observed
# projections with that code are beyond +/-100%. Intermediate levels are kept
# neutral instead of inventing undocumented Official wording.
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


def filtered_pressure(rows: Iterable[dict], direction: str, limit: int = 25) -> tuple[list[dict], list[dict]]:
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
        and abs(rate) >= 0.25
        and hours_to_deadline >= 1.0
        and abs(p0v - progress) < 0.05
    ):
        return "SUSPECT_STATIC_OFFSET0"
    return "LIVE"


def _trend(current_rate, previous_rate, elapsed_hours):
    if current_rate is None or previous_rate is None or not elapsed_hours or elapsed_hours <= 0:
        return "NEW", None
    acceleration = (current_rate - previous_rate) / elapsed_hours
    if current_rate * previous_rate < 0:
        label = "REVERSING"
    elif abs(current_rate) > abs(previous_rate) + 0.05:
        label = "ACCELERATING"
    elif abs(current_rate) < max(0.0, abs(previous_rate) - 0.05):
        label = "DECELERATING"
    else:
        label = "STEADY"
    return label, round(acceleration, 3)


def _trajectory_eta(now, progress, rate):
    if progress is None or rate is None or abs(rate) < 0.01:
        return None, None
    # A trajectory can only project a crossing if movement continues toward the
    # threshold implied by the current progress. This prevents a player at -90%
    # who has just started recovering (+rate) from being mislabelled as a rise.
    if abs(progress) >= 5:
        target = 100.0 if progress > 0 else -100.0
        if (target - progress) * rate <= 0:
            return None, None
    else:
        target = 100.0 if rate > 0 else -100.0
    remaining = target - progress
    eta = remaining / rate
    if eta < 0 or eta > 24 * 7:
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
    if abs_progress >= 90 or (hours is not None and hours <= 24 and abs_progress >= 75):
        return "CRITICAL"
    if abs_progress >= 75 or (hours is not None and hours <= 24):
        return "HIGH"
    if abs_progress >= 50 or (hours is not None and hours <= 48):
        return "MEDIUM"
    return "LOW"


def _risk_direction(progress, rate):
    # Current Official progress tells us which threshold is actually nearby.
    # Hourly rate tells us whether that risk is intensifying or recovering.
    if progress is not None and abs(progress) >= 5:
        return "RISE" if progress > 0 else "FALL"
    if rate is None or abs(rate) < 0.01:
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
        price_actionable = urgency in {"CRITICAL", "HIGH", "MEDIUM"} or abs(progress or 0) >= 50
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
        if row.get("urgency") not in {"CRITICAL", "HIGH"}:
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
    prices_path = root / "prices.json"
    latest_path = root / "latest.json"
    trajectory_path = root / "price_trajectory.json"
    alerts_path = root / "price_alerts.json"

    prices = json.loads(prices_path.read_text(encoding="utf-8"))
    bootstrap, official_health = get_json("bootstrap-static/", retries=2)
    now = datetime.now(timezone.utc)

    enriched = []
    trajectory_state = json.loads(trajectory_path.read_text(encoding="utf-8")) if trajectory_path.exists() else {}
    new_state = trajectory_state
    if bootstrap:
        total_players = int(bootstrap.get("total_players") or 0)
        raw_rows = [_price_row(p, total_players) for p in bootstrap.get("elements", [])]
        enriched, new_state = build_trajectory(raw_rows, trajectory_state, now)

        rising = sorted((r for r in enriched if r.get("risk_direction") == "RISE"), key=_risk_sort, reverse=True)
        falling = sorted((r for r in enriched if r.get("risk_direction") == "FALL"), key=_risk_sort, reverse=True)
        by_momentum = sorted(enriched, key=lambda r: float(r.get("momentum") or 0), reverse=True)
        prices.update({
            "players": enriched,
            "top_buy_pressure": by_momentum[:25],
            "top_sell_pressure": list(reversed(by_momentum[-25:])),
            "top_rise_risk": rising[:25],
            "top_fall_risk": falling[:25],
            "official_price_predictor_health": official_health,
            "official_price_fields": {
                "progress": "price_change_percent",
                "hourly_rate": "price_change_hourly_rate / 100",
                "projections": "price_change_projections",
                "price_deadline": "00:00 Europe/London",
                "authority": "Official FPL bootstrap native fields",
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
    external_watch = [r for r in sorted(all_rows, key=_risk_sort, reverse=True) if r.get("element") not in owned_ids][:MAX_MARKET_WATCH]
    alert_payload = {
        "generated_at": now.isoformat(),
        "policy": {
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
            "top_buy_pressure": filtered.get("top_buy_pressure", [])[:10],
            "top_sell_pressure": filtered.get("top_sell_pressure", [])[:10],
            "top_rise_risk": filtered.get("top_rise_risk", [])[:10],
            "top_fall_risk": filtered.get("top_fall_risk", [])[:10],
            "alerts": alerts[:20],
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
        latest.setdefault("files", {})["price_trajectory"] = "data/price_trajectory.json"
        latest.setdefault("files", {})["price_alerts"] = "data/price_alerts.json"
        latest_path.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    patch_files()
