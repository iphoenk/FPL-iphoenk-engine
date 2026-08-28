from __future__ import annotations

from src.models.v4_metrics import (
    calibration_error_values,
    mae_values,
    spearman_values,
)


def register(name, version, features, training_cutoff, actual=None, pred=None, status="challenger"):
    metrics = {}
    if actual is not None and pred is not None:
        mae_value = mae_values(pred, actual)
        spearman_value = spearman_values(actual, pred)
        calibration_value = calibration_error_values(actual, pred)
        metrics = {
            "mae": round(mae_value, 4) if mae_value is not None else None,
            "spearman": round(spearman_value, 4) if spearman_value is not None else None,
            "calibration_error": round(calibration_value, 4) if calibration_value is not None else None,
        }
    return {
        "name": name,
        "version": version,
        "features": features,
        "training_cutoff": training_cutoff,
        "status": status,
        "metrics": metrics,
    }
