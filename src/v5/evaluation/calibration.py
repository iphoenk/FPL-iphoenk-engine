from __future__ import annotations

from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/intelligence/prediction_evaluation.json"


def build_calibration_readiness(accuracy: dict[str, Any]) -> dict[str, Any]:
    """Gate calibration on both player observations and independent GW windows.

    Player rows within one Gameweek are correlated observations.  A large player
    sample from a single GW must therefore never be treated as sufficient temporal
    evidence for dynamic model weighting.
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

    baseline_candidate_eligible = settled_count >= baseline_gws and player_observations > 0
    dynamic_weight_eligible = player_observations >= minimum_observations and settled_count >= dynamic_gws

    if settled_count == 0:
        status = "AWAITING_FIRST_SETTLEMENT"
    elif settled_count < baseline_gws:
        status = "COLLECTING_TEMPORAL_SAMPLE"
    elif settled_count < dynamic_gws:
        status = "BASELINE_CANDIDATE_DYNAMIC_WEIGHT_LOCKED"
    elif player_observations < minimum_observations:
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
        "player_observation_gate_pass": player_observations >= minimum_observations,
        "temporal_gameweek_gate_pass": settled_count >= dynamic_gws,
        "governance": {
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
        # Override the legacy player-count-only flag with the stricter joint gate.
        "dynamic_weight_eligible": bool(readiness["dynamic_weight_eligible"]),
    }
