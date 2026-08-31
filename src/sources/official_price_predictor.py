from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from src.engines.team_value import sell_cost
from src.utils import CONFIG, read_json

POLICY_PATH = CONFIG / "intelligence" / "official_price_predictor.json"
SOURCE = "OFFICIAL_FPL"
CONTRACT = "OFFICIAL_FPL_PRICE_PREDICTOR_V1"


def load_policy() -> dict:
    policy = read_json(POLICY_PATH, {})
    if not policy.get("policy_id"):
        raise RuntimeError("official price predictor policy missing")
    return policy


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dt(value: datetime | str | None) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def next_official_update(now: datetime | str | None = None, policy: dict | None = None) -> dict:
    policy = policy or load_policy()
    current = _dt(now) or datetime.now(timezone.utc)
    uk = ZoneInfo(str(policy["official_update_timezone"]))
    report_tz = ZoneInfo(str(policy["report_timezone"]))
    local = current.astimezone(uk)
    next_date = local.date() + timedelta(days=1)
    target = datetime.combine(next_date, datetime.min.time(), tzinfo=uk)
    target_utc = target.astimezone(timezone.utc)
    eta_seconds = max(0, int((target_utc - current.astimezone(timezone.utc)).total_seconds()))
    hours, remainder = divmod(eta_seconds, 3600)
    minutes = remainder // 60
    return {
        "next_official_price_update_at": target_utc.isoformat(),
        "next_official_price_update_wib": target_utc.astimezone(report_tz).isoformat(),
        "eta_seconds": eta_seconds,
        "eta_human": f"{hours}j {minutes}m",
        "timezone_authority": str(policy["official_update_timezone"]),
        "report_timezone": str(policy["report_timezone"]),
    }


def _projections(raw: Any) -> list[dict]:
    rows: list[dict] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        offset = _int(item.get("offset"))
        if offset not in {0, 1, 2}:
            continue
        rows.append({
            "offset": offset,
            "projected_percent": _float(item.get("projected_percent")),
            "likelihood_raw": item.get("likelihood"),
        })
    return sorted(rows, key=lambda row: row["offset"])


def _projection_map(rows: Iterable[dict]) -> dict[int, dict]:
    return {int(row["offset"]): row for row in rows if row.get("offset") is not None}


def _direction(current: float | None, projections: list[dict]) -> str:
    pmap = _projection_map(projections)
    values = [
        (pmap.get(0) or {}).get("projected_percent"),
        current,
        (pmap.get(1) or {}).get("projected_percent"),
        (pmap.get(2) or {}).get("projected_percent"),
    ]
    signal = next((float(value) for value in values if value is not None and float(value) != 0.0), 0.0)
    if signal > 0:
        return "RISE"
    if signal < 0:
        return "FALL"
    return "STABLE"


def _urgency(current: float | None, projections: list[dict], *, calibrating: bool, locked: bool, policy: dict) -> str:
    if calibrating or locked:
        return "LOW"
    p0 = (_projection_map(projections).get(0) or {}).get("projected_percent")
    magnitude = max(abs(value) for value in (current, p0) if value is not None) if any(value is not None for value in (current, p0)) else 0.0
    thresholds = policy["model_interpretation"]["urgency"]
    if magnitude >= float(thresholds["critical_abs_pct"]):
        return "CRITICAL"
    if magnitude >= float(thresholds["high_abs_pct"]):
        return "HIGH"
    if magnitude >= float(thresholds["watch_abs_pct"]):
        return "WATCH"
    return "LOW"


def _predicted_cycle(projections: list[dict], *, calibrating: bool, lock_until: datetime | None, next_update_at: datetime, policy: dict) -> tuple[int | None, datetime | None]:
    if calibrating:
        return None, None
    threshold = float(policy["model_interpretation"]["candidate_progress_abs_pct"])
    for row in projections:
        projected = row.get("projected_percent")
        offset = row.get("offset")
        if projected is None or offset is None or abs(float(projected)) < threshold:
            continue
        candidate = next_update_at + timedelta(days=int(offset))
        if lock_until and candidate < lock_until:
            continue
        return int(offset), candidate
    return None, None


def _freshness(observed_at: datetime | str | None, now: datetime, policy: dict) -> tuple[str, float | None]:
    observed = _dt(observed_at)
    if not observed:
        return "UNKNOWN", None
    age = max(0.0, (now.astimezone(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds() / 60.0)
    fresh_limit = float(policy["freshness"]["fresh_minutes"])
    stale_limit = float(policy["freshness"]["stale_minutes"])
    if age <= fresh_limit:
        return "FRESH", round(age, 2)
    if age <= stale_limit:
        return "AGING", round(age, 2)
    return "STALE", round(age, 2)


def normalize_player(player: dict, *, observed_at: datetime | str | None = None, now: datetime | str | None = None, policy: dict | None = None) -> dict:
    policy = policy or load_policy()
    current_time = _dt(now) or datetime.now(timezone.utc)
    update = next_official_update(current_time, policy)
    next_update_at = _dt(update["next_official_price_update_at"])
    projections = _projections(player.get("price_change_projections"))
    current = _float(player.get("price_change_percent"))
    hourly_rate = _float(player.get("price_change_hourly_rate"))
    calibrating_raw = player.get("price_change_calibrating")
    calibrating = bool(calibrating_raw) if calibrating_raw is not None else False
    lock_until = _dt(player.get("price_change_locked_until"))
    locked = bool(lock_until and current_time < lock_until)
    cycle, predicted_at = _predicted_cycle(
        projections,
        calibrating=calibrating,
        lock_until=lock_until,
        next_update_at=next_update_at,
        policy=policy,
    )
    freshness, source_age_minutes = _freshness(observed_at, current_time, policy)
    predictor_fields_present = any(
        key in player
        for key in (
            "price_change_percent",
            "price_change_hourly_rate",
            "price_change_projections",
            "price_change_locked_until",
            "price_change_calibrating",
        )
    )
    evidence_state = "PARTIAL" if calibrating else "AVAILABLE" if predictor_fields_present else "UNAVAILABLE"
    if locked:
        evidence_state = "PARTIAL"
    return {
        "contract": CONTRACT,
        "element": _int(player.get("id")),
        "name": player.get("web_name"),
        "first_name": player.get("first_name"),
        "second_name": player.get("second_name"),
        "team_id": _int(player.get("team")),
        "element_type": _int(player.get("element_type")),
        "now_cost": _int(player.get("now_cost")),
        "ownership_pct": _float(player.get("selected_by_percent")),
        "transfers_in": _int(player.get("transfers_in")),
        "transfers_in_event": _int(player.get("transfers_in_event")),
        "transfers_out": _int(player.get("transfers_out")),
        "transfers_out_event": _int(player.get("transfers_out_event")),
        "current_official_progress": current,
        "official_hourly_rate_raw": hourly_rate,
        "official_projections": projections,
        "official_likelihood_raw": {str(row["offset"]): row.get("likelihood_raw") for row in projections},
        "official_locked_until": _iso(lock_until),
        "official_calibrating": player.get("price_change_calibrating"),
        "direction": _direction(current, projections),
        "model_urgency": _urgency(current, projections, calibrating=calibrating, locked=locked, policy=policy),
        "predicted_change_cycle": cycle,
        "predicted_change_at": _iso(predicted_at),
        "next_official_price_update_at": update["next_official_price_update_at"],
        "next_official_price_update_wib": update["next_official_price_update_wib"],
        "eta_seconds": update["eta_seconds"],
        "eta_human": update["eta_human"],
        "projection_cycle_timestamps": {
            str(offset): _iso(next_update_at + timedelta(days=offset)) for offset in (0, 1, 2)
        },
        "source": SOURCE,
        "observed_at": _iso(_dt(observed_at)),
        "freshness": freshness,
        "source_age_minutes": source_age_minutes,
        "evidence_state": evidence_state,
        "confidence": "PARTIAL" if evidence_state == "PARTIAL" else "HIGH" if evidence_state == "AVAILABLE" and freshness == "FRESH" else "LOW",
        "guardrails": {
            "raw_likelihood_preserved": True,
            "official_label_mapping_invented": False,
            "threshold_is_model_interpretation_only": True,
            "eta_is_to_official_update_not_crossing": True,
            "hourly_rate_not_used_for_exact_crossing_eta": True,
        },
    }


def build_market_context(bootstrap: dict, *, observed_at: datetime | str | None = None, now: datetime | str | None = None, previous_cache: dict | None = None, owned_ids: set[int] | None = None, watchlist_ids: Iterable[int] | None = None) -> dict:
    policy = load_policy()
    current_time = _dt(now) or datetime.now(timezone.utc)
    rows = [normalize_player(player, observed_at=observed_at, now=current_time, policy=policy) for player in bootstrap.get("elements") or []]
    previous = (previous_cache or {}).get("players") or {}
    confirmed = []
    current_cache = {}
    for row in rows:
        key = str(row["element"])
        current_cache[key] = {"now_cost": row.get("now_cost"), "ownership": row.get("ownership_pct")}
        old = previous.get(key) or {}
        if old.get("now_cost") is not None and row.get("now_cost") is not None and int(old["now_cost"]) != int(row["now_cost"]):
            confirmed.append({
                "element": row["element"],
                "name": row.get("name"),
                "previous": int(old["now_cost"]),
                "current": int(row["now_cost"]),
                "delta": int(row["now_cost"]) - int(old["now_cost"]),
                "state": "CONFIRMED_PRICE_CHANGE",
            })
    by_id = {int(row["element"]): row for row in rows if row.get("element") is not None}
    owned = [by_id[element] for element in sorted(owned_ids or set()) if element in by_id]
    watchlist = [by_id[int(element)] for element in (watchlist_ids or []) if int(element) in by_id and int(element) not in (owned_ids or set())]
    health = market_health(rows)
    return {
        "schema_version": 1,
        "contract": CONTRACT,
        "policy_id": policy["policy_id"],
        "generated_at": current_time.isoformat(),
        "source": SOURCE,
        "authority_rank": list(policy["source_authority"]),
        "health": health,
        "players": rows,
        "all15": owned,
        "all20_watchlist": watchlist[:20],
        "confirmed_changes": confirmed,
        "price_cache": {"generated_at": current_time.isoformat(), "players": current_cache},
        "guardrails": dict(policy.get("guardrails") or {}),
    }


def market_health(rows: list[dict]) -> dict:
    if not rows:
        return {"status": "FAIL", "reason": "NO_OFFICIAL_PLAYER_ROWS"}
    available = [row for row in rows if row.get("evidence_state") != "UNAVAILABLE"]
    if not available:
        return {"status": "FAIL", "reason": "OFFICIAL_PREDICTOR_SCHEMA_UNAVAILABLE", "coverage": 0.0}
    stale = [row for row in available if row.get("freshness") == "STALE"]
    partial = [row for row in available if row.get("evidence_state") == "PARTIAL"]
    coverage = round(len(available) / len(rows), 4)
    if stale and len(stale) == len(available):
        status, reason = "STALE", "OFFICIAL_PREDICTOR_FRESHNESS_EXCEEDED"
    elif partial or coverage < 1.0:
        status, reason = "PARTIAL", "CALIBRATION_LOCK_OR_PARTIAL_SCHEMA"
    else:
        status, reason = "PASS", "FRESH_OFFICIAL_PREDICTOR_VALID"
    return {
        "status": status,
        "reason": reason,
        "coverage": coverage,
        "available_rows": len(available),
        "total_rows": len(rows),
        "partial_rows": len(partial),
        "stale_rows": len(stale),
        "source": SOURCE,
    }


def _scenario(name: str, *, outgoing: dict, incoming: dict, ledger_row: dict, bank: int, outgoing_drop: int = 0, incoming_rise: int = 0) -> dict:
    purchase = ledger_row.get("purchase_cost")
    governed_sell = ledger_row.get("sell_cost")
    if purchase is None or governed_sell is None:
        return {
            "scenario": name,
            "affordable": None,
            "remaining_bank": None,
            "required_extra_budget": None,
            "sell_value_impact": None,
            "structural_flexibility_impact": None,
            "limitation": "AUTHORITATIVE_OR_RECONSTRUCTED_SELL_VALUE_UNAVAILABLE",
        }
    outgoing_now = int(outgoing.get("now_cost") or 0)
    incoming_now = int(incoming.get("now_cost") or 0)
    future_outgoing = max(0, outgoing_now - outgoing_drop)
    future_incoming = incoming_now + incoming_rise
    future_sell = sell_cost(future_outgoing, int(purchase))
    funds = int(bank) + future_sell
    remaining = funds - future_incoming
    base_remaining = int(bank) + int(governed_sell) - incoming_now
    return {
        "scenario": name,
        "affordable": remaining >= 0,
        "remaining_bank": remaining,
        "required_extra_budget": max(0, -remaining),
        "sell_value_impact": future_sell - int(governed_sell),
        "structural_flexibility_impact": remaining - base_remaining,
        "outgoing_future_sell_value": future_sell,
        "incoming_future_price": future_incoming,
    }


def price_squeeze(outgoing: dict, incoming: dict, ledger_row: dict, bank: int) -> dict:
    scenarios = [
        _scenario("BASE", outgoing=outgoing, incoming=incoming, ledger_row=ledger_row, bank=bank),
        _scenario("OUTGOING_FALL_0_1", outgoing=outgoing, incoming=incoming, ledger_row=ledger_row, bank=bank, outgoing_drop=1),
        _scenario("INCOMING_RISE_0_1", outgoing=outgoing, incoming=incoming, ledger_row=ledger_row, bank=bank, incoming_rise=1),
        _scenario("BOTH_SQUEEZE_0_1", outgoing=outgoing, incoming=incoming, ledger_row=ledger_row, bank=bank, outgoing_drop=1, incoming_rise=1),
        _scenario("OUTGOING_FALL_0_2", outgoing=outgoing, incoming=incoming, ledger_row=ledger_row, bank=bank, outgoing_drop=2),
        _scenario("INCOMING_RISE_0_2", outgoing=outgoing, incoming=incoming, ledger_row=ledger_row, bank=bank, incoming_rise=2),
        _scenario("BOTH_SQUEEZE_0_2", outgoing=outgoing, incoming=incoming, ledger_row=ledger_row, bank=bank, outgoing_drop=2, incoming_rise=2),
    ]
    outgoing_risk = outgoing.get("direction") == "FALL" and outgoing.get("model_urgency") in {"WATCH", "HIGH", "CRITICAL"}
    incoming_risk = incoming.get("direction") == "RISE" and incoming.get("model_urgency") in {"WATCH", "HIGH", "CRITICAL"}
    worst_out = 2 if outgoing_risk else 0
    worst_in = 2 if incoming_risk else 0
    scenarios.append(_scenario("WORST_REASONABLE_SHORT_HORIZON", outgoing=outgoing, incoming=incoming, ledger_row=ledger_row, bank=bank, outgoing_drop=worst_out, incoming_rise=worst_in))
    return {
        "outgoing": {
            "element": outgoing.get("element"), "name": outgoing.get("name"), "now_cost": outgoing.get("now_cost"),
            "sell_value": ledger_row.get("sell_cost"), "current_progress": outgoing.get("current_official_progress"),
            "offset0": (_projection_map(outgoing.get("official_projections") or []).get(0) or {}).get("projected_percent"),
            "raw_likelihood": (outgoing.get("official_likelihood_raw") or {}).get("0"), "direction": outgoing.get("direction"),
        },
        "incoming": {
            "element": incoming.get("element"), "name": incoming.get("name"), "now_cost": incoming.get("now_cost"),
            "current_progress": incoming.get("current_official_progress"),
            "offset0": (_projection_map(incoming.get("official_projections") or []).get(0) or {}).get("projected_percent"),
            "raw_likelihood": (incoming.get("official_likelihood_raw") or {}).get("0"), "direction": incoming.get("direction"),
        },
        "bank": int(bank),
        "next_official_price_update_at": incoming.get("next_official_price_update_at") or outgoing.get("next_official_price_update_at"),
        "eta_seconds": incoming.get("eta_seconds") if incoming.get("eta_seconds") is not None else outgoing.get("eta_seconds"),
        "scenarios": scenarios,
        "price_only_execution_authorized": False,
    }


def squeeze_for_pairs(prices: dict, pairs: Iterable[tuple[int, int]], ledger: list[dict], bank: int) -> list[dict]:
    by_id = {int(row["element"]): row for row in prices.get("players") or [] if row.get("element") is not None}
    ledger_by_id = {int(row["element"]): row for row in ledger if row.get("element") is not None}
    out = []
    for outgoing_id, incoming_id in pairs:
        outgoing, incoming = by_id.get(int(outgoing_id)), by_id.get(int(incoming_id))
        ledger_row = ledger_by_id.get(int(outgoing_id))
        if not outgoing or not incoming or not ledger_row:
            continue
        out.append(price_squeeze(outgoing, incoming, ledger_row, bank))
    return out
