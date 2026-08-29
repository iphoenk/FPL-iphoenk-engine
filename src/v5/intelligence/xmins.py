from __future__ import annotations

import math
from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/intelligence/xmins_v3.json"


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


def estimate_xmins(player: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)
    context = context or {}
    chance = player.get("chance_of_playing_next_round")
    if chance is not None:
        availability = clamp(_f(chance) / 100.0, 0.0, 1.0)
        availability_source = "official_chance"
    else:
        status = str(player.get("status") or "a")
        availability = clamp(_f((cfg.get("availability_defaults") or {}).get(status), 1.0), 0.0, 1.0)
        availability_source = f"status:{status}"

    neutral = clamp(_f(cfg.get("neutral_start_prior"), 0.72), 0.01, 0.99)
    weights = cfg.get("signal_weights") or {}
    signals: list[tuple[str, float, float]] = [("neutral_prior", neutral, _f(weights.get("neutral_prior"), 0.8))]
    starts = max(0.0, _f(player.get("starts")))
    matches = max(0.0, _f(context.get("team_matches_played")))
    if matches > 0:
        observed_rate = clamp(starts / max(1.0, matches), 0.0, 1.0)
        shrink = max(0.0, _f(cfg.get("season_start_rate_shrinkage_matches"), 4.0))
        season_rate = (observed_rate * matches + neutral * shrink) / max(1e-6, matches + shrink)
        signals.append(("season_start_rate", clamp(season_rate, 0.01, 0.99), _f(weights.get("season_start_rate"), 1.4)))
    for name in ("prior_start_probability", "role_start_probability", "manager_start_probability"):
        value = context.get(name)
        if value is not None:
            signals.append((name, clamp(_f(value), 0.01, 0.99), _f(weights.get(name), 1.0)))

    weighted_logit = sum(_logit(p) * w for _, p, w in signals if w > 0)
    total_weight = sum(w for _, _, w in signals if w > 0)
    raw_start = _sigmoid(weighted_logit / max(1e-6, total_weight))

    observed_rotation_risk = clamp(_f(context.get("rotation_risk"), 0.0), 0.0, 1.0)
    # Role-start probability and role-derived rotation risk are two views of the
    # same evidence family. Applying both would double-penalize a player. Rotation
    # risk only becomes a second multiplicative penalty when the caller explicitly
    # certifies that it comes from independent evidence (for example manager news,
    # verified congestion/rest information, or another separately governed source).
    rotation_risk_independent = bool(context.get("rotation_risk_independent_evidence", False))
    effective_rotation_risk = observed_rotation_risk if rotation_risk_independent else 0.0
    congestion_factor = clamp(_f(context.get("congestion_factor"), 1.0), 0.0, 1.0)
    start_probability = clamp(
        raw_start
        * availability
        * (1.0 - effective_rotation_risk * clamp(_f(cfg.get("rotation_risk_strength"), 0.55), 0.0, 1.0))
        * congestion_factor,
        0.0,
        availability,
    )
    bench_probability = clamp(
        (availability - start_probability) * clamp(_f(cfg.get("bench_share_when_not_start"), 0.65), 0.0, 1.0),
        0.0,
        1.0 - start_probability,
    )
    dnp_probability = clamp(1.0 - start_probability - bench_probability, 0.0, 1.0)
    norm = start_probability + bench_probability + dnp_probability
    start_probability, bench_probability, dnp_probability = (
        start_probability / norm,
        bench_probability / norm,
        dnp_probability / norm,
    )

    fallback_start = _f(cfg.get("fallback_starter_minutes"), 72.0)
    fallback_bench = _f(cfg.get("fallback_bench_minutes"), 18.0)
    observed_start_minutes = _f(player.get("minutes")) / starts if starts > 0 else fallback_start
    shrink_starts = max(0.0, _f(cfg.get("starter_minutes_shrinkage_starts"), 4.0))
    starter_minutes = (observed_start_minutes * starts + fallback_start * shrink_starts) / max(1e-6, starts + shrink_starts)
    starter_minutes = clamp(
        _f(context.get("starter_minutes_prior"), starter_minutes),
        _f(cfg.get("starter_minutes_min"), 45.0),
        _f(cfg.get("starter_minutes_max"), 90.0),
    )
    bench_minutes = clamp(_f(context.get("bench_minutes_prior"), fallback_bench), 1.0, 45.0)
    expected_minutes = start_probability * starter_minutes + bench_probability * bench_minutes

    small_sample = matches < int(cfg.get("small_sample_matches") or 3)
    uncertainty = cfg.get("uncertainty") or {}
    entropy = 0.0
    for probability in (start_probability, bench_probability, dnp_probability):
        if probability > 0:
            entropy -= probability * math.log(probability)
    entropy /= math.log(3)
    half_width = _f(uncertainty.get("base_start_probability_half_width"), 0.12) + (
        _f(uncertainty.get("small_sample_extra_half_width"), 0.12) if small_sample else 0.0
    )
    minutes_std = (
        _f(uncertainty.get("base_minutes_std"), 11.0)
        + entropy * _f(uncertainty.get("entropy_minutes_std_multiplier"), 18.0)
        + (_f(uncertainty.get("small_sample_minutes_std_extra"), 8.0) if small_sample else 0.0)
    )

    conf = cfg.get("confidence") or {}
    prior_probability = context.get("prior_start_probability")
    prior_minutes = max(0.0, _f(context.get("prior_evidence_minutes")))
    if starts >= _f(conf.get("high_min_starts"), 6) and len(signals) >= 2 and availability >= 0.95:
        confidence = "HIGH"
    elif starts >= _f(conf.get("medium_min_starts"), 2) and availability >= 0.75:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    medium_prior = max(0.0, _f(conf.get("medium_prior_minutes"), 900.0))
    high_prior = max(medium_prior, _f(conf.get("high_prior_minutes"), 1800.0))
    if prior_probability is not None and prior_minutes >= medium_prior and confidence == "LOW":
        confidence = "MEDIUM"
    high_current_starts = max(0.0, _f(conf.get("high_minimum_current_starts"), 2.0))
    if (
        prior_probability is not None
        and prior_minutes >= high_prior
        and starts >= high_current_starts
        and (not bool(conf.get("high_requires_current_start", True)) or starts >= 1.0)
        and availability >= 0.75
    ):
        confidence = "HIGH"

    return {
        "model": str(cfg.get("model_id") or "xmins_v3_historical_prior"),
        "start_probability": round(start_probability, 4),
        "bench_probability": round(bench_probability, 4),
        "dnp_probability": round(dnp_probability, 4),
        "expected_minutes": round(expected_minutes, 1),
        "starter_minutes_if_start": round(starter_minutes, 1),
        "bench_minutes_if_used": round(bench_minutes, 1),
        "start_probability_interval": [
            round(clamp(start_probability - half_width, 0.0, 1.0), 4),
            round(clamp(start_probability + half_width, 0.0, 1.0), 4),
        ],
        "expected_minutes_interval": [
            round(clamp(expected_minutes - 1.28 * minutes_std, 0.0, 90.0), 1),
            round(clamp(expected_minutes + 1.28 * minutes_std, 0.0, 90.0), 1),
        ],
        "minutes_std": round(minutes_std, 2),
        "availability": round(availability, 4),
        "availability_source": availability_source,
        "rotation_risk": round(observed_rotation_risk, 4),
        "effective_rotation_risk": round(effective_rotation_risk, 4),
        "rotation_risk_independent_evidence": rotation_risk_independent,
        "congestion_factor": round(congestion_factor, 4),
        "small_sample_guard": small_sample,
        "confidence": confidence,
        "historical_prior": {
            "available": prior_probability is not None,
            "start_probability": round(_f(prior_probability), 4) if prior_probability is not None else None,
            "evidence_minutes": round(prior_minutes, 1),
            "source": context.get("prior_source"),
            "identity_match": context.get("prior_identity_match"),
            "starter_minutes_prior": context.get("starter_minutes_prior"),
        },
        "evidence": [{"signal": n, "probability": round(p, 4), "weight": round(w, 3)} for n, p, w in signals],
        "governance": {
            "current_official_availability_is_authority": True,
            "historical_prior_is_shrinkage_evidence": True,
            "missing_historical_prior_is_not_fabricated": True,
            "role_probability_and_role_rotation_risk_not_double_counted": True,
            "independent_rotation_evidence_required_for_second_penalty": True,
        },
    }
