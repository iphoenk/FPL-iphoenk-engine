from __future__ import annotations

import math
from typing import Any


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def poisson_tail_at_least(threshold: int, expected_count: float) -> float:
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


def poisson_rate_for_tail(threshold: int, target_probability: float) -> float:
    target = clamp(target_probability, 0.0, 0.999999)
    if target <= 0.0:
        return 0.0
    low, high = 0.0, max(1.0, float(threshold))
    while poisson_tail_at_least(threshold, high) < target and high < 256.0:
        high *= 2.0
    for _ in range(64):
        mid = (low + high) / 2.0
        if poisson_tail_at_least(threshold, mid) < target:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def _rule(rules: dict[str, Any], element_type: int) -> dict[str, Any]:
    rows = rules.get("defensive_contributions") if isinstance(rules.get("defensive_contributions"), dict) else {}
    raw = rows.get(str(element_type), rows.get(element_type)) if isinstance(rows, dict) else None
    return raw if isinstance(raw, dict) else {}


def _sample_quality(minutes: float) -> str:
    if minutes <= 0:
        return "NO_ADVANCED_EVIDENCE"
    if minutes < 270:
        return "LIMITED"
    if minutes < 450:
        return "DEVELOPING"
    return "ESTABLISHED"


def build_rate_bundle(
    *,
    element_type: int,
    prior_expected_points90: float,
    advanced: dict[str, Any] | None,
    rules: dict[str, Any],
    shrink_minutes: float = 450.0,
) -> dict[str, Any]:
    rule = _rule(rules, element_type)
    if not bool(rule.get("eligible")):
        return {
            "model": "poisson_threshold_shrunk_rate_v1",
            "eligible": False,
            "expected_points90": 0.0,
            "count_rate_per90": 0.0,
            "threshold": None,
            "points_on_threshold": 0.0,
            "source": "ineligible_position",
            "evidence_minutes": 0.0,
            "sample_quality": "INELIGIBLE",
        }

    threshold = int(rule.get("threshold") or 0)
    points = max(0.0, _f(rule.get("points")))
    prior_probability = clamp(_f(prior_expected_points90) / max(points, 1e-6), 0.0, 0.999999)
    prior_count90 = poisson_rate_for_tail(threshold, prior_probability)

    advanced = advanced if isinstance(advanced, dict) else {}
    evidence_minutes = max(0.0, _f(advanced.get("dc_evidence_minutes"), _f(advanced.get("minutes"))))
    observed_raw = advanced.get("dc_reconstructed_per90")
    has_observed = evidence_minutes > 0.0 and observed_raw is not None
    observed_count90 = max(0.0, _f(observed_raw, prior_count90))
    shrink = max(1.0, _f(shrink_minutes, 450.0))

    if has_observed:
        count90 = (observed_count90 * evidence_minutes + prior_count90 * shrink) / (evidence_minutes + shrink)
        source = "player_cbit_cbirt_shrunk_to_position_prior"
    else:
        count90 = prior_count90
        source = "position_prior_probability_calibrated"

    probability90 = poisson_tail_at_least(threshold, count90)
    return {
        "model": "poisson_threshold_shrunk_rate_v1",
        "eligible": True,
        "expected_points90": max(0.0, points * probability90),
        "count_rate_per90": max(0.0, count90),
        "threshold": threshold,
        "points_on_threshold": points,
        "threshold_probability_90": probability90,
        "source": source,
        "evidence_minutes": evidence_minutes,
        "sample_quality": advanced.get("dc_sample_quality") or _sample_quality(evidence_minutes),
    }


def project_fixture_points(bundle: dict[str, Any], expected_minutes: float, appearance_probability: float) -> dict[str, float]:
    if not bool(bundle.get("eligible")) or bundle.get("threshold") is None or appearance_probability <= 0.0:
        return {"points": 0.0, "conditional_minutes": 0.0, "threshold_probability_if_appears": 0.0}
    p_appearance = clamp(_f(appearance_probability), 0.0, 1.0)
    conditional_minutes = min(90.0, max(0.0, _f(expected_minutes)) / max(p_appearance, 1e-6))
    expected_count = _f(bundle.get("count_rate_per90")) * conditional_minutes / 90.0
    threshold_probability = poisson_tail_at_least(int(bundle["threshold"]), expected_count)
    points = p_appearance * _f(bundle.get("points_on_threshold")) * threshold_probability
    return {
        "points": max(0.0, points),
        "conditional_minutes": conditional_minutes,
        "threshold_probability_if_appears": threshold_probability,
    }
