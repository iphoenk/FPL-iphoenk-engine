from __future__ import annotations

"""Stage-3 downstream decision composition.

Consumes governed P1.2/P1.4/P1.7/P1.8 and Stage-2 projection outputs read-only.
It does not create player xPts, minutes, FDR, posterior, package-search, Monte
Carlo, lineup, or mini-league model authority.
"""

from copy import deepcopy
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "intelligence" / "v12_stage3_decision.json"
MODEL_OWNER = "V12_STAGE3_DECISION"


class Stage3DecisionError(ValueError):
    pass


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)
    return out if math.isfinite(out) else float(default)


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(default if value is None else value)
    except (TypeError, ValueError):
        return int(default)


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if payload.get("contract") != "V12_STAGE3_DOWNSTREAM_DECISION_V1":
        raise Stage3DecisionError("Stage3 decision contract drift")
    if payload.get("model_owner") != MODEL_OWNER:
        raise Stage3DecisionError("Stage3 decision owner drift")
    return payload


def _route_map(package_utility: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if package_utility.get("model_owner") != "V12_PACKAGE_UTILITY":
        raise Stage3DecisionError("Stage3 requires P1.2B package utility")
    return {
        str(row.get("route_id")): dict(row)
        for row in package_utility.get("routes") or []
        if isinstance(row, Mapping) and row.get("route_id") is not None
    }


def _gross_horizon(route: Mapping[str, Any], horizon: int) -> float | None:
    rows = [
        dict(row)
        for row in (route.get("football_route_utility") or {}).get("per_gw") or []
        if isinstance(row, Mapping)
    ]
    subset = rows[: int(horizon)]
    if len(subset) < int(horizon):
        return None
    if any(
        row.get("status") != "READY"
        or row.get("expected_fpl_points") is None
        for row in subset
    ):
        return None
    return sum(_f(row.get("expected_fpl_points")) for row in subset)


def football_horizon_deltas(
    route: Mapping[str, Any],
    hold: Mapping[str, Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for horizon, label in ((1, "GW+1"), (3, "3GW"), (5, "5GW")):
        value = _gross_horizon(route, horizon)
        base = _gross_horizon(hold, horizon)
        out[label] = {
            "gross_route_points": value,
            "gross_hold_points": base,
            "gross_delta_vs_hold": (
                None if value is None or base is None else value - base
            ),
        }
    return out


def select_material_football_route(
    package_utility: Mapping[str, Any],
) -> dict[str, Any]:
    """Select a comparator for P1.4 without becoming transfer authority."""
    routes = _route_map(package_utility)
    hold = routes.get("HOLD")
    if hold is None:
        raise Stage3DecisionError("HOLD route missing")
    candidates = []
    for route_id, route in routes.items():
        if route_id == "HOLD":
            continue
        horizons = football_horizon_deltas(route, hold)
        deltas = [
            (horizons[label] or {}).get("gross_delta_vs_hold")
            for label in ("GW+1", "3GW", "5GW")
        ]
        if any(value is None for value in deltas):
            continue
        candidates.append(
            {
                "route_id": route_id,
                "route": route,
                "horizons": horizons,
                "key": (
                    _f(deltas[0]),
                    min(_f(deltas[1]), _f(deltas[2])),
                    _f(deltas[1]),
                    _f(deltas[2]),
                    -int(route.get("transfer_count") or 0),
                ),
            }
        )
    if not candidates:
        return {
            "status": "NO_MATERIAL_CHANGE_ROUTE",
            "route_id": "HOLD",
            "selection_authority": False,
            "purpose": "MC_MATERIAL_COMPARATOR_ONLY",
        }
    candidates.sort(key=lambda row: row["key"], reverse=True)
    winner = candidates[0]
    return {
        "status": "AVAILABLE",
        "route_id": winner["route_id"],
        "gross_horizons": winner["horizons"],
        "selection_authority": False,
        "purpose": "MC_MATERIAL_COMPARATOR_ONLY",
        "final_transfer_decision": False,
        "full_p1_2_route_denominator": len(routes),
    }


def _pair_vs_hold(
    monte_carlo: Mapping[str, Any],
    route_id: str,
    *,
    horizon: int,
) -> dict[str, Any] | None:
    pairs = dict(monte_carlo.get("paired_outputs") or {})
    direct = pairs.get(f"{route_id}__VS__HOLD__H{int(horizon)}")
    if isinstance(direct, Mapping):
        return dict(direct)
    reverse = pairs.get(f"HOLD__VS__{route_id}__H{int(horizon)}")
    if not isinstance(reverse, Mapping):
        return None
    row = dict(reverse)
    for key in (
        "mean_difference",
        "Q10",
        "Q25",
        "median",
        "Q75",
        "Q90",
    ):
        if row.get(key) is not None:
            row[key] = -_f(row.get(key))
    q10, q25, q75, q90 = (
        row.get("Q10"),
        row.get("Q25"),
        row.get("Q75"),
        row.get("Q90"),
    )
    if all(value is not None for value in (q10, q25, q75, q90)):
        row["Q10"], row["Q25"], row["Q75"], row["Q90"] = (
            -_f(q90), -_f(q75), -_f(q25), -_f(q10)
        )
    if row.get("p_a_gt_b") is not None:
        row["p_a_gt_b"] = 1.0 - _f(row.get("p_a_gt_b"))
    if row.get("p_a_lt_b") is not None:
        row["p_a_lt_b"] = 1.0 - _f(row.get("p_a_lt_b"))
    return row


def build_robustness(
    monte_carlo: Mapping[str, Any],
    *,
    route_id: str,
) -> dict[str, Any]:
    cfg = load_config()
    thresholds = dict(cfg.get("decision_thresholds") or {})
    canonical = bool(
        monte_carlo.get("execution_state") == "EXECUTED"
        and monte_carlo.get("canonical_pass") is True
        and int(monte_carlo.get("actual_paths") or 0) >= 500_000
    )
    pair = _pair_vs_hold(monte_carlo, route_id, horizon=1)
    route_metrics = dict(
        ((monte_carlo.get("metrics") or {}).get(route_id) or {}).get("1") or {}
    )
    invariants = dict(
        (monte_carlo.get("sampling_diagnostics") or {}).get(
            "match_state_invariants"
        )
        or {}
    )
    p_outperform = None if pair is None else pair.get("p_a_gt_b")
    p_meaningful = (
        None
        if pair is None
        else pair.get("p_delta_ge_meaningful_threshold")
    )
    q10 = None if pair is None else pair.get("Q10")
    expected_regret = route_metrics.get("expected_regret")
    tests = {
        "canonical_mc": canonical,
        "match_state_invariants": invariants.get("status") == "PASS",
        "positive_mean": bool(
            pair is not None
            and pair.get("mean_difference") is not None
            and _f(pair.get("mean_difference"))
            > _f(thresholds.get("minimum_positive_mean_delta"), 0.0)
        ),
        "outperform_probability": bool(
            p_outperform is not None
            and _f(p_outperform)
            >= _f(thresholds.get("minimum_outperform_probability"), 0.58)
        ),
        "meaningful_upside_probability": bool(
            p_meaningful is not None
            and _f(p_meaningful)
            >= _f(
                thresholds.get("minimum_meaningful_upside_probability"),
                0.15,
            )
        ),
        "q10_downside": bool(
            q10 is not None
            and _f(q10)
            >= _f(thresholds.get("minimum_q10_delta"), -4.0)
        ),
        "expected_regret": bool(
            expected_regret is not None
            and _f(expected_regret)
            <= _f(thresholds.get("maximum_expected_regret"), 2.0)
        ),
    }
    classification = "ROBUST" if all(tests.values()) else "FRAGILE"
    return {
        "classification": classification,
        "tests": tests,
        "thresholds": thresholds,
        "pairwise_gw1": pair,
        "expected_regret": expected_regret,
        "stress_coverage": {
            "modelled": list(
                (cfg.get("sensitivity") or {}).get("modelled_stress") or []
            ),
            "external_or_unmodelled": list(
                (cfg.get("sensitivity") or {}).get(
                    "explicitly_unmodelled_or_external"
                )
                or []
            ),
            "unexpected_bench_cameo_early_sub": (
                "P1_1_PATH_STATE_SAMPLED"
            ),
            "creator_absent": "P1_4_PATH_CONDITIONED_LINKUP",
            "early_cs_loss": "P1_4_SHARED_SCORELINE",
            "opponent_shape_change": "REQUIRES_FRESH_DYNAMIC_FDR_SNAPSHOT",
            "penalty_taker_change": "REQUIRES_FRESH_STAGE2_ROLE_SNAPSHOT",
            "price_move": "SEPARATE_ECONOMIC_SOURCE",
        },
        "automatic_methodology_mutation": False,
    }


def build_price_uncertainty(
    predictor: Mapping[str, Any],
    *,
    relevant_element_ids: Sequence[int],
) -> dict[str, Any]:
    rows = {
        _i(row.get("id")): dict(row)
        for row in ((predictor.get("data") or {}).get("players") or [])
        if isinstance(row, Mapping) and _i(row.get("id")) > 0
    }
    relevant = []
    calibrated = True
    for element in sorted(set(int(x) for x in relevant_element_ids if int(x) > 0)):
        row = rows.get(element) or {}
        rise = row.get("p_rise_before_deadline")
        fall = row.get("p_fall_before_deadline")
        if rise is None and fall is None:
            calibrated = False
        relevant.append(
            {
                "element_id": element,
                "P_rise_before_deadline": rise,
                "P_fall_before_deadline": fall,
                "source_native_progress": row.get("price_change_percent"),
                "source_native_hourly_rate": row.get("price_change_hourly_rate"),
                "source_native_projections": deepcopy(
                    row.get("price_change_projections") or []
                ),
                "source_native_likelihood": (
                    (row.get("price_change_projections") or [{}])[0].get(
                        "likelihood"
                    )
                    if row.get("price_change_projections")
                    else None
                ),
            }
        )
    return {
        "status": (
            "AVAILABLE_CALIBRATED_PROBABILITIES"
            if relevant and calibrated
            else "UNAVAILABLE_NO_CALIBRATED_PROBABILITY_MAPPING"
        ),
        "rows": relevant,
        "likelihood_bucket_to_probability_mapping_used": False,
        "price_predictor_is_truth": False,
        "price_predictor_is_football_authority": False,
        "expected_cost_of_waiting": None,
        "reason": (
            None
            if relevant and calibrated
            else (
                "source-native predictor does not expose calibrated "
                "P(rise/fall before deadline); no probability is fabricated"
            )
        ),
    }


def build_sequential_rollout(
    package_utility: Mapping[str, Any],
    *,
    current_team: Mapping[str, Any],
    material_route_id: str,
) -> dict[str, Any]:
    cfg = load_config()
    routes = _route_map(package_utility)
    hold = routes.get("HOLD")
    route = routes.get(material_route_id)
    if hold is None or route is None:
        raise Stage3DecisionError("sequential rollout route missing")
    availability = dict(current_team.get("availability") or {})
    factual_state = {
        "squad": [
            int(row.get("element_id"))
            for row in current_team.get("players") or []
            if isinstance(row, Mapping) and row.get("element_id") is not None
        ],
        "bank": current_team.get("bank"),
        "free_transfers": current_team.get("free_transfers"),
        "chips": current_team.get("chips"),
        "prices": "CURRENT_OFFICIAL_NOW_COST_AVAILABLE",
        "availability": "STAGE2_P1_1_DISTRIBUTIONS",
        "fixtures": "STAGE2_GW_SPECIFIC_DYNAMIC_FDR",
        "private_finance_status": {
            "bank": availability.get("bank"),
            "free_transfers": availability.get(
                "free_transfers", "NOT_SUPPORTED"
            ),
            "selling_price": availability.get("selling_price"),
            "purchase_price": availability.get("purchase_price"),
            "chips": availability.get("chips"),
        },
    }
    complete = (
        current_team.get("bank") is not None
        and current_team.get("free_transfers") is not None
        and all(
            row.get("selling_price") is not None
            for row in current_team.get("players") or []
            if isinstance(row, Mapping)
        )
    )
    return {
        "status": "READY" if complete else "PARTIAL_FACTUAL_ECONOMICS",
        "state_t": factual_state,
        "actions_considered": ["HOLD", material_route_id],
        "transition": (
            "S_(t+1) ~ P(S_(t+1)|S_t,A_t); player football outcomes use "
            "P1.4 correlated paths; future transfer action is not precommitted"
        ),
        "current_action_fixed_squad_horizons": football_horizon_deltas(
            route, hold
        ),
        "approximation": deepcopy(cfg.get("sequential_rollout") or {}),
        "next_state_policy": (
            "REBUILD_FROM_FRESH_V6_AND_STAGE2_THEN_REOPTIMIZE"
        ),
        "independent_future_gw_sum_claimed_as_dynamic_programming": False,
        "act_blocked_by_missing_private_economics": not complete,
    }


def build_information_value(
    package_route: Mapping[str, Any],
    price_uncertainty: Mapping[str, Any],
) -> dict[str, Any]:
    info = dict(package_route.get("information_value") or {})
    if info.get("status") == "AVAILABLE" and info.get("value") is not None:
        voi = max(0.0, _f(info.get("value")))
        waiting = price_uncertainty.get("expected_cost_of_waiting")
        return {
            "status": "AVAILABLE" if waiting is not None else "PARTIAL",
            "VOI": voi,
            "expected_cost_of_waiting": waiting,
            "net_value_of_waiting": (
                None if waiting is None else voi - _f(waiting)
            ),
            "formula": (
                "E[Utility after new information] - E[Utility action now]"
            ),
            "drivers": deepcopy(info.get("drivers") or {}),
        }
    return {
        "status": "UNAVAILABLE_NO_CALIBRATED_CONDITIONAL_UTILITIES",
        "VOI": None,
        "expected_cost_of_waiting": price_uncertainty.get(
            "expected_cost_of_waiting"
        ),
        "net_value_of_waiting": None,
        "formula": "E[Utility after new information] - E[Utility action now]",
        "reason": (
            "conditional decision utilities for future information states "
            "are not available; VOI is not fabricated"
        ),
    }


def decide_action(
    *,
    material_route: Mapping[str, Any],
    robustness: Mapping[str, Any],
    monte_carlo: Mapping[str, Any],
    information_value: Mapping[str, Any],
) -> dict[str, Any]:
    route_id = str(material_route.get("route_id") or "HOLD")
    if route_id == "HOLD":
        return {
            "state": "WAIT",
            "reason": "NO_MATERIAL_CHANGE_ROUTE",
        }
    economics = dict(material_route.get("transfer_economics") or {})
    if economics.get("status") != "PASS":
        return {
            "state": "PREPARE",
            "reason": "PRIVATE_TRANSFER_ECONOMICS_UNRESOLVED",
        }
    pair = _pair_vs_hold(monte_carlo, route_id, horizon=1)
    if not pair or monte_carlo.get("canonical_pass") is not True:
        return {
            "state": "PREPARE",
            "reason": "CANONICAL_CORRELATED_MC_NOT_READY",
        }
    if robustness.get("classification") != "ROBUST":
        return {
            "state": "PREPARE",
            "reason": "DECISION_FRAGILE_UNDER_DISTRIBUTIONAL_GATE",
        }
    if information_value.get("status") != "AVAILABLE":
        return {
            "state": "PREPARE",
            "reason": "VALUE_OF_INFORMATION_NOT_RESOLVED",
        }
    voi = _f(information_value.get("VOI"))
    wait_cost = _f(information_value.get("expected_cost_of_waiting"))
    if voi > wait_cost:
        return {
            "state": "PREPARE",
            "reason": "VALUE_OF_INFORMATION_EXCEEDS_EXPECTED_COST_OF_WAITING",
        }
    return {
        "state": "ACT",
        "reason": (
            "POSITIVE_EXPECTED_UTILITY_OUTPERFORM_DOWNSIDE_ROBUSTNESS_"
            "ECONOMICS_AND_VOI_GATES_PASS"
        ),
    }


def compose_stage3_decision(
    *,
    package_utility: Mapping[str, Any],
    monte_carlo: Mapping[str, Any],
    mini_league_overlay: Mapping[str, Any] | None,
    current_team: Mapping[str, Any],
    price_predictor: Mapping[str, Any],
    material_route_id: str,
) -> dict[str, Any]:
    routes = _route_map(package_utility)
    route = routes.get(material_route_id)
    if route is None:
        raise Stage3DecisionError("material route absent from P1.2")
    relevant_ids = [
        _i(row.get("element"))
        for row in (route.get("players_out") or [])
        + (route.get("players_in") or [])
        if isinstance(row, Mapping)
    ]
    price = build_price_uncertainty(
        price_predictor,
        relevant_element_ids=relevant_ids,
    )
    sequential = build_sequential_rollout(
        package_utility,
        current_team=current_team,
        material_route_id=material_route_id,
    )
    robustness = build_robustness(
        monte_carlo,
        route_id=material_route_id,
    )
    voi = build_information_value(route, price)
    action = decide_action(
        material_route=route,
        robustness=robustness,
        monte_carlo=monte_carlo,
        information_value=voi,
    )
    return {
        "schema_version": 1,
        "model_owner": MODEL_OWNER,
        "status": "READY",
        "material_route_id": material_route_id,
        "action": action,
        "sequential_decision": sequential,
        "price_uncertainty": price,
        "value_of_information": voi,
        "regret_robustness": robustness,
        "mini_league": deepcopy(dict(mini_league_overlay or {})),
        "governance": deepcopy(load_config().get("governance") or {}),
        "limitations": {
            "private_finance": (
                sequential.get("status") != "READY"
            ),
            "price_probability": (
                price.get("status")
                != "AVAILABLE_CALIBRATED_PROBABILITIES"
            ),
            "future_transfer_policy": (
                "BOUNDED_REOPTIMIZATION_NOT_FULL_SEASON_DYNAMIC_PROGRAM"
            ),
        },
    }
