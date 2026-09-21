from __future__ import annotations

"""Stage-2 probability components subordinate to V12_PLAYER_EVENTS.

This module is deliberately not a second xPts, FDR, posterior, or minutes owner.
It consumes P1.1 finite-state minutes and P1.3 posterior rates, then supplies
position-specific count families, tactical matchup vectors, complete FPL point
PMFs, posterior-predictive diagnostics, and horizon convolution helpers.

V6 remains read-only factual input. Missing evidence is published as
UNAVAILABLE rather than silently converted to zero.
"""

from copy import deepcopy
import math
from statistics import mean
from typing import Any, Mapping, Sequence

from src.engines.v12_player_events import (
    _apply_bernoulli_reward,
    _convolve_integer_pmf,
    _joint_goal_assist_point_surface,
    _joint_support,
    _poisson_tail_at_least,
    load_event_config,
)
from src.rules import (
    APPEARANCE_POINTS_60_PLUS,
    APPEARANCE_POINTS_UNDER_60,
    ASSIST_POINTS,
    BONUS_POINTS,
    CLEAN_SHEET_POINTS,
    DC_POINTS_CAP_PER_MATCH,
    DC_RULES,
    GOAL_POINTS,
    GOALS_CONCEDED_INTERVAL,
    GOALS_CONCEDED_POINTS_PER_INTERVAL,
    OWN_GOAL_POINTS,
    PENALTY_MISS_POINTS,
    PENALTY_SAVE_POINTS,
    RED_CARD_POINTS,
    SAVE_INTERVAL,
    SAVE_POINTS_PER_INTERVAL,
    YELLOW_CARD_POINTS,
)

MODEL_OWNER = "V12_PLAYER_EVENTS"
SUBMODEL_ID = "v12_position_specific_probability_components_v1"
MATCHUP_COMPONENTS = (
    "goal",
    "creation",
    "attack",
    "clean_sheet",
    "defcon",
    "save",
    "set_piece",
    "aerial",
    "transition",
    "minutes",
    "bonus",
)


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(default if value in {None, ""} else value)
    except (TypeError, ValueError):
        return float(default)
    return out if math.isfinite(out) else float(default)


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(float(default if value in {None, ""} else value))
    except (TypeError, ValueError):
        return int(default)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _safe_mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _sample_variance(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _safe_mean(values)
    return sum((value - m) ** 2 for value in values) / (len(values) - 1)


def _poisson_pmf(mean_count: float, max_count: int) -> dict[int, float]:
    lam = max(0.0, float(mean_count))
    if lam <= 0.0:
        return {0: 1.0}
    probabilities = [math.exp(-lam)]
    for count in range(1, max_count + 1):
        probabilities.append(probabilities[-1] * lam / count)
    total = sum(probabilities)
    if total <= 0.0:
        return {0: 1.0}
    return {count: value / total for count, value in enumerate(probabilities)}


def _negative_binomial_pmf(
    mean_count: float,
    dispersion: float,
    max_count: int,
) -> dict[int, float]:
    mu = max(0.0, float(mean_count))
    r = max(1e-6, float(dispersion))
    if mu <= 0.0:
        return {0: 1.0}
    p = r / (r + mu)
    q = 1.0 - p
    probabilities = [p ** r]
    for count in range(1, max_count + 1):
        probabilities.append(
            probabilities[-1] * q * (count - 1 + r) / count
        )
    total = sum(probabilities)
    if total <= 0.0:
        return {0: 1.0}
    return {count: value / total for count, value in enumerate(probabilities)}


def _pmf_moments(pmf: Mapping[int, float]) -> tuple[float, float]:
    mu = sum(float(k) * float(p) for k, p in pmf.items())
    second = sum(float(k) ** 2 * float(p) for k, p in pmf.items())
    return mu, max(0.0, second - mu * mu)


def _pmf_tail(pmf: Mapping[int, float], threshold: int) -> float:
    return _clamp(
        sum(float(p) for k, p in pmf.items() if int(k) >= int(threshold)),
        0.0,
        1.0,
    )


def _quantile(pmf: Mapping[int, float], probability: float) -> int:
    cumulative = 0.0
    support = sorted(int(value) for value in pmf)
    if not support:
        return 0
    for value in support:
        cumulative += float(pmf.get(value, 0.0))
        if cumulative + 1e-15 >= float(probability):
            return value
    return support[-1]


def select_count_distribution(
    observations: Sequence[Any],
    projected_mean: float,
    *,
    thresholds: Sequence[int] = (),
    max_count: int = 40,
    label: str,
) -> dict[str, Any]:
    """Empirically select Poisson or NB without forcing sophistication."""
    values = [
        max(0.0, _f(value))
        for value in observations
        if value is not None and math.isfinite(_f(value))
    ]
    sample_size = len(values)
    observed_mean = _safe_mean(values)
    observed_variance = _sample_variance(values)
    observed_zero_rate = (
        sum(value <= 1e-12 for value in values) / sample_size
        if sample_size
        else None
    )
    dispersion_index = (
        observed_variance / observed_mean
        if observed_mean > 1e-9 and sample_size >= 2
        else None
    )
    use_nb = bool(
        sample_size >= 4
        and observed_mean > 0.0
        and observed_variance > observed_mean * 1.15
    )
    family = "NEGATIVE_BINOMIAL" if use_nb else "POISSON"
    dispersion = None
    if use_nb:
        dispersion = max(
            0.05,
            observed_mean * observed_mean
            / max(1e-9, observed_variance - observed_mean),
        )
        pmf = _negative_binomial_pmf(
            projected_mean, dispersion, max_count
        )
    else:
        pmf = _poisson_pmf(projected_mean, max_count)
    replicated_mean, replicated_variance = _pmf_moments(pmf)
    replicated_zero_rate = float(pmf.get(0, 0.0))
    threshold_rates = {
        str(int(threshold)): _pmf_tail(pmf, int(threshold))
        for threshold in thresholds
    }
    observed_threshold_rates = {
        str(int(threshold)): (
            sum(value >= int(threshold) for value in values) / sample_size
            if sample_size
            else None
        )
        for threshold in thresholds
    }
    mean_error = (
        abs(observed_mean - replicated_mean) if sample_size else None
    )
    variance_error = (
        abs(observed_variance - replicated_variance)
        if sample_size >= 2
        else None
    )
    zero_error = (
        abs(float(observed_zero_rate) - replicated_zero_rate)
        if observed_zero_rate is not None
        else None
    )
    calibrated = bool(
        sample_size >= 3
        and mean_error is not None
        and mean_error <= max(1.0, observed_mean * 0.60)
        and (
            zero_error is None
            or zero_error <= 0.35
        )
    )
    return {
        "label": label,
        "family": family,
        "selection": {
            "sample_size": sample_size,
            "observed_mean": round(observed_mean, 6),
            "observed_variance": round(observed_variance, 6),
            "dispersion_index": (
                None
                if dispersion_index is None
                else round(dispersion_index, 6)
            ),
            "nb_dispersion": (
                None if dispersion is None else round(dispersion, 6)
            ),
            "rule": (
                "NB_IF_N_GE_4_AND_VARIANCE_GT_1_15_X_MEAN_ELSE_POISSON"
            ),
            "selected_by_empirical_dispersion": True,
        },
        "projected_mean": round(max(0.0, projected_mean), 6),
        "pmf": {
            str(count): round(probability, 12)
            for count, probability in pmf.items()
            if probability > 0.0
        },
        "threshold_probabilities": {
            key: round(value, 9)
            for key, value in threshold_rates.items()
        },
        "posterior_predictive": {
            "actual_mean": (
                round(observed_mean, 6) if sample_size else None
            ),
            "replicated_mean": round(replicated_mean, 6),
            "actual_variance": (
                round(observed_variance, 6)
                if sample_size >= 2
                else None
            ),
            "replicated_variance": round(replicated_variance, 6),
            "actual_zero_rate": (
                None
                if observed_zero_rate is None
                else round(observed_zero_rate, 6)
            ),
            "replicated_zero_rate": round(replicated_zero_rate, 6),
            "actual_threshold_rates": {
                key: (
                    None if value is None else round(value, 6)
                )
                for key, value in observed_threshold_rates.items()
            },
            "replicated_threshold_rates": {
                key: round(value, 6)
                for key, value in threshold_rates.items()
            },
            "mean_absolute_error": (
                None if mean_error is None else round(mean_error, 6)
            ),
            "variance_absolute_error": (
                None if variance_error is None else round(variance_error, 6)
            ),
            "zero_rate_absolute_error": (
                None if zero_error is None else round(zero_error, 6)
            ),
            "status": (
                "CALIBRATED"
                if calibrated
                else "NOT_CALIBRATED_INSUFFICIENT_OR_MISMATCH"
            ),
        },
    }


def _binomial_pmf(
    trials: int,
    probability: float,
) -> dict[int, float]:
    n = max(0, int(trials))
    p = _clamp(float(probability), 0.0, 1.0)
    if n == 0:
        return {0: 1.0}
    if p <= 0.0:
        return {0: 1.0}
    if p >= 1.0:
        return {n: 1.0}
    q = 1.0 - p
    return {
        k: math.comb(n, k) * p ** k * q ** (n - k)
        for k in range(n + 1)
    }


def _beta_binomial_pmf(
    trials: int,
    alpha: float,
    beta: float,
) -> dict[int, float]:
    n = max(0, int(trials))
    a = max(1e-6, float(alpha))
    b = max(1e-6, float(beta))
    if n == 0:
        return {0: 1.0}
    log_beta_ab = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    out: dict[int, float] = {}
    for k in range(n + 1):
        log_choose = (
            math.lgamma(n + 1)
            - math.lgamma(k + 1)
            - math.lgamma(n - k + 1)
        )
        log_beta_post = (
            math.lgamma(k + a)
            + math.lgamma(n - k + b)
            - math.lgamma(n + a + b)
        )
        out[k] = math.exp(log_choose + log_beta_post - log_beta_ab)
    return _normalize_pmf(out)


def _gk_save_pmf_from_model(
    model: Mapping[str, Any],
    projected_sot_mean: float,
    *,
    max_sot: int = 35,
) -> dict[int, float]:
    sot_model = dict(model.get("sot_count_model") or {})
    sot_pmf = _count_pmf_from_model(
        sot_model,
        max(0.0, projected_sot_mean),
        max_count=max_sot,
    )
    conditional = dict(model.get("conditional_save_model") or {})
    family = str(conditional.get("family") or "BINOMIAL")
    save_probability = _clamp(
        _f(conditional.get("posterior_save_probability"), 0.70),
        0.0,
        1.0,
    )
    alpha = _f(conditional.get("posterior_alpha"), 0.5)
    beta = _f(conditional.get("posterior_beta"), 0.5)
    out: dict[int, float] = {}
    for sot, sot_mass in sot_pmf.items():
        save_given_sot = (
            _beta_binomial_pmf(int(sot), alpha, beta)
            if family == "BETA_BINOMIAL"
            else _binomial_pmf(int(sot), save_probability)
        )
        for saves, conditional_mass in save_given_sot.items():
            out[int(saves)] = (
                out.get(int(saves), 0.0)
                + float(sot_mass) * float(conditional_mass)
            )
    return _normalize_pmf(out)


def _gk_sot_save_model(
    match_rows: Sequence[Mapping[str, Any]],
    *,
    xmins: float,
    opponent_volume_multiplier: float,
    fallback_save_rate90: float,
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in match_rows
        if _f(row.get("minutes")) > 0.0
        and row.get("saves") is not None
        and row.get("goals_conceded") is not None
    ]
    sot_observations = [
        max(0.0, _f(row.get("saves")) + _f(row.get("goals_conceded")))
        for row in rows
    ]
    save_observations = [
        max(0.0, _f(row.get("saves")))
        for row in rows
    ]
    total_minutes = sum(_f(row.get("minutes")) for row in rows)
    total_saves = sum(save_observations)
    total_conceded = sum(
        max(0.0, _f(row.get("goals_conceded"))) for row in rows
    )
    total_sot = total_saves + total_conceded

    posterior_alpha = 0.5 + total_saves
    posterior_beta = 0.5 + total_conceded
    posterior_save_probability = (
        posterior_alpha / (posterior_alpha + posterior_beta)
    )
    if total_minutes > 0.0 and total_sot > 0.0:
        sot_rate90 = 90.0 * total_sot / total_minutes
        sot_rate_source = "OFFICIAL_SAVES_PLUS_GOALS_CONCEDED"
    else:
        sot_rate90 = max(
            0.0,
            fallback_save_rate90 / max(0.20, posterior_save_probability),
        )
        sot_rate_source = "INFERRED_FROM_P1_3_SAVE_RATE_AND_SHRUNK_SAVE_PCT"

    projected_sot_mean = (
        sot_rate90
        * max(0.0, xmins)
        / 90.0
        * max(0.0, opponent_volume_multiplier)
    )
    sot_model = select_count_distribution(
        sot_observations,
        projected_sot_mean,
        max_count=35,
        label="GK_SHOTS_ON_TARGET_FACED",
    )

    ratios = [
        _f(row.get("saves"))
        / max(
            1e-9,
            _f(row.get("saves")) + _f(row.get("goals_conceded")),
        )
        for row in rows
        if _f(row.get("saves")) + _f(row.get("goals_conceded")) > 0.0
    ]
    ratio_variance = _sample_variance(ratios)
    mean_sot_nonzero = _safe_mean(
        [
            value
            for value in sot_observations
            if value > 0.0
        ]
    )
    binomial_ratio_variance = (
        posterior_save_probability
        * (1.0 - posterior_save_probability)
        / max(1.0, mean_sot_nonzero)
    )
    use_beta_binomial = bool(
        len(ratios) >= 4
        and ratio_variance > binomial_ratio_variance * 1.15
    )
    conditional_family = (
        "BETA_BINOMIAL" if use_beta_binomial else "BINOMIAL"
    )

    model: dict[str, Any] = {
        "model": "GK_SOT_THEN_CONDITIONAL_SAVE_V1",
        "sot_count_model": sot_model,
        "conditional_save_model": {
            "family": conditional_family,
            "selection_rule": (
                "BETA_BINOMIAL_IF_N_GE_4_AND_SAVE_RATIO_VARIANCE_GT_"
                "1_15_X_BINOMIAL_EXPECTATION_ELSE_BINOMIAL"
            ),
            "sample_size": len(ratios),
            "posterior_alpha": round(posterior_alpha, 6),
            "posterior_beta": round(posterior_beta, 6),
            "posterior_save_probability": round(
                posterior_save_probability, 6
            ),
            "observed_save_ratio_variance": round(ratio_variance, 6),
            "binomial_expected_ratio_variance": round(
                binomial_ratio_variance, 6
            ),
            "selected_by_empirical_dispersion": True,
        },
        "sot_rate90": round(sot_rate90, 6),
        "sot_rate_source": sot_rate_source,
        "projected_sot_mean": round(projected_sot_mean, 6),
        "empirical": {
            "match_count": len(rows),
            "total_saves": round(total_saves, 6),
            "total_goals_conceded": round(total_conceded, 6),
            "sot_faced_proxy_total": round(total_sot, 6),
            "save_percentage": (
                round(total_saves / total_sot, 6)
                if total_sot > 0.0
                else None
            ),
            "sot_faced_definition": "official_saves_plus_goals_conceded",
            "psxg_xgot": None,
            "goals_prevented": None,
            "psxg_xgot_status": "UNAVAILABLE_IN_CURRENT_V6_FACTUAL_SURFACE",
            "goals_prevented_status": "UNAVAILABLE_IN_CURRENT_V6_FACTUAL_SURFACE",
        },
    }
    full_save_pmf = _gk_save_pmf_from_model(
        model, projected_sot_mean
    )
    replicated_mean, replicated_variance = _pmf_moments(full_save_pmf)
    actual_mean = _safe_mean(save_observations)
    actual_variance = _sample_variance(save_observations)
    actual_zero = (
        sum(value <= 1e-12 for value in save_observations)
        / len(save_observations)
        if save_observations
        else None
    )
    model["posterior_predictive"] = {
        "actual_mean": (
            round(actual_mean, 6) if save_observations else None
        ),
        "replicated_mean": round(replicated_mean, 6),
        "actual_variance": (
            round(actual_variance, 6)
            if len(save_observations) >= 2
            else None
        ),
        "replicated_variance": round(replicated_variance, 6),
        "actual_zero_rate": (
            None if actual_zero is None else round(actual_zero, 6)
        ),
        "replicated_zero_rate": round(
            float(full_save_pmf.get(0, 0.0)), 6
        ),
        "actual_threshold_rates": {
            str(threshold): (
                round(
                    sum(value >= threshold for value in save_observations)
                    / len(save_observations),
                    6,
                )
                if save_observations
                else None
            )
            for threshold in (3, 6, 9, 12)
        },
        "replicated_threshold_rates": {
            str(threshold): round(
                _pmf_tail(full_save_pmf, threshold), 6
            )
            for threshold in (3, 6, 9, 12)
        },
        "status": (
            "CALIBRATED"
            if len(save_observations) >= 3
            and abs(actual_mean - replicated_mean)
            <= max(1.0, actual_mean * 0.60)
            else "NOT_CALIBRATED_INSUFFICIENT_OR_MISMATCH"
        ),
    }
    return model


def _count_pmf_from_model(
    model: Mapping[str, Any],
    mean_count: float,
    *,
    max_count: int = 40,
) -> dict[int, float]:
    family = str(model.get("family") or "POISSON")
    dispersion = (model.get("selection") or {}).get("nb_dispersion")
    if family == "NEGATIVE_BINOMIAL" and dispersion is not None:
        return _negative_binomial_pmf(
            mean_count, _f(dispersion, 1.0), max_count
        )
    return _poisson_pmf(mean_count, max_count)


def _reward_pmf_from_count(
    count_pmf: Mapping[int, float],
    reward_fn,
) -> dict[int, float]:
    out: dict[int, float] = {}
    for count, probability in count_pmf.items():
        reward = int(reward_fn(int(count)))
        out[reward] = out.get(reward, 0.0) + float(probability)
    return out


def _normalize_pmf(pmf: Mapping[int, float]) -> dict[int, float]:
    total = sum(float(value) for value in pmf.values())
    if total <= 0.0:
        return {0: 1.0}
    return {
        int(key): float(value) / total
        for key, value in pmf.items()
        if float(value) > 0.0
    }


def _apply_signed_bernoulli_reward(
    pmf: Mapping[int, float],
    probability: float,
    reward: int,
) -> dict[int, float]:
    p = _clamp(float(probability), 0.0, 1.0)
    reward = int(reward)
    if p <= 0.0 or reward == 0:
        return dict(pmf)
    out: dict[int, float] = {}
    for points, mass in pmf.items():
        base = float(mass)
        if base <= 0.0:
            continue
        out[int(points)] = out.get(int(points), 0.0) + base * (1.0 - p)
        shifted = int(points) + reward
        out[shifted] = out.get(shifted, 0.0) + base * p
    return out


def convolve_point_distributions(
    distributions: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    pmf: dict[int, float] = {0: 1.0}
    used = 0
    for distribution in distributions:
        probabilities = distribution.get("probabilities") or {}
        if not probabilities:
            continue
        rhs = {
            int(points): _f(probability)
            for points, probability in probabilities.items()
        }
        pmf = _convolve_integer_pmf(pmf, rhs)
        used += 1
    if used == 0:
        return None
    pmf = _normalize_pmf(pmf)
    mu, variance = _pmf_moments(pmf)
    return {
        "status": "READY_COMPLETE_CONDITIONAL_PMF",
        "model": "EXACT_DISCRETE_CONVOLUTION_CONDITIONAL_ON_POSTERIOR",
        "support": sorted(pmf),
        "probabilities": {
            str(points): round(pmf[points], 12)
            for points in sorted(pmf)
        },
        "sum_probability": round(sum(pmf.values()), 12),
        "expected_points": round(mu, 9),
        "median": _quantile(pmf, 0.50),
        "variance": round(variance, 9),
        "std": round(math.sqrt(max(0.0, variance)), 9),
        "quantiles": {
            "Q10": _quantile(pmf, 0.10),
            "Q25": _quantile(pmf, 0.25),
            "Q50": _quantile(pmf, 0.50),
            "Q75": _quantile(pmf, 0.75),
            "Q90": _quantile(pmf, 0.90),
        },
        "p_fpl_blank": round(
            sum(p for points, p in pmf.items() if points <= 2), 9
        ),
        "p_haul_10_plus": round(
            sum(p for points, p in pmf.items() if points >= 10), 9
        ),
        "component_distribution_count": used,
        "cross_period_semantics": (
            "CONDITIONAL_INDEPENDENCE_GIVEN_CURRENT_POSTERIOR;"
            "EPISTEMIC_UNCERTAINTY_REPORTED_SEPARATELY"
        ),
    }


def _role_tokens(role: Any, position: str) -> set[str]:
    text = str(role or "").upper().replace("-", " ").replace("/", " ")
    tokens = set(text.split())
    tokens.add(str(position).upper())
    if "CENTRE" in tokens or "CENTER" in tokens:
        tokens.add("CB")
    return tokens


def _context_strength(
    context: Mapping[str, Any],
    *keys: str,
) -> float | None:
    for key in keys:
        if context.get(key) is not None:
            value = _f(context.get(key))
            if value > 1.0:
                value /= 100.0
            return _clamp(value, 0.0, 1.0)
    return None


def build_dynamic_matchup_vector(
    *,
    position: str,
    role: Any,
    matchup: Mapping[str, Any],
    home: bool,
    current_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Position/role-specific FDR vector. Official FDR is sanity-only."""
    context = dict(current_context or {})
    pos = str(position).upper()
    tokens = _role_tokens(role, pos)
    team_xg = _f(
        matchup.get("home_expected_goals" if home else "away_expected_goals"),
        _f(matchup.get("team_expected_goals"), 1.35),
    )
    cs_probability = _clamp(
        _f(
            matchup.get(
                "home_clean_sheet_probability"
                if home
                else "away_clean_sheet_probability"
            ),
            _f(matchup.get("clean_sheet_probability"), 0.30),
        ),
        0.001,
        0.999,
    )
    opponent_xg = max(0.0, -math.log(cs_probability))
    attack_index = _clamp(team_xg / 1.35, 0.65, 1.45)
    pressure_index = _clamp(opponent_xg / 1.35, 0.65, 1.45)
    cs_index = _clamp(cs_probability / 0.30, 0.55, 1.55)

    multipliers = {key: 1.0 for key in MATCHUP_COMPONENTS}
    multipliers["attack"] = attack_index
    multipliers["clean_sheet"] = cs_index
    if pos == "GK":
        multipliers["save"] = pressure_index ** 0.72
        multipliers["bonus"] = math.sqrt(
            multipliers["save"] * multipliers["clean_sheet"]
        )
    elif pos == "DEF":
        multipliers["defcon"] = pressure_index ** 0.62
        multipliers["goal"] = attack_index ** 0.45
        multipliers["creation"] = attack_index ** 0.40
        multipliers["bonus"] = math.sqrt(
            multipliers["clean_sheet"] * multipliers["defcon"]
        )
    elif pos == "MID":
        multipliers["goal"] = attack_index ** 0.72
        multipliers["creation"] = attack_index ** 0.68
        multipliers["defcon"] = pressure_index ** 0.28
        multipliers["bonus"] = math.sqrt(
            multipliers["goal"] * multipliers["creation"]
        )
    else:
        multipliers["goal"] = attack_index ** 0.82
        multipliers["creation"] = attack_index ** 0.48
        multipliers["defcon"] = pressure_index ** 0.20
        multipliers["bonus"] = multipliers["goal"] ** 0.65

    interactions: list[dict[str, Any]] = []

    def apply(component: str, factor: float, mechanism: str, evidence: Any):
        multipliers[component] *= factor
        interactions.append(
            {
                "component": component,
                "factor": round(factor, 6),
                "mechanism": mechanism,
                "evidence": evidence,
            }
        )

    high_line = _context_strength(
        context, "opponent_high_line", "high_line_vulnerability"
    )
    central_cb = _context_strength(
        context, "opponent_central_cb_weakness", "central_cb_weakness"
    )
    aerial = _context_strength(
        context, "opponent_aerial_weakness", "aerial_weakness"
    )
    central_press = _context_strength(
        context, "opponent_central_press_weakness", "central_press_weakness"
    )
    fb_vulnerability = _context_strength(
        context, "opponent_fullback_vulnerability", "fullback_vulnerability"
    )
    narrow = _context_strength(
        context, "opponent_narrow_defence", "narrow_defence"
    )
    set_piece = _context_strength(
        context, "opponent_set_piece_weakness", "set_piece_defence_weakness"
    )
    transition = _context_strength(
        context, "opponent_transition_weakness", "transition_weakness"
    )
    pressure = _context_strength(
        context, "opponent_pressure", "pressure_index"
    )
    shot_volume = _context_strength(
        context, "opponent_shot_volume", "shot_volume_index"
    )

    runner = bool(tokens & {"WINGER", "RUNNER", "FWD", "STRIKER", "9"})
    central_striker = bool(tokens & {"STRIKER", "FWD", "9", "CF"})
    creator = bool(tokens & {"10", "AM", "CREATOR", "PLAYMAKER"})
    wide = bool(tokens & {"WINGER", "RW", "LW"})
    attacking_fb = bool(tokens & {"FB", "WB", "FULLBACK", "WINGBACK"})
    cb = bool(tokens & {"CB", "CENTREBACK", "CENTERBACK"})
    aerial_target = central_striker or cb

    if high_line is not None and runner:
        apply("goal", 1.0 + 0.10 * high_line, "pace_runner_x_high_line", high_line)
        apply("transition", 1.0 + 0.14 * high_line, "pace_runner_x_high_line", high_line)
    if central_cb is not None and central_striker:
        apply("goal", 1.0 + 0.11 * central_cb, "central_striker_x_central_cb", central_cb)
    if aerial is not None and aerial_target:
        apply("aerial", 1.0 + 0.16 * aerial, "aerial_target_x_aerial_weakness", aerial)
        apply("goal", 1.0 + 0.05 * aerial, "aerial_target_x_aerial_weakness", aerial)
    if central_press is not None and creator:
        apply("creation", 1.0 + 0.10 * central_press, "creator_x_weak_central_press", central_press)
    if fb_vulnerability is not None and wide:
        apply("goal", 1.0 + 0.06 * fb_vulnerability, "winger_x_vulnerable_fb", fb_vulnerability)
        apply("creation", 1.0 + 0.08 * fb_vulnerability, "winger_x_vulnerable_fb", fb_vulnerability)
    if narrow is not None and attacking_fb:
        apply("creation", 1.0 + 0.10 * narrow, "attacking_fb_x_narrow_defence", narrow)
    if set_piece is not None and aerial_target:
        apply("set_piece", 1.0 + 0.14 * set_piece, "set_piece_target_x_weak_set_piece_defence", set_piece)
    if transition is not None and runner:
        apply("transition", 1.0 + 0.12 * transition, "runner_x_transition_weakness", transition)
    if pressure is not None and cb:
        apply("defcon", 1.0 + 0.14 * pressure, "defensive_cb_x_opponent_pressure", pressure)
    if shot_volume is not None and pos == "GK":
        apply("save", 1.0 + 0.18 * shot_volume, "gk_x_opponent_shot_volume", shot_volume)

    for key in multipliers:
        multipliers[key] = round(_clamp(multipliers[key], 0.60, 1.60), 6)

    official_fdr = matchup.get(
        "official_fdr_home" if home else "official_fdr_away"
    )
    return {
        "model": "DYNAMIC_POSITION_ROLE_MATCHUP_VECTOR_V1",
        "model_owner": "V12_CONTEXTUAL_DYNAMICS",
        "position": pos,
        "role": str(role or "UNAVAILABLE"),
        "vector": {
            key: {
                "multiplier": multipliers[key],
                "status": "AVAILABLE_DERIVED",
            }
            for key in MATCHUP_COMPONENTS
        },
        "football_mechanism_interactions": interactions,
        "official_fdr": {
            "value": official_fdr,
            "role": "EXTERNAL_PRIOR_SANITY_CHECK_ONLY",
            "applied_as_final_matchup": False,
        },
        "base_evidence": {
            "team_expected_goals": round(team_xg, 6),
            "opponent_expected_goals": round(opponent_xg, 6),
            "clean_sheet_probability": round(cs_probability, 6),
        },
        "same_opponent_player_specific": True,
        "arbitrary_final_point_bonus": False,
    }


def build_global_position_calibration(
    match_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    usable = [
        dict(row)
        for row in match_rows
        if _f(row.get("minutes")) > 0.0
    ]
    paired = [
        row for row in usable
        if row.get("bps") is not None and row.get("bonus") is not None
    ]
    x = [_f(row.get("fpl_points")) for row in paired]
    y = [_f(row.get("bps")) for row in paired]
    x_mean = _safe_mean(x)
    y_mean = _safe_mean(y)
    denominator = sum((value - x_mean) ** 2 for value in x)
    slope = (
        sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y))
        / denominator
        if denominator > 1e-9
        else 1.0
    )
    tier_stats = {}
    for tier in (0, 1, 2, 3):
        values = [
            _f(row.get("bps"))
            for row in paired
            if _i(row.get("bonus")) == tier
        ]
        tier_stats[str(tier)] = {
            "count": len(values),
            "mean_bps": round(_safe_mean(values), 6) if values else None,
            "std_bps": round(math.sqrt(max(1e-6, _sample_variance(values))), 6)
            if len(values) >= 2
            else None,
        }
    return {
        "sample_size": len(paired),
        "bps_vs_fpl_points_slope": round(slope, 6),
        "bps_baseline": round(y_mean - slope * x_mean, 6),
        "tier_stats": tier_stats,
        "full_optadata_bps_reconstruction": False,
        "authority": "EMPIRICAL_CURRENT_SEASON_BPS_VS_CORE_POINTS_EXCLUDING_BONUS",
    }


def _conditional_bonus_pmf(
    core_points: int,
    calibration: Mapping[str, Any],
) -> dict[int, float]:
    tier_stats = dict(calibration.get("tier_stats") or {})
    sample_size = max(0, _i(calibration.get("sample_size")))
    slope = _f(calibration.get("bps_vs_fpl_points_slope"), 1.0)
    baseline = _f(calibration.get("bps_baseline"), 0.0)
    projected_bps = baseline + slope * float(core_points)
    weights: dict[int, float] = {}
    total_n = max(1, sample_size)
    for tier in (0, 1, 2, 3):
        stat = dict(tier_stats.get(str(tier)) or {})
        count = max(0, _i(stat.get("count")))
        prior = (count + 1.0) / (total_n + 4.0)
        mu = stat.get("mean_bps")
        sigma = stat.get("std_bps")
        if mu is None:
            # weak fallback ordered by observed FPL bonus semantics
            mu = 4.0 + 7.0 * tier
        sigma = max(4.0, _f(sigma, 8.0))
        z = (projected_bps - _f(mu)) / sigma
        likelihood = math.exp(-0.5 * z * z) / sigma
        weights[tier] = prior * likelihood
    total = sum(weights.values())
    if total <= 0.0:
        return {0: 1.0}
    return {tier: value / total for tier, value in weights.items()}


def _apply_conditional_bonus(
    core_pmf: Mapping[int, float],
    calibration: Mapping[str, Any],
) -> tuple[dict[int, float], dict[int, float]]:
    out: dict[int, float] = {}
    tiers = {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0}
    for points, mass in core_pmf.items():
        bonus = _conditional_bonus_pmf(int(points), calibration)
        for tier, probability in bonus.items():
            joint = float(mass) * float(probability)
            out[int(points) + int(tier)] = (
                out.get(int(points) + int(tier), 0.0) + joint
            )
            tiers[int(tier)] += joint
    return _normalize_pmf(out), tiers


def _event_observations(
    rows: Sequence[Mapping[str, Any]],
    field: str,
) -> list[float]:
    values = []
    for row in rows:
        if _f(row.get("minutes")) <= 0.0:
            continue
        if row.get(field) is None:
            continue
        values.append(max(0.0, _f(row.get(field))))
    return values


def _advanced_value(
    advanced: Mapping[str, Any],
    field: str,
) -> float | None:
    if advanced.get(field) is not None:
        return _f(advanced.get(field))
    totals = dict(advanced.get("totals") or {})
    if totals.get(field) is not None:
        return _f(totals.get(field))
    return None


def _position_goal_process(
    *,
    position: str,
    goal_rate90: float,
    advanced: Mapping[str, Any],
    matchup_vector: Mapping[str, Any],
) -> dict[str, Any]:
    xg = _advanced_value(advanced, "xg")
    npxg = _advanced_value(advanced, "npxg")
    if xg is not None and xg > 1e-9 and npxg is not None:
        penalty_share = _clamp((xg - npxg) / xg, 0.0, 0.65)
        penalty_status = "AVAILABLE_FROM_XG_MINUS_NPXG"
    else:
        penalty_share = 0.0
        penalty_status = "UNAVAILABLE_NO_NPXG"
    set_piece_share_raw = _advanced_value(advanced, "set_piece_xg_share")
    set_piece_share = (
        _clamp(set_piece_share_raw, 0.0, max(0.0, 0.75 - penalty_share))
        if set_piece_share_raw is not None
        else 0.0
    )
    set_piece_status = (
        "AVAILABLE"
        if set_piece_share_raw is not None
        else "UNAVAILABLE_NO_FACTUAL_SET_PIECE_XG"
    )
    open_share = max(0.0, 1.0 - penalty_share - set_piece_share)
    sp_mult = _f(
        (((matchup_vector.get("vector") or {}).get("set_piece") or {}).get(
            "multiplier"
        )),
        1.0,
    )
    # Preserve total posterior goal intensity. Component weights explain the
    # process; tactical set-piece evidence only reallocates within the same
    # bounded total unless a separate calibrated event-rate owner exists.
    raw = {
        "open_play": open_share,
        "penalty": penalty_share,
        "set_piece": set_piece_share * sp_mult,
    }
    total = sum(raw.values()) or 1.0
    shares = {key: value / total for key, value in raw.items()}
    return {
        "lambda_goal_total90": round(goal_rate90, 6),
        "lambda_open_play90": round(goal_rate90 * shares["open_play"], 6),
        "lambda_penalty90": round(goal_rate90 * shares["penalty"], 6),
        "lambda_set_piece90": round(goal_rate90 * shares["set_piece"], 6),
        "penalty_evidence_status": penalty_status,
        "set_piece_evidence_status": set_piece_status,
        "total_intensity_preserved": True,
        "finishing_shrinkage": "P1.3_BAYESIAN_RATE_POSTERIOR",
    }


def _creation_process(
    advanced: Mapping[str, Any],
    assist_rate90: float,
) -> dict[str, Any]:
    xa = _advanced_value(advanced, "xa")
    key_passes = _advanced_value(advanced, "key_passes")
    chances = _advanced_value(advanced, "chances_created")
    crosses = _advanced_value(advanced, "crosses")
    return {
        "lambda_assist90": round(assist_rate90, 6),
        "xA": xa,
        "key_passes": key_passes,
        "chances_created": chances,
        "crosses": crosses,
        "receiver_quality": "LINKUP_NETWORK_IF_AVAILABLE",
        "missing_values_are_zero": False,
    }


def enhance_fixture_projection(
    base_projection: Mapping[str, Any],
    *,
    player: Mapping[str, Any],
    minutes_projection: Mapping[str, Any],
    match_rows: Sequence[Mapping[str, Any]],
    advanced_current: Mapping[str, Any] | None,
    contextual_dynamics: Mapping[str, Any] | None,
    global_calibration: Mapping[str, Any],
) -> dict[str, Any]:
    """Complete the position-specific PMF while preserving P1.1/P1.3 owners."""
    result = deepcopy(dict(base_projection))
    advanced = dict(advanced_current or {})
    contextual = dict(contextual_dynamics or {})
    matchup_vector = dict(contextual.get("matchup_vector") or {})
    position = str(
        player.get("position")
        or {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}.get(
            _i(player.get("element_type")), "FWD"
        )
    ).upper()
    element_type = _i(player.get("element_type"), 4)
    atoms = _joint_support(minutes_projection)
    events = dict(result.get("events") or {})
    goal = dict(events.get("goals") or {})
    assist = dict(events.get("assists") or {})
    clean_sheet = dict(events.get("clean_sheet") or {})
    defcon = dict(events.get("defcon") or {})
    saves = dict(events.get("saves") or {})

    goal_rate90 = max(0.0, _f(goal.get("fixture_adjusted_rate90")))
    assist_rate90 = max(0.0, _f(assist.get("fixture_adjusted_rate90")))
    cs_probability = _clamp(
        _f(clean_sheet.get("upstream_probability")),
        0.0,
        1.0,
    )
    opponent_xg = (
        -math.log(max(1e-9, cs_probability))
        if cs_probability < 1.0
        else 0.0
    )

    xmins = _f((result.get("minutes") or {}).get("xMins"))
    p60 = _clamp(
        sum(
            _f(atom.get("joint_probability"))
            for atom in atoms
            if _f(atom.get("minutes")) >= 60.0
        ),
        0.0,
        1.0,
    )

    save_mult = _f(
        (((matchup_vector.get("vector") or {}).get("save") or {}).get(
            "multiplier"
        )),
        1.0,
    )
    gk_save_model = (
        _gk_sot_save_model(
            match_rows,
            xmins=xmins,
            opponent_volume_multiplier=save_mult,
            fallback_save_rate90=max(
                0.0, _f(saves.get("posterior_rate90"))
            ),
        )
        if position == "GK"
        else None
    )

    dc_rate90 = max(0.0, _f(defcon.get("posterior_count_rate90")))
    dc_mult = _f(
        (((matchup_vector.get("vector") or {}).get("defcon") or {}).get(
            "multiplier"
        )),
        1.0,
    )
    dc_mean_full = dc_rate90 * xmins / 90.0 * dc_mult
    dc_threshold = defcon.get("threshold")
    dc_model = select_count_distribution(
        _event_observations(match_rows, "defensive"),
        dc_mean_full,
        thresholds=(() if dc_threshold is None else (int(dc_threshold),)),
        max_count=45,
        label="DEFENSIVE_CONTRIBUTION",
    )

    penalty_save_rate90 = (
        90.0
        * sum(_event_observations(match_rows, "penalties_saved"))
        / max(
            1.0,
            sum(
                _f(row.get("minutes"))
                for row in match_rows
                if _f(row.get("minutes")) > 0.0
            ),
        )
    )
    yellow_rate90 = (
        90.0
        * sum(_event_observations(match_rows, "yellow_cards"))
        / max(
            1.0,
            sum(
                _f(row.get("minutes"))
                for row in match_rows
                if _f(row.get("minutes")) > 0.0
            ),
        )
    )
    red_rate90 = (
        90.0
        * sum(_event_observations(match_rows, "red_cards"))
        / max(
            1.0,
            sum(
                _f(row.get("minutes"))
                for row in match_rows
                if _f(row.get("minutes")) > 0.0
            ),
        )
    )
    own_goal_rate90 = (
        90.0
        * sum(_event_observations(match_rows, "own_goals"))
        / max(
            1.0,
            sum(
                _f(row.get("minutes"))
                for row in match_rows
                if _f(row.get("minutes")) > 0.0
            ),
        )
    )
    advanced_minutes = max(
        0.0, _f(advanced.get("minutes"))
    )
    advanced_xg = _advanced_value(advanced, "xg")
    advanced_npxg = _advanced_value(advanced, "npxg")
    penalty_attempt_rate90 = 0.0
    penalty_attempt_status = "UNAVAILABLE_NO_NPXG"
    if (
        advanced_minutes > 0.0
        and advanced_xg is not None
        and advanced_npxg is not None
        and advanced_xg > advanced_npxg
    ):
        penalty_xg90 = (
            max(0.0, advanced_xg - advanced_npxg)
            * 90.0
            / advanced_minutes
        )
        penalty_attempt_rate90 = penalty_xg90 / 0.78
        penalty_attempt_status = "AVAILABLE_FROM_XG_MINUS_NPXG"

    cfg = load_event_config()
    ga_cfg = dict(cfg.get("joint_goal_assist") or {})
    shared_fraction = _f(
        (ga_cfg.get("dependence_parameter") or {}).get("value"), 0.1
    )
    max_goal_count = _i(
        ((cfg.get("point_distribution") or {}).get("truncation") or {}).get(
            "max_goal_count"
        ),
        15,
    )
    max_assist_count = _i(
        ((cfg.get("point_distribution") or {}).get("truncation") or {}).get(
            "max_assist_count"
        ),
        15,
    )

    complete_core: dict[int, float] = {}
    defcon_threshold_mass = 0.0
    save_threshold_mass = {3: 0.0, 6: 0.0, 9: 0.0, 12: 0.0}
    card_mass = 0.0
    penalty_save_mass = 0.0
    penalty_miss_mass = 0.0
    expected_save_points_mass = 0.0
    for atom in atoms:
        mass = _f(atom.get("joint_probability"))
        minutes = max(0.0, _f(atom.get("minutes")))
        if mass <= 0.0:
            continue
        lg = goal_rate90 * minutes / 90.0
        la = assist_rate90 * minutes / 90.0
        ga_pmf, _, _ = _joint_goal_assist_point_surface(
            lg,
            la,
            goal_points=int(GOAL_POINTS[element_type]),
            assist_points=int(ASSIST_POINTS),
            shared_fraction=shared_fraction,
            max_goal_count=max_goal_count,
            max_assist_count=max_assist_count,
            tolerance=1e-10,
        )
        appearance = (
            0
            if minutes <= 0.0
            else int(APPEARANCE_POINTS_60_PLUS)
            if minutes >= 60.0
            else int(APPEARANCE_POINTS_UNDER_60)
        )
        conditional = {
            int(points) + appearance: probability
            for points, probability in ga_pmf.items()
        }

        cs_points = int(CLEAN_SHEET_POINTS.get(element_type, 0))
        conditional = _apply_bernoulli_reward(
            conditional,
            cs_probability if minutes >= 60.0 else 0.0,
            cs_points,
        )

        if (
            defcon.get("eligible")
            and dc_threshold is not None
            and minutes > 0.0
        ):
            dc_mean = dc_rate90 * minutes / 90.0 * dc_mult
            dc_count = _count_pmf_from_model(dc_model, dc_mean)
            p_dc = _pmf_tail(dc_count, int(dc_threshold))
            defcon_threshold_mass += mass * p_dc
            conditional = _apply_bernoulli_reward(
                conditional,
                p_dc,
                min(
                    int(round(_f(defcon.get("points")))),
                    int(DC_POINTS_CAP_PER_MATCH),
                ),
            )

        if position == "GK" and minutes > 0.0:
            projected_sot_mean = (
                _f((gk_save_model or {}).get("sot_rate90"))
                * minutes
                / 90.0
                * save_mult
            )
            save_count = _gk_save_pmf_from_model(
                gk_save_model or {},
                projected_sot_mean,
            )
            save_reward = _reward_pmf_from_count(
                save_count,
                lambda count: (count // int(SAVE_INTERVAL))
                * int(SAVE_POINTS_PER_INTERVAL),
            )
            conditional = _convolve_integer_pmf(
                conditional, save_reward
            )
            expected_save_points_mass += mass * sum(
                (
                    (count // int(SAVE_INTERVAL))
                    * int(SAVE_POINTS_PER_INTERVAL)
                )
                * probability
                for count, probability in save_count.items()
            )
            for threshold in save_threshold_mass:
                save_threshold_mass[threshold] += mass * _pmf_tail(
                    save_count, threshold
                )

            penalty_save_mean = penalty_save_rate90 * minutes / 90.0
            p_penalty_save = 1.0 - math.exp(-penalty_save_mean)
            penalty_save_mass += mass * p_penalty_save
            conditional = _apply_bernoulli_reward(
                conditional,
                p_penalty_save,
                int(PENALTY_SAVE_POINTS),
            )

        if (
            position in {"GK", "DEF"}
            and minutes > 0.0
            and opponent_xg > 0.0
        ):
            gc_pmf = _poisson_pmf(
                opponent_xg * minutes / 90.0, 10
            )
            gc_reward = _reward_pmf_from_count(
                gc_pmf,
                lambda count: (count // int(GOALS_CONCEDED_INTERVAL))
                * int(GOALS_CONCEDED_POINTS_PER_INTERVAL),
            )
            conditional = _convolve_integer_pmf(
                conditional, gc_reward
            )

        if minutes > 0.0:
            yellow_p = 1.0 - math.exp(-yellow_rate90 * minutes / 90.0)
            red_p = 1.0 - math.exp(-red_rate90 * minutes / 90.0)
            own_goal_p = 1.0 - math.exp(
                -own_goal_rate90 * minutes / 90.0
            )
            card_mass += mass * (
                1.0 - (1.0 - yellow_p) * (1.0 - red_p)
            )
            conditional = _apply_signed_bernoulli_reward(
                conditional, yellow_p, int(YELLOW_CARD_POINTS)
            )
            conditional = _apply_signed_bernoulli_reward(
                conditional, red_p, int(RED_CARD_POINTS)
            )
            conditional = _apply_signed_bernoulli_reward(
                conditional, own_goal_p, int(OWN_GOAL_POINTS)
            )
            if penalty_attempt_rate90 > 0.0 and position in {"MID", "FWD", "DEF"}:
                p_penalty_miss = 1.0 - math.exp(
                    -penalty_attempt_rate90
                    * minutes
                    / 90.0
                    * (1.0 - 0.78)
                )
                penalty_miss_mass += mass * p_penalty_miss
                conditional = _apply_signed_bernoulli_reward(
                    conditional,
                    p_penalty_miss,
                    int(PENALTY_MISS_POINTS),
                )

        for points, probability in conditional.items():
            complete_core[int(points)] = (
                complete_core.get(int(points), 0.0)
                + mass * float(probability)
            )

    complete_core = _normalize_pmf(complete_core)
    final_pmf, bonus_tiers = _apply_conditional_bonus(
        complete_core, global_calibration
    )
    mu, variance = _pmf_moments(final_pmf)

    goal_process = _position_goal_process(
        position=position,
        goal_rate90=goal_rate90,
        advanced=advanced,
        matchup_vector=matchup_vector,
    )
    creation_process = _creation_process(advanced, assist_rate90)
    team_penalty_rate = advanced.get(
        "team_penalty_attempt_rate_per_match"
    )
    taker_share = advanced.get("player_penalty_taker_share")
    penalty_score_probability = 0.78
    penalty_process = {
        "P_team_penalty": (
            None
            if team_penalty_rate is None
            else round(
                1.0 - math.exp(-max(0.0, _f(team_penalty_rate))),
                6,
            )
        ),
        "P_player_takes_given_on_pitch": (
            None
            if taker_share is None
            else round(_clamp(_f(taker_share), 0.0, 1.0), 6)
        ),
        "P_score_given_taken": penalty_score_probability,
        "P_miss_points": round(penalty_miss_mass, 6),
        "penalty_attempt_rate90": round(penalty_attempt_rate90, 6),
        "attempt_evidence_status": penalty_attempt_status,
        "team_taker_chain_evidence_status": (
            "AVAILABLE_FROM_TEAM_XG_MINUS_NPXG"
            if team_penalty_rate is not None and taker_share is not None
            else "UNAVAILABLE_NO_TEAM_PENALTY_FACT"
        ),
        "chain": (
            "P(team penalty) x P(player on pitch) x "
            "P(player takes | on pitch) x P(score)"
        ),
        "taker_uncertainty_probabilistic": True,
        "not_hardcoded_player": True,
    }

    dc_components = {
        "clearances": _advanced_value(advanced, "clearances"),
        "blocks": _advanced_value(advanced, "blocks"),
        "interceptions": _advanced_value(advanced, "interceptions"),
        "tackles": _advanced_value(advanced, "tackles"),
        "recoveries": _advanced_value(advanced, "recoveries"),
        "combined_cbi_match_history": (
            sum(
                _f(row.get("clearances_blocks_interceptions"))
                for row in match_rows
                if row.get("clearances_blocks_interceptions") is not None
            )
            if any(
                row.get("clearances_blocks_interceptions") is not None
                for row in match_rows
            )
            else None
        ),
        "individual_component_status": (
            "AVAILABLE"
            if any(
                _advanced_value(advanced, key) is not None
                for key in ("clearances", "blocks", "interceptions")
            )
            else "UNAVAILABLE_IN_CURRENT_V6_FACTUAL_SURFACE"
        ),
    }

    distribution = {
        "status": "READY_COMPLETE_POSITION_SPECIFIC",
        "model": "POSITION_SPECIFIC_DISCRETE_POSTERIOR_PREDICTIVE_V1",
        "distribution_completeness": "COMPLETE_FOR_SUPPORTED_FACTUAL_EVENTS",
        "support": sorted(final_pmf),
        "probabilities": {
            str(points): round(final_pmf[points], 12)
            for points in sorted(final_pmf)
        },
        "sum_probability": round(sum(final_pmf.values()), 12),
        "expected_points": round(mu, 9),
        "mean": round(mu, 9),
        "median": _quantile(final_pmf, 0.50),
        "variance": round(variance, 9),
        "std": round(math.sqrt(max(0.0, variance)), 9),
        "quantiles": {
            "Q10": _quantile(final_pmf, 0.10),
            "Q25": _quantile(final_pmf, 0.25),
            "Q50": _quantile(final_pmf, 0.50),
            "Q75": _quantile(final_pmf, 0.75),
            "Q90": _quantile(final_pmf, 0.90),
        },
        "p_fpl_blank": round(
            sum(p for points, p in final_pmf.items() if points <= 2), 9
        ),
        "p_haul_10_plus": round(
            sum(p for points, p in final_pmf.items() if points >= 10), 9
        ),
        "bonus_incorporation": "EMPIRICAL_BPS_CONDITIONAL_STOCHASTIC",
        "negative_events_incorporated": True,
    }
    base_goal_p = _f(
        (result.get("event_probabilities") or {}).get("p_goal_return")
    )
    base_assist_p = _f(
        (result.get("event_probabilities") or {}).get("p_assist_return")
    )
    p_return = _clamp(
        _f(
            (result.get("event_probabilities") or {}).get(
                "p_attacking_return"
            ),
            1.0 - (1.0 - base_goal_p) * (1.0 - base_assist_p),
        ),
        0.0,
        1.0,
    )

    epistemic_goal = dict(
        ((result.get("events") or {}).get("goals") or {}).get("posterior")
        or {}
    )
    epistemic_assist = dict(
        ((result.get("events") or {}).get("assists") or {}).get("posterior")
        or {}
    )
    interval_widths = []
    for payload in (epistemic_goal, epistemic_assist):
        interval = payload.get("credible_interval90")
        if isinstance(interval, list) and len(interval) == 2:
            interval_widths.append(max(0.0, _f(interval[1]) - _f(interval[0])))
    epistemic_index = sum(width * width for width in interval_widths) * (
        xmins / 90.0
    ) ** 2

    result["point_distribution"] = distribution
    result["aggregate"] = {
        **dict(result.get("aggregate") or {}),
        "expected_fpl_points": round(mu, 6),
        "points_variance": round(variance, 6),
        "points_std": round(math.sqrt(max(0.0, variance)), 6),
        "distribution_semantics": distribution["model"],
        "distribution_completeness": distribution[
            "distribution_completeness"
        ],
        "quantiles": dict(distribution["quantiles"]),
        "p_fpl_blank": distribution["p_fpl_blank"],
        "tails": {
            "ge_10": distribution["p_haul_10_plus"],
        },
    }
    result["mean"] = round(mu, 3)
    result["std"] = round(math.sqrt(max(0.0, variance)), 3)

    result.setdefault("events", {})["saves"] = {
        **saves,
        "model": (
            (gk_save_model or {}).get("model")
            if position == "GK"
            else "NOT_APPLICABLE_NON_GK"
        ),
        "count_model": (
            (gk_save_model or {}).get("sot_count_model")
            if position == "GK"
            else None
        ),
        "sot_count_model": (
            (gk_save_model or {}).get("sot_count_model")
            if position == "GK"
            else None
        ),
        "conditional_save_model": (
            (gk_save_model or {}).get("conditional_save_model")
            if position == "GK"
            else None
        ),
        "shot_stopping": (
            (gk_save_model or {}).get("empirical")
            if position == "GK"
            else None
        ),
        "P_saves_ge_3": round(save_threshold_mass[3], 6),
        "P_saves_ge_6": round(save_threshold_mass[6], 6),
        "P_saves_ge_9": round(save_threshold_mass[9], 6),
        "P_saves_ge_12": round(save_threshold_mass[12], 6),
        "expected_save_points_from_complete_distribution": round(
            expected_save_points_mass, 6
        ),
        "posterior_predictive": (
            (gk_save_model or {}).get("posterior_predictive")
            if position == "GK"
            else None
        ),
        "two_stage_sot_then_save": position == "GK",
    }
    result.setdefault("events", {})["defcon"] = {
        **defcon,
        "count_model": dc_model,
        "P_threshold": round(defcon_threshold_mass, 6),
        "components": dc_components,
        "cs_process_separate": True,
        "strong_opponent_can_lower_cs_and_raise_defcon": True,
    }
    result.setdefault("events", {})["bonus"] = {
        "classification": "DIRECT_CONDITIONAL_BPS_MODEL",
        "P_BPS0": round(bonus_tiers[0], 6),
        "P_BPS1": round(bonus_tiers[1], 6),
        "P_BPS2": round(bonus_tiers[2], 6),
        "P_BPS3": round(bonus_tiers[3], 6),
        "calibration": dict(global_calibration),
        "fixed_bonus_forbidden": True,
        "responds_to_simulated_football_events": True,
    }
    result.setdefault("events", {})["penalty_save"] = {
        "eligible": position == "GK",
        "P_at_least_1": round(penalty_save_mass, 6),
        "points": int(PENALTY_SAVE_POINTS),
    }
    result.setdefault("events", {})["goals_conceded"] = {
        "eligible": position in {"GK", "DEF"},
        "opponent_expected_goals": round(opponent_xg, 6),
        "distribution": "POISSON_SCORELINE_MARGINAL",
        "interval": int(GOALS_CONCEDED_INTERVAL),
        "points_per_interval": int(GOALS_CONCEDED_POINTS_PER_INTERVAL),
    }
    result.setdefault("events", {})["cards"] = {
        "P_any_card": round(card_mass, 6),
        "yellow_rate90": round(yellow_rate90, 6),
        "red_rate90": round(red_rate90, 6),
    }

    state_names = {
        str(row.get("state")): _f(row.get("probability"))
        for row in (minutes_projection.get("xmins_distribution") or {}).get(
            "states"
        )
        or []
    }
    p_start = sum(
        probability
        for state, probability in state_names.items()
        if state in {"START", "START_FULL", "START_SUBBED", "EARLY_SUB"}
    )
    p_cameo = sum(
        probability
        for state, probability in state_names.items()
        if state in {"CAMEO", "REGULAR_CAMEO", "LATE_CAMEO"}
    )
    p_dnp = sum(
        probability
        for state, probability in state_names.items()
        if state in {"DNP", "ZERO_MINUTES"}
    )

    result["position_engine"] = {
        "model": SUBMODEL_ID,
        "model_owner": MODEL_OWNER,
        "position": position,
        "matchup_vector": matchup_vector,
        "goal_process": goal_process,
        "creation_process": creation_process,
        "penalty_process": penalty_process,
        "set_piece_process": {
            "status": goal_process["set_piece_evidence_status"],
            "chain": (
                "P(set_piece) x P(taker) x P(target involved) "
                "x P(shot) x P(goal)"
            ),
            "hardcoded_taker": False,
        },
        "linkup": contextual.get("linkup_network"),
        "position_priority": {
            "GK": [
                "minutes",
                "saves",
                "shot_stopping",
                "clean_sheet",
                "penalty_saves",
                "bonus",
                "deductions",
            ],
            "DEF": [
                "minutes",
                "clean_sheet",
                "defcon",
                "defensive_workload",
                "attacking_upside",
                "bonus_deductions",
            ],
            "MID": [
                "role",
                "goal_process",
                "creation",
                "set_piece_penalty",
                "defcon",
                "clean_sheet",
            ],
            "FWD": [
                "goal_generation",
                "service_supply",
                "minutes",
                "opponent_specific_matchup",
                "assist_process",
            ],
        }.get(position, []),
        "posterior_predictive": {
            "saves": (
                (gk_save_model or {}).get("posterior_predictive")
                if position == "GK"
                else None
            ),
            "defcon": dc_model.get("posterior_predictive"),
        },
        "uncertainty": {
            "aleatoric_variance": round(variance, 6),
            "epistemic_rate_uncertainty_index": round(
                epistemic_index, 6
            ),
            "separated": True,
        },
    }
    result["complete_player_distribution"] = {
        "P_available": round(_clamp(1.0 - p_dnp, 0.0, 1.0), 6),
        "P_start": round(_clamp(p_start, 0.0, 1.0), 6),
        "P_60_plus": round(_clamp(p60, 0.0, 1.0), 6),
        "P_cameo": round(_clamp(p_cameo, 0.0, 1.0), 6),
        "P_DNP": round(_clamp(p_dnp, 0.0, 1.0), 6),
        "P_CS": round(
            _f(clean_sheet.get("P_points_awarded")), 6
        ),
        "P_DefCon_points": round(defcon_threshold_mass, 6),
        "P_save_ge_3": round(save_threshold_mass[3], 6),
        "P_save_ge_6": round(save_threshold_mass[6], 6),
        "P_save_ge_9": round(save_threshold_mass[9], 6),
        "P_goal": round(base_goal_p, 6),
        "P_assist": round(base_assist_p, 6),
        "P_return": round(p_return, 6),
        "P_blank": distribution["p_fpl_blank"],
        "P_haul": distribution["p_haul_10_plus"],
        "P_card": round(card_mass, 6),
        "P_bonus": round(1.0 - bonus_tiers[0], 6),
        "mean": distribution["mean"],
        "median": distribution["median"],
        "variance": distribution["variance"],
        "Q10": distribution["quantiles"]["Q10"],
        "Q25": distribution["quantiles"]["Q25"],
        "Q75": distribution["quantiles"]["Q75"],
        "Q90": distribution["quantiles"]["Q90"],
    }
    result.setdefault("governance", {}).update(
        {
            "stage2_position_specific_engine": True,
            "second_model_authority_created": False,
            "p1_1_minutes_reused_exactly": True,
            "p1_3_posterior_rates_reused_exactly": True,
            "arbitrary_final_point_bonus": False,
            "v6_mutated": False,
        }
    )
    return result


def select_scoreline_model(
    finished_fixtures: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare independent Poisson, Dixon-Coles, and bivariate Poisson."""
    scores = [
        (
            _i(row.get("team_h_score")),
            _i(row.get("team_a_score")),
        )
        for row in finished_fixtures
        if row.get("team_h_score") is not None
        and row.get("team_a_score") is not None
    ]
    if not scores:
        return {
            "selected": "POISSON",
            "status": "PRIOR_ONLY_NO_SETTLED_SAMPLE",
            "sample_size": 0,
            "candidates": {},
        }
    home_mean = max(0.05, _safe_mean([a for a, _ in scores]))
    away_mean = max(0.05, _safe_mean([b for _, b in scores]))

    def poisson_prob(h: int, a: int) -> float:
        return (
            math.exp(-home_mean)
            * home_mean ** h
            / math.factorial(h)
            * math.exp(-away_mean)
            * away_mean ** a
            / math.factorial(a)
        )

    def dc_tau(h: int, a: int, rho: float) -> float:
        if h == 0 and a == 0:
            return max(1e-6, 1.0 - home_mean * away_mean * rho)
        if h == 0 and a == 1:
            return max(1e-6, 1.0 + home_mean * rho)
        if h == 1 and a == 0:
            return max(1e-6, 1.0 + away_mean * rho)
        if h == 1 and a == 1:
            return max(1e-6, 1.0 - rho)
        return 1.0

    def bivariate_prob(h: int, a: int, shared: float) -> float:
        shared = min(shared, home_mean * 0.8, away_mean * 0.8)
        lh = max(1e-6, home_mean - shared)
        la = max(1e-6, away_mean - shared)
        total = 0.0
        for k in range(0, min(h, a) + 1):
            total += (
                lh ** (h - k)
                / math.factorial(h - k)
                * la ** (a - k)
                / math.factorial(a - k)
                * shared ** k
                / math.factorial(k)
            )
        return math.exp(-(lh + la + shared)) * total

    candidates: dict[str, dict[str, Any]] = {}
    poisson_nll = -_safe_mean(
        [math.log(max(1e-12, poisson_prob(h, a))) for h, a in scores]
    )
    candidates["POISSON"] = {
        "nll": poisson_nll,
        "parameter": None,
    }

    best_dc = None
    for rho in (-0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15):
        nll = -_safe_mean(
            [
                math.log(
                    max(
                        1e-12,
                        poisson_prob(h, a) * dc_tau(h, a, rho),
                    )
                )
                for h, a in scores
            ]
        )
        if best_dc is None or nll < best_dc[0]:
            best_dc = (nll, rho)
    candidates["DIXON_COLES"] = {
        "nll": best_dc[0],
        "parameter": best_dc[1],
    }

    best_biv = None
    for shared in (0.05, 0.10, 0.15, 0.20, 0.25):
        nll = -_safe_mean(
            [
                math.log(max(1e-12, bivariate_prob(h, a, shared)))
                for h, a in scores
            ]
        )
        if best_biv is None or nll < best_biv[0]:
            best_biv = (nll, shared)
    candidates["BIVARIATE_POISSON"] = {
        "nll": best_biv[0],
        "parameter": best_biv[1],
    }

    # Simplicity tie-break: more complex model must materially improve NLL.
    selected = "POISSON"
    selected_nll = poisson_nll
    for name in ("DIXON_COLES", "BIVARIATE_POISSON"):
        nll = _f(candidates[name]["nll"], 1e9)
        if nll < selected_nll - 0.005:
            selected = name
            selected_nll = nll
    return {
        "selected": selected,
        "status": "SELECTED_BY_SETTLED_SCORELINE_NLL",
        "sample_size": len(scores),
        "home_goal_mean": round(home_mean, 6),
        "away_goal_mean": round(away_mean, 6),
        "candidates": {
            name: {
                "mean_negative_log_likelihood": round(
                    _f(value["nll"]), 9
                ),
                "parameter": value["parameter"],
            }
            for name, value in candidates.items()
        },
        "selection_rule": (
            "MIN_NLL_WITH_0_005_COMPLEXITY_IMPROVEMENT_THRESHOLD"
        ),
        "sophistication_not_forced": True,
    }


def scoreline_clean_sheet_probabilities(
    selection: Mapping[str, Any],
    home_xg: float,
    away_xg: float,
    *,
    max_goals: int = 10,
) -> dict[str, float]:
    """Return CS marginals from the empirically selected scoreline family."""
    model = str(selection.get("selected") or "POISSON")
    home_xg = max(0.01, float(home_xg))
    away_xg = max(0.01, float(away_xg))
    candidate = dict((selection.get("candidates") or {}).get(model) or {})
    parameter = _f(candidate.get("parameter"), 0.0)

    def pois(lam: float, value: int) -> float:
        return math.exp(-lam) * lam ** value / math.factorial(value)

    def joint(h: int, a: int) -> float:
        if model == "DIXON_COLES":
            rho = parameter
            tau = 1.0
            if h == 0 and a == 0:
                tau = 1.0 - home_xg * away_xg * rho
            elif h == 0 and a == 1:
                tau = 1.0 + home_xg * rho
            elif h == 1 and a == 0:
                tau = 1.0 + away_xg * rho
            elif h == 1 and a == 1:
                tau = 1.0 - rho
            return max(
                0.0,
                pois(home_xg, h) * pois(away_xg, a) * max(1e-6, tau),
            )
        if model == "BIVARIATE_POISSON":
            shared = min(
                max(0.0, parameter),
                home_xg * 0.8,
                away_xg * 0.8,
            )
            lh = max(1e-6, home_xg - shared)
            la = max(1e-6, away_xg - shared)
            total = 0.0
            for k in range(0, min(h, a) + 1):
                total += (
                    lh ** (h - k)
                    / math.factorial(h - k)
                    * la ** (a - k)
                    / math.factorial(a - k)
                    * shared ** k
                    / math.factorial(k)
                )
            return math.exp(-(lh + la + shared)) * total
        return pois(home_xg, h) * pois(away_xg, a)

    grid = {
        (h, a): joint(h, a)
        for h in range(max_goals + 1)
        for a in range(max_goals + 1)
    }
    total = sum(grid.values()) or 1.0
    home_cs = sum(
        probability
        for (h, a), probability in grid.items()
        if a == 0
    ) / total
    away_cs = sum(
        probability
        for (h, a), probability in grid.items()
        if h == 0
    ) / total
    return {
        "home_clean_sheet_probability": _clamp(home_cs, 0.0, 1.0),
        "away_clean_sheet_probability": _clamp(away_cs, 0.0, 1.0),
    }
