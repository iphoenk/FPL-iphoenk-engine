from __future__ import annotations

"""V12-native posterior predictive player-event engine.

This owner consumes the P1.1 finite-state minutes mixture and produces
fixture-level event-derived expectations and uncertainty. It deliberately does
not implement Monte Carlo, cross-player covariance, or the P1.6 tactical
scorer. Legacy projection components remain migration oracles only.
"""

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from src.engines.v12_model_evidence import (
    bind_deterministic_output,
    validate_operational_model_evidence,
)
from src.rules import (
    APPEARANCE_POINTS_60_PLUS,
    APPEARANCE_POINTS_UNDER_60,
    ASSIST_POINTS,
    CLEAN_SHEET_POINTS,
    DC_POINTS_CAP_PER_MATCH,
    DC_RULES,
    ELEMENT_TYPE_TO_POSITION,
    GOAL_POINTS,
    SAVE_INTERVAL,
    SAVE_POINTS_PER_INTERVAL,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "intelligence" / "player_events.json"
MODEL_OWNER = "V12_PLAYER_EVENTS"
MODEL_ID = "v12_player_events_joint_predictive_v2"
DIRECT_EVENT_MODEL = "DIRECT_EVENT_MODEL"
RESIDUAL_EXPECTATION_COMPONENT = "RESIDUAL_EXPECTATION_COMPONENT"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@lru_cache(maxsize=1)
def load_event_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _confidence(minutes: float, cfg: Mapping[str, Any]) -> str:
    policy = dict(cfg.get("confidence") or {})
    if minutes >= _f(policy.get("high_evidence_minutes"), 450.0):
        return "HIGH"
    if minutes >= _f(policy.get("medium_evidence_minutes"), 180.0):
        return "MEDIUM"
    return "LOW"


def _historical_prior(
    position_prior: float,
    historical: Mapping[str, Any] | None,
    field: str,
) -> tuple[float, str, float]:
    row = dict(historical or {})
    weight = clamp(_f(row.get("attacking_prior_weight")), 0.0, 1.0)
    if weight <= 0.0 or row.get(field) is None:
        return max(0.0, position_prior), "position_prior", 0.0
    player_prior = max(0.0, _f(row.get(field)))
    return (
        max(0.0, position_prior * (1.0 - weight) + player_prior * weight),
        "historical_player_prior+position_prior",
        weight,
    )


def _robust_rate_posterior(
    player: Mapping[str, Any],
    cumulative_field: str,
    prior: float,
    prior_source: str,
    cfg: Mapping[str, Any],
) -> dict[str, Any]:
    minutes = max(0.0, _f(player.get("minutes")))
    cumulative_raw = player.get(cumulative_field)
    robust = dict(cfg.get("early_season_robust_rates") or {})
    tiers = list(robust.get("tiers") or [])
    if robust.get("model") != "adaptive_shrinkage_winsor_v1" or not tiers:
        raise RuntimeError("P1.3 robust posterior rate policy missing")

    if minutes <= 0.0 or cumulative_raw is None:
        return {
            "prior": round(max(0.0, prior), 6),
            "prior_source": prior_source,
            "observed_rate90": None,
            "bounded_observed_rate90": None,
            "posterior_rate90": round(max(0.0, prior), 6),
            "evidence_minutes": round(minutes, 1),
            "shrinkage": 1.0,
            "shrinkage_minutes": None,
            "winsorized": False,
            "confidence": "LOW",
            "provenance": "prior_only_no_observed_evidence",
        }

    cumulative = max(0.0, _f(cumulative_raw))
    selected = next(
        (
            tier
            for tier in tiers
            if tier.get("max_minutes") is None
            or minutes <= _f(tier.get("max_minutes"))
        ),
        tiers[-1],
    )
    shrink_minutes = max(0.0, _f(selected.get("shrink_minutes"), 450.0))
    cap_multiplier = max(1.0, _f(selected.get("upper_prior_multiplier"), 6.0))
    observed = cumulative * 90.0 / minutes
    upper = max(
        prior * cap_multiplier,
        _f(robust.get("absolute_upper_rate90"), 1.5),
    )
    bounded = clamp(observed, 0.0, upper)
    posterior = (
        bounded * minutes + prior * shrink_minutes
    ) / max(1e-9, minutes + shrink_minutes)
    return {
        "prior": round(max(0.0, prior), 6),
        "prior_source": prior_source,
        "observed_rate90": round(observed, 6),
        "bounded_observed_rate90": round(bounded, 6),
        "posterior_rate90": round(max(0.0, posterior), 6),
        "evidence_minutes": round(minutes, 1),
        "shrinkage": round(
            shrink_minutes / max(1e-9, minutes + shrink_minutes), 6
        ),
        "shrinkage_minutes": round(shrink_minutes, 1),
        "cap_multiplier": round(cap_multiplier, 4),
        "winsorized": abs(observed - bounded) > 1e-12,
        "confidence": _confidence(minutes, cfg),
        "provenance": "current_observed_shrunk_to_prior",
    }


def _simple_rate_posterior(
    player: Mapping[str, Any],
    cumulative_field: str,
    prior: float,
    cfg: Mapping[str, Any],
) -> dict[str, Any]:
    minutes = max(0.0, _f(player.get("minutes")))
    cumulative_raw = player.get(cumulative_field)
    shrink_minutes = max(0.0, _f(cfg.get("rate_shrinkage_minutes"), 450.0))
    if minutes <= 0.0 or cumulative_raw is None:
        return {
            "prior": round(max(0.0, prior), 6),
            "observed_rate90": None,
            "posterior_rate90": round(max(0.0, prior), 6),
            "evidence_minutes": round(minutes, 1),
            "shrinkage": 1.0,
            "confidence": "LOW",
            "provenance": "position_prior_only",
        }
    observed = max(0.0, _f(cumulative_raw)) * 90.0 / minutes
    posterior = (
        observed * minutes + prior * shrink_minutes
    ) / max(1e-9, minutes + shrink_minutes)
    return {
        "prior": round(max(0.0, prior), 6),
        "observed_rate90": round(observed, 6),
        "posterior_rate90": round(max(0.0, posterior), 6),
        "evidence_minutes": round(minutes, 1),
        "shrinkage": round(
            shrink_minutes / max(1e-9, minutes + shrink_minutes), 6
        ),
        "confidence": _confidence(minutes, cfg),
        "provenance": "current_observed_shrunk_to_position_prior",
    }


def _poisson_tail_at_least(threshold: int, expected_count: float) -> float:
    if threshold <= 0:
        return 1.0
    lam = max(0.0, float(expected_count))
    if lam <= 0.0:
        return 0.0
    term = math.exp(-lam)
    cumulative = term
    for k in range(1, threshold):
        term *= lam / k
        cumulative += term
    return clamp(1.0 - cumulative, 0.0, 1.0)


@lru_cache(maxsize=64)
def _poisson_rate_for_tail(threshold: int, target_probability: float) -> float:
    target = clamp(float(target_probability), 0.0, 0.999999)
    if target <= 0.0:
        return 0.0
    low, high = 0.0, max(1.0, float(threshold))
    while _poisson_tail_at_least(threshold, high) < target and high < 256.0:
        high *= 2.0
    for _ in range(64):
        mid = (low + high) / 2.0
        if _poisson_tail_at_least(threshold, mid) < target:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def _defcon_posterior(
    element_type: int,
    feature: Mapping[str, Any] | None,
    prior_expected_points90: float,
    cfg: Mapping[str, Any],
) -> dict[str, Any]:
    rule = dict(DC_RULES.get(int(element_type)) or {})
    if not rule.get("eligible"):
        return {
            "eligible": False,
            "threshold": None,
            "points": 0.0,
            "prior_count_rate90": 0.0,
            "observed_count_rate90": None,
            "posterior_count_rate90": 0.0,
            "expected_points90": 0.0,
            "evidence_minutes": 0.0,
            "shrinkage": 1.0,
            "sample_quality": "INELIGIBLE",
            "source": "ineligible_position",
            "confidence": "NONE",
        }

    threshold = int(rule.get("threshold") or 0)
    points = min(
        float(rule.get("points") or 0.0),
        float(DC_POINTS_CAP_PER_MATCH),
    )
    prior_probability = clamp(
        prior_expected_points90 / max(points, 1e-9), 0.0, 0.999999
    )
    prior_count = _poisson_rate_for_tail(threshold, prior_probability)
    advanced = dict((feature or {}).get("advanced_current") or {})
    evidence_minutes = max(0.0, _f(advanced.get("minutes")))
    observed_raw = advanced.get("dc_reconstructed_per90")
    has_observed = evidence_minutes > 0.0 and observed_raw is not None
    observed = max(0.0, _f(observed_raw, prior_count))
    shrink_minutes = max(0.0, _f(cfg.get("rate_shrinkage_minutes"), 450.0))
    if has_observed:
        posterior = (
            observed * evidence_minutes + prior_count * shrink_minutes
        ) / max(1e-9, evidence_minutes + shrink_minutes)
        source = "player_cbit_cbirt_shrunk_to_position_prior"
    else:
        posterior = prior_count
        source = "position_prior_probability_calibrated"
    p90 = _poisson_tail_at_least(threshold, posterior)
    return {
        "eligible": True,
        "threshold": threshold,
        "points": points,
        "prior_count_rate90": round(prior_count, 6),
        "observed_count_rate90": round(observed, 6) if has_observed else None,
        "posterior_count_rate90": round(max(0.0, posterior), 6),
        "expected_points90": round(points * p90, 6),
        "evidence_minutes": round(evidence_minutes, 1),
        "shrinkage": round(
            shrink_minutes / max(1e-9, evidence_minutes + shrink_minutes), 6
        )
        if has_observed
        else 1.0,
        "sample_quality": advanced.get("sample_quality")
        or "NO_ADVANCED_EVIDENCE",
        "source": source,
        "confidence": _confidence(evidence_minutes, cfg)
        if has_observed
        else "LOW",
    }


def build_posterior_rates(
    player: Mapping[str, Any],
    *,
    position_prior: Mapping[str, Any],
    historical: Mapping[str, Any] | None = None,
    feature: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build V12-owned posterior scoring rates without tactical P1.6 input."""
    cfg = load_event_config()
    element_type = int(player.get("element_type") or 4)
    position = str(
        player.get("position")
        or ELEMENT_TYPE_TO_POSITION.get(element_type)
        or "FWD"
    )
    xg_prior, xg_prior_source, historical_weight = _historical_prior(
        _f(position_prior.get("xg90")), historical, "xg90"
    )
    xa_prior, xa_prior_source, _ = _historical_prior(
        _f(position_prior.get("xa90")), historical, "xa90"
    )
    goal = _robust_rate_posterior(
        player, "expected_goals", xg_prior, xg_prior_source, cfg
    )
    assist = _robust_rate_posterior(
        player, "expected_assists", xa_prior, xa_prior_source, cfg
    )
    bonus = _simple_rate_posterior(
        player, "bonus", _f(position_prior.get("bonus90")), cfg
    )
    saves = _simple_rate_posterior(
        player, "saves", _f(position_prior.get("saves90")), cfg
    )
    defcon = _defcon_posterior(
        element_type, feature, _f(position_prior.get("dc90")), cfg
    )
    return {
        "model": MODEL_ID,
        "model_owner": MODEL_OWNER,
        "position": position,
        "goal": goal,
        "assist": assist,
        "bonus": {
            **bonus,
            "classification": RESIDUAL_EXPECTATION_COMPONENT,
            "independent_stochastic_process": False,
        },
        "saves": saves,
        "defcon": defcon,
        "historical_attacking_prior_weight": round(historical_weight, 6),
        "governance": {
            "p1_6_tactical_scorer_applied": False,
            "tactical_role_evidence_used_for_rate_adjustment": False,
            "automatic_parameter_retuning": False,
            "methodology_weights_20_25_30_25_unchanged": True,
            "p1_3b_joint_event_probability_complete": True,
            "p1_6_formula_mutated": False,
            "transfer_economics_consumed": False,
            "named_player_conditioning": False,
            "single_match_overfit": False,
        },
    }


def _finite_states(minutes_projection: Mapping[str, Any]) -> list[dict[str, Any]]:
    dist = dict(minutes_projection.get("xmins_distribution") or {})
    if dist.get("distribution") != "FINITE_STATE_MINUTES_MIXTURE":
        raise ValueError("P1.3 requires P1.1 FINITE_STATE_MINUTES_MIXTURE")
    rows: list[dict[str, Any]] = []
    allowed = {"START", "CAMEO", "REGULAR_CAMEO", "LATE_CAMEO", "ZERO_MINUTES"}
    for raw in dist.get("states") or []:
        name = str(raw.get("state") or raw.get("appearance_state") or "")
        if name not in allowed:
            raise ValueError(f"unsupported minutes state: {name}")
        if name == "CAMEO":
            name = "REGULAR_CAMEO"
        rows.append(
            {
                "state": name,
                "probability": clamp(_f(raw.get("probability")), 0.0, 1.0),
                "minutes_mean": max(0.0, _f(raw.get("minutes_mean"))),
                "minutes_std": max(0.0, _f(raw.get("minutes_std"))),
            }
        )
    required = {"START", "REGULAR_CAMEO", "LATE_CAMEO", "ZERO_MINUTES"}
    if {row["state"] for row in rows} != required:
        raise ValueError("P1.3 requires START/REGULAR_CAMEO/LATE_CAMEO/ZERO_MINUTES")
    total = sum(row["probability"] for row in rows)
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=0.002):
        raise ValueError("finite-state minutes probabilities must sum to one")
    if total <= 0.0:
        raise ValueError("finite-state minutes probability mass is empty")
    for row in rows:
        row["probability"] /= total
    return rows


def _minute_support(state: Mapping[str, Any]) -> list[tuple[float, float]]:
    name = str(state.get("state"))
    mean = max(0.0, _f(state.get("minutes_mean")))
    std = max(0.0, _f(state.get("minutes_std")))
    if name == "ZERO_MINUTES" or mean <= 0.0:
        return [(1.0, 0.0)]
    if name == "START":
        low, high = 1.0, 90.0
    elif name == "REGULAR_CAMEO":
        low, high = 1.0, 59.0
    else:
        low, high = 1.0, 30.0
    if std <= 1e-12:
        return [(1.0, clamp(mean, low, high))]
    cfg = load_event_config().get("minutes_quadrature") or {}
    outer = clamp(_f(cfg.get("outer_weight"), 0.25), 0.0, 0.5)
    centre = clamp(_f(cfg.get("centre_weight"), 0.50), 0.0, 1.0)
    spread = max(0.0, _f(cfg.get("outer_std_multiplier"), math.sqrt(2.0)))
    raw = [
        (outer, clamp(mean - spread * std, low, high)),
        (centre, clamp(mean, low, high)),
        (outer, clamp(mean + spread * std, low, high)),
    ]
    combined: dict[float, float] = {}
    for weight, minute in raw:
        combined[minute] = combined.get(minute, 0.0) + weight
    total = sum(combined.values())
    return [(weight / total, minute) for minute, weight in sorted(combined.items())]


def _joint_support(minutes_projection: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for state in _finite_states(minutes_projection):
        for within_weight, minutes in _minute_support(state):
            rows.append(
                {
                    "state": state["state"],
                    "state_probability": state["probability"],
                    "within_state_probability": within_weight,
                    "joint_probability": state["probability"] * within_weight,
                    "minutes": minutes,
                }
            )
    return rows


def _poisson_reward_moments(lam: float) -> tuple[float, float]:
    """Moments of FPL save points=floor(saves/SAVE_INTERVAL)*points."""
    lam = max(0.0, float(lam))
    if lam <= 0.0:
        return 0.0, 0.0
    p = math.exp(-lam)
    total_p = p
    mean = 0.0
    second = 0.0
    k = 0
    while k < 200 and total_p < 1.0 - 1e-13:
        k += 1
        p *= lam / k
        reward = (k // SAVE_INTERVAL) * SAVE_POINTS_PER_INTERVAL
        mean += p * reward
        second += p * reward * reward
        total_p += p
    return mean, max(0.0, second - mean * mean)


def _fixture_context(
    matchup: Mapping[str, Any],
    home: bool,
    league_baseline: Mapping[str, Any] | None,
) -> dict[str, Any]:
    cfg = load_event_config()
    team_xg = _f(
        matchup.get("team_expected_goals"),
        _f(
            matchup.get("home_expected_goals")
            if home
            else matchup.get("away_expected_goals"),
            1.3,
        ),
    )
    fallback = dict(cfg.get("fallback_league_goals") or {})
    league = dict(league_baseline or {})
    league_goal = _f(
        league.get("home_goals" if home else "away_goals"),
        _f(fallback.get("home" if home else "away"), 1.3),
    )
    attack_multiplier = clamp(
        team_xg / max(0.2, league_goal),
        _f(cfg.get("attack_multiplier_min"), 0.55),
        _f(cfg.get("attack_multiplier_max"), 1.75),
    )
    cs_prob = clamp(
        _f(
            matchup.get("clean_sheet_probability"),
            _f(
                matchup.get("home_clean_sheet_probability")
                if home
                else matchup.get("away_clean_sheet_probability")
            ),
        ),
        0.0,
        1.0,
    )
    return {
        "team_expected_goals": team_xg,
        "league_goal_baseline": league_goal,
        "fixture_attack_multiplier": attack_multiplier,
        "clean_sheet_probability": cs_prob,
    }


def _calibration_hook(summary: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(summary or {})
    overall = dict(raw.get("overall") or raw.get("prediction_overall") or {})
    sample_size = int(
        raw.get("prediction_sample_size")
        or overall.get("sample_size")
        or raw.get("sample_size")
        or 0
    )
    confidence = str(raw.get("calibration_confidence") or "").upper()
    if confidence not in {"LOW", "MEDIUM", "HIGH"}:
        confidence = "LOW" if sample_size < 50 else "MEDIUM" if sample_size < 150 else "HIGH"

    def metric(name: str) -> Any:
        return overall.get(name) if name in overall else raw.get(name)

    return {
        "status": "AVAILABLE" if sample_size > 0 else "NO_SETTLED_SAMPLE",
        "sample_size": sample_size,
        "calibration_confidence": confidence,
        "metrics": {
            "xpts_mae": metric("xpts_mae"),
            "xpts_rmse": metric("xpts_rmse"),
            "goal_brier": metric("goal_brier"),
            "assist_brier": metric("assist_brier"),
            "attacking_return_brier": metric("attacking_return_brier"),
            "fpl_blank_brier": metric("fpl_blank_brier"),
            "point_tail_brier": metric("point_tail_brier"),
            "p10_p90_coverage": metric("p10_p90_coverage"),
            "clean_sheet_brier": metric("clean_sheet_brier"),
            "defcon_brier": metric("defcon_brier"),
            "save_mae": metric("save_mae"),
            "save_rmse": metric("save_rmse"),
            "predictive_interval_coverage": metric("predictive_interval_coverage"),
        },
        "parameters_mutated": False,
        "automatic_retuning": False,
        "governance": {
            "future_settlement_hook_only": True,
            "p1_3b_distribution_metrics_diagnostic_only": True,
            "dependence_parameter_automatic_retuning": False,
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
        output_fingerprint = bind_deterministic_output(
            binding, result
        )["output_fingerprint"]
    result["model_evidence"] = {
        "status": validation.get("status"),
        "authority": False,
        "evidence_only": True,
        "repository_python_execution_proven": False,
        "raw_v6_payload_persisted": False,
        **compact,
        "output_fingerprint": output_fingerprint,
    }
    return result



def _distribution_config() -> dict[str, Any]:
    cfg = load_event_config()
    block = dict(cfg.get("point_distribution") or {})
    if block.get("model") != "FINITE_STATE_CONDITIONAL_CORE_POINT_PMF_V1":
        raise RuntimeError("P1.3B point-distribution policy missing")
    return block


def _joint_ga_config() -> dict[str, Any]:
    cfg = load_event_config()
    block = dict(cfg.get("joint_goal_assist") or {})
    if block.get("model") != "BIVARIATE_POISSON_SHARED_COMPONENT_V1":
        raise RuntimeError("P1.3B joint goal-assist policy missing")
    return block


def _bounded_poisson_probabilities(
    lam: float,
    max_count: int,
) -> tuple[list[float], float]:
    lam = max(0.0, float(lam))
    max_count = int(max_count)
    if max_count < 0:
        raise ValueError("max_count must be non-negative")
    probs = [math.exp(-lam)]
    for count in range(1, max_count + 1):
        probs.append(probs[-1] * lam / count)
    mass = sum(probs)
    truncated = max(0.0, 1.0 - mass)
    if mass <= 0.0:
        raise RuntimeError("bounded Poisson support has no probability mass")
    return [value / mass for value in probs], truncated


def _compound_poisson_point_pmf(
    jumps: Sequence[tuple[int, float]],
    *,
    max_points: int,
    tolerance: float,
) -> tuple[dict[int, float], float]:
    """Exact compound-Poisson recursion on bounded integer point support."""
    active = [
        (int(reward), max(0.0, float(rate)))
        for reward, rate in jumps
        if int(reward) > 0 and float(rate) > 0.0
    ]
    if not active:
        return {0: 1.0}, 0.0
    upper = max(0, int(max_points))
    if upper <= 0:
        return {0: 1.0}, 0.0
    tol = max(0.0, min(1.0, float(tolerance)))
    total_rate = sum(rate for _, rate in active)
    probabilities = [0.0] * (upper + 1)
    probabilities[0] = math.exp(-total_rate)
    represented = probabilities[0]
    max_jump = max(reward for reward, _ in active)
    last = 0
    for points in range(1, upper + 1):
        numerator = 0.0
        for reward, rate in active:
            previous = points - reward
            if previous >= 0:
                numerator += rate * reward * probabilities[previous]
        probability = numerator / points
        probabilities[points] = probability
        represented += probability
        last = points
        if points >= max_jump and represented >= 1.0 - tol:
            break
    pmf = {
        points: probability
        for points, probability in enumerate(probabilities[: last + 1])
        if probability > 0.0
    }
    represented = sum(pmf.values())
    if represented <= 0.0:
        return {0: 1.0}, 0.0
    truncated = max(0.0, 1.0 - represented)
    return (
        {
            points: probability / represented
            for points, probability in pmf.items()
        },
        truncated,
    )


def _joint_goal_assist_point_surface(
    goal_lambda: float,
    assist_lambda: float,
    *,
    goal_points: int,
    assist_points: int,
    shared_fraction: float,
    max_goal_count: int,
    max_assist_count: int,
    tolerance: float,
) -> tuple[dict[int, float], dict[str, float], float]:
    """Return GA point PMF + exact return probabilities for one minute atom."""
    fraction = clamp(float(shared_fraction), 0.0, 1.0)
    goal_lambda = max(0.0, float(goal_lambda))
    assist_lambda = max(0.0, float(assist_lambda))
    shared = fraction * min(goal_lambda, assist_lambda)
    goal_only = max(0.0, goal_lambda - shared)
    assist_only = max(0.0, assist_lambda - shared)

    p_goal = 1.0 - math.exp(-goal_lambda)
    p_assist = 1.0 - math.exp(-assist_lambda)
    p00 = math.exp(-(goal_only + assist_only + shared))
    p_attack = 1.0 - p00
    p_both = max(0.0, min(1.0, p_goal + p_assist - p_attack))
    independent_single_rate = goal_only + assist_only
    p_exactly_one_total_return = p00 * independent_single_rate
    p_exactly_two_total_returns = p00 * (
        independent_single_rate * independent_single_rate / 2.0 + shared
    )
    p_ge_2 = clamp(1.0 - p00 - p_exactly_one_total_return, 0.0, 1.0)
    p_ge_3 = clamp(
        1.0
        - p00
        - p_exactly_one_total_return
        - p_exactly_two_total_returns,
        0.0,
        1.0,
    )

    max_points = (
        int(max_goal_count) * int(goal_points)
        + int(max_assist_count) * int(assist_points)
    )
    point_pmf, truncated = _compound_poisson_point_pmf(
        (
            (int(goal_points), goal_only),
            (int(assist_points), assist_only),
            (int(goal_points) + int(assist_points), shared),
        ),
        max_points=max_points,
        tolerance=tolerance,
    )
    return (
        point_pmf,
        {
            "p_goal": clamp(p_goal, 0.0, 1.0),
            "p_assist": clamp(p_assist, 0.0, 1.0),
            "p_both": clamp(p_both, 0.0, 1.0),
            "p_attack": clamp(p_attack, 0.0, 1.0),
            "p_ge_2": p_ge_2,
            "p_ge_3": p_ge_3,
        },
        truncated,
    )


def _convolve_integer_pmf(
    left: Mapping[int, float],
    right: Mapping[int, float],
) -> dict[int, float]:
    out: dict[int, float] = {}
    for left_points, left_probability in left.items():
        left_mass = float(left_probability)
        if left_mass <= 0.0:
            continue
        for right_points, right_probability in right.items():
            right_mass = float(right_probability)
            if right_mass <= 0.0:
                continue
            points = int(left_points) + int(right_points)
            out[points] = out.get(points, 0.0) + left_mass * right_mass
    return {
        points: probability
        for points, probability in out.items()
        if probability > 0.0
    }


def _bernoulli_reward_pmf(probability: float, reward: float) -> dict[int, float]:
    p = clamp(float(probability), 0.0, 1.0)
    reward_int = int(round(float(reward)))
    if reward_int <= 0 or p <= 0.0:
        return {0: 1.0}
    if p >= 1.0:
        return {reward_int: 1.0}
    return {0: 1.0 - p, reward_int: p}


def _apply_bernoulli_reward(
    pmf: Mapping[int, float],
    probability: float,
    reward: float,
) -> dict[int, float]:
    p = clamp(float(probability), 0.0, 1.0)
    reward_int = int(round(float(reward)))
    if reward_int <= 0 or p <= 0.0:
        return dict(pmf)
    if p >= 1.0:
        return {
            int(points) + reward_int: float(mass)
            for points, mass in pmf.items()
            if float(mass) > 0.0
        }
    no_reward = 1.0 - p
    out: dict[int, float] = {}
    for points, mass_value in pmf.items():
        mass = float(mass_value)
        if mass <= 0.0:
            continue
        base_points = int(points)
        base_mass = mass * no_reward
        reward_mass = mass * p
        if base_mass > 0.0:
            out[base_points] = out.get(base_points, 0.0) + base_mass
        if reward_mass > 0.0:
            rewarded = base_points + reward_int
            out[rewarded] = out.get(rewarded, 0.0) + reward_mass
    return out


def _save_reward_pmf(lam: float) -> tuple[dict[int, float], float]:
    cfg = dict(_distribution_config().get("truncation") or {})
    max_count = int(cfg.get("max_save_count") or 30)
    probabilities, truncated = _bounded_poisson_probabilities(lam, max_count)
    out: dict[int, float] = {}
    for count, probability in enumerate(probabilities):
        reward = (count // SAVE_INTERVAL) * SAVE_POINTS_PER_INTERVAL
        out[int(reward)] = out.get(int(reward), 0.0) + probability
    return out, truncated


def _pmf_moments(pmf: Mapping[int, float]) -> tuple[float, float]:
    mean = sum(float(points) * float(probability) for points, probability in pmf.items())
    second = sum(
        float(points) * float(points) * float(probability)
        for points, probability in pmf.items()
    )
    return mean, max(0.0, second - mean * mean)


def _discrete_quantile(pmf: Mapping[int, float], probability: float) -> int:
    target = clamp(float(probability), 0.0, 1.0)
    cumulative = 0.0
    support = sorted(int(points) for points in pmf)
    if not support:
        return 0
    for points in support:
        cumulative += float(pmf.get(points, 0.0))
        if cumulative + 1e-15 >= target:
            return points
    return support[-1]


def _build_joint_predictive_surface(
    minute_atoms: list[Mapping[str, Any]],
    *,
    element_type: int,
    position: str,
    goal_rate: float,
    assist_rate: float,
    clean_sheet_probability: float,
    dc: Mapping[str, Any],
    dc_rate: float,
    dc_threshold: Any,
    dc_points: float,
    save_rate: float,
    bonus_residual_expectation: float,
    legacy_expected_total: float,
    legacy_moment_variance: float,
) -> dict[str, Any]:
    dist_cfg = _distribution_config()
    trunc_cfg = dict(dist_cfg.get("truncation") or {})
    blank_cfg = dict(dist_cfg.get("blank") or {})
    tail_cfg = dict(dist_cfg.get("tails") or {})
    quantile_cfg = dict(dist_cfg.get("quantiles") or {})
    dependence_cfg = _joint_ga_config()
    dependence_parameter = dict(
        dependence_cfg.get("dependence_parameter") or {}
    )
    shared_fraction = clamp(
        _f(dependence_parameter.get("value")),
        _f(dependence_parameter.get("lower_bound"), 0.0),
        _f(dependence_parameter.get("upper_bound"), 0.25),
    )
    max_goal_count = int(trunc_cfg.get("max_goal_count") or 15)
    max_assist_count = int(trunc_cfg.get("max_assist_count") or 15)
    normalization_tolerance = max(
        0.0, _f(trunc_cfg.get("normalization_tolerance"), 1e-9)
    )
    goal_points_value = int(GOAL_POINTS[element_type])
    assist_points_value = int(ASSIST_POINTS)

    core_pmf: dict[int, float] = {}
    p_goal = p_assist = p_both = p_attack = p_multiple = p_ga2 = p_ga3 = 0.0
    max_joint_truncated = 0.0
    max_save_truncated = 0.0
    evaluated_minute_atom_count = 0

    for atom in minute_atoms:
        atom_probability = float(atom.get("joint_probability") or 0.0)
        if atom_probability <= 0.0:
            continue
        minutes = max(0.0, float(atom.get("minutes") or 0.0))
        lg = max(0.0, goal_rate * minutes / 90.0)
        la = max(0.0, assist_rate * minutes / 90.0)
        ga_points, ga_events, ga_truncated = _joint_goal_assist_point_surface(
            lg,
            la,
            goal_points=goal_points_value,
            assist_points=assist_points_value,
            shared_fraction=shared_fraction,
            max_goal_count=max_goal_count,
            max_assist_count=max_assist_count,
            tolerance=normalization_tolerance,
        )
        evaluated_minute_atom_count += 1
        max_joint_truncated = max(max_joint_truncated, ga_truncated)
        p_goal += atom_probability * ga_events["p_goal"]
        p_assist += atom_probability * ga_events["p_assist"]
        p_both += atom_probability * ga_events["p_both"]
        p_attack += atom_probability * ga_events["p_attack"]
        p_multiple += atom_probability * ga_events["p_ge_2"]
        p_ga2 += atom_probability * ga_events["p_ge_2"]
        p_ga3 += atom_probability * ga_events["p_ge_3"]

        appearance_points = (
            0
            if minutes <= 0.0
            else int(APPEARANCE_POINTS_60_PLUS)
            if minutes >= 60.0
            else int(APPEARANCE_POINTS_UNDER_60)
        )
        conditional_pmf: dict[int, float] = {
            int(points) + appearance_points: float(probability)
            for points, probability in ga_points.items()
            if float(probability) > 0.0
        }

        cs_points = float(CLEAN_SHEET_POINTS.get(element_type, 0))
        cs_qualified = minutes >= 60.0 and cs_points > 0.0
        conditional_pmf = _apply_bernoulli_reward(
            conditional_pmf,
            clean_sheet_probability if cs_qualified else 0.0,
            cs_points,
        )

        dc_probability = 0.0
        if (
            minutes > 0.0
            and dc.get("eligible")
            and dc_threshold is not None
            and dc_points > 0.0
        ):
            dc_probability = _poisson_tail_at_least(
                int(dc_threshold), dc_rate * minutes / 90.0
            )
        conditional_pmf = _apply_bernoulli_reward(
            conditional_pmf, dc_probability, dc_points
        )

        if position == "GK" and minutes > 0.0:
            save_pmf, save_truncated = _save_reward_pmf(save_rate * minutes / 90.0)
            max_save_truncated = max(max_save_truncated, save_truncated)
            conditional_pmf = _convolve_integer_pmf(conditional_pmf, save_pmf)

        for points, probability in conditional_pmf.items():
            core_pmf[int(points)] = core_pmf.get(int(points), 0.0) + atom_probability * float(probability)

    sum_probability = sum(core_pmf.values())
    tolerance = max(0.0, _f(trunc_cfg.get("normalization_tolerance"), 1e-9))
    if sum_probability <= 0.0:
        core_pmf = {0: 1.0}
        sum_probability = 1.0
    if not math.isclose(sum_probability, 1.0, rel_tol=0.0, abs_tol=tolerance):
        core_pmf = {
            points: probability / sum_probability
            for points, probability in core_pmf.items()
        }
        sum_probability = sum(core_pmf.values())

    core_mean, core_variance = _pmf_moments(core_pmf)
    adjusted_expected_total = core_mean + max(0.0, float(bonus_residual_expectation))
    mean_delta = adjusted_expected_total - float(legacy_expected_total)

    tail_thresholds = [int(value) for value in tail_cfg.get("thresholds") or []]
    tails = {
        f"ge_{threshold}": clamp(
            sum(
                probability
                for points, probability in core_pmf.items()
                if int(points) >= threshold
            ),
            0.0,
            1.0,
        )
        for threshold in tail_thresholds
    }
    quantile_probabilities = [
        float(value) for value in quantile_cfg.get("probabilities") or []
    ]
    quantiles = {
        f"P{int(round(probability * 100))}": _discrete_quantile(
            core_pmf, probability
        )
        for probability in quantile_probabilities
    }
    blank_threshold = int(blank_cfg.get("threshold") or 2)
    p_blank = clamp(
        sum(
            probability
            for points, probability in core_pmf.items()
            if int(points) <= blank_threshold
        ),
        0.0,
        1.0,
    )
    core_pmf = {
        int(points): float(probability)
        for points, probability in core_pmf.items()
        if float(probability) > 0.0
    }
    probabilities = {
        str(points): round(core_pmf[points], 12)
        for points in sorted(core_pmf)
    }
    return {
        "event_probabilities": {
            "p_goal_return": round(clamp(p_goal, 0.0, 1.0), 9),
            "p_assist_return": round(clamp(p_assist, 0.0, 1.0), 9),
            "p_goal_and_assist": round(clamp(p_both, 0.0, 1.0), 9),
            "p_attacking_return": round(clamp(p_attack, 0.0, 1.0), 9),
            "p_no_attacking_return": round(clamp(1.0 - p_attack, 0.0, 1.0), 9),
            "p_multiple_attacking_returns": round(clamp(p_multiple, 0.0, 1.0), 9),
            "p_total_ga_ge_1": round(clamp(p_attack, 0.0, 1.0), 9),
            "p_total_ga_ge_2": round(clamp(p_ga2, 0.0, 1.0), 9),
            "p_total_ga_ge_3": round(clamp(p_ga3, 0.0, 1.0), 9),
        },
        "point_distribution": {
            "status": "READY_PARTIAL_BONUS_RESIDUAL",
            "model": dist_cfg.get("model"),
            "distribution_completeness": dist_cfg.get("distribution_completeness"),
            "support": sorted(int(points) for points in core_pmf),
            "probabilities": probabilities,
            "sum_probability": round(sum(core_pmf.values()), 12),
            "expected_points": round(core_mean, 9),
            "variance": round(core_variance, 9),
            "std": round(math.sqrt(max(0.0, core_variance)), 9),
            "quantiles": quantiles,
            "quantile_semantics": quantile_cfg.get("semantics"),
            "blank_threshold": blank_threshold,
            "blank_definition": blank_cfg.get("definition"),
            "p_fpl_blank": round(p_blank, 9),
            "tails": {key: round(value, 9) for key, value in tails.items()},
            "p_haul_10_plus": (
                round(tails.get("ge_10"), 9)
                if tails.get("ge_10") is not None
                else None
            ),
            "bonus_residual_expectation": round(
                max(0.0, float(bonus_residual_expectation)), 9
            ),
            "adjusted_expected_total": round(adjusted_expected_total, 9),
            "bonus_incorporation": "EXPECTATION_ONLY_NOT_STOCHASTIC",
            "tail_probability_scope": "CORE_STOCHASTIC_POINTS_EXCLUDES_BONUS_RESIDUAL",
            "blank_probability_scope": "CORE_STOCHASTIC_POINTS_EXCLUDES_BONUS_RESIDUAL",
            "truncation": {
                "max_goal_count": int(trunc_cfg.get("max_goal_count") or 15),
                "max_assist_count": int(trunc_cfg.get("max_assist_count") or 15),
                "max_save_count": int(trunc_cfg.get("max_save_count") or 30),
                "max_joint_truncated_probability_mass": round(max_joint_truncated, 12),
                "max_save_truncated_probability_mass": round(max_save_truncated, 12),
                "renormalized": True,
            },
            "provenance": {
                "minutes": "P1.1 FINITE_STATE_MINUTES_MIXTURE + bounded quadrature",
                "goal_assist": dependence_cfg.get("model"),
                "clean_sheet": "fixture clean-sheet probability conditional on >=60 minutes",
                "defcon": "P1.3 Poisson threshold process",
                "saves": "P1.3 Poisson save-count interval reward",
                "bonus": "P1.3 residual expectation only",
            },
        },
        "dependence": {
            "goal_assist_model": dependence_cfg.get("model"),
            "dependence_parameter_id": dependence_parameter.get("parameter_id"),
            "dependence_parameter": dependence_parameter.get("value"),
            "parameter_version": dependence_parameter.get("version"),
            "calibration_status": dependence_parameter.get("calibration_status"),
            "calibration_sample_size": int(
                dependence_parameter.get("calibration_sample_size") or 0
            ),
            "calibration_confidence": dependence_parameter.get(
                "calibration_confidence"
            ),
            "assumptions": {
                "goal_assist_jointly_modelled": True,
                "silent_independence": False,
                "other_event_blocks_conditionally_factorized_given_minutes": True,
                "shared_minutes_dependence": True,
                "cross_player_correlation": "NOT_MODELLED_YET",
                "cross_fixture_correlation": "NOT_MODELLED_YET",
            },
            "computational_form": "LATENT_BIVARIATE_POISSON_ANALYTIC_RETURNS_PLUS_COMPOUND_POISSON_PGF_RECURSION",
            "evaluated_minute_atom_count": evaluated_minute_atom_count,
            "max_joint_truncated_probability_mass": round(
                max_joint_truncated, 12
            ),
            "minute_atom_diagnostics_materialized": False,
            "mathematical_model_unchanged_by_performance_optimization": True,
        },
        "reconciliation": {
            "core_pmf_expected_points": round(core_mean, 9),
            "bonus_residual_expectation": round(
                max(0.0, float(bonus_residual_expectation)), 9
            ),
            "pmf_plus_bonus_expected_total": round(adjusted_expected_total, 9),
            "legacy_expected_total": round(float(legacy_expected_total), 9),
            "mean_delta": round(mean_delta, 12),
            "mean_tolerance": _f(
                trunc_cfg.get("mean_reconciliation_tolerance"), 0.0005
            ),
            "core_pmf_variance": round(core_variance, 9),
            "legacy_moment_variance_before_joint_dependence": round(
                max(0.0, float(legacy_moment_variance)), 9
            ),
            "variance_delta_due_joint_dependence_and_truncation": round(
                core_variance - max(0.0, float(legacy_moment_variance)), 9
            ),
            "published_variance_source": "CORE_POINT_PMF",
            "variance_reconciled_to_published": True,
            "bonus_variance_modelled": False,
        },
        "parameter_uncertainty": dict(
            load_event_config().get("parameter_uncertainty") or {}
        ),
    }

def project_player_fixture(
    player: Mapping[str, Any],
    minutes_projection: Mapping[str, Any],
    matchup: Mapping[str, Any],
    *,
    home: bool,
    rates: Mapping[str, Any],
    league_baseline: Mapping[str, Any] | None = None,
    calibration_summary: Mapping[str, Any] | None = None,
    model_evidence_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Posterior predictive fixture projection from state/event uncertainty."""
    element_type = int(player.get("element_type") or 4)
    position = str(
        player.get("position")
        or ELEMENT_TYPE_TO_POSITION.get(element_type)
        or "FWD"
    )
    states = _finite_states(minutes_projection)
    joint = _joint_support(minutes_projection)
    fixture = _fixture_context(matchup, home, league_baseline)
    attack_multiplier = fixture["fixture_attack_multiplier"]
    cs_prob = fixture["clean_sheet_probability"]

    goal_rate = max(
        0.0, _f((rates.get("goal") or {}).get("posterior_rate90"))
    ) * attack_multiplier
    assist_rate = max(
        0.0, _f((rates.get("assist") or {}).get("posterior_rate90"))
    ) * attack_multiplier
    bonus_rate = max(
        0.0, _f((rates.get("bonus") or {}).get("posterior_rate90"))
    )
    save_rate = max(
        0.0, _f((rates.get("saves") or {}).get("posterior_rate90"))
    )
    dc = dict(rates.get("defcon") or {})
    dc_rate = max(0.0, _f(dc.get("posterior_count_rate90")))
    dc_threshold = dc.get("threshold")
    dc_points = min(
        max(0.0, _f(dc.get("points"))),
        float(DC_POINTS_CAP_PER_MATCH),
    )

    component_names = (
        "appearance",
        "goals",
        "assists",
        "clean_sheet",
        "defensive_contribution",
        "saves",
        "bonus",
    )
    component_mean = {name: 0.0 for name in component_names}
    component_second = {name: 0.0 for name in component_names}
    total_mean = 0.0
    total_second = 0.0
    goal_count_mean = goal_count_second = goal_p1 = 0.0
    assist_count_mean = assist_count_second = assist_p1 = 0.0
    defcon_p = 0.0
    save_count_mean = 0.0
    cs_points_probability = 0.0
    per_state: dict[str, dict[str, float]] = {
        row["state"]: {
            "probability": row["probability"],
            "goal_mean": 0.0,
            "goal_p1": 0.0,
            "assist_mean": 0.0,
            "assist_p1": 0.0,
            "defcon_p": 0.0,
            "save_mean": 0.0,
            "cs_qualifying_probability": 0.0,
        }
        for row in states
    }

    for atom in joint:
        jp = atom["joint_probability"]
        sp = atom["state_probability"]
        within = atom["within_state_probability"]
        minutes = atom["minutes"]
        lg = goal_rate * minutes / 90.0
        la = assist_rate * minutes / 90.0
        appearance_points = (
            0.0
            if minutes <= 0.0
            else float(APPEARANCE_POINTS_60_PLUS)
            if minutes >= 60.0
            else float(APPEARANCE_POINTS_UNDER_60)
        )
        goal_mean_points = GOAL_POINTS[element_type] * lg
        goal_var_points = GOAL_POINTS[element_type] ** 2 * lg
        assist_mean_points = ASSIST_POINTS * la
        assist_var_points = ASSIST_POINTS ** 2 * la

        cs_points = float(CLEAN_SHEET_POINTS.get(element_type, 0))
        cs_qualified = minutes >= 60.0 and cs_points > 0.0
        cs_mean_points = cs_points * cs_prob if cs_qualified else 0.0
        cs_var_points = (
            cs_points * cs_points * cs_prob * (1.0 - cs_prob)
            if cs_qualified
            else 0.0
        )
        if cs_qualified:
            cs_points_probability += jp * cs_prob

        dc_prob = 0.0
        dc_mean_points = dc_var_points = 0.0
        if (
            minutes > 0.0
            and dc.get("eligible")
            and dc_threshold is not None
            and dc_points > 0.0
        ):
            dc_prob = _poisson_tail_at_least(
                int(dc_threshold), dc_rate * minutes / 90.0
            )
            dc_mean_points = dc_points * dc_prob
            dc_var_points = (
                dc_points * dc_points * dc_prob * (1.0 - dc_prob)
            )

        save_lambda = (
            save_rate * minutes / 90.0 if position == "GK" and minutes > 0.0 else 0.0
        )
        save_mean_points, save_var_points = _poisson_reward_moments(save_lambda)
        bonus_mean_points = bonus_rate * minutes / 90.0

        conditional = {
            "appearance": (appearance_points, 0.0),
            "goals": (goal_mean_points, goal_var_points),
            "assists": (assist_mean_points, assist_var_points),
            "clean_sheet": (cs_mean_points, cs_var_points),
            "defensive_contribution": (dc_mean_points, dc_var_points),
            "saves": (save_mean_points, save_var_points),
            "bonus": (bonus_mean_points, 0.0),
        }
        conditional_total_mean = sum(v[0] for v in conditional.values())
        conditional_total_var = sum(v[1] for v in conditional.values())
        total_mean += jp * conditional_total_mean
        total_second += jp * (
            conditional_total_var + conditional_total_mean * conditional_total_mean
        )
        for name, (mean_points, var_points) in conditional.items():
            component_mean[name] += jp * mean_points
            component_second[name] += jp * (
                var_points + mean_points * mean_points
            )

        goal_count_mean += jp * lg
        goal_count_second += jp * (lg + lg * lg)
        goal_p1 += jp * (1.0 - math.exp(-lg))
        assist_count_mean += jp * la
        assist_count_second += jp * (la + la * la)
        assist_p1 += jp * (1.0 - math.exp(-la))
        defcon_p += jp * dc_prob
        save_count_mean += jp * save_lambda

        state_row = per_state[atom["state"]]
        if sp > 0.0:
            state_row["goal_mean"] += within * lg
            state_row["goal_p1"] += within * (1.0 - math.exp(-lg))
            state_row["assist_mean"] += within * la
            state_row["assist_p1"] += within * (1.0 - math.exp(-la))
            state_row["defcon_p"] += within * dc_prob
            state_row["save_mean"] += within * save_lambda
            state_row["cs_qualifying_probability"] += (
                within * cs_prob if cs_qualified else 0.0
            )

    legacy_moment_variance = max(
        0.0, total_second - total_mean * total_mean
    )
    predictive_surface = _build_joint_predictive_surface(
        joint,
        element_type=element_type,
        position=position,
        goal_rate=goal_rate,
        assist_rate=assist_rate,
        clean_sheet_probability=cs_prob,
        dc=dc,
        dc_rate=dc_rate,
        dc_threshold=dc_threshold,
        dc_points=dc_points,
        save_rate=save_rate,
        bonus_residual_expectation=component_mean["bonus"],
        legacy_expected_total=total_mean,
        legacy_moment_variance=legacy_moment_variance,
    )
    event_probabilities = predictive_surface["event_probabilities"]
    point_distribution = predictive_surface["point_distribution"]
    total_variance = float(point_distribution["variance"])
    component_variance = {
        name: max(0.0, component_second[name] - component_mean[name] ** 2)
        for name in component_names
    }
    expected_component_sum = sum(component_mean.values())
    component_variance_sum = sum(component_variance.values())
    state_rows = [
        {
            "state": name,
            **{k: round(v, 6) for k, v in row.items()},
        }
        for name, row in per_state.items()
    ]

    gw = int(matchup.get("event") or matchup.get("gw") or 0)
    team_h = matchup.get("team_h")
    team_a = matchup.get("team_a")
    kickoff = matchup.get("kickoff_time")
    fixture_id = (
        matchup.get("fixture")
        or matchup.get("id")
        or f"gw{gw}:{team_h}:{team_a}:{kickoff or 'unknown'}"
    )
    opponent = matchup.get("opponent")
    if opponent is None:
        opponent = team_a if home else team_h

    result = {
        "model": MODEL_ID,
        "model_owner": MODEL_OWNER,
        "identity": {
            "element": int(player.get("id") or player.get("element") or 0),
            "gw": gw,
            "fixture": fixture_id,
            "opponent": opponent,
            "home": bool(home),
        },
        "event": gw,
        "fixture": fixture_id,
        "kickoff_time": kickoff,
        "opponent": opponent,
        "home": bool(home),
        "team_expected_goals": round(fixture["team_expected_goals"], 6),
        "fixture_attack_multiplier": round(attack_multiplier, 6),
        "clean_sheet_probability": round(cs_prob, 6),
        "minutes": {
            "Pstart": round(
                next(r["probability"] for r in states if r["state"] == "START"),
                6,
            ),
            "Pregular_cameo": round(
                next(
                    r["probability"]
                    for r in states
                    if r["state"] == "REGULAR_CAMEO"
                ),
                6,
            ),
            "Plate_cameo": round(
                next(
                    r["probability"]
                    for r in states
                    if r["state"] == "LATE_CAMEO"
                ),
                6,
            ),
            "PDNP": round(
                next(
                    r["probability"]
                    for r in states
                    if r["state"] == "ZERO_MINUTES"
                ),
                6,
            ),
            "xMins": round(
                sum(
                    row["probability"] * row["minutes_mean"] for row in states
                ),
                6,
            ),
            "finite_state_distribution_reference": "P1.1:xmins_distribution",
            "quadrature": "BOUNDED_THREE_POINT_MOMENT_QUADRATURE_V1",
        },
        "events": {
            "goals": {
                "classification": DIRECT_EVENT_MODEL,
                "distribution": "STATE_CONDITIONAL_POISSON_MIXTURE",
                "posterior_rate90": round(
                    _f((rates.get("goal") or {}).get("posterior_rate90")), 6
                ),
                "fixture_adjusted_rate90": round(goal_rate, 6),
                "P_at_least_1": round(event_probabilities["p_goal_return"], 6),
                "expected_count": round(goal_count_mean, 6),
                "count_variance": round(
                    max(0.0, goal_count_second - goal_count_mean**2), 6
                ),
                "expected_fpl_points": round(component_mean["goals"], 6),
                "points_variance": round(component_variance["goals"], 6),
                "posterior": dict(rates.get("goal") or {}),
                "state_conditional": state_rows,
            },
            "assists": {
                "classification": DIRECT_EVENT_MODEL,
                "distribution": "STATE_CONDITIONAL_POISSON_MIXTURE",
                "posterior_rate90": round(
                    _f((rates.get("assist") or {}).get("posterior_rate90")), 6
                ),
                "fixture_adjusted_rate90": round(assist_rate, 6),
                "P_at_least_1": round(event_probabilities["p_assist_return"], 6),
                "expected_count": round(assist_count_mean, 6),
                "count_variance": round(
                    max(0.0, assist_count_second - assist_count_mean**2), 6
                ),
                "expected_fpl_points": round(component_mean["assists"], 6),
                "points_variance": round(component_variance["assists"], 6),
                "posterior": dict(rates.get("assist") or {}),
                "state_conditional": state_rows,
            },
            "clean_sheet": {
                "classification": DIRECT_EVENT_MODEL,
                "upstream_probability": round(cs_prob, 6),
                "points_if_qualified": float(CLEAN_SHEET_POINTS.get(element_type, 0)),
                "minimum_minutes": 60,
                "P_points_awarded": round(cs_points_probability, 6),
                "expected_fpl_points": round(component_mean["clean_sheet"], 6),
                "points_variance": round(component_variance["clean_sheet"], 6),
                "minutes_threshold_model": "FINITE_STATE_WITHIN_STATE_QUADRATURE",
            },
            "defcon": {
                "classification": DIRECT_EVENT_MODEL,
                "eligible": bool(dc.get("eligible")),
                "threshold": dc_threshold,
                "points": dc_points,
                "posterior_count_rate90": round(dc_rate, 6),
                "P_threshold": round(defcon_p, 6),
                "expected_fpl_points": round(
                    component_mean["defensive_contribution"], 6
                ),
                "points_variance": round(
                    component_variance["defensive_contribution"], 6
                ),
                "evidence_minutes": dc.get("evidence_minutes"),
                "sample_quality": dc.get("sample_quality"),
                "source": dc.get("source"),
            },
            "saves": {
                "classification": DIRECT_EVENT_MODEL,
                "eligible": position == "GK",
                "distribution": "STATE_CONDITIONAL_POISSON_COUNT_WITH_FPL_INTERVAL_REWARD",
                "posterior_rate90": round(save_rate, 6),
                "expected_count": round(save_count_mean, 6),
                "expected_fpl_points": round(component_mean["saves"], 6),
                "points_variance": round(component_variance["saves"], 6),
                "confidence": (rates.get("saves") or {}).get("confidence"),
            },
            "bonus": {
                "classification": RESIDUAL_EXPECTATION_COMPONENT,
                "posterior_rate90": round(bonus_rate, 6),
                "expected_fpl_points": round(component_mean["bonus"], 6),
                "points_variance_modelled": 0.0,
                "independent_stochastic_process": False,
                "reason": "bonus retained as expectation-only residual; goal/assist/CS-linked covariance is not independently sampled",
            },
            "appearance": {
                "classification": DIRECT_EVENT_MODEL,
                "expected_fpl_points": round(component_mean["appearance"], 6),
                "points_variance": round(component_variance["appearance"], 6),
            },
        },
        "event_probabilities": dict(event_probabilities),
        "point_distribution": dict(point_distribution),
        "dependence": predictive_surface["dependence"],
        "parameter_uncertainty": predictive_surface["parameter_uncertainty"],
        "aggregate": {
            "expected_fpl_points": round(total_mean, 6),
            "points_variance": round(total_variance, 6),
            "points_std": round(math.sqrt(total_variance), 6),
            "distribution_semantics": "FINITE_STATE_CONDITIONAL_CORE_POINT_PMF_V1",
            "distribution_completeness": point_distribution["distribution_completeness"],
            "canonical_gaussian": False,
            "quantiles": dict(point_distribution["quantiles"]),
            "p_fpl_blank": point_distribution["p_fpl_blank"],
            "blank_threshold": point_distribution["blank_threshold"],
            "tails": dict(point_distribution["tails"]),
        },
        "mean": round(total_mean, 3),
        "std": round(math.sqrt(total_variance), 3),
        "components": {
            "appearance": round(component_mean["appearance"], 3),
            "attack": round(
                component_mean["goals"] + component_mean["assists"], 3
            ),
            "clean_sheet": round(component_mean["clean_sheet"], 3),
            "saves": round(component_mean["saves"], 3),
            "defensive_contribution": round(
                component_mean["defensive_contribution"], 3
            ),
            "bonus": round(component_mean["bonus"], 3),
        },
        "reconciliation": {
            "expected_component_sum": round(expected_component_sum, 6),
            "expected_total": round(total_mean, 6),
            "mean_delta": round(total_mean - expected_component_sum, 12),
            "component_variance_sum": round(component_variance_sum, 6),
            "total_variance": round(total_variance, 6),
            "shared_minutes_interaction_variance": round(
                total_variance - component_variance_sum, 6
            ),
            "bonus_counted_once": True,
            "p1_3b": predictive_surface["reconciliation"],
        },
        "assumptions": {
            "poisson_goal_count": True,
            "poisson_assist_count": True,
            "poisson_defcon_count_threshold": bool(dc.get("eligible")),
            "poisson_save_count": position == "GK",
            "conditional_event_independence_given_state_and_minutes": "PARTIAL_BLOCK_FACTORISATION_AFTER_JOINT_GOAL_ASSIST",
            "shared_minutes_mixture_creates_component_dependence": True,
            "goal_assist_dependence": predictive_surface["dependence"]["goal_assist_model"],
            "goal_assist_dependence_parameter": predictive_surface["dependence"]["dependence_parameter"],
            "goal_assist_dependence_calibration_status": predictive_surface["dependence"]["calibration_status"],
            "goal_assist_silent_independence": False,
            "cross_player_correlation": "NOT_MODELLED_YET",
            "cross_fixture_correlation": "NOT_MODELLED_YET",
            "parameter_uncertainty_propagation": "PARTIAL",
            "point_distribution_completeness": point_distribution["distribution_completeness"],
            "p1_4_capability_claimed": False,
            "p1_6_tactical_scorer_applied": False,
            "p1_7_started": False,
            "package_optimizer_started": False,
            "mini_league_overlay_started": False,
            "monte_carlo_applied": False,
        },
        "calibration_hook": _calibration_hook(calibration_summary),
        "governance": {
            "v12_native_event_owner": True,
            "legacy_projection_components_are_migration_oracle_only": True,
            "raw_v6_payload_persisted": False,
            "automatic_parameter_retuning": False,
            "methodology_weights_20_25_30_25_unchanged": True,
        },
    }
    return _attach_model_evidence(result, model_evidence_binding)


def aggregate_gameweek(
    fixtures: list[Mapping[str, Any]],
    *,
    gw: int,
) -> dict[str, Any]:
    """Aggregate fixture moments without inventing cross-fixture tail dependence."""
    mean = sum(
        _f(
            (row.get("aggregate") or {}).get("expected_fpl_points"),
            _f(row.get("mean")),
        )
        for row in fixtures
    )
    variance = sum(
        _f(
            (row.get("aggregate") or {}).get("points_variance"),
            _f(row.get("std")) ** 2,
        )
        for row in fixtures
    )
    no_clean_sheet = 1.0
    for row in fixtures:
        no_clean_sheet *= 1.0 - clamp(
            _f(row.get("clean_sheet_probability")), 0.0, 1.0
        )

    single_fixture_distribution = None
    single_fixture_events = None
    if len(fixtures) == 1:
        single_fixture_distribution = dict(
            fixtures[0].get("point_distribution") or {}
        )
        single_fixture_events = dict(
            fixtures[0].get("event_probabilities") or {}
        )

    return {
        "gw": int(gw),
        "mean": round(mean, 3),
        "std": round(math.sqrt(max(0.0, variance)), 3),
        "points_variance": round(max(0.0, variance), 6),
        "clean_sheet_probability": round(1.0 - no_clean_sheet, 4)
        if fixtures
        else 0.0,
        "event_probabilities": single_fixture_events,
        "point_distribution": single_fixture_distribution,
        "distribution_aggregation_status": (
            "EXACT_SINGLE_FIXTURE"
            if len(fixtures) == 1 and single_fixture_distribution
            else "PARTIAL_CROSS_FIXTURE_DEPENDENCE_NOT_MODELLED"
            if len(fixtures) > 1
            else "NO_FIXTURE"
        ),
        "tail_aggregation_status": (
            "AVAILABLE_SINGLE_FIXTURE"
            if len(fixtures) == 1 and single_fixture_distribution
            else "PARTIAL_NOT_AGGREGATED_WITHOUT_CROSS_FIXTURE_DEPENDENCE"
        ),
        "return_probability_aggregation_status": (
            "AVAILABLE_SINGLE_FIXTURE"
            if len(fixtures) == 1 and single_fixture_events
            else "PARTIAL_NOT_AGGREGATED_WITHOUT_CROSS_FIXTURE_DEPENDENCE"
        ),
        "fixtures": [dict(row) for row in fixtures],
        "dependency_assumption": "ZERO_CROSS_FIXTURE_COVARIANCE_NOT_MODELLED_YET",
        "monte_carlo_applied": False,
    }
