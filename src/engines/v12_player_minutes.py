from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from src.engines.p0_decision_quality import enrich_xmins_contract
from src.engines.v12_model_evidence import bind_deterministic_output, validate_operational_model_evidence

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "intelligence" / "player_minutes.json"
HISTORICAL_POLICY_PATH = ROOT / "config" / "intelligence" / "historical_priors.json"
MODEL_OWNER = "V12_PLAYER_MINUTES"
MODEL_ID = "v12_player_minutes_finite_state"


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


@lru_cache(maxsize=1)
def load_historical_policy() -> dict[str, Any]:
    return json.loads(HISTORICAL_POLICY_PATH.read_text(encoding="utf-8"))


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


def _estimate_core(
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

    starter_rows = [
        dict(row)
        for row in context.get("player_match_rows") or []
        if isinstance(row, Mapping)
        and bool(row.get("starter"))
        and _f(row.get("minutes")) > 0.0
    ]
    full_rows = [
        row for row in starter_rows
        if _f(row.get("minutes")) >= 80.0
    ]
    subbed_rows = [
        row for row in starter_rows
        if 60.0 <= _f(row.get("minutes")) < 80.0
    ]
    early_rows = [
        row for row in starter_rows
        if _f(row.get("minutes")) < 60.0
    ]
    state_prior = dict(
        cfg.get("starter_state_prior")
        or {
            "START_FULL": 2.0,
            "START_SUBBED": 2.0,
            "EARLY_SUB": 1.0,
        }
    )
    counts = {
        "START_FULL": len(full_rows),
        "START_SUBBED": len(subbed_rows),
        "EARLY_SUB": len(early_rows),
    }
    denominator = sum(counts.values()) + sum(
        max(0.0, _f(state_prior.get(name), 0.0))
        for name in counts
    )
    conditional_start = {
        name: (
            counts[name] + max(0.0, _f(state_prior.get(name), 0.0))
        ) / max(1e-9, denominator)
        for name in counts
    }

    def observed_mean(
        rows: list[dict[str, Any]],
        fallback: float,
    ) -> float:
        if not rows:
            return fallback
        return sum(_f(row.get("minutes")) for row in rows) / len(rows)

    if starter_rows:
        full_minutes = clamp(
            observed_mean(full_rows, max(80.0, starter_minutes)),
            80.0,
            90.0,
        )
        subbed_minutes = clamp(
            observed_mean(
                subbed_rows,
                min(79.0, max(60.0, starter_minutes)),
            ),
            60.0,
            79.0,
        )
        early_minutes = clamp(
            observed_mean(
                early_rows,
                min(59.0, max(30.0, starter_minutes - 20.0)),
            ),
            1.0,
            59.0,
        )
    else:
        # Preserve the existing aggregate xMins when factual substitution
        # timing is unavailable. State probability is still explicit, while
        # within-start timing remains prior-only rather than fabricated.
        full_minutes = subbed_minutes = early_minutes = starter_minutes

    states = [
        (
            "START_FULL",
            start_probability * conditional_start["START_FULL"],
            full_minutes,
            max(4.0, starter_std * 0.55),
        ),
        (
            "START_SUBBED",
            start_probability * conditional_start["START_SUBBED"],
            subbed_minutes,
            max(5.0, starter_std * 0.70),
        ),
        (
            "EARLY_SUB",
            start_probability * conditional_start["EARLY_SUB"],
            early_minutes,
            max(7.0, starter_std),
        ),
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
        ("DNP", dnp_probability, 0.0, 0.0),
    ]
    expected_minutes, mixture_variance = _mixture_mean_variance(states)
    mixture_std = math.sqrt(mixture_variance)

    small_sample_limit = int(cfg.get("small_sample_matches") or 3)
    small_sample = matches < small_sample_limit
    uncertainty = cfg.get("uncertainty") or {}
    entropy = 0.0
    for _, probability, _, _ in states:
        if probability > 0:
            entropy -= probability * math.log(probability)
    entropy /= math.log(6)
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
        "starter_minutes_if_start": round(
            sum(
                conditional_start[name] * minutes
                for name, minutes in (
                    ("START_FULL", full_minutes),
                    ("START_SUBBED", subbed_minutes),
                    ("EARLY_SUB", early_minutes),
                )
            ),
            1,
        ),
        "p_60_plus": round(
            start_probability
            * (
                conditional_start["START_FULL"]
                + conditional_start["START_SUBBED"]
            ),
            4,
        ),
        "starter_state_evidence": {
            "sample_starts": len(starter_rows),
            "counts": counts,
            "dirichlet_prior": {
                name: _f(state_prior.get(name), 0.0)
                for name in counts
            },
            "conditional_probabilities": {
                name: round(value, 6)
                for name, value in conditional_start.items()
            },
            "substitution_timing_source": (
                "MATCH_MINUTES_DERIVED"
                if starter_rows
                else "PRIOR_ONLY_NO_MATCH_LEVEL_START_MINUTES"
            ),
        },
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


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(default if value is None else value)
    except (TypeError, ValueError):
        return int(default)


def _calibration_hook(summary: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(summary or {})
    overall = dict(raw.get("overall") or raw.get("prediction_overall") or {})
    sample_size = _i(
        raw.get("prediction_sample_size"),
        _i(overall.get("sample_size"), _i(raw.get("sample_size"), 0)),
    )
    confidence = str(raw.get("calibration_confidence") or "").upper()
    if confidence not in {"LOW", "MEDIUM", "HIGH"}:
        confidence = "LOW" if sample_size < 50 else "MEDIUM" if sample_size < 150 else "HIGH"

    def metric(name: str) -> Any:
        return overall.get(name) if name in overall else raw.get(name)

    return {
        "status": "AVAILABLE" if sample_size > 0 else "NO_SETTLED_SAMPLE",
        "calibration_confidence": confidence,
        "sample_size": sample_size,
        "metrics": {
            "starter_brier": metric("starter_brier"),
            "dnp_brier": metric("dnp_brier"),
            "xmins_mae": metric("xmins_mae"),
            "cameo_calibration": raw.get("cameo_calibration"),
            "late_cameo_calibration": raw.get("late_cameo_calibration"),
            "interval_coverage": raw.get("interval_coverage"),
        },
        "parameters_mutated": False,
        "automatic_retuning": False,
        "conservative_parameters_retained": confidence == "LOW",
        "governance": {
            "settled_evidence_required_for_future_tuning": True,
            "insufficient_sample_retains_current_parameters": True,
            "methodology_weights_20_25_30_25_unchanged": True,
        },
    }


def _attach_model_evidence(
    result: dict[str, Any],
    binding: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if binding is None:
        result["model_evidence"] = {
            "status": "UNBOUND",
            "authority": False,
            "evidence_only": True,
            "repository_python_execution_proven": False,
            "raw_v6_payload_persisted": False,
            "run_fingerprint": None,
            "output_fingerprint": None,
        }
        return result

    validation = validate_operational_model_evidence(
        binding,
        serious_decision=True,
        reproducibility_claimed=False,
        repository_python_executed=False,
    )
    fields = (
        "input_snapshot_id",
        "model_version",
        "feature_version",
        "parameter_version",
        "calibration_version",
        "calibration_cutoff",
        "input_fingerprint",
        "model_fingerprint",
        "parameter_fingerprint",
        "calibration_fingerprint",
        "run_fingerprint",
    )
    compact = {name: binding.get(name) for name in fields}
    output_fingerprint = None
    if validation.get("reproducible"):
        output_fingerprint = bind_deterministic_output(binding, result)["output_fingerprint"]
    result["model_evidence"] = {
        "status": validation["status"],
        "authority": False,
        "evidence_only": True,
        "repository_python_execution_proven": False,
        "raw_v6_payload_persisted": False,
        **compact,
        "output_fingerprint": output_fingerprint,
    }
    return result


def estimate_player_minutes(
    player: dict[str, Any],
    context: dict[str, Any] | None = None,
    *,
    calibration_summary: Mapping[str, Any] | None = None,
    model_evidence_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    context = dict(context or {})
    out = _estimate_core(player, context)

    policy = load_historical_policy()
    conf = policy.get("confidence") or {}
    prior_probability = context.get("prior_start_probability")
    prior_minutes = max(0.0, _f(context.get("prior_evidence_minutes")))
    current_starts = max(0.0, _f(player.get("starts")))

    confidence = str(out.get("confidence") or "LOW")
    medium_prior = max(0.0, _f(conf.get("medium_prior_minutes"), 900.0))
    high_prior = max(medium_prior, _f(conf.get("high_prior_minutes"), 1800.0))
    if prior_probability is not None and prior_minutes >= medium_prior:
        confidence = "MEDIUM" if confidence == "LOW" else confidence
    if (
        prior_probability is not None
        and prior_minutes >= high_prior
        and current_starts >= (1.0 if conf.get("high_requires_current_start", True) else 0.0)
        and current_starts >= 2.0
    ):
        confidence = "HIGH"

    states = list((out.get("xmins_distribution") or {}).get("states") or [])
    regular_cameo = 0.0
    mixture_mean = 0.0
    mixture_second = 0.0
    for row in states:
        if row.get("state") == "CAMEO":
            regular_cameo = round(_f(row.get("probability")), 4)
            row["appearance_state"] = "REGULAR_CAMEO"
        else:
            row["appearance_state"] = row.get("state")
        p = _f(row.get("probability"))
        mean = _f(row.get("minutes_mean"))
        std = _f(row.get("minutes_std"))
        mixture_mean += p * mean
        mixture_second += p * (std * std + mean * mean)
    mixture_variance = max(0.0, mixture_second - mixture_mean * mixture_mean)
    total_std = _f((out.get("xmins_distribution") or {}).get("std"))
    total_variance = total_std * total_std

    out["model"] = MODEL_ID
    out["model_owner"] = MODEL_OWNER
    out["confidence"] = confidence
    out["regular_cameo_probability"] = regular_cameo
    out["derived_probabilities"] = {
        "p_start": out.get("start_probability"),
        "p_bench": out.get("bench_probability"),
        "p_cameo": out.get("cameo_probability"),
        "p_regular_cameo": regular_cameo,
        "p_late_cameo": out.get("late_cameo_probability"),
        "p_dnp": out.get("dnp_probability"),
    }
    out["historical_prior"] = {
        "available": prior_probability is not None,
        "start_probability": round(_f(prior_probability), 4) if prior_probability is not None else None,
        "evidence_minutes": round(prior_minutes, 1),
        "source": context.get("prior_source"),
        "identity_match": context.get("prior_identity_match"),
        "starter_minutes_prior": context.get("starter_minutes_prior"),
    }
    out["evidence_lineage"] = {
        "official_availability": {
            "available": True,
            "source": out.get("availability_source"),
        },
        "current_season_start_rate": {
            "available": _f(context.get("team_matches_played")) > 0,
            "team_matches_played": round(max(0.0, _f(context.get("team_matches_played"))), 1),
        },
        "historical_prior": {
            "available": prior_probability is not None,
            "source": context.get("prior_source"),
            "identity_match": context.get("prior_identity_match"),
            "evidence_minutes": round(prior_minutes, 1),
        },
        "role_start_probability": {
            "available": context.get("role_start_probability") is not None,
        },
        "manager_start_probability": {
            "available": context.get("manager_start_probability") is not None,
        },
    }
    out["calibration_hook"] = _calibration_hook(calibration_summary)
    out["minutes_variance"] = round(_f(out.get("minutes_std")) ** 2, 4)
    distribution = out.setdefault("xmins_distribution", {})
    distribution["variance"] = round(total_variance, 6)
    distribution["mixture_only_variance"] = round(mixture_variance, 6)
    distribution["states"] = states
    out.setdefault("governance", {}).update({
        "production_owner": MODEL_OWNER,
        "current_official_availability_is_authority": True,
        "historical_prior_is_shrinkage_evidence": True,
        "missing_historical_prior_is_not_fabricated": True,
        "legacy_xmins_v2_v3_are_migration_oracles_only": True,
        "automatic_parameter_retuning": False,
        "methodology_weights_20_25_30_25_unchanged": True,
    })
    out = enrich_xmins_contract(out)
    return _attach_model_evidence(out, model_evidence_binding)


def estimate_xmins(
    player: dict[str, Any],
    context: dict[str, Any] | None = None,
    *,
    calibration_summary: Mapping[str, Any] | None = None,
    model_evidence_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility entry point for current V12/shared consumers."""
    return estimate_player_minutes(
        player,
        context,
        calibration_summary=calibration_summary,
        model_evidence_binding=model_evidence_binding,
    )
