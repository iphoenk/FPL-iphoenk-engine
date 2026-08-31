from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from src.utils import ROOT

CONFIG_PATH = ROOT / "config" / "intelligence" / "price_radar.json"


@lru_cache(maxsize=1)
def load_policy() -> dict[str, Any]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload.get("model_id"):
        raise RuntimeError("price radar policy must be a configured JSON object")
    return payload


_POLICY = load_policy()
_URGENCY = _POLICY.get("urgency") or {}
_MODEL = _POLICY.get("model_interpretation") or {}
_FRESHNESS = _POLICY.get("freshness") or {}

OFFICIAL_UPDATE_TIMEZONE = str(_POLICY["official_update_timezone"])
DISPLAY_TIMEZONE = str(_POLICY["display_timezone"])
UK = ZoneInfo(OFFICIAL_UPDATE_TIMEZONE)
WIB = ZoneInfo(DISPLAY_TIMEZONE)
MODEL_THRESHOLD = float(_MODEL["threshold_percent"])
STABLE_EPSILON = float(_MODEL["stable_epsilon_percent"])
CRITICAL_PROGRESS = float(_URGENCY["critical_progress_pct"])
HIGH_PROGRESS = float(_URGENCY["high_progress_pct"])
WATCH_PROGRESS = float(_URGENCY["watch_progress_pct"])
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
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
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
        out.append({"offset": offset, "projected_percent": projected, "likelihood": likelihood})
    out.sort(key=lambda item: int(item["offset"]))
    return out, errors


def _direction(progress: float | None, projection0: float | None = None) -> str:
    signal = progress if progress is not None else projection0
    if signal is None or abs(signal) <= STABLE_EPSILON:
        return "STABLE"
    return "RISE" if signal > 0 else "FALL"


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


def _narrative(row: dict[str, Any]) -> str:
    if row.get("price_change_calibrating") is True:
        return "Prediktor harga resmi masih dalam kalibrasi; proyeksi yang belum tersedia tidak dianggap nol."
    if row.get("evidence_state") == "LOCKED":
        return f"Harga masih terkunci sampai {row.get('price_change_locked_until')}; tidak ada prediksi perubahan sebelum waktu tersebut."
    direction = "kenaikan" if row.get("direction") == "RISE" else "penurunan" if row.get("direction") == "FALL" else "perubahan"
    cycle = row.get("predicted_change_cycle")
    predicted = _parse_dt(row.get("predicted_change_at"))
    if cycle != "NONE" and predicted is not None:
        cycle_text = {
            "NEXT_UPDATE": "pembaruan harga berikutnya",
            "PLUS_1_UPDATE": "satu siklus setelah pembaruan berikutnya",
            "PLUS_2_UPDATE": "dua siklus setelah pembaruan berikutnya",
        }.get(str(cycle), "siklus harga mendatang")
        return f"Proyeksi resmi menempatkan sinyal {direction} melewati ambang model pada {cycle_text}; ini bukan jaminan perubahan harga."
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

    for field, value in (("id", element_id), ("team", team_id), ("element_type", element_type), ("now_cost", now_cost), ("selected_by_percent", ownership)):
        if value is None and field in player:
            errors.append(f"{field}:SCHEMA_CHANGED")
    if current_progress is None and "price_change_percent" in player and player.get("price_change_percent") is not None:
        errors.append("price_change_percent:SCHEMA_CHANGED")
    if hourly_rate is None and "price_change_hourly_rate" in player and player.get("price_change_hourly_rate") is not None:
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
        evidence_state = "SCHEMA_CHANGED" if any("SCHEMA_CHANGED" in item for item in errors) else "FIELD_MISSING"
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

    if evidence_state in {"SCHEMA_CHANGED", "FIELD_MISSING"}:
        predictor_serving_state = "UNAVAILABLE"
    elif evidence_state == "STALE":
        predictor_serving_state = "STALE"
    elif cycle == "NONE":
        predictor_serving_state = "NO_SIGNAL"
    else:
        predictor_serving_state = "AVAILABLE"

    fetched_at_iso = observed_at.astimezone(timezone.utc).isoformat() if observed_at is not None else None
    freshness_state = "UNAVAILABLE" if observed_at is None else "STALE" if stale else "FRESH"
    trajectory_basis = {
        "current_progress_percent": current_progress,
        "price_change_hourly_rate": hourly_rate,
        "projection_offsets": [0, 1, 2],
        "model_threshold_percent": MODEL_THRESHOLD,
        "predicted_change_cycle": cycle,
    }

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
        "provider": "OFFICIAL_FPL",
        "observed_at": observed_at.astimezone(timezone.utc).isoformat() if observed_at is not None else None,
        "fetched_at": fetched_at_iso,
        "fetched_at_distinct": False,
        "age_seconds": freshness_seconds,
        "freshness_seconds": freshness_seconds,
        "freshness_state": freshness_state,
        "trajectory_basis": trajectory_basis,
        "predictor_serving_state": predictor_serving_state,
        "raw_evidence_state": evidence_state,
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
        "publication_state_vocabulary": ["AVAILABLE", "NO_SIGNAL", "UNAVAILABLE", "STALE"],
        "raw_evidence_state_preserved": True,
    }


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
        "predicted_change_cycle", "predicted_change_at", "model_urgency", "source", "provider", "observed_at",
        "fetched_at", "fetched_at_distinct", "age_seconds", "freshness_seconds", "freshness_state",
        "trajectory_basis", "predictor_serving_state", "raw_evidence_state",
        "schema_version", "raw_payload_hash", "confidence", "fallback_reason", "evidence_state", "narrative",
    )
    served = {key: row.get(key) for key in keys}
    served.update({"element": row.get("element_id"), "name": row.get("player_name"), "owned": owned, "sell_value_relevance": sell_relevance, "action": action})
    return served


def canonical_contract() -> dict[str, Any]:
    return {
        "model_id": _POLICY.get("model_id"),
        "schema_version": SCHEMA_VERSION,
        "source_authority": list(_POLICY.get("source_authority") or []),
        "current_progress_field": "price_change_percent",
        "projected_progress_field": "price_change_projections",
        "likelihood_preserved_raw": True,
        "official_update_clock": f"00:00 {OFFICIAL_UPDATE_TIMEZONE}",
        "display_timezone": DISPLAY_TIMEZONE,
        "model_threshold_percent": MODEL_THRESHOLD,
        "threshold_is_official_rule": False,
        "no_intra_cycle_crossing_eta": True,
    }
