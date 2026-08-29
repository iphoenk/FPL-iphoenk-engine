from __future__ import annotations

from src.models.metrics import calibration_error, mae, rank, spearman


def calibration(actual, pred, bins=5):
    return calibration_error(actual, pred, bins=bins)


def register(name, version, features, training_cutoff, actual=None, pred=None, status="challenger"):
    metrics = {}
    if actual is not None and pred is not None:
        rank_metric = spearman(actual, pred)
        cal = calibration_error(actual, pred)
        metrics = {
            "mae": round(mae(actual, pred), 4),
            "spearman": round(rank_metric, 4) if rank_metric is not None else None,
            "calibration_error": round(cal, 4) if cal is not None else None,
        }
    return {
        "name": name,
        "version": version,
        "features": features,
        "training_cutoff": training_cutoff,
        "status": status,
        "metrics": metrics,
    }
