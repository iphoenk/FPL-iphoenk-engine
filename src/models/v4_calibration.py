from __future__ import annotations

from src.engines.leakage_guard import availability_before_deadline
from src.models.metrics import calibration_error as metric_calibration_error
from src.models.metrics import mae as metric_mae
from src.models.metrics import rank
from src.models.metrics import spearman as metric_spearman


def eligible(available_at, deadline):
    return availability_before_deadline(available_at, deadline)


def _series(rows):
    return [float(r["actual"]) for r in rows], [float(r["predicted"]) for r in rows]


def mae(rows):
    actual, predicted = _series(rows)
    return metric_mae(actual, predicted)


def spearman(rows):
    actual, predicted = _series(rows)
    return metric_spearman(actual, predicted)


def calibration_error(rows, bins=5):
    actual, predicted = _series(rows)
    return metric_calibration_error(actual, predicted, bins=bins)


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
    passed = better_mae and rank_ok and cal_ok
    return {"promote": bool(passed), "reason": "passed" if passed else "metrics_not_better"}
