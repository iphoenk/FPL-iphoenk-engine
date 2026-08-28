from __future__ import annotations

import math
from collections import defaultdict
from statistics import mean

from src.models.v4_calibration import eligible
from src.models.v4_metrics import mae_rows, spearman_rows

POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def rmse(rows):
    if not rows:
        return None
    return math.sqrt(sum((float(r["actual"]) - float(r["predicted"])) ** 2 for r in rows) / len(rows))


def interval_coverage(rows):
    with_band = [r for r in rows if r.get("lower80") is not None and r.get("upper80") is not None]
    if not with_band:
        return None
    hit = sum(float(r["lower80"]) <= float(r["actual"]) <= float(r["upper80"]) for r in with_band)
    return hit / len(with_band)


def minutes_metrics(rows):
    m = [r for r in rows if r.get("actual_minutes") is not None and r.get("predicted_minutes") is not None]
    if not m:
        return {"n": 0, "mae": None, "start_n": 0, "start_missing": 0, "start_brier": None, "p60_brier": None}
    mmae = mean(abs(float(r["actual_minutes"]) - float(r["predicted_minutes"])) for r in m)
    sb = []
    p6 = []
    start_missing = 0
    for r in m:
        actual_started = r.get("actual_started")
        if actual_started is None:
            start_missing += 1
        elif r.get("start_probability") is not None:
            actual_start = 1.0 if bool(actual_started) else 0.0
            sb.append((float(r["start_probability"]) - actual_start) ** 2)
        actual60 = 1.0 if float(r["actual_minutes"]) >= 60 else 0.0
        if r.get("p60") is not None:
            p6.append((float(r["p60"]) - actual60) ** 2)
    return {
        "n": len(m),
        "mae": round(mmae, 4),
        "start_n": len(sb),
        "start_missing": start_missing,
        "start_brier": round(mean(sb), 4) if sb else None,
        "p60_brier": round(mean(p6), 4) if p6 else None,
    }


def ranking_metrics(rows, ks=(10, 25, 50)):
    if not rows:
        return {}
    actual_sorted = sorted(rows, key=lambda r: float(r["actual"]), reverse=True)
    predicted_sorted = sorted(rows, key=lambda r: float(r["predicted"]), reverse=True)
    spearman_value = spearman_rows(rows)
    out = {"spearman": round(spearman_value, 4) if spearman_value is not None else None}
    for k in ks:
        pred = {r["element"] for r in predicted_sorted[:k]}
        actual = {r["element"] for r in actual_sorted[:k]}
        out[f"top{k}_precision"] = round(len(pred & actual) / max(1, len(pred)), 4)
        out[f"top{k}_actual_points"] = round(sum(float(r["actual"]) for r in predicted_sorted[:k]), 2)
    return out


def position_breakdown(rows):
    groups = defaultdict(list)
    for r in rows:
        groups[r.get("position", "UNK")].append(r)
    out = {}
    for pos, group in groups.items():
        mae_value = mae_rows(group)
        out[pos] = {
            "n": len(group),
            "mae": round(mae_value, 4) if mae_value is not None else None,
            "rmse": round(rmse(group), 4),
            "mean_predicted": round(mean(float(x["predicted"]) for x in group), 4),
            "mean_actual": round(mean(float(x["actual"]) for x in group), 4),
        }
    return out


def captaincy_metric(rows):
    if not rows:
        return None
    best_pred = max(rows, key=lambda r: float(r["predicted"]))
    best_actual = max(rows, key=lambda r: float(r["actual"]))
    return {
        "predicted_captain": best_pred["element"],
        "predicted_captain_actual": float(best_pred["actual"]),
        "actual_best": best_actual["element"],
        "actual_best_points": float(best_actual["actual"]),
        "regret": round(float(best_actual["actual"]) - float(best_pred["actual"]), 2),
    }


def validate_rows(rows, deadline):
    safe = [r for r in rows if eligible(r.get("available_at"), deadline)]
    rejected = [r for r in rows if r not in safe]
    if not safe:
        return {"status": "NO_SAFE_SAMPLE", "n": 0, "leakage_rejected": len(rejected)}
    mae_value = mae_rows(safe)
    interval_value = interval_coverage(safe)
    return {
        "status": "PASS",
        "n": len(safe),
        "leakage_rejected": len(rejected),
        "mae": round(mae_value, 4) if mae_value is not None else None,
        "rmse": round(rmse(safe), 4),
        "interval80_coverage": round(interval_value, 4) if interval_value is not None else None,
        "ranking": ranking_metrics(safe),
        "minutes": minutes_metrics(safe),
        "by_position": position_breakdown(safe),
        "captaincy": captaincy_metric(safe),
    }


def reconcile_prediction_snapshot(prediction_snapshot, actual_by_element, event, deadline):
    rows = []
    generated = prediction_snapshot.get("generated_at")
    for p in prediction_snapshot.get("players", []):
        fx = next((x for x in p.get("fixtures", []) if int(x.get("event") or -1) == int(event)), None)
        if not fx:
            continue
        actual = actual_by_element.get(int(p["element"]))
        if not actual:
            continue
        xmins = fx.get("xmins", {})
        rows.append({
            "element": int(p["element"]),
            "name": p.get("name"),
            "position": p.get("position"),
            "predicted": float(fx.get("xpts", 0)),
            "actual": float(actual.get("total_points", 0)),
            "lower80": fx.get("lower80"),
            "upper80": fx.get("upper80"),
            "predicted_minutes": xmins.get("expected_minutes"),
            "actual_minutes": actual.get("minutes"),
            "actual_started": actual.get("started"),
            "start_probability": xmins.get("start_probability"),
            "p60": xmins.get("p60"),
            "available_at": generated,
        })
    return {
        "event": event,
        "deadline": deadline,
        "prediction_generated_at": generated,
        "rows": rows,
        "metrics": validate_rows(rows, deadline),
    }


def promotion_gate(report, minimum_n=300):
    metrics = report.get("metrics", report)
    if metrics.get("status") != "PASS":
        return {"promote": False, "reason": "validation_not_passed"}
    if metrics.get("n", 0) < minimum_n:
        return {"promote": False, "reason": "insufficient_sample"}
    if metrics.get("mae") is None or metrics["mae"] > 3.5:
        return {"promote": False, "reason": "mae_too_high"}
    if metrics.get("ranking", {}).get("spearman") is None or metrics["ranking"]["spearman"] < 0.15:
        return {"promote": False, "reason": "ranking_too_weak"}
    coverage = metrics.get("interval80_coverage")
    if coverage is not None and not 0.65 <= coverage <= 0.92:
        return {"promote": False, "reason": "interval_miscalibrated"}
    return {"promote": True, "reason": "passed"}
