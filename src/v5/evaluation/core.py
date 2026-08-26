from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from src.v5.config_cache import load_json_config

EVAL_CONFIG = "config/intelligence/prediction_evaluation.json"
CHALLENGER_CONFIG = "config/intelligence/challenger_registry.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _mae(pred: list[float], actual: list[float]) -> float | None:
    return sum(abs(a - p) for p, a in zip(pred, actual)) / len(pred) if pred else None


def _brier(prob: list[float], outcomes: list[float]) -> float | None:
    return sum((p - o) ** 2 for p, o in zip(prob, outcomes)) / len(prob) if prob else None


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    def ranks(values: list[float]) -> list[int]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        result = [0] * len(values)
        for rank, index in enumerate(order): result[index] = rank + 1
        return result
    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    return 1 - 6 * sum((a - b) ** 2 for a, b in zip(rx, ry)) / (n * (n * n - 1))


def _forecast_rows(prediction: dict[str, Any], gw: int) -> list[dict[str, Any]]:
    rows = []
    for player in prediction.get("players") or []:
        event = next((x for x in player.get("xpts_by_gw") or [] if int(x.get("gw") or -1) == gw), None)
        if event is None: continue
        xm = player.get("xmins") or {}
        rows.append({"element": int(player["element"]), "name": player.get("name"), "position": player.get("position"), "xpts": round(_f(event.get("mean")), 4), "xpts_std": round(_f(event.get("std")), 4), "xmins": round(_f(xm.get("expected_minutes")), 2), "start_probability": round(_f(xm.get("start_probability")), 4), "clean_sheet_probability": round(_f(event.get("clean_sheet_probability")), 4)})
    return rows


def _actual_rows(event_live: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for player in event_live.get("elements") or []:
        stats = player.get("stats") or {}
        starts = stats.get("starts")
        rows.append({"element": int(player.get("id") or -1), "points": _f(stats.get("total_points")), "minutes": _f(stats.get("minutes")), "started": int(starts > 0) if starts is not None else None, "clean_sheet": int(_f(stats.get("clean_sheets")) > 0)})
    return rows


def _metrics(forecasts: list[dict[str, Any]], actuals: list[dict[str, Any]]) -> dict[str, Any]:
    amap = {int(x["element"]): x for x in actuals}
    pairs = [(f, amap[int(f["element"])]) for f in forecasts if int(f["element"]) in amap]
    if not pairs: return {"sample_size": 0, "status": "NO_SETTLED_SAMPLE"}
    pp, ap = [_f(f["xpts"]) for f, _ in pairs], [_f(a["points"]) for _, a in pairs]
    pm, am = [_f(f["xmins"]) for f, _ in pairs], [_f(a["minutes"]) for _, a in pairs]
    starters = [(f, a) for f, a in pairs if a.get("started") is not None]
    cs = [(f, a) for f, a in pairs if f.get("position") in {"GK", "DEF", "MID"}]
    rmse = math.sqrt(sum((a - p) ** 2 for p, a in zip(pp, ap)) / len(pp))
    rank = _spearman(pp, ap)
    return {"sample_size": len(pairs), "points_mae": round(_mae(pp, ap) or 0.0, 4), "points_rmse": round(rmse, 4), "xmins_mae": round(_mae(pm, am) or 0.0, 4), "starter_brier": round(_brier([_f(f["start_probability"]) for f, _ in starters], [_f(a["started"]) for _, a in starters]) or 0.0, 4) if starters else None, "starter_sample_size": len(starters), "clean_sheet_brier": round(_brier([_f(f["clean_sheet_probability"]) for f, _ in cs], [_f(a["clean_sheet"]) for _, a in cs]) or 0.0, 4) if cs else None, "clean_sheet_sample_size": len(cs), "spearman": round(rank, 4) if rank is not None else None, "status": "SETTLED"}


def evaluate(prediction: dict[str, Any], context: dict[str, Any], bootstrap: dict[str, Any], event_live: dict[str, Any] | None, ledger: dict[str, Any] | None) -> dict[str, Any]:
    cfg = load_json_config(EVAL_CONFIG)
    ledger = dict(ledger or {"schema_version": 1, "records": {}})
    records = dict(ledger.get("records") or {})
    planning_gw = int(context.get("planning_gw") or prediction.get("planning_gw") or 0)
    deadline_text = context.get("deadline_time")
    deadline = datetime.fromisoformat(str(deadline_text).replace("Z", "+00:00")) if deadline_text else None
    now = datetime.now(timezone.utc)
    if planning_gw > 0:
        record = dict(records.get(str(planning_gw)) or {"gw": planning_gw})
        forecast = {"generated_at": prediction.get("generated_at") or _now(), "players": _forecast_rows(prediction, planning_gw)}
        if deadline and now < deadline:
            record.update({"deadline_time": deadline_text, "latest_pre_deadline_forecast": forecast, "status": "COLLECTING"})
        elif not record.get("frozen_forecast") and record.get("latest_pre_deadline_forecast"):
            record.update({"frozen_forecast": record["latest_pre_deadline_forecast"], "frozen_at": _now(), "status": "FROZEN_AWAITING_SETTLEMENT"})
        records[str(planning_gw)] = record
    events = {int(e["id"]): e for e in bootstrap.get("events") or []}
    live_gw = int(context.get("scoring_gw") or 0)
    for key, record in list(records.items()):
        gw = int(record.get("gw") or key)
        if record.get("status") == "SETTLED" or not record.get("frozen_forecast"): continue
        if not (events.get(gw) or {}).get("finished"): continue
        if event_live and gw == live_gw:
            actuals = _actual_rows(event_live)
            record = dict(record)
            record["actual"] = {"settled_at": _now(), "players": actuals}
            record["metrics"] = _metrics((record["frozen_forecast"] or {}).get("players") or [], actuals)
            record["status"] = "SETTLED"
            records[key] = record
    settled_forecasts, settled_actuals = [], []
    for record in records.values():
        if record.get("status") != "SETTLED": continue
        settled_forecasts.extend((record.get("frozen_forecast") or {}).get("players") or [])
        settled_actuals.extend((record.get("actual") or {}).get("players") or [])
    overall = _metrics(settled_forecasts, settled_actuals)
    sample = int(overall.get("sample_size") or 0)
    thresholds = cfg.get("confidence_sample_thresholds") or {}
    confidence = "LOW" if sample <= int(thresholds.get("low_max") or 49) else ("MEDIUM" if sample <= int(thresholds.get("medium_max") or 149) else "HIGH")
    ledger_out = {**ledger, "updated_at": _now(), "model": cfg.get("model_id"), "records": records}
    accuracy = {"generated_at": _now(), "model": cfg.get("model_id"), "freeze_policy": cfg.get("freeze_policy"), "overall": overall, "confidence": confidence, "settled_gameweeks": sorted(int(k) for k, v in records.items() if v.get("status") == "SETTLED"), "collecting_gameweeks": sorted(int(k) for k, v in records.items() if v.get("status") != "SETTLED"), "dynamic_weight_eligible": sample >= int(cfg.get("minimum_sample_for_dynamic_weight") or 50), "governance": {"accuracy_claim_requires_settled_sample": True, "pre_deadline_forecast_is_frozen_before_scoring": True, "post_deadline_information_cannot_rewrite_frozen_forecast": True}}
    return {"ledger": ledger_out, "accuracy": accuracy}


def challenger_scorecard(prediction: dict[str, Any], observations: dict[str, Any] | None, accuracy: dict[str, Any]) -> dict[str, Any]:
    cfg = load_json_config(CHALLENGER_CONFIG)
    rows = list((observations or {}).get("observations") or [])
    planning_gw = int(prediction.get("planning_gw") or 0)
    providers = []
    for provider in cfg.get("providers") or []:
        pid = str(provider["id"])
        if pid == "internal":
            providers.append({"id": pid, "name": provider.get("name"), "mode": "native", "enabled": True, "state": "ACTIVE", "current_coverage": len(prediction.get("players") or []), "historical_sample": int((accuracy.get("overall") or {}).get("sample_size") or 0), "dynamic_weight_eligible": bool(accuracy.get("dynamic_weight_eligible"))})
            continue
        current = [r for r in rows if str(r.get("provider")) == pid and int(r.get("gw") or -1) == planning_gw]
        providers.append({"id": pid, "name": provider.get("name"), "mode": "observation_file", "enabled": bool(provider.get("enabled", True)), "state": "OBSERVED" if current else "NO_OBSERVATION", "current_coverage": len({int(r.get("element") or -1) for r in current}), "historical_sample": len([r for r in rows if str(r.get("provider")) == pid and r.get("actual") is not None]), "dynamic_weight_eligible": False})
    return {"generated_at": _now(), "registry": cfg.get("registry"), "planning_gw": planning_gw, "auto_scrape": bool(cfg.get("auto_scrape", False)), "providers": providers, "external_observation_count": len(rows), "governance": cfg.get("governance"), "status": "ACTIVE" if any(p["state"] == "OBSERVED" for p in providers if p["id"] != "internal") else "ACTIVE_INTERNAL_ONLY_EXTERNAL_DATA_ABSENT"}
