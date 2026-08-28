from __future__ import annotations

from datetime import datetime

from src.models.v4_metrics import calibration_error_rows, mae_rows, spearman_rows


def dt(x):
    return datetime.fromisoformat(x.replace("Z", "+00:00"))


def eligible(available_at, deadline):
    try:
        return dt(available_at) <= dt(deadline)
    except Exception:
        return False


# Backward-compatible names. Metric formulas live only in src.models.v4_metrics.
def mae(rows):
    return mae_rows(rows)


def spearman(rows):
    return spearman_rows(rows)


def calibration_error(rows, bins=5):
    return calibration_error_rows(rows, bins=bins)


def backtest(rows, deadline):
    safe = [r for r in rows if eligible(r.get("available_at"), deadline)]
    rejected = len(rows) - len(safe)
    return {
        "n": len(safe),
        "leakage_rejected": rejected,
        "mae": round(mae(safe), 4) if safe else None,
        "spearman": round(spearman(safe), 4) if len(safe) > 1 else None,
        "calibration_error": round(calibration_error(safe), 4) if safe else None,
    }


def champion_gate(champion, challenger, min_n=100):
    if challenger.get("n", 0) < min_n:
        return {"promote": False, "reason": "insufficient_sample"}
    if champion.get("mae") is None:
        return {"promote": True, "reason": "no_existing_champion"}
    better_mae = challenger["mae"] <= champion["mae"] * 0.99
    rank_ok = (challenger.get("spearman") or -1) >= (champion.get("spearman") or -1)
    cal_ok = (challenger.get("calibration_error") or 999) <= (champion.get("calibration_error") or 999) * 1.05
    return {
        "promote": bool(better_mae and rank_ok and cal_ok),
        "reason": "passed" if better_mae and rank_ok and cal_ok else "metrics_not_better",
    }
