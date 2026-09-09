from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from src.settings import PRICE_PRESSURE_LIST_SIZE, PRICE_SUMMARY_LIST_SIZE
from src.utils import ROOT, atomic_json

CONFIG_PATH = ROOT / "config" / "intelligence" / "price_radar.json"


@lru_cache(maxsize=1)
def load_policy() -> dict[str, Any]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload.get("model_id"):
        raise RuntimeError("price radar policy must be a configured JSON object")
    return payload


_POLICY = load_policy()
_MARKET = _POLICY.get("market_filter") or {}
_URGENCY = _POLICY.get("urgency") or {}
_SERVING = _POLICY.get("serving") or {}
_MODEL = _POLICY.get("model_interpretation") or {}
_FRESHNESS = _POLICY.get("freshness") or {}

MIN_OWNERSHIP_PCT = float(_MARKET["minimum_ownership_pct"])
MIN_ABS_NET = int(_MARKET["minimum_abs_net_transfers"])
HIGH_NET = int(_MARKET["high_confidence_abs_net_transfers"])
MAX_MARKET_WATCH = int(_SERVING["market_watch_capacity"])
ALERT_SUMMARY_SIZE = int(_SERVING["alert_summary_size"])
OFFICIAL_UPDATE_TIMEZONE = str(_POLICY["official_update_timezone"])
DISPLAY_TIMEZONE = str(_POLICY["display_timezone"])
UK = ZoneInfo(OFFICIAL_UPDATE_TIMEZONE)
WIB = ZoneInfo(DISPLAY_TIMEZONE)
MODEL_THRESHOLD = float(_MODEL["threshold_percent"])
STABLE_EPSILON = float(_MODEL["stable_epsilon_percent"])
CRITICAL_PROGRESS = float(_URGENCY["critical_progress_pct"])
HIGH_PROGRESS = float(_URGENCY["high_progress_pct"])
WATCH_PROGRESS = float(_URGENCY["watch_progress_pct"])
ALERT_LEVELS = frozenset(str(x) for x in _URGENCY["alert_levels"])
OFFICIAL_MAX_AGE_SECONDS = int(_FRESHNESS["official_max_age_seconds"])
SCHEMA_VERSION = int(_POLICY["schema_version"])

REQUIRED_RAW_FIELDS = (
    "id",
    "first_name",
    "second_name",
    "web_name",
    "team",
    "element_type",
    "now_cost",
    "selected_by_percent",
    "transfers_in",
    "transfers_in_event",
    "transfers_out",
    "transfers_out_event",
    "price_change_percent",
    "price_change_hourly_rate",
    "price_change_projections",
    "price_change_locked_until",
    "price_change_calibrating",
)


class PredictorSchemaError(ValueError):
    pass


def _float(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _raw_payload_hash(rows: list[dict[str, Any]]) -> str:
    encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _position_map(element_types: list[dict[str, Any]]) -> dict[int, str]:
    out: dict[int, str] = {}
    for row in element_types or []:
        if not isinstance(row, dict):
            continue
        key = _int(row.get("id"))
        label = row.get("singular_name_short") or row.get("singular_name")
        if key is not None and isinstance(label, str) and label:
            out[key] = label
    return out


def _scheduled_update(now: datetime, offset: int = 0) -> datetime:
    """Return a scheduled Official update in UTC, preserving London DST transitions."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local = now.astimezone(UK)
    target_date = local.date() + timedelta(days=1 + int(offset))
    london_midnight = datetime.combine(target_date, datetime.min.time(), tzinfo=UK)
    return london_midnight.astimezone(timezone.utc)


def _next_uk_midnight(now: datetime) -> datetime:
    return _scheduled_update(now, 0)


def _projection_timestamp(now: datetime, offset: int) -> datetime:
    return _scheduled_update(now, offset)


def _eta_human(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours >= 24:
        days, hours = divmod(hours, 24)
        return f"{days} hari {hours} jam {minutes} menit"
    if hours:
        return f"{hours} jam {minutes} menit"
    return f"{minutes} menit"


def _normalise_projections(raw: Any, *, calibrating: bool = False) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    if raw is None:
        return [], [] if calibrating else ["price_change_projections:FIELD_MISSING"]
    if not isinstance(raw, list):
        return [], ["price_change_projections:SCHEMA_CHANGED"]
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in raw:
        if not isinstance(item, dict):
            errors.append("price_change_projections:item_schema_changed")
            continue
        offset = _int(item.get("offset"))
        projected = _float(item.get("projected_percent"))
        likelihood = item.get("likelihood")
        if offset not in {0, 1, 2}:
            errors.append("price_change_projections:offset_invalid")
            continue
        if offset in seen:
            errors.append(f"price_change_projections:offset_{offset}_duplicate")
            continue
        if projected is None:
            errors.append(f"price_change_projections:offset_{offset}_projected_percent_invalid")
        if likelihood is not None and (isinstance(likelihood, bool) or not isinstance(likelihood, int)):
            errors.append(f"price_change_projections:offset_{offset}_likelihood_type_changed")
        seen.add(offset)
        out.append({
            "offset": offset,
            "projected_percent": projected,
            "likelihood": likelihood,
        })
    out.sort(key=lambda item: int(item["offset"]))
    return out, errors


def _direction(progress: float | None, projection0: float | None = None) -> str:
    signal = progress if progress is not None else projection0
    if signal is None or abs(signal) <= STABLE_EPSILON:
        return "STABLE"
    return "RISE" if signal > 0 else "FALL"


def _risk_direction(progress: float | None, rate: float | None = None) -> str:
    # Compatibility helper. Direction is governed by Official progress, not transfer trend.
    return _direction(progress)


def _prediction_cycle(projections: list[dict[str, Any]], now: datetime, locked_until: datetime | None) -> tuple[str, datetime | None]:
    labels = {0: "NEXT_UPDATE", 1: "PLUS_1_UPDATE", 2: "PLUS_2_UPDATE"}
    for item in projections:
        projected = item.get("projected_percent")
        offset = item.get("offset")
        if projected is None or offset not in labels:
            continue
        if abs(float(projected)) < MODEL_THRESHOLD:
            continue
        update_at = _projection_timestamp(now, int(offset))
        if locked_until is not None and update_at < locked_until.astimezone(timezone.utc):
            continue
        return labels[int(offset)], update_at
    return "NONE", None


def _urgency(progress: float | None, projection0: float | None, cycle: str) -> str:
    current_abs = abs(progress) if progress is not None else 0.0
    projection_abs = abs(projection0) if projection0 is not None else 0.0
    strongest = max(current_abs, projection_abs)
    if cycle == "NEXT_UPDATE" or strongest >= CRITICAL_PROGRESS:
        return "CRITICAL"
    if cycle == "PLUS_1_UPDATE" or strongest >= HIGH_PROGRESS:
        return "HIGH"
    if cycle == "PLUS_2_UPDATE" or strongest >= WATCH_PROGRESS:
        return "WATCH"
    return "LOW"


def _official_projection_health(progress: float | None, rate: float | None, projections: list[dict[str, Any]], hours_to_deadline: float | None = None) -> str:
    del rate, hours_to_deadline
    if progress is None:
        return "UNAVAILABLE"
    return "COMPLETE" if projections else "PARTIAL"


def _trajectory_eta(now: datetime, progress: float | None, rate: float | None) -> tuple[None, None]:
    # Deliberately disabled: extrapolating a threshold crossing fabricates an intra-cycle ETA.
    del now, progress, rate
    return None, None


def _trend(current_rate: float | None, previous_rate: float | None, elapsed_hours: float | None) -> tuple[str, float | None]:
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


def _narrative(row: dict[str, Any]) -> str:
    if row.get("price_change_calibrating") is True:
        return "Prediktor harga resmi masih dalam kalibrasi; proyeksi yang belum tersedia tidak dianggap nol."
    if row.get("evidence_state") == "LOCKED":
        return f"Harga masih terkunci sampai {row.get('price_change_locked_until')}; tidak ada prediksi perubahan sebelum waktu tersebut."
    direction = "kenaikan" if row.get("direction") == "RISE" else "penurunan" if row.get("direction") == "FALL" else "perubahan"
    cycle = row.get("predicted_change_cycle")
    predicted = _parse_dt(row.get("predicted_change_at"))
    if cycle != "NONE" and predicted is not None:
        local = predicted.astimezone(WIB)
        when = local.strftime("%H:%M WIB")
        cycle_text = {
            "NEXT_UPDATE": "pembaruan harga berikutnya",
            "PLUS_1_UPDATE": "satu siklus setelah pembaruan berikutnya",
            "PLUS_2_UPDATE": "dua siklus setelah pembaruan berikutnya",
        }.get(str(cycle), "siklus harga mendatang")
        return f"Proyeksi resmi menempatkan sinyal {direction} melewati ambang model pada {cycle_text}, sekitar {when}; ini bukan jaminan perubahan harga."
    return f"Belum ada proyeksi resmi yang melewati ambang model untuk {direction} dalam tiga siklus yang tersedia."


def _normalise_player(
    player: dict[str, Any],
    *,
    position_by_type: dict[int, str],
    observed_at: datetime | None,
    now: datetime,
    raw_payload_hash: str,
    confirmed_change: dict[str, Any] | None = None,
) -> dict[str, Any]:
    missing = [field for field in REQUIRED_RAW_FIELDS if field not in player]
    calibrating = player.get("price_change_calibrating") is True
    errors = [f"{field}:FIELD_MISSING" for field in missing]

    element_id = _int(player.get("id"))
    team_id = _int(player.get("team"))
    element_type = _int(player.get("element_type"))
    now_cost = _int(player.get("now_cost"))
    ownership = _float(player.get("selected_by_percent"))
    current_progress = _float(player.get("price_change_percent"))
    hourly_rate = _float(player.get("price_change_hourly_rate"))
    locked_raw = player.get("price_change_locked_until")
    locked_until = _parse_dt(locked_raw) if locked_raw else None

    if element_id is None:
        errors.append("id:SCHEMA_CHANGED")
    if team_id is None:
        errors.append("team:SCHEMA_CHANGED")
    if element_type is None:
        errors.append("element_type:SCHEMA_CHANGED")
    if now_cost is None:
        errors.append("now_cost:SCHEMA_CHANGED")
    if ownership is None:
        errors.append("selected_by_percent:SCHEMA_CHANGED")
    if current_progress is None and "price_change_percent" in player:
        errors.append("price_change_percent:SCHEMA_CHANGED")
    if hourly_rate is None and "price_change_hourly_rate" in player:
        errors.append("price_change_hourly_rate:SCHEMA_CHANGED")
    if "price_change_calibrating" in player and not isinstance(player.get("price_change_calibrating"), bool):
        errors.append("price_change_calibrating:SCHEMA_CHANGED")
    if locked_raw not in (None, "") and locked_until is None:
        errors.append("price_change_locked_until:SCHEMA_CHANGED")

    projections, projection_errors = _normalise_projections(player.get("price_change_projections"), calibrating=calibrating)
    errors.extend(projection_errors)
    pmap = {int(item["offset"]): item for item in projections if item.get("offset") is not None}
    p0 = (pmap.get(0) or {}).get("projected_percent")

    next_update_utc = _scheduled_update(now, 0)
    next_update_local = next_update_utc.astimezone(WIB)
    eta_seconds = max(0, int((next_update_utc - now.astimezone(timezone.utc)).total_seconds()))
    lock_is_active = locked_until is not None and locked_until.astimezone(timezone.utc) > now.astimezone(timezone.utc)
    cycle, predicted_at = _prediction_cycle(projections, now, locked_until if lock_is_active else None)
    direction = _direction(current_progress, p0)
    urgency = _urgency(current_progress, p0, cycle)

    freshness_seconds = None
    if observed_at is not None:
        freshness_seconds = max(0, int((now.astimezone(timezone.utc) - observed_at.astimezone(timezone.utc)).total_seconds()))
    stale = freshness_seconds is None or freshness_seconds > OFFICIAL_MAX_AGE_SECONDS

    if errors:
        evidence_state = "FIELD_MISSING" if all(item.endswith("FIELD_MISSING") for item in errors) else "SCHEMA_CHANGED"
        confidence = "LOW"
        fallback_reason = ";".join(sorted(set(errors)))
    elif stale:
        evidence_state = "STALE"
        confidence = "LOW"
        fallback_reason = "STALE"
    elif calibrating:
        evidence_state = "CALIBRATING"
        confidence = "MEDIUM"
        fallback_reason = "CALIBRATING"
    elif lock_is_active:
        evidence_state = "LOCKED"
        confidence = "HIGH"
        fallback_reason = None
    else:
        evidence_state = "REAL_ZERO" if current_progress == 0 else "AVAILABLE"
        confidence = "HIGH"
        fallback_reason = None

    def projection_value(offset: int, key: str) -> Any:
        return (pmap.get(offset) or {}).get(key)

    row = {
        "element_id": element_id,
        "player_name": player.get("web_name"),
        "team_id": team_id,
        "position": position_by_type.get(element_type) if element_type is not None else None,
        "current_price": round(now_cost / 10.0, 1) if now_cost is not None else None,
        "ownership_percent": ownership,
        "transfers_in_total": _int(player.get("transfers_in")),
        "transfers_in_event": _int(player.get("transfers_in_event")),
        "transfers_out_total": _int(player.get("transfers_out")),
        "transfers_out_event": _int(player.get("transfers_out_event")),
        "current_progress_percent": current_progress,
        "price_change_hourly_rate": hourly_rate,
        "projection_offset_0_percent": projection_value(0, "projected_percent"),
        "projection_offset_0_likelihood": projection_value(0, "likelihood"),
        "projection_offset_1_percent": projection_value(1, "projected_percent"),
        "projection_offset_1_likelihood": projection_value(1, "likelihood"),
        "projection_offset_2_percent": projection_value(2, "projected_percent"),
        "projection_offset_2_likelihood": projection_value(2, "likelihood"),
        "price_change_locked_until": player.get("price_change_locked_until"),
        "price_change_calibrating": calibrating,
        "direction": direction,
        "next_official_price_update_at": next_update_local.isoformat(),
        "eta_to_next_price_update_seconds": eta_seconds,
        "eta_human": _eta_human(eta_seconds),
        "projection_offset_0_at": _projection_timestamp(now, 0).astimezone(WIB).isoformat(),
        "projection_offset_1_at": _projection_timestamp(now, 1).astimezone(WIB).isoformat(),
        "projection_offset_2_at": _projection_timestamp(now, 2).astimezone(WIB).isoformat(),
        "predicted_change_cycle": cycle,
        "predicted_change_at": predicted_at.astimezone(WIB).isoformat() if predicted_at is not None else None,
        "model_urgency": urgency,
        "source": "OFFICIAL_FPL",
        "observed_at": observed_at.astimezone(timezone.utc).isoformat() if observed_at is not None else None,
        "freshness_seconds": freshness_seconds,
        "schema_version": SCHEMA_VERSION,
        "raw_payload_hash": raw_payload_hash,
        "confidence": confidence,
        "fallback_reason": fallback_reason,
        "evidence_state": evidence_state,
        "confirmed_price_change": confirmed_change,
        "official_likelihood_raw": {
            "offset_0": projection_value(0, "likelihood"),
            "offset_1": projection_value(1, "likelihood"),
            "offset_2": projection_value(2, "likelihood"),
        },
        "official_projections": projections,
        "raw": {key: player[key] for key in REQUIRED_RAW_FIELDS if key in player},
        "schema_errors": sorted(set(errors)),
        "narrative": None,
        # Backwards-compatible field aliases. These do not change authority or semantics.
        "element": element_id,
        "name": player.get("web_name"),
        "element_type": element_type,
        "now_cost": now_cost,
        "ownership_pct": ownership,
        "net_transfers": (
            _int(player.get("transfers_in_event")) - _int(player.get("transfers_out_event"))
            if _int(player.get("transfers_in_event")) is not None and _int(player.get("transfers_out_event")) is not None
            else None
        ),
        "official_progress_pct": current_progress,
        "official_hourly_rate_raw": hourly_rate,
        "official_hourly_rate_pct": round(hourly_rate / 100.0, 3) if hourly_rate is not None else None,
        "official_locked_until": player.get("price_change_locked_until"),
        "official_calibrating": calibrating,
        "risk_direction": direction,
        "urgency": urgency,
        "official_projection_health": evidence_state,
        "predicted_change_deadline": predicted_at.astimezone(WIB).isoformat() if predicted_at is not None else None,
        "prediction_source": "OFFICIAL_PROJECTED_PROGRESS" if cycle != "NONE" else None,
        "trajectory_eta_hours": None,
        "trajectory_predicted_change_deadline": None,
    }
    row["narrative"] = _narrative(row)
    return row


def _price_row(player: dict[str, Any], total_players: int = 0) -> dict[str, Any]:
    del total_players
    now = datetime.now(timezone.utc)
    return _normalise_player(
        player,
        position_by_type={1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"},
        observed_at=now,
        now=now,
        raw_payload_hash=_raw_payload_hash([player]),
    )


def build_trajectory(players: list[dict[str, Any]], previous_state: dict[str, Any], now: datetime) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    prior = (previous_state or {}).get("players", {})
    enriched: list[dict[str, Any]] = []
    state: dict[str, Any] = {"generated_at": now.isoformat(), "players": {}}
    for row in players:
        element = row.get("element") if row.get("element") is not None else row.get("element_id")
        key = str(element)
        prev = prior.get(key) or {}
        prev_ts = _parse_dt(prev.get("timestamp"))
        elapsed = (now.astimezone(timezone.utc) - prev_ts.astimezone(timezone.utc)).total_seconds() / 3600 if prev_ts else None
        rate = _float(row.get("official_hourly_rate_pct"))
        previous_rate = _float(prev.get("official_hourly_rate_pct"))
        progress = _float(row.get("official_progress_pct"))
        previous_progress = _float(prev.get("official_progress_pct"))
        trend, acceleration = _trend(rate, previous_rate, elapsed)
        observed_velocity = None
        if progress is not None and previous_progress is not None and elapsed and elapsed > 0:
            observed_velocity = round((progress - previous_progress) / elapsed, 3)
        item = {
            **row,
            "observed_progress_velocity_pct_per_hour": observed_velocity,
            "acceleration_pct_per_hour2": acceleration,
            "trajectory": trend,
            "trajectory_eta_hours": None,
            "trajectory_predicted_change_deadline": None,
        }
        enriched.append(item)
        state["players"][key] = {
            "timestamp": now.isoformat(),
            "now_cost": row.get("now_cost"),
            "official_progress_pct": progress,
            "official_hourly_rate_pct": rate,
            "net_transfers": row.get("net_transfers"),
        }
    return enriched, state


def classify(net_transfers: int | None, ownership_pct: float | None, estimated_owners: int = 1) -> dict[str, Any]:
    if net_transfers is None or ownership_pct is None:
        return {
            "momentum": None,
            "actionable": False,
            "confidence": "UNAVAILABLE",
            "market_noise": False,
            "min_ownership_pct": MIN_OWNERSHIP_PCT,
            "min_abs_net": MIN_ABS_NET,
        }
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


def classify_row(row: dict[str, Any]) -> dict[str, Any]:
    ownership = _float(row.get("ownership_pct"))
    net = _int(row.get("net_transfers"))
    meta = classify(net, ownership, 1)
    return {**row, "actionable": meta["actionable"], "confidence": meta["confidence"], "market_noise": meta["market_noise"]}


def filtered_pressure(rows: Iterable[dict[str, Any]], direction: str, limit: int | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    limit = PRICE_PRESSURE_LIST_SIZE if limit is None else int(limit)
    classified = [classify_row(row) for row in rows]
    actionable = [row for row in classified if row["actionable"]]
    noise = [row for row in classified if row["market_noise"]]
    if direction == "buy":
        actionable.sort(key=lambda row: (float(row.get("momentum") or 0), abs(int(row.get("net_transfers") or 0))), reverse=True)
    else:
        actionable.sort(key=lambda row: (float(row.get("momentum") or 0), -abs(int(row.get("net_transfers") or 0))))
    noise.sort(key=lambda row: abs(int(row.get("net_transfers") or 0)), reverse=True)
    return actionable[:limit], noise[:limit]


def apply_to_payload(prices: dict[str, Any]) -> dict[str, Any]:
    buys, buy_noise = filtered_pressure(prices.get("top_buy_pressure", []), "buy")
    sells, sell_noise = filtered_pressure(prices.get("top_sell_pressure", []), "sell")
    return {
        **prices,
        "filter_policy": {
            "model_id": _POLICY.get("model_id"),
            "min_ownership_pct": MIN_OWNERSHIP_PCT,
            "min_abs_net_transfers": MIN_ABS_NET,
            "purpose": "suppress tiny-denominator transfer-momentum noise; Official predictor evidence is evaluated separately",
        },
        "top_buy_pressure": buys,
        "top_sell_pressure": sells,
        "market_noise": {"buy": buy_noise, "sell": sell_noise},
    }


def _risk_sort(row: dict[str, Any]) -> tuple[int, float, float]:
    rank = {"CRITICAL": 4, "HIGH": 3, "WATCH": 2, "LOW": 1}.get(str(row.get("model_urgency") or row.get("urgency")), 0)
    p0 = _float(row.get("projection_offset_0_percent"))
    current = _float(row.get("current_progress_percent"))
    return rank, abs(p0 or 0.0), abs(current or 0.0)


def _served_evidence(row: dict[str, Any], *, owned: bool) -> dict[str, Any]:
    direction = row.get("direction")
    urgency = row.get("model_urgency")
    if owned and direction == "FALL" and urgency in {"CRITICAL", "HIGH"}:
        action = "Tinjau risiko kehilangan nilai jual, tetapi transfer tetap harus lolos keputusan DSS."
        sell_relevance = "MATERIAL_REVIEW"
    elif not owned and direction == "RISE" and urgency in {"CRITICAL", "HIGH"}:
        action = "Jika pemain memang target DSS, pertimbangkan waktu transfer sebelum siklus harga berikutnya; jangan membeli hanya karena harga."
        sell_relevance = "NOT_OWNED"
    else:
        action = "Pantau; sinyal harga adalah overlay dan tidak menggantikan keputusan sepak bola/DSS."
        sell_relevance = "LOW_OR_NONE" if owned else "NOT_OWNED"
    keys = (
        "element_id", "player_name", "team_id", "position", "current_price", "ownership_percent",
        "transfers_in_total", "transfers_in_event", "transfers_out_total", "transfers_out_event",
        "confirmed_price_change", "current_progress_percent", "price_change_hourly_rate",
        "projection_offset_0_percent", "projection_offset_0_likelihood", "projection_offset_0_at",
        "projection_offset_1_percent", "projection_offset_1_likelihood", "projection_offset_1_at",
        "projection_offset_2_percent", "projection_offset_2_likelihood", "projection_offset_2_at",
        "price_change_locked_until", "price_change_calibrating", "direction",
        "next_official_price_update_at", "eta_to_next_price_update_seconds", "eta_human",
        "predicted_change_cycle", "predicted_change_at", "model_urgency", "source", "observed_at",
        "freshness_seconds", "schema_version", "raw_payload_hash", "confidence", "fallback_reason",
        "evidence_state", "narrative",
    )
    served = {key: row.get(key) for key in keys}
    served.update({"element": row.get("element_id"), "name": row.get("player_name"), "owned": owned, "sell_value_relevance": sell_relevance, "action": action})
    return served


def _overall_health(rows: list[dict[str, Any]], transport: dict[str, Any]) -> dict[str, Any]:
    if not rows:
        return {"status": "FAIL", "source": "OFFICIAL_FPL", "reason": "UNAVAILABLE", "transport": transport}
    states = [str(row.get("evidence_state")) for row in rows]
    bad = sum(state in {"SCHEMA_CHANGED", "FIELD_MISSING"} for state in states)
    stale = sum(state == "STALE" for state in states)
    calibrating = sum(state == "CALIBRATING" for state in states)
    if bad == len(rows):
        status = "FAIL"
    elif bad or calibrating:
        status = "PARTIAL"
    elif stale:
        status = "STALE"
    else:
        status = "PASS"
    return {
        "status": status,
        "source": "OFFICIAL_FPL",
        "players": len(rows),
        "schema_invalid_players": bad,
        "calibrating_players": calibrating,
        "stale_players": stale,
        "transport": transport,
        "auth_required": False,
        "ui_scraping": False,
        "dedicated_predictor_endpoint": False,
        "model_threshold_percent": MODEL_THRESHOLD,
        "threshold_is_official_rule": False,
        "no_intra_cycle_crossing_eta": True,
    }


def patch_files(data_dir: str | Path = "data") -> None:
    root = Path(data_dir)
    prices_path = root / "prices.json"
    latest_path = root / "latest.json"
    trajectory_path = root / "price_trajectory.json"
    alerts_path = root / "price_alerts.json"

    prices = json.loads(prices_path.read_text(encoding="utf-8"))
    raw_rows = prices.get("official_predictor_raw") or []
    if not isinstance(raw_rows, list):
        raw_rows = []
    observed_at = _parse_dt(prices.get("official_predictor_observed_at"))
    transport = prices.get("official_predictor_transport_health") or {}
    position_by_type = _position_map(prices.get("official_element_types") or [])
    raw_hash = _raw_payload_hash(raw_rows)
    now = datetime.now(timezone.utc)
    confirmed_by_id = {
        int(row["element"]): row
        for row in prices.get("confirmed_changes") or []
        if isinstance(row, dict) and row.get("element") is not None
    }

    normalised = [
        _normalise_player(
            raw,
            position_by_type=position_by_type,
            observed_at=observed_at,
            now=now,
            raw_payload_hash=raw_hash,
            confirmed_change=confirmed_by_id.get(_int(raw.get("id")) or -1),
        )
        for raw in raw_rows
        if isinstance(raw, dict)
    ]
    previous_state = json.loads(trajectory_path.read_text(encoding="utf-8")) if trajectory_path.exists() else {}
    enriched, new_state = build_trajectory(normalised, previous_state, now)
    health = _overall_health(enriched, transport)

    rising = sorted((row for row in enriched if row.get("direction") == "RISE"), key=_risk_sort, reverse=True)
    falling = sorted((row for row in enriched if row.get("direction") == "FALL"), key=_risk_sort, reverse=True)
    by_id = {int(row["element_id"]): row for row in enriched if row.get("element_id") is not None}
    prices.update({
        "players": enriched,
        "top_rise_risk": rising[:PRICE_PRESSURE_LIST_SIZE],
        "top_fall_risk": falling[:PRICE_PRESSURE_LIST_SIZE],
        "official_price_predictor_health": health,
        "official_price_predictor_contract": {
            "model_id": _POLICY.get("model_id"),
            "source_authority": _POLICY.get("source_authority"),
            "current_progress_field": "price_change_percent",
            "projected_progress_field": "price_change_projections",
            "likelihood_preserved_raw": True,
            "official_update_clock": f"00:00 {OFFICIAL_UPDATE_TIMEZONE}",
            "display_timezone": DISPLAY_TIMEZONE,
            "model_threshold_percent": MODEL_THRESHOLD,
            "threshold_is_official_rule": False,
            "no_intra_cycle_crossing_eta": True,
        },
    })
    filtered = apply_to_payload(prices)
    atomic_json(prices_path, filtered)
    new_state["contract"] = "official_price_predictor_state_v3"
    new_state["raw_payload_hash"] = raw_hash
    atomic_json(trajectory_path, new_state)

    team = json.loads((root / "team.json").read_text(encoding="utf-8")) if (root / "team.json").exists() else {}
    owned_ids = {int(row["element"]) for row in team.get("squad", []) if isinstance(row, dict) and row.get("element") is not None}
    owned_price_radar = [_served_evidence(by_id[element], owned=True) for element in sorted(owned_ids) if element in by_id]
    market_watch = [
        _served_evidence(row, owned=False)
        for row in sorted(enriched, key=_risk_sort, reverse=True)
        if row.get("element_id") not in owned_ids
    ][:MAX_MARKET_WATCH]
    alerts = [
        _served_evidence(row, owned=row.get("element_id") in owned_ids)
        for row in sorted(enriched, key=_risk_sort, reverse=True)
        if row.get("model_urgency") in ALERT_LEVELS
    ]
    alert_payload = {
        "generated_at": now.isoformat(),
        "health": health,
        "policy": {
            "model_id": _POLICY.get("model_id"),
            "watch_capacity": MAX_MARKET_WATCH,
            "price_signal_is_overlay": True,
            "owned_coverage_required": 15,
            "external_watchlist_price_evidence_is_resolved_from_prices_by_element_id": True,
        },
        "owned_price_radar": owned_price_radar,
        "owned_price_radar_count": len(owned_price_radar),
        "alerts": alerts,
        "market_watch_candidates": market_watch,
    }
    atomic_json(alerts_path, alert_payload)

    if latest_path.exists():
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        latest["price_summary"] = {
            "confirmed_changes": filtered.get("confirmed_changes", []),
            "top_buy_pressure": filtered.get("top_buy_pressure", [])[:PRICE_SUMMARY_LIST_SIZE],
            "top_sell_pressure": filtered.get("top_sell_pressure", [])[:PRICE_SUMMARY_LIST_SIZE],
            "top_rise_risk": [_served_evidence(row, owned=row.get("element_id") in owned_ids) for row in rising[:PRICE_SUMMARY_LIST_SIZE]],
            "top_fall_risk": [_served_evidence(row, owned=row.get("element_id") in owned_ids) for row in falling[:PRICE_SUMMARY_LIST_SIZE]],
            "alerts": alerts[:ALERT_SUMMARY_SIZE],
            "owned_price_radar": owned_price_radar,
            "owned_price_radar_count": len(owned_price_radar),
            "official_price_predictor_health": health,
            "filter_policy": filtered.get("filter_policy", {}),
            "market_noise_count": {
                "buy": len(filtered.get("market_noise", {}).get("buy", [])),
                "sell": len(filtered.get("market_noise", {}).get("sell", [])),
            },
            "governance": {
                "likelihood_raw_only": True,
                "no_false_crossing_eta": True,
                "next_update_is_london_midnight_dst_safe": True,
                "confirmed_and_predicted_are_separate": True,
            },
        }
        latest.setdefault("files", {})["price_trajectory"] = "data/price_trajectory.json"
        latest.setdefault("files", {})["price_alerts"] = "data/price_alerts.json"
        atomic_json(latest_path, latest)


if __name__ == "__main__":
    patch_files()