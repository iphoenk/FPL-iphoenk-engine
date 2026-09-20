from __future__ import annotations

"""Bounded V12 trajectory, opponent-matchup and teammate-dependency features.

This module is a derived methodology layer only. It consumes factual match rows
supplied by V6/report evidence and returns bounded modifiers for the existing
V12 posterior event engine. It is not a factual provider or prediction engine.
"""

import math
from typing import Any, Mapping, Sequence

MODEL_OWNER = "V12_TRAJECTORY_MATCHUP_LINKUP"
MODEL_VERSION = "v12-trajectory-matchup-linkup-v1"


def _f(v: Any, d: float = 0.0) -> float:
    try:
        x = float(d if v is None else v)
        return x if math.isfinite(x) else float(d)
    except (TypeError, ValueError):
        return float(d)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def recency_weights(n: int, *, half_life_matches: float = 3.0) -> list[float]:
    """Old evidence remains non-zero; newest observation receives weight 1."""
    if n <= 0:
        return []
    h = max(1.0, float(half_life_matches))
    return [2.0 ** (-(n - 1 - i) / h) for i in range(n)]


def weighted_metric(rows: Sequence[Mapping[str, Any]], field: str, *, half_life_matches: float = 3.0) -> dict[str, Any]:
    valid = [(i, _f(r.get(field))) for i, r in enumerate(rows) if r.get(field) is not None]
    if not valid:
        return {"value": None, "sample_size": 0, "weight_sum": 0.0}
    all_w = recency_weights(len(rows), half_life_matches=half_life_matches)
    denom = sum(all_w[i] for i, _ in valid)
    value = sum(all_w[i] * v for i, v in valid) / max(1e-12, denom)
    return {"value": value, "sample_size": len(valid), "weight_sum": denom}


def bayesian_shrink(observed: float | None, baseline: float, effective_sample: float, *, prior_strength: float = 4.0) -> float:
    if observed is None:
        return baseline
    n = max(0.0, float(effective_sample))
    p = max(0.1, float(prior_strength))
    return (float(observed) * n + float(baseline) * p) / (n + p)


def build_trajectory(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Retain GW1-current match sequence and classify sustained process movement."""
    ordered = sorted((dict(r) for r in rows), key=lambda r: (int(r.get("gw") or 0), str(r.get("match_id") or "")))
    xgi = weighted_metric(ordered, "xgi90")
    if xgi["value"] is None:
        # Derive xGI/90 only when factual xG/xA/minutes exist.
        derived = []
        for r in ordered:
            m = _f(r.get("minutes"))
            if m > 0 and (r.get("xg") is not None or r.get("xa") is not None):
                rr = dict(r)
                rr["xgi90"] = 90.0 * (_f(r.get("xg")) + _f(r.get("xa"))) / m
                derived.append(rr)
        xgi = weighted_metric(derived, "xgi90")
    recent = ordered[-3:]
    older = ordered[:-3]
    recent_xgi = weighted_metric(recent, "xgi90")["value"]
    older_xgi = weighted_metric(older, "xgi90")["value"]
    if recent_xgi is None or older_xgi is None or len(recent) < 2:
        trend = "INSUFFICIENT_SAMPLE"
    else:
        ratio = (recent_xgi + 0.05) / (older_xgi + 0.05)
        trend = "IMPROVING" if ratio >= 1.25 else "DECLINING" if ratio <= 0.80 else "STABLE"
    roles = [str(r.get("role")) for r in ordered if r.get("role")]
    role_transition = len(roles) >= 2 and roles[-1] != roles[0] and roles[-2:] == [roles[-1], roles[-1]]
    return {
        "model_owner": MODEL_OWNER,
        "matches": ordered,
        "sample_size": len(ordered),
        "weighted_xgi90": xgi["value"],
        "trend": trend,
        "role_transition_sustained": role_transition,
        "latest_role": roles[-1] if roles else None,
        "governance": {"gw1_retained": True, "single_match_reset_forbidden": True},
    }


def _similarity(meeting: Mapping[str, Any], current: Mapping[str, Any]) -> float:
    keys = ("manager", "formation", "defensive_shape", "player_role")
    available = [(meeting.get(k), current.get(k)) for k in keys if meeting.get(k) is not None and current.get(k) is not None]
    if not available:
        return 0.35
    return sum(1.0 if a == b else 0.25 for a, b in available) / len(available)


def opponent_matchup(meetings: Sequence[Mapping[str, Any]], current_context: Mapping[str, Any], *, baseline_xgi90: float) -> dict[str, Any]:
    """Result and process evidence are separate; small H2H samples shrink hard."""
    rows = [dict(r) for r in meetings if _f(r.get("minutes")) > 0]
    if not rows:
        return {"classification": "INSUFFICIENT SAMPLE", "sample_size": 0, "modifier": 1.0, "confidence": "LOW"}
    sims = [_similarity(r, current_context) for r in rows]
    process_rates = []
    results = 0.0
    for r in rows:
        m = max(1.0, _f(r.get("minutes")))
        process_rates.append(90.0 * (_f(r.get("xg")) + _f(r.get("xa"))) / m)
        results += _f(r.get("goals")) + _f(r.get("assists"))
    sim = sum(sims) / len(sims)
    observed = sum(p * s for p, s in zip(process_rates, sims)) / max(1e-12, sum(sims))
    effective_n = len(rows) * sim
    posterior = bayesian_shrink(observed, baseline_xgi90, effective_n, prior_strength=5.0)
    ratio = posterior / max(0.05, baseline_xgi90)
    if effective_n < 1.25:
        classification = "INSUFFICIENT SAMPLE"
    elif ratio >= 1.15:
        classification = "SUPPORTIVE"
    elif ratio <= 0.85:
        classification = "ADVERSE"
    else:
        classification = "NEUTRAL"
    return {
        "classification": classification,
        "sample_size": len(rows),
        "effective_sample": effective_n,
        "tactical_similarity": sim,
        "result_evidence": {"returns": results},
        "process_evidence": {"observed_xgi90": observed, "posterior_xgi90": posterior},
        "modifier": _clamp(ratio, 0.80, 1.20),
        "confidence": "HIGH" if effective_n >= 4 else "MEDIUM" if effective_n >= 2 else "LOW",
        "governance": {"raw_h2h_result_is_authority": False, "sample_size_shrinkage": True},
    }


def dependency_edge(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Directional evidence-derived link. Correlation-only rows stay weak."""
    shared = max(0.0, _f(evidence.get("shared_minutes")))
    direct = max(0.0, _f(evidence.get("direct_chances_created")))
    xa_xg = max(0.0, _f(evidence.get("xa_to_xg")))
    progression = max(0.0, _f(evidence.get("progressive_connections")))
    tactical = _clamp(_f(evidence.get("tactical_complementarity"), 0.5), 0.0, 1.0)
    delta = _f(evidence.get("with_without_xgi90_delta"))
    process_signal = min(1.0, (direct + xa_xg + 0.25 * progression) / 6.0)
    sample_conf = shared / (shared + 360.0)
    confidence = _clamp(sample_conf * (0.65 * process_signal + 0.35 * tactical), 0.0, 1.0)
    # No direct/process evidence => co-return correlation cannot create dependency.
    if direct + xa_xg + progression <= 0:
        confidence *= 0.20
    effect = _clamp(delta * confidence, -0.35, 0.35)
    return {
        "direction": evidence.get("direction", "A_TO_B"),
        "relationship_type": evidence.get("relationship_type", "ATTACKING"),
        "shared_minutes": shared,
        "strength": abs(effect),
        "signed_effect_xgi90": effect,
        "confidence": confidence,
        "sample_size": evidence.get("sample_size"),
        "tactical_relevance": tactical,
        "governance": {"correlation_alone_sufficient": False, "named_player_rule": False},
    }


def marginalize_teammate(base_rate: float, edge: Mapping[str, Any], p_start: float) -> dict[str, float]:
    """P(B)=P(A starts)P(B|A starts)+P(A not)P(B|A not)."""
    p = _clamp(float(p_start), 0.0, 1.0)
    effect = _f(edge.get("signed_effect_xgi90"))
    present = max(0.0, base_rate + effect * (1.0 - p))
    absent = max(0.0, base_rate - effect * p)
    marginal = p * present + (1.0 - p) * absent
    return {"with_linked_starter": present, "without_linked_starter": absent, "marginal_rate": marginal, "linked_p_start": p}


def combine_bounded_modifiers(matchup_modifier: float, dependency_rate: float, baseline_rate: float) -> float:
    dep = dependency_rate / max(0.05, baseline_rate)
    return _clamp(float(matchup_modifier) * dep, 0.70, 1.30)
