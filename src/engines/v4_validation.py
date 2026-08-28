from __future__ import annotations

import math
from collections import defaultdict
from statistics import mean

from src.models.v4_calibration import eligible
from src.models.v4_metrics import brier_values, mae_rows, mae_values, spearman_rows

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
    sample = [r for r in rows if r.get("actual_minutes") is not None and r.get("predicted_minutes") is not None]
    if not sample:
        return {"n": 0, "mae": None, "start_n": 0, "start_missing": 0, "start_brier": None, "p60_brier": None}

    minutes_mae = mae_values(
        [float(r["predicted_minutes"]) for r in sample],
        [float(r["actual_minutes"]) for r in sample],
    )
    start_probabilities = []
    start_outcomes = []
    p60_probabilities = []
    p60_outcomes = []
    start_missing = 0
    for row in sample:
        actual_started = row.get("actual_started")
        if actual_started is None:
            start_missing += 1
        elif row.get("start_probability") is not None:
            start_probabilities.append(float(row["start_probability"]))
            start_outcomes.append(1.0 if bool(actual_started) else 0.0)
        if row.get("p60") is not None:
            p60_probabilities.append(float(row["p60"]))
            p60_outcomes.append(1.0 if float(row["actual_minutes"]) >= 60 else 0.0)

    start_brier = brier_values(start_probabilities, start_outcomes)
    p60_brier = brier_values(p60_probabilities, p60_outcomes)
    return {
        "n": len(sample),
        "mae": round(minutes_mae, 4) if minutes_mae is not None else None,
        "start_n": len(start_probabilities),
        "start_missing": start_missing,
        "start_brier": round(start_brier, 4) if start_brier is not None else None,
        "p60_brier": round(p60_brier, 4) if p60_brier is not None else None,
    }


def ranking_metrics(rows, ks=(10, 25, 50)):
    if not rows:
        return {}
    actual_sorted = sorted(rows, key=lambda r: float(r["actual"]), reverse=True)
    predicted_sorted = sorted(rows, key=lambda r: float(r["predicted"]), reverse=True)
    spearman_value = spearman_rows(rows)
    out = {"spearman": round(spearman_value, 4) if spearman_value is not None else None}
    for k in ks:
        predicted = {r["element"] for r in predicted_sorted[:k]}
        actual = {r["element"] for r in actual_sorted[:k]}
        out[f"top{k}_precision"] = round(len(predicted & actual) / max(1, len(predicted)), 4)
        out[f"top{k}_actual_points"] = round(sum(float(r["actual"]) for r in predicted_sorted[:k]), 2)
    return out


def position_breakdown(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row.get("position", "UNK")].append(row)
    out = {}
    for position, group in groups.items():
        mae_value = mae_rows(group)
        out[position] = {
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
    for player in prediction_snapshot.get("players", []):
        fixture = next((row for row in player.get("fixtures", []) if int(row.get("event") or -1) == int(event)), None)
        if not fixture:
            continue
        actual = actual_by_element.get(int(player["element"]))
        if not actual:
            continue
        xmins = fixture.get("xmins", {})
        rows.append({
            "element": int(player["element"]),
            "name": player.get("name"),
            "position": player.get("position"),
            "predicted": float(fixture.get("xpts", 0)),
            "actual": float(actual.get("total_points", 0)),
            "lower80": fixture.get("lower80"),
            "upper80": fixture.get("upper80"),
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
