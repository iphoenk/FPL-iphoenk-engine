from __future__ import annotations

"""P0.5 scoring-integrity contract for ChatGPT downstream decision support.

The numerical methodology weights are intentionally NOT defined here. The only
canonical owner of detailed player-evaluation weights is Library
/FPL/FPL_MASTER_SPEC_V11.txt. Runtime/caller code must hydrate those weights and
pass them into these pure validation/composition helpers.

This module keeps the decision chain explicit:
FOOTBALL SCORE -> EXPECTED POINTS / UNCERTAINTY -> TRANSFER ECONOMICS ->
PACKAGE UTILITY -> ACTION.
"""

from dataclasses import dataclass
from math import isclose
from typing import Any, Mapping, Sequence


SPEC_AUTHORITY = "/FPL/FPL_MASTER_SPEC_V11.txt"
FOOTBALL_COMPONENTS = (
    "PROVEN_HISTORICAL",
    "TACTICAL_ROLE",
    "CURRENT_UNDERLYING",
    "FIXTURE_SECURITY",
)
SCENARIO_STATES = frozenset({"CONTEMPLATED", "EXECUTED", "REJECTED", "SUPERSEDED"})
ACTION_STATES = frozenset({"WAIT", "PREPARE", "ACT"})


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


def validate_methodology_weights(
    weights: Mapping[str, Any],
    *,
    authority: str,
) -> dict[str, float]:
    """Validate caller-hydrated weights without defining a second authority."""
    if authority != SPEC_AUTHORITY:
        raise MethodologyContractError("methodology weights must come from FPL_MASTER_SPEC_V11.txt")
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
    return normalized


def compute_football_score(
    component_scores: Mapping[str, Any],
    *,
    weights: Mapping[str, Any],
    authority: str = SPEC_AUTHORITY,
) -> dict[str, Any]:
    """Compute the football-only score. Economics are deliberately impossible here."""
    normalized_weights = validate_methodology_weights(weights, authority=authority)
    keys = set(component_scores)
    expected = set(FOOTBALL_COMPONENTS)
    if keys != expected:
        raise MethodologyContractError("football component scores must match canonical components")
    normalized_scores: dict[str, float] = {}
    for key in FOOTBALL_COMPONENTS:
        score = _finite_number(component_scores[key], label=f"component_scores.{key}")
        if score < 0.0 or score > 100.0:
            raise MethodologyContractError("football component scores must be within [0,100]")
        normalized_scores[key] = score
    total = sum(normalized_scores[key] * normalized_weights[key] for key in FOOTBALL_COMPONENTS)
    return {
        "status": "PASS",
        "authority": authority,
        "component_scores": normalized_scores,
        "weights_hydrated_from_authority": True,
        "football_score": round(total, 6),
        "transfer_economics_included": False,
        "decision_chain_stage": "FOOTBALL_SCORE",
    }


def propagate_availability(
    *,
    p_start: Any,
    p_cameo: Any,
    p_dnp: Any,
    xmins: Any,
    evidence_class: str,
    unknown_injury_duration: bool = False,
) -> dict[str, Any]:
    """Validate availability propagation while preventing rumor -> automatic SELL."""
    start = _finite_number(p_start, label="p_start")
    cameo = _finite_number(p_cameo, label="p_cameo")
    dnp = _finite_number(p_dnp, label="p_dnp")
    minutes = _finite_number(xmins, label="xmins")
    for label, value in (("p_start", start), ("p_cameo", cameo), ("p_dnp", dnp)):
        if value < 0.0 or value > 1.0:
            raise MethodologyContractError(f"{label} must be within [0,1]")
    if not isclose(start + cameo + dnp, 1.0, rel_tol=0.0, abs_tol=1e-6):
        raise MethodologyContractError("start/cameo/DNP probabilities must total 1.0")
    if minutes < 0.0 or minutes > 90.0:
        raise MethodologyContractError("xmins must be within [0,90]")
    evidence = str(evidence_class or "").strip().upper()
    if not evidence:
        raise MethodologyContractError("evidence_class is required")
    return {
        "status": "PASS",
        "p_available": round(1.0 - dnp, 6),
        "p_start": round(start, 6),
        "p_cameo": round(cameo, 6),
        "p_dnp": round(dnp, 6),
        "xmins": round(minutes, 3),
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
) -> dict[str, Any]:
    """Keep ONE-GW, 3GW and 5GW distinct; never collapse them into one unlabeled score."""
    required = {
        "ONE_GW": dict(one_gw),
        "3GW": dict(three_gw),
        "5GW": dict(five_gw),
    }
    for horizon, payload in required.items():
        if "expected_points_delta" not in payload:
            raise MethodologyContractError(f"{horizon}.expected_points_delta is required")
        payload["expected_points_delta"] = _finite_number(
            payload["expected_points_delta"],
            label=f"{horizon}.expected_points_delta",
        )
    return {
        "status": "PASS",
        "horizons": required,
        "collapsed": False,
        "one_gw_is_distinct": True,
        "three_gw_is_distinct": True,
        "five_gw_is_distinct": True,
    }


def build_transfer_economics(
    *,
    ft_used: int,
    hit_points: Any,
    future_ft_shadow_value: Any,
    buy_back_cost: Any,
    sell_value_loss: Any,
    price_movement_effect: Any,
    affordability_after: Any,
    itb_after: Any,
    concentration_risk: Any,
    correlation_risk: Any,
    exit_route: Mapping[str, Any] | None,
    reacquisition_plan: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Downstream transfer economics, explicitly separate from football score."""
    return {
        "status": "PASS",
        "decision_chain_stage": "TRANSFER_ECONOMICS",
        "included_in_football_score": False,
        "ft_used": int(ft_used),
        "hit_points": _finite_number(hit_points, label="hit_points"),
        "future_ft_shadow_value": _finite_number(
            future_ft_shadow_value, label="future_ft_shadow_value"
        ),
        "buy_back_cost": _finite_number(buy_back_cost, label="buy_back_cost"),
        "sell_value_loss": _finite_number(sell_value_loss, label="sell_value_loss"),
        "price_movement_effect": _finite_number(
            price_movement_effect, label="price_movement_effect"
        ),
        "affordability_after": affordability_after,
        "itb_after": itb_after,
        "concentration_risk": concentration_risk,
        "correlation_risk": correlation_risk,
        "exit_route": dict(exit_route or {}),
        "reacquisition_plan": dict(reacquisition_plan or {}),
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
    """Compose one user or optimizer route without biasing toward HOLD or TRANSFER."""
    sid = str(scenario_id or "").strip()
    state = str(scenario_state or "").strip().upper()
    action = str(action_state or "").strip().upper()
    route_kind = str(route_type or "NORMAL").strip().upper()
    if not sid:
        raise MethodologyContractError("scenario_id is required")
    if state not in SCENARIO_STATES:
        raise MethodologyContractError("invalid scenario state")
    if action not in ACTION_STATES:
        raise MethodologyContractError("invalid action state")
    if football_score.get("status") != "PASS":
        raise MethodologyContractError("football_score must pass")
    if horizons.get("status") != "PASS":
        raise MethodologyContractError("horizons must pass")
    if availability.get("status") != "PASS":
        raise MethodologyContractError("availability must pass")
    if transfer_economics.get("status") != "PASS":
        raise MethodologyContractError("transfer_economics must pass")
    if route_kind == "ONE_GW_PUNT":
        exit_route = transfer_economics.get("exit_route") or {}
        if not exit_route:
            raise MethodologyContractError("ONE_GW_PUNT requires an explicit GW+1 exit route")
    return {
        "status": "PASS",
        "scenario_id": sid,
        "scenario_state": state,
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
    }


def merge_active_and_optimizer_scenarios(
    *,
    active_user_scenarios: Sequence[Mapping[str, Any]],
    optimizer_alternatives: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Preserve active user routes while still exposing full-universe alternatives."""
    active = [dict(row) for row in active_user_scenarios if row.get("scenario_state") == "CONTEMPLATED"]
    optimizer = [dict(row) for row in optimizer_alternatives]
    by_id: dict[str, dict[str, Any]] = {}
    for row in optimizer:
        sid = str(row.get("scenario_id") or "").strip()
        if sid:
            by_id[sid] = row
    for row in active:
        sid = str(row.get("scenario_id") or "").strip()
        if sid:
            # User route visibility wins presentation inclusion only, never score/rank.
            by_id[sid] = row
    return {
        "status": "PASS",
        "active_user_scenario_ids": [row.get("scenario_id") for row in active],
        "optimizer_alternative_ids": [row.get("scenario_id") for row in optimizer],
        "scenarios": list(by_id.values()),
        "active_user_routes_preserved": True,
        "full_universe_alternatives_preserved": bool(optimizer),
        "user_mention_forces_recommendation": False,
    }
