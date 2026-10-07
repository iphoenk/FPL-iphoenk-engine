from __future__ import annotations

"""Canonical captain frontier and contextual C/VC reconciliation.

This module does not create a second football model, Monte Carlo engine, or
arbitrary weighted CaptainScore.  It consumes the existing P1.3B one-GW point
PMFs plus P1.7 legality/start evidence, derives distribution profiles and
pairwise outcome comparisons, and allows P1.8 mini-league context to resolve
only genuinely non-dominated CLOSE football decisions.

Cross-player PMFs are compared under an explicit conditional-independence
approximation because player-level joint PMFs are not currently published by
P1.3B.  Candidate-specific relative-points MC is never fabricated from EO.
"""

from math import isfinite
from typing import Any, Mapping, Sequence


EPS = 1e-12
MODEL_OWNER = "V12_CAPTAIN_FRONTIER_RECONCILER"
MODEL_ID = "v12_captain_frontier_v2"


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _i(value: Any) -> int | None:
    try:
        out = int(value)
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


def _pmf(distribution: Mapping[str, Any] | None) -> dict[float, float] | None:
    raw = dict(distribution or {}).get("probabilities") or {}
    if not isinstance(raw, Mapping) or not raw:
        return None
    out: dict[float, float] = {}
    for points, probability in raw.items():
        x = _f(points)
        p = _f(probability)
        if x is None or p is None or p < 0.0:
            return None
        if p > 0.0:
            out[x] = out.get(x, 0.0) + p
    total = sum(out.values())
    if total <= 0.0:
        return None
    return {points: mass / total for points, mass in out.items()}


def _mean(pmf: Mapping[float, float]) -> float:
    return sum(points * probability for points, probability in pmf.items())


def _quantile(pmf: Mapping[float, float], q: float) -> float:
    target = min(1.0, max(0.0, float(q)))
    cumulative = 0.0
    last = 0.0
    for points, probability in sorted(pmf.items()):
        last = float(points)
        cumulative += float(probability)
        if cumulative + EPS >= target:
            return last
    return last


def _prob_ge(pmf: Mapping[float, float], threshold: float) -> float:
    return sum(
        probability
        for points, probability in pmf.items()
        if points + EPS >= float(threshold)
    )


def _prob_le(pmf: Mapping[float, float], threshold: float) -> float:
    return sum(
        probability
        for points, probability in pmf.items()
        if points <= float(threshold) + EPS
    )


def _distribution_profile(candidate: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(candidate)
    distribution = dict(row.get("point_distribution") or {})
    pmf = _pmf(distribution)
    expected_points = _f(row.get("expected_points"))
    if expected_points is None:
        expected_points = _f(distribution.get("adjusted_expected_total"))
    if expected_points is None:
        expected_points = _f(distribution.get("expected_points"))
    if expected_points is None and pmf:
        expected_points = _mean(pmf)

    quantiles = dict(distribution.get("quantiles") or {})
    tails = dict(distribution.get("tails") or {})
    blank_threshold = _f(distribution.get("blank_threshold"))
    canonical_blank = _f(distribution.get("p_fpl_blank"))
    canonical_haul = _f(distribution.get("p_haul_10_plus"))
    if canonical_haul is None:
        canonical_haul = _f(tails.get("ge_10"))
    p_start = _f(row.get("p_start"))
    xmins = _f(row.get("xmins"))
    # DNP cannot be inferred as 1-P(start): cameo states exist and would be
    # misclassified as DNP.  Missing DNP evidence stays missing/fail-safe.
    p_dnp = _f(row.get("p_dnp"))

    profile = {
        "element_id": _i(row.get("element_id", row.get("element"))),
        "player": row.get("player") or row.get("name"),
        "position": row.get("position"),
        "team_id": row.get("team_id"),
        "expected_points": expected_points,
        "median": (
            _f(quantiles.get("Q50"))
            if _f(quantiles.get("Q50")) is not None
            else _quantile(pmf, 0.50)
            if pmf
            else _f(row.get("median"))
        ),
        "q75": (
            _f(quantiles.get("Q75"))
            if _f(quantiles.get("Q75")) is not None
            else _quantile(pmf, 0.75)
            if pmf
            else _f(row.get("q75"))
        ),
        "q90": (
            _f(quantiles.get("Q90"))
            if _f(quantiles.get("Q90")) is not None
            else _quantile(pmf, 0.90)
            if pmf
            else _f(row.get("q90"))
        ),
        "p_blank": (
            canonical_blank
            if canonical_blank is not None
            else _prob_le(pmf, blank_threshold)
            if pmf and blank_threshold is not None
            else _f(row.get("p_blank"))
        ),
        "blank_threshold": blank_threshold,
        "blank_semantics": distribution.get("blank_definition"),
        "p_ge_6": _prob_ge(pmf, 6.0) if pmf else None,
        "p_ge_8": (
            _f(tails.get("ge_8"))
            if _f(tails.get("ge_8")) is not None
            else _prob_ge(pmf, 8.0)
            if pmf else None
        ),
        "p_ge_10": (
            canonical_haul
            if canonical_haul is not None
            else _prob_ge(pmf, 10.0)
            if pmf else None
        ),
        "p_ge_12": (
            _f(tails.get("ge_12"))
            if _f(tails.get("ge_12")) is not None
            else _prob_ge(pmf, 12.0)
            if pmf else None
        ),
        "p_haul": (
            canonical_haul
            if canonical_haul is not None
            else _prob_ge(pmf, 10.0)
            if pmf
            else _f(row.get("p_haul"))
        ),
        "p_start": p_start,
        "xmins": xmins,
        "p_dnp": p_dnp,
        "pmf_available": pmf is not None,
        "distribution_status": distribution.get("status"),
        "distribution_completeness": distribution.get("distribution_completeness"),
        "bonus_residual_expectation_only": (
            str(distribution.get("distribution_completeness") or "").upper()
            == "PARTIAL_BONUS_RESIDUAL"
        ),
        "league_scope": dict(row.get("league_scope") or {}),
        "rivals_scope": dict(row.get("rivals_scope") or {}),
        "competitive_scope": dict(row.get("competitive_scope") or {}),
        "exposure_leverage_class": str(
            row.get("exposure_leverage_class") or "UNAVAILABLE"
        ),
        "_pmf": pmf,
    }
    required = (
        "expected_points",
        "median",
        "q90",
        "p_blank",
        "p_ge_10",
        "p_start",
        "xmins",
        "p_dnp",
    )
    profile["football_evidence_complete"] = bool(
        pmf is not None and all(profile.get(key) is not None for key in required)
    )
    return profile


def _no_worse(a: float | None, b: float | None, *, higher: bool) -> bool:
    if a is None or b is None:
        return False
    return a + EPS >= b if higher else a <= b + EPS


def _strictly_better(a: float | None, b: float | None, *, higher: bool) -> bool:
    if a is None or b is None:
        return False
    return a > b + EPS if higher else a + EPS < b


def _dominates(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """Pareto dominance across football-only distribution/security evidence."""
    beneficial = (
        "expected_points",
        "median",
        "q90",
        "p_ge_10",
        "p_start",
        "xmins",
    )
    harmful = ("p_blank", "p_dnp")
    if not (
        a.get("football_evidence_complete")
        and b.get("football_evidence_complete")
    ):
        return False
    all_no_worse = all(
        _no_worse(_f(a.get(key)), _f(b.get(key)), higher=True)
        for key in beneficial
    ) and all(
        _no_worse(_f(a.get(key)), _f(b.get(key)), higher=False)
        for key in harmful
        if a.get(key) is not None and b.get(key) is not None
    )
    any_better = any(
        _strictly_better(_f(a.get(key)), _f(b.get(key)), higher=True)
        for key in beneficial
    ) or any(
        _strictly_better(_f(a.get(key)), _f(b.get(key)), higher=False)
        for key in harmful
        if a.get(key) is not None and b.get(key) is not None
    )
    return bool(all_no_worse and any_better)


def _first_order_stochastic_dominates(
    a: Mapping[str, Any],
    b: Mapping[str, Any],
) -> bool:
    """True only when A's canonical core PMF FSD-dominates B's.

    This is deliberately stronger than a tiny mean edge.  No arbitrary
    probability or xPts threshold is introduced: every support threshold must
    be no worse and at least one must be strictly better.
    """
    pa = a.get("_pmf")
    pb = b.get("_pmf")
    if not isinstance(pa, Mapping) or not isinstance(pb, Mapping):
        return False
    support = sorted({float(x) for x in pa} | {float(x) for x in pb})
    strict = False
    for threshold in support:
        cdf_a = sum(
            float(probability)
            for points, probability in pa.items()
            if float(points) <= threshold + EPS
        )
        cdf_b = sum(
            float(probability)
            for points, probability in pb.items()
            if float(points) <= threshold + EPS
        )
        if cdf_a > cdf_b + EPS:
            return False
        if cdf_a + EPS < cdf_b:
            strict = True
    return strict


def _robust_clear_dominates(
    a: Mapping[str, Any],
    b: Mapping[str, Any],
) -> bool:
    """Distribution-first CLEAR rule with security guardrails."""
    if not (
        a.get("football_evidence_complete")
        and b.get("football_evidence_complete")
        and _first_order_stochastic_dominates(a, b)
    ):
        return False
    return bool(
        _no_worse(_f(a.get("expected_points")), _f(b.get("expected_points")), higher=True)
        and _no_worse(_f(a.get("p_start")), _f(b.get("p_start")), higher=True)
        and _no_worse(_f(a.get("xmins")), _f(b.get("xmins")), higher=True)
        and _no_worse(_f(a.get("p_blank")), _f(b.get("p_blank")), higher=False)
        and _no_worse(_f(a.get("p_dnp")), _f(b.get("p_dnp")), higher=False)
    )


def _pairwise(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    pa = a.get("_pmf")
    pb = b.get("_pmf")
    if not isinstance(pa, Mapping) or not isinstance(pb, Mapping):
        return {
            "status": "UNAVAILABLE",
            "reason": "CANONICAL_PLAYER_PMF_UNAVAILABLE",
        }

    pmf_mean_a = _mean(pa)
    pmf_mean_b = _mean(pb)
    adjusted_mean_a = _f(a.get("expected_points"))
    adjusted_mean_b = _f(b.get("expected_points"))
    delta: dict[float, float] = {}
    for xa, ma in pa.items():
        for xb, mb in pb.items():
            value = round(float(xa) - float(xb), 9)
            delta[value] = delta.get(value, 0.0) + float(ma) * float(mb)
    total = sum(delta.values())
    if total <= 0.0:
        return {"status": "UNAVAILABLE", "reason": "PAIRWISE_PMF_EMPTY"}
    delta = {value: mass / total for value, mass in delta.items()}
    p_gt = sum(mass for value, mass in delta.items() if value > EPS)
    p_eq = sum(mass for value, mass in delta.items() if abs(value) <= EPS)
    p_lt = max(0.0, 1.0 - p_gt - p_eq)
    return {
        "status": "AVAILABLE",
        "method": "EXACT_CANONICAL_CORE_DISCRETE_PMF_DIFFERENCE",
        "dependence_assumption": "CONDITIONAL_INDEPENDENCE_CROSS_PLAYER",
        "cross_player_correlation": "NOT_MODELLED_YET",
        "bonus_residual_handling": "EXPECTATION_ONLY_NOT_STOCHASTICALLY_FABRICATED",
        "a_element_id": a.get("element_id"),
        "a_player": a.get("player"),
        "b_element_id": b.get("element_id"),
        "b_player": b.get("player"),
        "p_a_gt_b": round(p_gt, 9),
        "p_equal": round(p_eq, 9),
        "p_a_lt_b": round(p_lt, 9),
        "mean_delta": round(sum(value * mass for value, mass in delta.items()), 9),
        "core_pmf_mean_delta": round(pmf_mean_a - pmf_mean_b, 9),
        "adjusted_expected_mean_delta": (
            None
            if adjusted_mean_a is None or adjusted_mean_b is None
            else round(adjusted_mean_a - adjusted_mean_b, 9)
        ),
        "p10": _quantile(delta, 0.10),
        "p50": _quantile(delta, 0.50),
        "p90": _quantile(delta, 0.90),
    }


def _scope_value(profile: Mapping[str, Any], scope: str, field: str) -> float | None:
    return _f((profile.get(scope) or {}).get(field))


def _public_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in profile.items() if key != "_pmf"}


def _football_leader(
    frontier: Sequence[Mapping[str, Any]],
    pairwise: Sequence[Mapping[str, Any]],
    baseline_captain_id: int | None,
) -> Mapping[str, Any]:
    by_id = {
        int(row["element_id"]): row
        for row in frontier
        if row.get("element_id") is not None
    }
    net: dict[int, int] = {element: 0 for element in by_id}
    available_pairs = 0
    for pair in pairwise:
        if pair.get("status") != "AVAILABLE":
            continue
        available_pairs += 1
        a = _i(pair.get("a_element_id"))
        b = _i(pair.get("b_element_id"))
        if a not in net or b not in net:
            continue
        p_gt = _f(pair.get("p_a_gt_b")) or 0.0
        p_lt = _f(pair.get("p_a_lt_b")) or 0.0
        if p_gt > p_lt + EPS:
            net[a] += 1
            net[b] -= 1
        elif p_lt > p_gt + EPS:
            net[b] += 1
            net[a] -= 1
    if available_pairs <= 0 and baseline_captain_id in by_id:
        return by_id[int(baseline_captain_id)]
    return max(
        frontier,
        key=lambda row: (
            net.get(int(row.get("element_id") or 0), 0),
            _f(row.get("expected_points")) or float("-inf"),
            _f(row.get("q90")) or float("-inf"),
            _f(row.get("p_start")) or float("-inf"),
        ),
    )


def _competitive_tiebreak(
    frontier: Sequence[Mapping[str, Any]],
    *,
    football_leader: Mapping[str, Any],
    risk_posture: str,
    risk_context: Mapping[str, Any] | None,
    risk_context_complete: bool,
    league_complete: bool,
    competitive_complete: bool,
) -> tuple[Mapping[str, Any], bool, dict[str, Any]]:
    posture = str(risk_posture or "BALANCED").upper()
    if posture == "CHASE":
        posture = "ATTACK"
    if posture not in {"PROTECT", "BALANCED", "ATTACK"}:
        posture = "BALANCED"

    consequence = []
    exposure_complete = True
    for row in frontier:
        league_c = _scope_value(row, "league_scope", "captain_pct")
        league_eo = _scope_value(row, "league_scope", "eo_pct")
        comp_c = _scope_value(row, "competitive_scope", "captain_pct")
        comp_eo = _scope_value(row, "competitive_scope", "eo_pct")
        if comp_c is None or league_c is None:
            exposure_complete = False
        consequence.append(
            {
                "element_id": row.get("element_id"),
                "player": row.get("player"),
                "league_captain_pct": league_c,
                "league_eo_pct": league_eo,
                "competitive_captain_pct": comp_c,
                "competitive_eo_pct": comp_eo,
                "protection_exposure": comp_c,
                "leverage_exposure": (
                    None if comp_c is None else round(max(0.0, 100.0 - comp_c), 6)
                ),
                "league_relative_upside_index_if_captain_succeeds": (
                    None if league_c is None
                    else round(max(0.0, 1.0 - league_c / 100.0), 9)
                ),
                "league_relative_downside_index_if_captain_fails": (
                    None if league_c is None
                    else round(max(0.0, league_c / 100.0), 9)
                ),
                "competitive_relative_upside_index_if_captain_succeeds": (
                    None if comp_c is None
                    else round(max(0.0, 1.0 - comp_c / 100.0), 9)
                ),
                "competitive_relative_downside_index_if_captain_fails": (
                    None if comp_c is None
                    else round(max(0.0, comp_c / 100.0), 9)
                ),
                "exposure_index_semantics": "P1_8_EXPOSURE_ONLY_NOT_RELATIVE_POINTS_MC",
                "expected_relative_points_delta_vs_league": None,
                "expected_relative_points_delta_vs_competitive_window": None,
                "probability_gain_relative_points": None,
                "probability_lose_relative_points": None,
                "relative_points_mc_status": "UNAVAILABLE_CANDIDATE_SPECIFIC_SHARED_WORLD_MC_NOT_SIMULATED",
            }
        )

    context = {
        "risk_posture": posture,
        "risk_posture_evidence": dict(risk_context or {}),
        "risk_posture_context_complete": bool(risk_context_complete),
        "football_frontier_close": len(frontier) >= 2,
        "league_complete": bool(league_complete),
        "competitive_window_complete": bool(competitive_complete),
        "captain_exposure_complete": exposure_complete,
        "competitive_consequence": consequence,
        "relative_points_not_invented_from_eo": True,
        "method": "P1_8_EXPOSURE_TIEBREAK_WITHIN_FOOTBALL_FRONTIER",
    }
    if posture == "BALANCED":
        # A CLOSE football frontier is intentionally not auto-LOCKed in a
        # balanced posture.  In particular, a goalkeeper may not become a
        # locked captain merely because its mean is fractionally highest while
        # outfield candidates carry stronger haul/ceiling or materially
        # different competitive exposure.  Keep the football leader visible,
        # but require a later evidence-based resolution.
        context["tie_break_status"] = "UNRESOLVED_BALANCED_CLOSE"
        context["balanced_close_requires_explicit_resolution"] = True
        return football_leader, False, context

    if (
        not risk_context_complete
        or not league_complete
        or not competitive_complete
        or not exposure_complete
        or len(frontier) < 2
    ):
        if not risk_context_complete:
            tie_break_status = "UNAVAILABLE_INCOMPLETE_RISK_POSTURE_CONTEXT"
        else:
            tie_break_status = "UNAVAILABLE_INCOMPLETE_MINI_LEAGUE_EVIDENCE"
        context["tie_break_status"] = tie_break_status
        return football_leader, False, context

    reverse = posture == "PROTECT"
    selected = sorted(
        frontier,
        key=lambda row: (
            _scope_value(row, "competitive_scope", "captain_pct") or 0.0,
            _scope_value(row, "competitive_scope", "eo_pct") or 0.0,
            _scope_value(row, "league_scope", "captain_pct") or 0.0,
            _f(row.get("expected_points")) or float("-inf"),
        ),
        reverse=reverse,
    )[0]
    if posture == "ATTACK":
        selected = sorted(
            frontier,
            key=lambda row: (
                _scope_value(row, "competitive_scope", "captain_pct")
                if _scope_value(row, "competitive_scope", "captain_pct") is not None
                else float("inf"),
                _scope_value(row, "competitive_scope", "eo_pct")
                if _scope_value(row, "competitive_scope", "eo_pct") is not None
                else float("inf"),
                _scope_value(row, "league_scope", "captain_pct")
                if _scope_value(row, "league_scope", "captain_pct") is not None
                else float("inf"),
                _scope_value(row, "league_scope", "eo_pct")
                if _scope_value(row, "league_scope", "eo_pct") is not None
                else float("inf"),
                -(_f(row.get("expected_points")) or float("-inf")),
            ),
        )[0]
    changed = selected.get("element_id") != football_leader.get("element_id")
    context["tie_break_status"] = (
        "COMPETITIVE_TIEBREAK_APPLIED" if changed else "FOOTBALL_LEADER_RETAINED"
    )
    return selected, changed, context


def _select_vice(
    profiles: Sequence[Mapping[str, Any]],
    captain_id: int,
    baseline_vice_id: int | None,
) -> tuple[Mapping[str, Any] | None, str]:
    legal = [row for row in profiles if row.get("element_id") != captain_id]
    if not legal:
        return None, "NO_LEGAL_VICE_CANDIDATE"

    complete = [
        row
        for row in legal
        if row.get("p_dnp") is not None
        and row.get("p_start") is not None
        and row.get("xmins") is not None
        and row.get("expected_points") is not None
    ]
    if not complete:
        baseline = next(
            (row for row in legal if row.get("element_id") == baseline_vice_id),
            legal[0],
        )
        return baseline, "P1_7_VICE_FALLBACK_DISTRIBUTIONAL_SAFETY_INCOMPLETE"

    selected = min(
        complete,
        key=lambda row: (
            _f(row.get("p_dnp")) if _f(row.get("p_dnp")) is not None else 1.0,
            -(_f(row.get("p_start")) or 0.0),
            -(_f(row.get("xmins")) or 0.0),
            -(_f(row.get("expected_points")) or 0.0),
            _f(row.get("p_blank")) if _f(row.get("p_blank")) is not None else 1.0,
        ),
    )
    return selected, (
        "VICE_PRIORITIZES_LOW_DNP_HIGH_START_AND_MINUTES_SECURITY_THEN_RETURN;"
        "CAPTAIN_VICE_DNP_CORRELATION_NOT_MODELLED_YET"
    )


def decide_captain_vice(
    candidates: Sequence[Mapping[str, Any]],
    *,
    baseline_captain_id: int | None,
    baseline_vice_id: int | None,
    risk_posture: str = "BALANCED",
    risk_context: Mapping[str, Any] | None = None,
    risk_context_complete: bool = True,
    league_complete: bool = False,
    competitive_complete: bool = False,
) -> dict[str, Any]:
    profiles = [
        _distribution_profile(row)
        for row in candidates
        if _i(row.get("element_id", row.get("element"))) is not None
    ]
    if not profiles:
        return {
            "model_owner": MODEL_OWNER,
            "model_id": MODEL_ID,
            "classification": "FRAGILE",
            "status": "UNAVAILABLE",
            "reason": "NO_LEGAL_SELECTED_XI_CANDIDATES",
            "captain": None,
            "vice_captain": None,
            "frontier": [],
            "pairwise": [],
        }

    incomplete = [row for row in profiles if not row["football_evidence_complete"]]
    pareto_frontier = [
        row
        for row in profiles
        if not any(
            other.get("element_id") != row.get("element_id")
            and _dominates(other, row)
            for other in profiles
        )
    ]

    clear_candidates = []
    if not incomplete:
        clear_candidates = [
            row
            for row in profiles
            if all(
                other.get("element_id") == row.get("element_id")
                or _robust_clear_dominates(row, other)
                for other in profiles
            )
        ]

    classification = (
        "FRAGILE"
        if incomplete
        else "CLEAR"
        if len(clear_candidates) == 1
        else "CLOSE"
    )

    if classification == "CLEAR":
        frontier = list(clear_candidates)
        pairwise = [
            _pairwise(clear_candidates[0], other)
            for other in profiles
            if other.get("element_id") != clear_candidates[0].get("element_id")
        ]
        football_leader = clear_candidates[0]
    else:
        frontier = list(pareto_frontier)
        if classification == "CLOSE" and len(frontier) == 1:
            leader = frontier[0]
            frontier.extend(
                row
                for row in profiles
                if row.get("element_id") != leader.get("element_id")
                and not _robust_clear_dominates(leader, row)
            )
            seen: set[int] = set()
            frontier = [
                row
                for row in frontier
                if row.get("element_id") is not None
                and int(row["element_id"]) not in seen
                and not seen.add(int(row["element_id"]))
            ]
        pairwise = [
            _pairwise(a, b)
            for index, a in enumerate(frontier)
            for b in frontier[index + 1 :]
        ]
        football_leader = _football_leader(
            frontier, pairwise, baseline_captain_id
        )
    selected = football_leader
    mini_changed = False
    competitive = {
        "risk_posture": str(risk_posture or "BALANCED").upper(),
        "risk_posture_evidence": dict(risk_context or {}),
        "risk_posture_context_complete": bool(risk_context_complete),
        "tie_break_status": "NOT_APPLICABLE_FOOTBALL_CLEAR",
        "competitive_consequence": [],
        "relative_points_not_invented_from_eo": True,
    }
    if classification == "CLOSE":
        selected, mini_changed, competitive = _competitive_tiebreak(
            frontier,
            football_leader=football_leader,
            risk_posture=risk_posture,
            risk_context=risk_context,
            risk_context_complete=risk_context_complete,
            league_complete=league_complete,
            competitive_complete=competitive_complete,
        )

    if classification == "FRAGILE":
        baseline = next(
            (
                row
                for row in profiles
                if row.get("element_id") == baseline_captain_id
            ),
            None,
        )
        if baseline is not None:
            selected = baseline
        competitive = {
            **competitive,
            "tie_break_status": "PRESERVE_P1_7_BASELINE_FRAGILE_FOOTBALL_EVIDENCE",
        }

    captain_id = int(selected.get("element_id") or 0)
    vice, vice_reason = _select_vice(profiles, captain_id, baseline_vice_id)

    if classification == "CLEAR":
        decision_state = "LOCK"
        reason = (
            "One selected-XI candidate robustly first-order stochastically "
            "dominates every alternative on the canonical core return PMF while "
            "remaining no worse on mean/start/minutes/blank/DNP security; "
            "mini-league context cannot override it."
        )
    elif classification == "CLOSE":
        resolved = competitive.get("tie_break_status") in {
            "COMPETITIVE_TIEBREAK_APPLIED",
            "FOOTBALL_LEADER_RETAINED",
        }
        decision_state = "LOCK" if resolved else "PREPARE"
        reason = (
            "No selected-XI candidate satisfies the threshold-free robust CLEAR "
            "rule across the full return distribution and security evidence. "
            "Mini-league context is used only as a secondary tie-break inside "
            "the football frontier when its required scopes are complete."
        )
    else:
        decision_state = "PREPARE"
        reason = (
            "Football distribution evidence is incomplete for at least one legal "
            "selected-XI candidate, so the P1.7 baseline is preserved and no "
            "competitive override is permitted."
        )

    public_frontier = [_public_profile(row) for row in frontier]
    public_profiles = [_public_profile(row) for row in profiles]
    return {
        "model_owner": MODEL_OWNER,
        "model_id": MODEL_ID,
        "status": "AVAILABLE",
        "classification": classification,
        "decision_state": decision_state,
        "football_leader": _public_profile(football_leader),
        "captain": _public_profile(selected),
        "vice_captain": _public_profile(vice) if vice is not None else None,
        "frontier": public_frontier,
        "profiles": public_profiles,
        "pairwise": pairwise,
        "mini_league_override_applied": bool(mini_changed),
        "competitive_context": competitive,
        "vice_reason": vice_reason,
        "reason": reason,
        "governance": {
            "owned_selected_xi_only": True,
            "position_neutral": True,
            "highest_mean_alone_is_not_authority": True,
            "arbitrary_weighted_captain_score_created": False,
            "p_haul_semantics": "P_POINTS_GE_10_FROM_CANONICAL_PMF",
            "p_haul_not_double_counted": True,
            "football_distribution_first": True,
            "clear_rule": "FIRST_ORDER_STOCHASTIC_DOMINANCE_PLUS_SECURITY_NO_ARBITRARY_THRESHOLD",
            "mini_league_second_close_only": True,
            "eo_is_not_expected_points": True,
            "candidate_specific_relative_mc_fabricated": False,
            "cross_player_correlation": "NOT_MODELLED_YET",
            "blank_semantics": "CANONICAL_P_FPL_BLANK_OR_PUBLISHED_BLANK_THRESHOLD_NO_HARDCODE",
            "bonus_residual_distribution_fabricated": False,
            "mc500k_mutated": False,
        },
    }
