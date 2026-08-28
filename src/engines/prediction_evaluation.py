from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.engines.official_snapshot_primitives import endpoint_health, load_snapshot, snapshot_event_live_for_gw
from src.models.calibration import brier, mae, spearman_rank
from src.sources.official_fpl import get_json
from src.utils import DATA, ROOT, atomic_json, parse_dt, read_json, utcnow

CONFIG_PATH = ROOT / "config" / "intelligence" / "prediction_evaluation.json"
LEDGER_PATH = DATA / "prediction_ledger.json"
OUT_PATH = DATA / "prediction_accuracy.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _forecast_rows(projections: dict[str, Any], gw: int) -> list[dict[str, Any]]:
    rows = []
    for player in projections.get("players") or []:
        event = next((x for x in player.get("xpts_by_gw") or [] if int(x.get("gw") or -1) == gw), None)
        if event is None:
            continue
        rows.append({
            "element": int(player["element"]),
            "name": player.get("name"),
            "position": player.get("position"),
            "xpts": round(_f(event.get("mean")), 4),
            "xpts_std": round(_f(event.get("std")), 4),
            "xmins": round(_f((player.get("xmins") or {}).get("expected_minutes")), 2),
            "start_probability": round(_f((player.get("xmins") or {}).get("start_probability")), 4),
            "clean_sheet_probability": round(_f(event.get("clean_sheet_probability")), 4),
            "projection_confidence": player.get("projection_confidence"),
        })
    return rows


def _actual_rows(event_live: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for player in event_live.get("elements") or []:
        stats = player.get("stats") or {}
        starts = stats.get("starts")
        rows.append({
            "element": int(player.get("id") or -1),
            "points": _f(stats.get("total_points")),
            "minutes": _f(stats.get("minutes")),
            "started": int(starts > 0) if starts is not None else None,
            "clean_sheet": int(_f(stats.get("clean_sheets")) > 0),
        })
    return rows


def _metrics(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    if not pairs:
        return {"sample_size": 0, "status": "NO_SETTLED_SAMPLE"}
    pred_points = [_f(x["forecast"].get("xpts")) for x in pairs]
    actual_points = [_f(x["actual"].get("points")) for x in pairs]
    pred_minutes = [_f(x["forecast"].get("xmins")) for x in pairs]
    actual_minutes = [_f(x["actual"].get("minutes")) for x in pairs]
    sq = [(a - p) ** 2 for a, p in zip(actual_points, pred_points)]
    starter_pairs = [x for x in pairs if x["actual"].get("started") is not None]
    cs_pairs = [x for x in pairs if x["forecast"].get("position") in {"GK", "DEF", "MID"}]
    rank = spearman_rank(pred_points, actual_points) if len(pairs) >= 2 else None
    return {
        "sample_size": len(pairs),
        "points_mae": round(mae(pred_points, actual_points), 4),
        "points_rmse": round(math.sqrt(sum(sq) / len(sq)), 4),
        "xmins_mae": round(mae(pred_minutes, actual_minutes), 4),
        "starter_brier": round(brier(
            [_f(x["forecast"].get("start_probability")) for x in starter_pairs],
            [_f(x["actual"].get("started")) for x in starter_pairs],
        ), 4) if starter_pairs else None,
        "starter_sample_size": len(starter_pairs),
        "clean_sheet_brier": round(brier(
            [_f(x["forecast"].get("clean_sheet_probability")) for x in cs_pairs],
            [_f(x["actual"].get("clean_sheet")) for x in cs_pairs],
        ), 4) if cs_pairs else None,
        "clean_sheet_sample_size": len(cs_pairs),
        "spearman": round(rank, 4) if rank is not None else None,
        "status": "SETTLED",
    }


def _confidence(sample_size: int) -> str:
    cfg = load_config()
    thresholds = cfg.get("confidence_sample_thresholds") or {}
    if sample_size <= int(thresholds.get("low_max") or 49):
        return "LOW"
    if sample_size <= int(thresholds.get("medium_max") or 149):
        return "MEDIUM"
    return "HIGH"


def _settle_record(record: dict[str, Any], event_live: dict[str, Any]) -> None:
    actual = _actual_rows(event_live)
    amap = {int(x["element"]): x for x in actual}
    frozen = (record.get("frozen_forecast") or {}).get("players") or []
    pairs = [{"forecast": f, "actual": amap[int(f["element"])]} for f in frozen if int(f["element"]) in amap]
    record["actual"] = {"settled_at": _now(), "players": actual}
    record["metrics"] = _metrics(pairs)
    record["status"] = "SETTLED"


def run() -> dict[str, Any]:
    cfg = load_config()
    latest = read_json(DATA / "latest.json", {})
    projections = read_json(DATA / "projections.json", {})
    ledger = read_json(LEDGER_PATH, {"schema_version": 1, "records": {}})
    snapshot = load_snapshot()
    records = ledger.setdefault("records", {})
    phase = latest.get("phase") or snapshot.get("phase") or {}
    planning_gw = int(phase.get("planning_gw") or projections.get("planning_gw") or 0)
    deadline = parse_dt(phase.get("deadline_time"))

    if planning_gw > 0:
        record = records.setdefault(str(planning_gw), {"gw": planning_gw, "status": "COLLECTING"})
        forecast = {"generated_at": projections.get("generated_at") or _now(), "players": _forecast_rows(projections, planning_gw)}
        if deadline and utcnow() < deadline:
            record["deadline_time"] = phase.get("deadline_time")
            record["latest_pre_deadline_forecast"] = forecast
            record["status"] = "COLLECTING"
        elif not record.get("frozen_forecast"):
            candidate = record.get("latest_pre_deadline_forecast")
            candidate_time = parse_dt((candidate or {}).get("generated_at"))
            if candidate and candidate_time and deadline and candidate_time <= deadline:
                record["frozen_forecast"] = candidate
                record["frozen_at"] = _now()
                record["status"] = "FROZEN_AWAITING_SETTLEMENT"
            else:
                record["status"] = "MISSED_PRE_DEADLINE_FREEZE"

    bootstrap = snapshot.get("bootstrap") or {}
    bh = endpoint_health(snapshot, "bootstrap")
    events = {int(e["id"]): e for e in bootstrap.get("events", [])}
    settled_from_snapshot = 0
    settled_from_network = 0
    for key, record in records.items():
        gw = int(record.get("gw") or key)
        if record.get("status") == "SETTLED" or not record.get("frozen_forecast"):
            continue
        event = events.get(gw) or {}
        if cfg.get("settle_only_finished_events", True) and not event.get("finished"):
            continue
        live, health = snapshot_event_live_for_gw(snapshot, gw)
        if live is not None:
            settled_from_snapshot += 1
            health = {**health, "reuse": "CORE_SNAPSHOT"}
        else:
            live, health = get_json(f"event/{gw}/live/")
            settled_from_network += 1
        if live:
            _settle_record(record, live)
            record["settlement_source_health"] = health.get("status")
            record["settlement_source"] = "CORE_SNAPSHOT" if health.get("reuse") else "HISTORICAL_EVENT_LIVE"

    all_pairs = []
    by_position: dict[str, list[dict[str, Any]]] = {}
    by_gw: dict[str, dict[str, Any]] = {}
    for key, record in records.items():
        if record.get("status") != "SETTLED":
            continue
        actual = {int(x["element"]): x for x in (record.get("actual") or {}).get("players") or []}
        frozen = (record.get("frozen_forecast") or {}).get("players") or []
        pairs = [{"forecast": f, "actual": actual[int(f["element"])]} for f in frozen if int(f["element"]) in actual]
        all_pairs.extend(pairs)
        by_gw[str(record.get("gw") or key)] = _metrics(pairs)
        for pair in pairs:
            by_position.setdefault(str(pair["forecast"].get("position")), []).append(pair)

    overall = _metrics(all_pairs)
    sample_size = int(overall.get("sample_size") or 0)
    accuracy = {
        "generated_at": _now(),
        "model": cfg.get("model_id"),
        "freeze_policy": cfg.get("freeze_policy"),
        "overall": overall,
        "confidence": _confidence(sample_size),
        "by_position": {k: _metrics(v) for k, v in sorted(by_position.items())},
        "by_gw": by_gw,
        "settled_gameweeks": sorted(int(k) for k, v in records.items() if v.get("status") == "SETTLED"),
        "collecting_gameweeks": sorted(int(k) for k, v in records.items() if v.get("status") != "SETTLED"),
        "dynamic_weight_eligible": sample_size >= int(cfg.get("minimum_sample_for_dynamic_weight") or 50),
        "governance": {
            "accuracy_claim_requires_settled_sample": True,
            "pre_deadline_forecast_is_frozen_before_scoring": True,
            "post_deadline_information_cannot_rewrite_frozen_forecast": True,
            "core_snapshot_consumed_before_historical_network": True,
        },
        "source_health": {
            "bootstrap": bh.get("status"),
            "bootstrap_source": "CORE_SNAPSHOT",
            "event_live_snapshot_reused": settled_from_snapshot,
            "historical_event_live_fetched": settled_from_network,
        },
    }
    ledger["updated_at"] = _now()
    ledger["model"] = cfg.get("model_id")
    atomic_json(LEDGER_PATH, ledger)
    atomic_json(OUT_PATH, accuracy)

    latest.setdefault("files", {}).update({"prediction_ledger": "data/prediction_ledger.json", "prediction_accuracy": "data/prediction_accuracy.json"})
    latest["prediction_evaluation"] = {
        "status": overall.get("status"),
        "sample_size": sample_size,
        "confidence": accuracy["confidence"],
        "settled_gameweeks": accuracy["settled_gameweeks"],
        "dynamic_weight_eligible": accuracy["dynamic_weight_eligible"],
        "core_snapshot_consumed": True,
    }
    atomic_json(DATA / "latest.json", latest)
    return accuracy


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
