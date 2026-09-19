from __future__ import annotations

"""Deterministic conformance helpers for FPL Master Canonical V12.

This module is NOT a second methodology authority. The only active methodology
authority is control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt. Constants
below are conformance invariants mirrored from that authority so deterministic
code can fail closed when a caller supplies legacy or drifted semantics.

Decision chain:
FOOTBALL SCORE -> EXPECTED POINTS / UNCERTAINTY -> TRANSFER ECONOMICS ->
PACKAGE UTILITY -> ACTION.
"""

from dataclasses import dataclass
from math import isclose
from typing import Any, Mapping, Sequence


CANONICAL_AUTHORITY = "control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt"
# Compatibility alias for older imports. It intentionally resolves to V12 now.
SPEC_AUTHORITY = CANONICAL_AUTHORITY
LEGACY_AUTHORITIES = frozenset(
    {
        "/FPL/FPL_MASTER_SPEC_V11.txt",
        "/FPL/FPL_MASTER_RUNTIME_CONTRACT.txt",
        "/FPL/state/ACTIVE_DECISION_CONTEXT.json",
    }
)
FOOTBALL_COMPONENTS = (
    "PROVEN_HISTORICAL",
    "TACTICAL_ROLE",
    "CURRENT_UNDERLYING",
    "FIXTURE_SECURITY",
)
# Mirrored conformance invariant, not an independent authority.
CANONICAL_WEIGHTS = {
    "PROVEN_HISTORICAL": 0.20,
    "TACTICAL_ROLE": 0.25,
    "CURRENT_UNDERLYING": 0.30,
    "FIXTURE_SECURITY": 0.25,
}
SCENARIO_STATES = frozenset(
    {"CONTEMPLATED", "EXECUTED", "REJECTED", "SUPERSEDED", "EXPIRED"}
)
ACTION_STATES = frozenset({"WAIT", "PREPARE", "ACT"})
MC_STATES = frozenset({"EXECUTED", "NOT_RUN", "PARTIAL"})
SEARCH_AUTHORITIES = frozenset({"FULL", "PARTIAL"})


class MethodologyContractError(ValueError):
    pass


def _finite_number(value: Any, *, label: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise MethodologyContractError(f"{label} must be numeric") from exc
    if numeric != numeric or numeric in {float("inf"), float("-inf")}:
        raise MethodologyContractError(f"{label} must be finite")
    return numeric


def _probability(value: Any, *, label: str) -> float:
    numeric = _finite_number(value, label=label)
    if numeric < 0.0 or numeric > 1.0:
        raise MethodologyContractError(f"{label} must be within [0,1]")
    return numeric


def _nonempty(value: Any, *, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MethodologyContractError(f"{label} is required")
    return text


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in text)


def validate_methodology_weights(
    weights: Mapping[str, Any],
    *,
    authority: str,
) -> dict[str, float]:
    """Fail closed on legacy authority or any V12 weight drift."""
    if authority in LEGACY_AUTHORITIES:
        raise MethodologyContractError("legacy Library authority is historical-only under V12")
    if authority != CANONICAL_AUTHORITY:
        raise MethodologyContractError(
            "methodology authority must be FPL_MASTER_CANONICAL_V12.txt"
        )
    keys = set(weights)
    expected = set(FOOTBALL_COMPONENTS)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        raise MethodologyContractError(
            f"methodology component mismatch; missing={missing}; extra={extra}"
        )
    normalized = {
        key: _finite_number(weights[key], label=f"weights.{key}")
        for key in FOOTBALL_COMPONENTS
    }
    if any(value < 0.0 or value > 1.0 for value in normalized.values()):
        raise MethodologyContractError("methodology weights must be within [0,1]")
    if not isclose(sum(normalized.values()), 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise MethodologyContractError("methodology weights must total exactly 1.0")
    for key, expected_weight in CANONICAL_WEIGHTS.items():
        if not isclose(
            normalized[key], expected_weight, rel_tol=0.0, abs_tol=1e-12
        ):
            raise MethodologyContractError(
                f"V12 methodology weight drift for {key}: "
                f"{normalized[key]} != {expected_weight}"
            )
    return normalized


def compute_football_score(
    component_scores: Mapping[str, Any],
    *,
    weights: Mapping[str, Any] = CANONICAL_WEIGHTS,
    authority: str = CANONICAL_AUTHORITY,
) -> dict[str, Any]:
    """Compute football-only score. Transfer economics are impossible here."""
    normalized_weights = validate_methodology_weights(weights, authority=authority)
    keys = set(component_scores)
    expected = set(FOOTBALL_COMPONENTS)
    if keys != expected:
        raise MethodologyContractError(
            "football component scores must match canonical components"
        )
    normalized_scores: dict[str, float] = {}
    for key in FOOTBALL_COMPONENTS:
        score = _finite_number(
            component_scores[key], label=f"component_scores.{key}"
        )
        if score < 0.0 or score > 100.0:
            raise MethodologyContractError(
                "football component scores must be within [0,100]"
            )
        normalized_scores[key] = score
    total = sum(
        normalized_scores[key] * normalized_weights[key]
        for key in FOOTBALL_COMPONENTS
    )
    return {
        "status": "PASS",
        "authority": authority,
        "component_scores": normalized_scores,
        "weights": normalized_weights,
        "weights_hydrated_from_authority": True,
        "exact_v12_weight_conformance": True,
        "football_score": round(total, 6),
        "transfer_economics_included": False,
        "decision_chain_stage": "FOOTBALL_SCORE",
    }


def build_probability_state(
    *,
    p_available: Any,
    p_start_given_available: Any,
    p_bench_given_available_not_start: Any,
    p_cameo_given_bench: Any,
    p_late_cameo_given_cameo: Any,
) -> dict[str, Any]:
    """Build conditional and truthful unconditional V12 availability states.

    Bench is an overlapping roster state, while START/CAMEO/DNP are mutually
    exclusive appearance outcomes. We therefore never force
    START+BENCH+CAMEO+DNP to equal one.
    """
    available = _probability(p_available, label="p_available")
    start_if_available = _probability(
        p_start_given_available, label="p_start_given_available"
    )
    bench_if_not_start = _probability(
        p_bench_given_available_not_start,
        label="p_bench_given_available_not_start",
    )
    cameo_if_bench = _probability(
        p_cameo_given_bench, label="p_cameo_given_bench"
    )
    late_if_cameo = _probability(
        p_late_cameo_given_cameo, label="p_late_cameo_given_cameo"
    )

    available_not_start = available * (1.0 - start_if_available)
    start = available * start_if_available
    bench = available_not_start * bench_if_not_start
    cameo = bench * cameo_if_bench
    late_cameo = cameo * late_if_cameo
    no_appearance_from_bench = bench * (1.0 - cameo_if_bench)
    not_benched_when_available = available_not_start * (1.0 - bench_if_not_start)
    unavailable = 1.0 - available
    dnp = unavailable + no_appearance_from_bench + not_benched_when_available

    if not isclose(start + cameo + dnp, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise MethodologyContractError(
            "mutually exclusive appearance outcomes failed normalization"
        )
    return {
        "status": "PASS",
        "semantics": "V12_HIERARCHICAL_AVAILABILITY_APPEARANCE",
        "conditional": {
            "p_available": round(available, 8),
            "p_start_given_available": round(start_if_available, 8),
            "p_bench_given_available_not_start": round(bench_if_not_start, 8),
            "p_cameo_given_bench": round(cameo_if_bench, 8),
            "p_late_cameo_given_cameo": round(late_if_cameo, 8),
            "p_no_appearance_given_bench": round(1.0 - cameo_if_bench, 8),
        },
        "unconditional": {
            "p_available": round(available, 8),
            "p_start": round(start, 8),
            "p_bench": round(bench, 8),
            "p_cameo": round(cameo, 8),
            "p_late_cameo": round(late_cameo, 8),
            "p_dnp": round(dnp, 8),
        },
        "appearance_outcomes_sum_to_one": True,
        "bench_is_overlapping_state": True,
        "flat_sum_start_bench_cameo_dnp_forbidden": True,
    }


def validate_probability_state(state: Mapping[str, Any]) -> dict[str, Any]:
    conditional = state.get("conditional")
    unconditional = state.get("unconditional")
    if not isinstance(conditional, Mapping) or not isinstance(unconditional, Mapping):
        raise MethodologyContractError(
            "probability_state requires conditional and unconditional mappings"
        )
    rebuilt = build_probability_state(
        p_available=conditional.get("p_available"),
        p_start_given_available=conditional.get("p_start_given_available"),
        p_bench_given_available_not_start=conditional.get(
            "p_bench_given_available_not_start"
        ),
        p_cameo_given_bench=conditional.get("p_cameo_given_bench"),
        p_late_cameo_given_cameo=conditional.get(
            "p_late_cameo_given_cameo"
        ),
    )
    for key, expected in rebuilt["unconditional"].items():
        actual = _probability(unconditional.get(key), label=f"unconditional.{key}")
        if not isclose(actual, expected, rel_tol=0.0, abs_tol=1e-6):
            raise MethodologyContractError(
                f"probability_state inconsistent for {key}: {actual} != {expected}"
            )
    return rebuilt


def propagate_availability(
    *,
    evidence_class: str,
    probability_state: Mapping[str, Any] | None = None,
    xmins_distribution: Mapping[str, Any] | None = None,
    p_start: Any | None = None,
    p_cameo: Any | None = None,
    p_dnp: Any | None = None,
    xmins: Any | None = None,
    unknown_injury_duration: bool = False,
) -> dict[str, Any]:
    """Publish V12 state semantics while retaining explicit legacy-call compatibility."""
    evidence = _nonempty(evidence_class, label="evidence_class").upper()
    if probability_state is not None:
        state = validate_probability_state(probability_state)
        u = state["unconditional"]
        distribution = dict(xmins_distribution or {})
        if not distribution:
            raise MethodologyContractError(
                "V12 probability_state requires xmins_distribution"
            )
        mean_minutes = _finite_number(
            distribution.get("mean"), label="xmins_distribution.mean"
        )
        if mean_minutes < 0.0 or mean_minutes > 90.0:
            raise MethodologyContractError(
                "xmins_distribution.mean must be within [0,90]"
            )
        semantics = "V12_HIERARCHICAL"
    else:
        # Backward compatibility is explicit and cannot masquerade as canonical
        # serious-decision proof.
        start = _probability(p_start, label="p_start")
        cameo = _probability(p_cameo, label="p_cameo")
        dnp = _probability(p_dnp, label="p_dnp")
        if not isclose(start + cameo + dnp, 1.0, rel_tol=0.0, abs_tol=1e-6):
            raise MethodologyContractError(
                "legacy START/CAMEO/DNP appearance outcomes must total 1.0"
            )
        mean_minutes = _finite_number(xmins, label="xmins")
        if mean_minutes < 0.0 or mean_minutes > 90.0:
            raise MethodologyContractError("xmins must be within [0,90]")
        u = {
            "p_available": round(1.0 - dnp, 8),
            "p_start": round(start, 8),
            "p_bench": None,
            "p_cameo": round(cameo, 8),
            "p_late_cameo": None,
            "p_dnp": round(dnp, 8),
        }
        state = {
            "status": "PARTIAL",
            "semantics": "LEGACY_FLAT_COMPATIBILITY_NOT_V12_PROOF",
            "unconditional": u,
        }
        distribution = {
            "mean": round(mean_minutes, 3),
            "status": "LEGACY_MEAN_ONLY",
        }
        semantics = "LEGACY_COMPATIBILITY"

    return {
        "status": "PASS" if semantics == "V12_HIERARCHICAL" else "PARTIAL",
        "probability_semantics": semantics,
        "probability_state": state,
        "p_available": u.get("p_available"),
        "p_start": u.get("p_start"),
        "p_bench": u.get("p_bench"),
        "p_cameo": u.get("p_cameo"),
        "p_late_cameo": u.get("p_late_cameo"),
        "p_dnp": u.get("p_dnp"),
        "xmins": round(mean_minutes, 3),
        "xmins_distribution": distribution,
        "evidence_class": evidence,
        "unknown_injury_duration": bool(unknown_injury_duration),
        "uncertainty_penalty_required": bool(unknown_injury_duration),
        "automatic_sell": False,
        "propagates_to": [
            "FIXTURE_SECURITY",
            "EXPECTED_POINTS",
            "XI_BENCH",
            "PACKAGE_UTILITY",
            "ACTION_BOARD",
        ],
    }


def build_horizon_analysis(
    *,
    one_gw: Mapping[str, Any],
    three_gw: Mapping[str, Any],
    five_gw: Mapping[str, Any],
    two_gw: Mapping[str, Any] | None = None,
    rental_or_exit: bool = False,
) -> dict[str, Any]:
    """Canonical serious-decision horizons are GW+1, optional-required 2GW, 3GW, 5GW."""
    required: dict[str, dict[str, Any]] = {
        "GW+1": dict(one_gw),
        "3GW": dict(three_gw),
        "5GW": dict(five_gw),
    }
    if rental_or_exit:
        if two_gw is None:
            raise MethodologyContractError(
                "2GW horizon is required for rental/exit routes"
            )
        required["2GW"] = dict(two_gw)
    elif two_gw is not None:
        required["2GW"] = dict(two_gw)

    for horizon, payload in required.items():
        if "expected_points_delta" not in payload:
            raise MethodologyContractError(
                f"{horizon}.expected_points_delta is required"
            )
        payload["expected_points_delta"] = _finite_number(
            payload["expected_points_delta"],
            label=f"{horizon}.expected_points_delta",
        )
    ordered = {
        key: required[key]
        for key in ("GW+1", "2GW", "3GW", "5GW")
        if key in required
    }
    return {
        "status": "PASS",
        "horizons": ordered,
        "collapsed": False,
        "gw_plus_1_is_distinct": True,
        "two_gw_required_for_rental_or_exit": bool(rental_or_exit),
        "three_gw_is_distinct": True,
        "five_gw_is_distinct": True,
        "legacy_10_15gw_may_be_background_only": True,
    }


def derive_dynamic_ft_shadow_value(
    *,
    best_future_utility_with_ft: Any,
    best_future_utility_with_ft_consumed: Any,
    frontier_snapshot_id: str,
) -> dict[str, Any]:
    """FT opportunity value from future optimization, never a universal point tax."""
    with_ft = _finite_number(
        best_future_utility_with_ft, label="best_future_utility_with_ft"
    )
    consumed = _finite_number(
        best_future_utility_with_ft_consumed,
        label="best_future_utility_with_ft_consumed",
    )
    snapshot = _nonempty(frontier_snapshot_id, label="frontier_snapshot_id")
    return {
        "status": "PASS",
        "method": "FUTURE_OPTIMIZATION_OPPORTUNITY_DIFFERENCE",
        "best_future_utility_with_ft": with_ft,
        "best_future_utility_with_ft_consumed": consumed,
        "ft_shadow_value": round(with_ft - consumed, 6),
        "frontier_snapshot_id": snapshot,
        "fixed_universal_ft_value": False,
    }


def build_transfer_economics(
    *,
    ft_used: int,
    hit_points: Any,
    buy_back_cost: Any,
    sell_value_loss: Any,
    price_movement_effect: Any,
    affordability_after: Any,
    itb_after: Any,
    concentration_risk: Any,
    correlation_risk: Any,
    exit_route: Mapping[str, Any] | None,
    reacquisition_plan: Mapping[str, Any] | None,
    ft_shadow: Mapping[str, Any] | None = None,
    future_ft_shadow_value: Any | None = None,
    possible_future_ft: Any | None = None,
    possible_future_hit: Any | None = None,
    exit_security: str | None = None,
) -> dict[str, Any]:
    """Downstream economics, explicitly separated from football score."""
    if ft_shadow is not None:
        shadow = dict(ft_shadow)
        if shadow.get("status") != "PASS" or shadow.get("fixed_universal_ft_value") is not False:
            raise MethodologyContractError(
                "ft_shadow must be dynamically derived from future optimization"
            )
        shadow_value = _finite_number(
            shadow.get("ft_shadow_value"), label="ft_shadow.ft_shadow_value"
        )
        shadow_semantics = "DYNAMIC_CANONICAL"
    elif future_ft_shadow_value is not None:
        shadow_value = _finite_number(
            future_ft_shadow_value, label="future_ft_shadow_value"
        )
        shadow = {
            "status": "LEGACY_HEURISTIC",
            "ft_shadow_value": shadow_value,
            "fixed_universal_ft_value": True,
        }
        shadow_semantics = "LEGACY_HEURISTIC_NOT_CANONICAL"
    else:
        shadow_value = 0.0
        shadow = {
            "status": "UNAVAILABLE",
            "ft_shadow_value": None,
            "fixed_universal_ft_value": False,
        }
        shadow_semantics = "UNAVAILABLE"

    security = str(exit_security or "NOT_ASSESSED").strip().upper()
    if security not in {
        "PUNT EXIT SECURE",
        "PUNT EXIT FRAGILE",
        "PUNT EXIT NOT SECURE",
        "NOT_ASSESSED",
    }:
        raise MethodologyContractError("invalid exit_security")
    return {
        "status": "PASS",
        "decision_chain_stage": "TRANSFER_ECONOMICS",
        "included_in_football_score": False,
        "ft_used": int(ft_used),
        "hit_points": _finite_number(hit_points, label="hit_points"),
        "future_ft_shadow_value": shadow_value,
        "ft_shadow": shadow,
        "ft_shadow_semantics": shadow_semantics,
        "buy_back_cost": _finite_number(buy_back_cost, label="buy_back_cost"),
        "sell_value_loss": _finite_number(
            sell_value_loss, label="sell_value_loss"
        ),
        "price_movement_effect": _finite_number(
            price_movement_effect, label="price_movement_effect"
        ),
        "affordability_after": affordability_after,
        "itb_after": itb_after,
        "concentration_risk": concentration_risk,
        "correlation_risk": correlation_risk,
        "exit_route": dict(exit_route or {}),
        "exit_route_is_provisional": True,
        "reacquisition_plan": dict(reacquisition_plan or {}),
        "possible_future_ft": possible_future_ft,
        "possible_future_hit": possible_future_hit,
        "exit_security": security,
    }


def validate_monte_carlo_provenance(
    monte_carlo: Mapping[str, Any],
    *,
    required_for_close_decision: bool = False,
) -> dict[str, Any]:
    """Truth gate for V12 MC. Legacy Gaussian diagnostics can never PASS it."""
    row = dict(monte_carlo or {})
    state = str(row.get("execution_state") or "").strip().upper()
    if state not in MC_STATES:
        raise MethodologyContractError("MC execution_state must be EXECUTED/NOT_RUN/PARTIAL")
    failures: list[str] = []
    limitations: list[str] = []

    if state == "EXECUTED":
        try:
            actual_paths = int(row.get("actual_paths") or 0)
        except (TypeError, ValueError):
            actual_paths = 0
        if actual_paths < 500_000:
            failures.append("MC_ACTUAL_PATHS_LT_500000")
        if row.get("correlated") is not True:
            failures.append("MC_NOT_CORRELATED")
        for key in (
            "method",
            "correlation_model",
            "seed_policy",
            "input_freshness",
            "convergence_evidence",
        ):
            if row.get(key) in (None, "", {}, []):
                failures.append(f"MC_{key.upper()}_MISSING")
        if not row.get("input_snapshot_ids"):
            failures.append("MC_INPUT_SNAPSHOT_IDS_MISSING")
        if not _is_sha256(row.get("output_fingerprint")):
            failures.append("MC_OUTPUT_FINGERPRINT_INVALID")
        legacy_method = str(row.get("method") or "").lower()
        if "independent_normal_aggregate" in legacy_method:
            failures.append("MC_LEGACY_INDEPENDENT_GAUSSIAN_NOT_CANONICAL")
        if failures:
            return {
                "status": "FAIL",
                "execution_state": state,
                "canonical_pass": False,
                "failures": failures,
                "report_must_not_label_mc_canonical_pass": True,
            }
        return {
            "status": "PASS",
            "execution_state": state,
            "canonical_pass": True,
            "actual_paths": actual_paths,
            "correlated": True,
            "method": row.get("method"),
            "correlation_model": row.get("correlation_model"),
            "seed_policy": row.get("seed_policy"),
            "common_random_numbers": row.get("common_random_numbers"),
            "input_snapshot_ids": list(row.get("input_snapshot_ids") or []),
            "input_freshness": row.get("input_freshness"),
            "convergence_evidence": row.get("convergence_evidence"),
            "output_fingerprint": row.get("output_fingerprint"),
            "paired_outputs": dict(row.get("paired_outputs") or {}),
            "limitations": list(row.get("limitations") or []),
        }

    reason_key = "reason" if state == "NOT_RUN" else "degradation_reason"
    reason = str(row.get(reason_key) or "").strip()
    if not reason:
        failures.append(f"MC_{state}_{reason_key.upper()}_MISSING")
    if required_for_close_decision:
        limitations.append("MC_REQUIRED_FOR_CLOSE_DECISION_BUT_NOT_CANONICALLY_EXECUTED")
    return {
        "status": "PARTIAL" if not failures else "FAIL",
        "execution_state": state,
        "canonical_pass": False,
        "truthful_non_execution": not failures,
        reason_key: reason or None,
        "failures": failures,
        "limitations": limitations,
        "report_can_continue": not failures,
    }


def build_decision_proof(
    *,
    authority_path: str,
    authority_sha: str,
    authority_version: str,
    official_universe_denominator: int,
    evaluated_denominator: int,
    gate0: Mapping[str, Any],
    component_scores: Mapping[str, Any],
    weights: Mapping[str, Any],
    bayesian_lineage: Mapping[str, Any],
    probability_state: Mapping[str, Any],
    xmins_distribution: Mapping[str, Any],
    horizons: Mapping[str, Any],
    transfer_economics: Mapping[str, Any],
    robustness: Mapping[str, Any],
    expected_regret: Any,
    information_value_of_waiting: Any,
    covariance: Mapping[str, Any] | None,
    icon_overlay: Mapping[str, Any] | None,
    monte_carlo: Mapping[str, Any],
    final_action: str,
    search_authority: str,
    execution_provenance: Mapping[str, Any],
    route_type: str = "NORMAL",
    optimization_claim: str | None = None,
    mc_required: bool = False,
) -> dict[str, Any]:
    """Build transient proof for one serious V12 decision.

    The proof is evidence, never durable authority.
    """
    if authority_path != CANONICAL_AUTHORITY:
        raise MethodologyContractError("DECISION_PROOF authority must be Canonical V12")
    if not _is_sha256(authority_sha):
        raise MethodologyContractError("authority_sha must be a SHA-256 content fingerprint")
    version = _nonempty(authority_version, label="authority_version")
    universe_n = int(official_universe_denominator)
    evaluated_n = int(evaluated_denominator)
    if universe_n <= 0 or evaluated_n < 0 or evaluated_n > universe_n:
        raise MethodologyContractError("invalid universe/evaluated denominator")
    if not isinstance(gate0, Mapping) or gate0.get("status") != "PASS":
        raise MethodologyContractError("Gate0 must PASS before serious decision composition")
    football = compute_football_score(
        component_scores,
        weights=weights,
        authority=authority_path,
    )
    probability = validate_probability_state(probability_state)
    if not isinstance(xmins_distribution, Mapping) or xmins_distribution.get("mean") is None:
        raise MethodologyContractError("xMins distribution is required, not only a mean")
    if not isinstance(bayesian_lineage, Mapping) or not bayesian_lineage:
        raise MethodologyContractError("Bayesian/shrinkage lineage is required")
    if not isinstance(horizons, Mapping) or horizons.get("status") != "PASS":
        raise MethodologyContractError("canonical horizon proof is required")
    horizon_keys = set((horizons.get("horizons") or {}).keys())
    if not {"GW+1", "3GW", "5GW"} <= horizon_keys:
        raise MethodologyContractError("GW+1/3GW/5GW horizons are mandatory")
    if str(route_type or "").upper() in {"ONE_GW_PUNT", "RENTAL", "EXIT"} and "2GW" not in horizon_keys:
        raise MethodologyContractError("2GW is mandatory for rental/exit routes")
    if (
        not isinstance(transfer_economics, Mapping)
        or transfer_economics.get("decision_chain_stage") != "TRANSFER_ECONOMICS"
        or transfer_economics.get("included_in_football_score") is not False
    ):
        raise MethodologyContractError("transfer economics must remain downstream")
    if not isinstance(robustness, Mapping) or not robustness:
        raise MethodologyContractError("robustness proof is required")
    if robustness.get("expected_regret") is None and expected_regret is None:
        raise MethodologyContractError("expected regret is required")
    _finite_number(
        information_value_of_waiting,
        label="information_value_of_waiting",
    )
    action = str(final_action or "").strip().upper()
    if action not in ACTION_STATES:
        raise MethodologyContractError("final action must be WAIT/PREPARE/ACT")
    search = str(search_authority or "").strip().upper()
    if search not in SEARCH_AUTHORITIES:
        raise MethodologyContractError("search_authority must be FULL/PARTIAL")
    claim = str(optimization_claim or "").strip().upper()
    if search == "PARTIAL" and claim == "FULL_UNIVERSE_OPTIMIZED":
        raise MethodologyContractError(
            "lossy/PARTIAL search cannot claim FULL_UNIVERSE_OPTIMIZED"
        )
    overlay = dict(icon_overlay or {})
    if overlay and overlay.get("applied_after_football_optimal_baseline") is not True:
        raise MethodologyContractError(
            "ICON+ overlay must be downstream of football-optimal baseline"
        )
    execution = dict(execution_provenance or {})
    if not execution:
        raise MethodologyContractError("execution provenance is required")
    mc = validate_monte_carlo_provenance(
        monte_carlo,
        required_for_close_decision=bool(mc_required),
    )
    failures: list[str] = []
    if mc.get("status") == "FAIL":
        failures.extend(mc.get("failures") or [])
    if mc_required and mc.get("execution_state") != "EXECUTED":
        failures.append("CANONICAL_MC_REQUIRED_BUT_NOT_EXECUTED")
    status = "PASS" if not failures else "PARTIAL"
    return {
        "status": status,
        "proof_kind": "TRANSIENT_DECISION_PROOF",
        "authoritative": False,
        "canonical_authority": {
            "path": authority_path,
            "sha256": authority_sha,
            "version": version,
        },
        "official_fpl_universe_denominator": universe_n,
        "evaluated_denominator": evaluated_n,
        "denominator_complete": evaluated_n == universe_n,
        "gate0": dict(gate0),
        "football_score": football,
        "bayesian_shrinkage_lineage": dict(bayesian_lineage),
        "probability_state": probability,
        "xmins_distribution": dict(xmins_distribution),
        "horizons": dict(horizons),
        "transfer_economics": dict(transfer_economics),
        "robustness": dict(robustness),
        "expected_regret": expected_regret,
        "information_value_of_waiting": information_value_of_waiting,
        "covariance_correlation": dict(covariance or {}),
        "icon_overlay": overlay,
        "monte_carlo": mc,
        "search_authority": search,
        "route_type": str(route_type or "NORMAL").upper(),
        "optimization_claim": (
            claim
            or (
                "FULL_UNIVERSE_OPTIMIZED"
                if search == "FULL"
                else "FULL_UNIVERSE_SCANNED_SEARCH_PARTIAL_AFTER_PRUNING"
            )
        ),
        "execution_provenance": execution,
        "final_action": action,
        "failures": failures,
        "report_can_continue": True,
        "canonical_v12_compliant": not failures,
    }


def build_scenario_evaluation(
    *,
    scenario_id: str,
    scenario_state: str,
    route: Mapping[str, Any],
    football_score: Mapping[str, Any],
    horizons: Mapping[str, Any],
    availability: Mapping[str, Any],
    transfer_economics: Mapping[str, Any],
    action_state: str,
    downside: str,
    reversal_trigger: str,
    optimizer_selected: bool,
    route_type: str = "NORMAL",
) -> dict[str, Any]:
    """Compose a user/optimizer route without inferring execution."""
    sid = _nonempty(scenario_id, label="scenario_id")
    state = str(scenario_state or "").strip().upper()
    action = str(action_state or "").strip().upper()
    route_kind = str(route_type or "NORMAL").strip().upper()
    if state not in SCENARIO_STATES:
        raise MethodologyContractError("invalid scenario state")
    if action not in ACTION_STATES:
        raise MethodologyContractError("invalid action state")
    if football_score.get("status") != "PASS":
        raise MethodologyContractError("football_score must pass")
    if horizons.get("status") != "PASS":
        raise MethodologyContractError("horizons must pass")
    if availability.get("status") not in {"PASS", "PARTIAL"}:
        raise MethodologyContractError("availability must be truthful PASS/PARTIAL")
    if transfer_economics.get("status") != "PASS":
        raise MethodologyContractError("transfer_economics must pass")
    if route_kind == "ONE_GW_PUNT":
        if "2GW" not in (horizons.get("horizons") or {}):
            raise MethodologyContractError("ONE_GW_PUNT requires 2GW net horizon")
    return {
        "status": "PASS",
        "scenario_id": sid,
        "scenario_state": state,
        "executed_only_when_explicit": state == "EXECUTED",
        "active": state == "CONTEMPLATED",
        "route": dict(route),
        "route_type": route_kind,
        "football_score": dict(football_score),
        "horizons": dict(horizons),
        "availability": dict(availability),
        "transfer_economics": dict(transfer_economics),
        "action_state": action,
        "downside": str(downside or ""),
        "reversal_trigger": str(reversal_trigger or ""),
        "optimizer_selected": bool(optimizer_selected),
        "visible_even_if_optimizer_not_selected": state == "CONTEMPLATED",
        "mentioned_by_user_is_not_recommendation": True,
        "next_route_precommitted": False,
        "fresh_full_universe_rescan_required_at_gw_plus_1": route_kind
        == "ONE_GW_PUNT",
    }


def merge_active_and_optimizer_scenarios(
    *,
    active_user_scenarios: Sequence[Mapping[str, Any]],
    optimizer_alternatives: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Preserve contemplated routes while exposing universe alternatives."""
    active = [
        dict(row)
        for row in active_user_scenarios
        if row.get("scenario_state") == "CONTEMPLATED"
    ]
    optimizer = [dict(row) for row in optimizer_alternatives]
    by_id: dict[str, dict[str, Any]] = {}
    for row in optimizer:
        sid = str(row.get("scenario_id") or "").strip()
        if sid:
            by_id[sid] = row
    for row in active:
        sid = str(row.get("scenario_id") or "").strip()
        if sid:
            by_id[sid] = row
    return {
        "status": "PASS",
        "active_user_scenario_ids": [row.get("scenario_id") for row in active],
        "optimizer_alternative_ids": [
            row.get("scenario_id") for row in optimizer
        ],
        "scenarios": list(by_id.values()),
        "active_user_routes_preserved": True,
        "full_universe_alternatives_preserved": bool(optimizer),
        "user_mention_forces_recommendation": False,
    }
