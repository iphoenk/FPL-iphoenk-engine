from __future__ import annotations

from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/intelligence/prediction_evaluation.json"


def build_calibration_readiness(accuracy: dict[str, Any]) -> dict[str, Any]:
    """Refine the evaluator's observation-count gate with independent GW evidence.

    Metric calculation remains owned by ``evaluation.core``.  This module does not
    calculate MAE, Brier, Spearman, RMSE, or settlement truth.  It consumes the
    evaluator's existing player-count candidate flag and adds only the temporal
    Gameweek requirement needed to prevent one-GW overfitting.
    """
    cfg = load_json_config(CONFIG)
    calibration = cfg.get("calibration_readiness") if isinstance(cfg.get("calibration_readiness"), dict) else {}
    overall = accuracy.get("overall") if isinstance(accuracy.get("overall"), dict) else {}
    player_observations = int(overall.get("sample_size") or 0)
    settled_gameweeks = sorted({int(gw) for gw in accuracy.get("settled_gameweeks") or []})
    settled_count = len(settled_gameweeks)

    minimum_observations = int(
        calibration.get("minimum_player_observations_for_dynamic_weight")
        or cfg.get("minimum_sample_for_dynamic_weight")
        or 50
    )
    baseline_gws = max(1, int(calibration.get("minimum_settled_gameweeks_for_baseline_candidate") or 3))
    dynamic_gws = max(baseline_gws, int(calibration.get("minimum_settled_gameweeks_for_dynamic_weight") or 5))

    # ``evaluation.core`` owns the player-observation candidate gate. Reuse it
    # rather than recomputing the same business rule in a second module.
    player_observation_gate_pass = bool(accuracy.get("dynamic_weight_eligible"))
    baseline_candidate_eligible = settled_count >= baseline_gws and player_observations > 0
    temporal_gameweek_gate_pass = settled_count >= dynamic_gws
    dynamic_weight_eligible = player_observation_gate_pass and temporal_gameweek_gate_pass

    if settled_count == 0:
        status = "AWAITING_FIRST_SETTLEMENT"
    elif settled_count < baseline_gws:
        status = "COLLECTING_TEMPORAL_SAMPLE"
    elif settled_count < dynamic_gws:
        status = "BASELINE_CANDIDATE_DYNAMIC_WEIGHT_LOCKED"
    elif not player_observation_gate_pass:
        status = "TEMPORAL_SAMPLE_READY_OBSERVATION_COUNT_LOW"
    else:
        status = "DYNAMIC_WEIGHT_ELIGIBLE"

    return {
        "status": status,
        "player_observations": player_observations,
        "settled_gameweek_count": settled_count,
        "settled_gameweeks": settled_gameweeks,
        "minimum_player_observations_for_dynamic_weight": minimum_observations,
        "minimum_settled_gameweeks_for_baseline_candidate": baseline_gws,
        "minimum_settled_gameweeks_for_dynamic_weight": dynamic_gws,
        "baseline_candidate_eligible": baseline_candidate_eligible,
        "dynamic_weight_eligible": dynamic_weight_eligible,
        "player_observation_gate_pass": player_observation_gate_pass,
        "temporal_gameweek_gate_pass": temporal_gameweek_gate_pass,
        "governance": {
            "metric_calculation_owner": "evaluation.core",
            "legacy_player_count_gate_reused_not_recomputed": True,
            "player_rows_within_same_gameweek_are_not_independent_temporal_samples": True,
            "single_gameweek_can_never_enable_dynamic_weighting": True,
            "no_synthetic_or_retroactive_settlement_allowed": True,
        },
    }


def apply_calibration_readiness(accuracy: dict[str, Any]) -> dict[str, Any]:
    readiness = build_calibration_readiness(accuracy)
    return {
        **accuracy,
        "calibration_readiness": readiness,
        # External evaluation consumers see only the stricter joint gate.
        "dynamic_weight_eligible": bool(readiness["dynamic_weight_eligible"]),
    }
