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
MODEL_ID = "v12_player_events_posterior_predictive_v1"
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

    total_variance = max(0.0, total_second - total_mean * total_mean)
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
                "P_at_least_1": round(goal_p1, 6),
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
                "P_at_least_1": round(assist_p1, 6),
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
        "aggregate": {
            "expected_fpl_points": round(total_mean, 6),
            "points_variance": round(total_variance, 6),
            "points_std": round(math.sqrt(total_variance), 6),
            "distribution_semantics": "FINITE_STATE_EVENT_MIXTURE_MOMENTS",
            "canonical_gaussian": False,
            "quantiles": None,
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
        },
        "assumptions": {
            "poisson_goal_count": True,
            "poisson_assist_count": True,
            "poisson_defcon_count_threshold": bool(dc.get("eligible")),
            "poisson_save_count": position == "GK",
            "conditional_event_independence_given_state_and_minutes": True,
            "shared_minutes_mixture_creates_component_dependence": True,
            "goal_assist_dependence": "NOT_MODELLED_YET",
            "cross_player_correlation": "NOT_MODELLED_YET",
            "cross_fixture_correlation": "NOT_MODELLED_YET",
            "p1_4_capability_claimed": False,
            "p1_6_tactical_scorer_applied": False,
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
    """Aggregate separate fixture moments under explicit zero cross-fixture covariance."""
    mean = sum(_f((row.get("aggregate") or {}).get("expected_fpl_points"), _f(row.get("mean"))) for row in fixtures)
    variance = sum(_f((row.get("aggregate") or {}).get("points_variance"), _f(row.get("std")) ** 2) for row in fixtures)
    no_clean_sheet = 1.0
    for row in fixtures:
        no_clean_sheet *= 1.0 - clamp(_f(row.get("clean_sheet_probability")), 0.0, 1.0)
    return {
        "gw": int(gw),
        "mean": round(mean, 3),
        "std": round(math.sqrt(max(0.0, variance)), 3),
        "points_variance": round(max(0.0, variance), 6),
        "clean_sheet_probability": round(1.0 - no_clean_sheet, 4)
        if fixtures
        else 0.0,
        "fixtures": [dict(row) for row in fixtures],
        "dependency_assumption": "ZERO_CROSS_FIXTURE_COVARIANCE_NOT_MODELLED_YET",
    }
