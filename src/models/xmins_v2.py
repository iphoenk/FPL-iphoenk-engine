from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "intelligence" / "xmins_v2.json"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _logit(p: float) -> float:
    p = clamp(p, 1e-5, 1 - 1e-5)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _availability(player: dict[str, Any], cfg: dict[str, Any]) -> tuple[float, str]:
    """Official FPL availability remains factual authority."""
    chance = player.get("chance_of_playing_next_round")
    if chance is not None:
        return clamp(_f(chance) / 100.0, 0.0, 1.0), "official_chance"
    status = str(player.get("status") or "a")
    defaults = cfg.get("availability_defaults") or {}
    return (
        clamp(_f(defaults.get(status), 1.0), 0.0, 1.0),
        f"status:{status}",
    )


def _mixture_mean_variance(
    states: list[tuple[str, float, float, float]],
) -> tuple[float, float]:
    mean = sum(weight * state_mean for _, weight, state_mean, _ in states)
    second = sum(
        weight * (state_std * state_std + state_mean * state_mean)
        for _, weight, state_mean, state_std in states
    )
    return mean, max(0.0, second - mean * mean)


def estimate_xmins(
    player: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = load_config()
    context = context or {}
    availability, availability_source = _availability(player, cfg)

    neutral = clamp(_f(cfg.get("neutral_start_prior"), 0.72), 0.01, 0.99)
    weights = cfg.get("signal_weights") or {}
    signals: list[tuple[str, float, float]] = [
        ("neutral_prior", neutral, _f(weights.get("neutral_prior"), 0.8))
    ]

    starts = max(0.0, _f(player.get("starts")))
    matches = max(0.0, _f(context.get("team_matches_played")))
    if matches > 0:
        observed_rate = clamp(starts / max(1.0, matches), 0.0, 1.0)
        shrink = max(
            0.0,
            _f(cfg.get("season_start_rate_shrinkage_matches"), 4.0),
        )
        season_rate = (
            observed_rate * matches + neutral * shrink
        ) / max(1e-6, matches + shrink)
        signals.append(
            (
                "season_start_rate",
                clamp(season_rate, 0.01, 0.99),
                _f(weights.get("season_start_rate"), 1.4),
            )
        )

    optional_signals = {
        "prior_start_probability": context.get("prior_start_probability"),
        "role_start_probability": context.get("role_start_probability"),
        "manager_start_probability": context.get("manager_start_probability"),
    }
    for name, value in optional_signals.items():
        if value is not None:
            signals.append(
                (
                    name,
                    clamp(_f(value), 0.01, 0.99),
                    _f(weights.get(name), 1.0),
                )
            )

    weighted_logit = sum(_logit(p) * w for _, p, w in signals if w > 0)
    total_weight = sum(w for _, _, w in signals if w > 0)
    raw_start_given_available = _sigmoid(
        weighted_logit / max(1e-6, total_weight)
    )

    rotation_risk = clamp(
        _f(context.get("rotation_risk"), 0.0), 0.0, 1.0
    )
    rotation_strength = clamp(
        _f(cfg.get("rotation_risk_strength"), 0.55), 0.0, 1.0
    )
    congestion_factor = clamp(
        _f(context.get("congestion_factor"), 1.0), 0.0, 1.0
    )
    start_given_available = clamp(
        raw_start_given_available
        * (1.0 - rotation_risk * rotation_strength)
        * congestion_factor,
        0.0,
        1.0,
    )

    bench_given_available_not_start = clamp(
        _f(cfg.get("bench_share_when_not_start"), 0.65), 0.0, 1.0
    )
    cameo_given_bench = clamp(
        _f(cfg.get("cameo_probability_when_benched"), 0.72), 0.0, 1.0
    )
    late_given_cameo = clamp(
        _f(cfg.get("late_cameo_share_of_cameos"), 0.35), 0.0, 1.0
    )

    available_not_start = availability * (1.0 - start_given_available)
    start_probability = availability * start_given_available
    bench_probability = (
        available_not_start * bench_given_available_not_start
    )
    cameo_probability = bench_probability * cameo_given_bench
    late_cameo_probability = cameo_probability * late_given_cameo
    regular_cameo_probability = max(
        0.0, cameo_probability - late_cameo_probability
    )
    no_appearance_from_bench = bench_probability * (1.0 - cameo_given_bench)
    not_benched_when_available = (
        available_not_start * (1.0 - bench_given_available_not_start)
    )
    dnp_probability = clamp(
        (1.0 - availability)
        + no_appearance_from_bench
        + not_benched_when_available,
        0.0,
        1.0,
    )

    appearance_norm = (
        start_probability + cameo_probability + dnp_probability
    )
    if appearance_norm <= 0:
        start_probability = 0.0
        cameo_probability = 0.0
        late_cameo_probability = 0.0
        regular_cameo_probability = 0.0
        dnp_probability = 1.0
    elif not math.isclose(
        appearance_norm, 1.0, rel_tol=0.0, abs_tol=1e-9
    ):
        # Numerical guard only for mutually-exclusive appearance states.
        start_probability /= appearance_norm
        cameo_probability /= appearance_norm
        late_cameo_probability /= appearance_norm
        regular_cameo_probability /= appearance_norm
        dnp_probability /= appearance_norm

    fallback_start = _f(cfg.get("fallback_starter_minutes"), 72.0)
    fallback_cameo = _f(cfg.get("fallback_bench_minutes"), 18.0)
    fallback_late = _f(cfg.get("fallback_late_cameo_minutes"), 8.0)
    observed_start_minutes = fallback_start
    if starts > 0:
        observed_start_minutes = _f(player.get("minutes")) / starts
    shrink_starts = max(
        0.0, _f(cfg.get("starter_minutes_shrinkage_starts"), 4.0)
    )
    starter_minutes = (
        observed_start_minutes * starts + fallback_start * shrink_starts
    ) / max(1e-6, starts + shrink_starts)
    starter_minutes = clamp(
        _f(context.get("starter_minutes_prior"), starter_minutes),
        _f(cfg.get("starter_minutes_min"), 45.0),
        _f(cfg.get("starter_minutes_max"), 90.0),
    )
    cameo_minutes = clamp(
        _f(context.get("bench_minutes_prior"), fallback_cameo),
        1.0,
        45.0,
    )
    late_cameo_minutes = clamp(
        _f(context.get("late_cameo_minutes_prior"), fallback_late),
        1.0,
        min(30.0, cameo_minutes),
    )

    starter_std = max(
        0.0, _f(cfg.get("starter_minutes_state_std"), 10.0)
    )
    cameo_std = max(
        0.0, _f(cfg.get("cameo_minutes_state_std"), 7.0)
    )
    late_std = max(
        0.0, _f(cfg.get("late_cameo_minutes_state_std"), 4.0)
    )
    states = [
        ("START", start_probability, starter_minutes, starter_std),
        (
            "CAMEO",
            regular_cameo_probability,
            cameo_minutes,
            cameo_std,
        ),
        (
            "LATE_CAMEO",
            late_cameo_probability,
            late_cameo_minutes,
            late_std,
        ),
        ("ZERO_MINUTES", dnp_probability, 0.0, 0.0),
    ]
    expected_minutes, mixture_variance = _mixture_mean_variance(states)
    mixture_std = math.sqrt(mixture_variance)

    small_sample_limit = int(cfg.get("small_sample_matches") or 3)
    small_sample = matches < small_sample_limit
    uncertainty = cfg.get("uncertainty") or {}
    entropy = 0.0
    for p in (
        start_probability,
        regular_cameo_probability,
        late_cameo_probability,
        dnp_probability,
    ):
        if p > 0:
            entropy -= p * math.log(p)
    entropy /= math.log(4)
    probability_half_width = _f(
        uncertainty.get("base_start_probability_half_width"), 0.12
    )
    if small_sample:
        probability_half_width += _f(
            uncertainty.get("small_sample_extra_half_width"), 0.12
        )
    calibration_std = _f(
        uncertainty.get("base_minutes_std"), 11.0
    )
    calibration_std += entropy * _f(
        uncertainty.get("entropy_minutes_std_multiplier"), 18.0
    )
    if small_sample:
        calibration_std += _f(
            uncertainty.get("small_sample_minutes_std_extra"), 8.0
        )
    minutes_std = math.sqrt(
        mixture_std * mixture_std + calibration_std * calibration_std
    )

    conf_cfg = cfg.get("confidence") or {}
    if (
        starts >= _f(conf_cfg.get("high_min_starts"), 6)
        and len(signals) >= 2
        and availability >= 0.95
    ):
        confidence = "HIGH"
    elif (
        starts >= _f(conf_cfg.get("medium_min_starts"), 2)
        and availability >= 0.75
    ):
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return {
        "model": str(
            cfg.get("model_id") or "xmins_v2_hierarchical_state_mixture"
        ),
        "probability_semantics": "V12_HIERARCHICAL",
        "conditional_probabilities": {
            "p_available": round(availability, 4),
            "p_start_given_available": round(start_given_available, 4),
            "p_bench_given_available_not_start": round(
                bench_given_available_not_start, 4
            ),
            "p_cameo_given_bench": round(cameo_given_bench, 4),
            "p_late_cameo_given_cameo": round(late_given_cameo, 4),
            "p_no_appearance_given_bench": round(
                1.0 - cameo_given_bench, 4
            ),
        },
        "start_probability": round(start_probability, 4),
        "bench_probability": round(bench_probability, 4),
        "cameo_probability": round(cameo_probability, 4),
        "late_cameo_probability": round(late_cameo_probability, 4),
        "dnp_probability": round(dnp_probability, 4),
        "appearance_outcomes_sum_to_one": True,
        "bench_is_overlapping_state": True,
        "expected_minutes": round(expected_minutes, 1),
        "starter_minutes_if_start": round(starter_minutes, 1),
        "bench_minutes_if_used": round(cameo_minutes, 1),
        "cameo_minutes_if_used": round(cameo_minutes, 1),
        "late_cameo_minutes_if_used": round(late_cameo_minutes, 1),
        "xmins_distribution": {
            "distribution": "FINITE_STATE_MINUTES_MIXTURE",
            "mean": round(expected_minutes, 3),
            "std": round(minutes_std, 3),
            "mixture_only_std": round(mixture_std, 3),
            "states": [
                {
                    "state": name,
                    "probability": round(weight, 6),
                    "minutes_mean": round(state_mean, 3),
                    "minutes_std": round(state_std, 3),
                }
                for name, weight, state_mean, state_std in states
            ],
            "zero_minutes_state_included": True,
            "uncertainty_published_not_mean_only": True,
        },
        "start_probability_interval": [
            round(
                clamp(
                    start_probability - probability_half_width,
                    0.0,
                    1.0,
                ),
                4,
            ),
            round(
                clamp(
                    start_probability + probability_half_width,
                    0.0,
                    1.0,
                ),
                4,
            ),
        ],
        "expected_minutes_interval": [
            round(
                clamp(
                    expected_minutes - 1.28 * minutes_std,
                    0.0,
                    90.0,
                ),
                1,
            ),
            round(
                clamp(
                    expected_minutes + 1.28 * minutes_std,
                    0.0,
                    90.0,
                ),
                1,
            ),
        ],
        "minutes_std": round(minutes_std, 2),
        "availability": round(availability, 4),
        "availability_source": availability_source,
        "rotation_risk": round(rotation_risk, 4),
        "congestion_factor": round(congestion_factor, 4),
        "small_sample_guard": small_sample,
        "confidence": confidence,
        "evidence": [
            {
                "signal": name,
                "probability": round(prob, 4),
                "weight": round(weight, 3),
            }
            for name, prob, weight in signals
        ],
        "governance": {
            "official_fpl_availability_is_factual_authority": True,
            "historical_and_role_signals_are_model_evidence": True,
            "bench_probability_overlaps_cameo_and_dnp": True,
            "flat_start_bench_cameo_dnp_normalization_forbidden": True,
            "xmins_derived_from_start_cameo_zero_mixture": True,
        },
    }
