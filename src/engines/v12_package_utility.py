from __future__ import annotations

"""P1.2B V12-native canonical package utility.

P1.2A owns what legal routes exist. This module owns how those routes are
evaluated under existing Canonical V12 methodology. It does not enumerate a
candidate universe, implement Monte Carlo, or consume mini-league leverage.
"""

from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.engines.canonical_decision_methodology import (
    CANONICAL_AUTHORITY,
    CANONICAL_WEIGHTS,
    build_horizon_analysis,
    build_transfer_economics,
    derive_dynamic_ft_shadow_value,
    validate_methodology_weights,
)
from src.engines.v12_lineup_optimizer import optimize_lineup
from src.engines.v12_model_evidence import (
    bind_deterministic_output,
    build_model_run_binding,
    fingerprint,
    freeze_prediction,
    settle_frozen_record,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "intelligence" / "v12_package_utility.json"
CANONICAL_PATH = ROOT / CANONICAL_AUTHORITY
MODEL_OWNER = "V12_PACKAGE_UTILITY"
SEARCH_OWNER = "V12_PACKAGE_SEARCH"


class PackageUtilityError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)
    return out if math.isfinite(out) else float(default)


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if payload.get("contract") != "V12_CANONICAL_PACKAGE_UTILITY_V1":
        raise PackageUtilityError("P1.2B utility contract drift")
    if payload.get("model_owner") != MODEL_OWNER:
        raise PackageUtilityError("P1.2B utility owner drift")
    validate_methodology_weights(CANONICAL_WEIGHTS, authority=CANONICAL_AUTHORITY)
    governance = payload.get("governance") or {}
    if governance.get("search_utility_separated") is not True:
        raise PackageUtilityError("P1.2 search/utility boundary drift")
    if governance.get("legacy_fixed_change_penalty_forbidden") is not True:
        raise PackageUtilityError("legacy fixed change penalty is forbidden")
    if governance.get("fake_mc_probability_forbidden") is not True:
        raise PackageUtilityError("fake Monte Carlo probability is forbidden")
    return payload


def _canonical_sha256() -> str:
    return hashlib.sha256(CANONICAL_PATH.read_bytes()).hexdigest()


def _projection_map(projections: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(row.get("element") or -1): dict(row)
        for row in projections.get("players") or []
        if int(row.get("element") or -1) > 0
    }


def _gw_available(player: Mapping[str, Any], gw: int) -> bool:
    return any(int(row.get("gw") or -1) == int(gw) for row in player.get("xpts_by_gw") or [])


def _route_squad(route: Mapping[str, Any]) -> tuple[int, ...]:
    ids = tuple(sorted(int(value) for value in route.get("final_squad_elements") or []))
    if len(ids) != 15 or len(set(ids)) != 15:
        raise PackageUtilityError(f"route {route.get('route_id')} lost exact 15-player identity")
    return ids


def _validate_search(search_result: Mapping[str, Any]) -> list[dict[str, Any]]:
    if search_result.get("model_owner") != SEARCH_OWNER:
        raise PackageUtilityError("P1.2B requires P1.2A V12_PACKAGE_SEARCH input")
    routes = [dict(row) for row in search_result.get("routes") or []]
    if not routes:
        raise PackageUtilityError("P1.2A returned no routes")
    holds = [row for row in routes if row.get("route_id") == "HOLD"]
    if len(holds) != 1:
        raise PackageUtilityError("P1.2B requires exactly one HOLD baseline")
    if any(row.get("legal") is not True for row in routes):
        raise PackageUtilityError("illegal route reached P1.2B")
    ids = [str(row.get("route_id") or "") for row in routes]
    if len(ids) != len(set(ids)):
        raise PackageUtilityError("duplicate P1.2A route identity")
    return routes


def _lineup_decision(
    projections: Mapping[str, Any],
    squad_ids: Sequence[int],
    *,
    gw: int,
    generated_at: str,
) -> dict[str, Any]:
    pmap = _projection_map(projections)
    missing_players = [element for element in squad_ids if element not in pmap]
    if missing_players:
        return {
            "status": "UNAVAILABLE",
            "reason": "MISSING_PROJECTION_PLAYER",
            "missing_elements": missing_players,
            "gw": int(gw),
        }
    missing_gw = [element for element in squad_ids if not _gw_available(pmap[element], int(gw))]
    if missing_gw:
        return {
            "status": "UNAVAILABLE",
            "reason": "MISSING_HORIZON_PROJECTION",
            "missing_elements": missing_gw,
            "gw": int(gw),
        }
    decision = optimize_lineup(
        projections,
        list(squad_ids),
        planning_gw=int(gw),
        generated_at=generated_at,
    )
    score = dict(decision.get("lineup_score") or {})
    bench = dict(decision.get("bench") or {})
    captain = dict(decision.get("captain") or {})
    vice = dict(decision.get("vice_captain") or {})
    return {
        "status": "READY",
        "gw": int(gw),
        "route_utility": score.get("robust"),
        "expected_fpl_points": score.get("xpts_mean"),
        "distributional_downside": score.get("distributional_downside"),
        "supportable_upside": score.get("supportable_upside"),
        "expected_autosub_value": score.get("expected_autosub_value"),
        "cameo_blocking_cost": score.get("cameo_blocking_cost"),
        "formation": decision.get("formation"),
        "starting_xi": [
            int(row.get("element") or 0)
            for row in decision.get("starting_xi") or []
        ],
        "bench_gk": int(((bench.get("gk") or {}).get("element") or 0)),
        "bench_order": [
            int(row.get("element") or 0)
            for row in bench.get("order") or []
        ],
        "captain": int(captain.get("element") or 0),
        "vice_captain": int(vice.get("element") or 0),
        "captain_safe_pool_count": len(decision.get("captain_safe_pool") or []),
        "confidence": score.get("confidence"),
        "covariance_status": score.get("covariance_status"),
        "p1_7_model_evidence_output_fingerprint": (
            (decision.get("model_evidence_binding") or {}).get("output_fingerprint")
        ),
        "governance": {
            "p1_7_consumed_read_only": True,
            "p1_1_math_mutated": False,
            "p1_3_math_mutated": False,
            "p1_6_math_mutated": False,
            "p1_7_math_mutated": False,
        },
    }


def _cumulative_lineup_horizons(
    projections: Mapping[str, Any],
    squad_ids: Sequence[int],
    *,
    planning_gw: int,
    generated_at: str,
) -> dict[str, Any]:
    gw_rows = [
        _lineup_decision(
            projections,
            squad_ids,
            gw=int(planning_gw) + offset,
            generated_at=generated_at,
        )
        for offset in range(5)
    ]
    out: dict[str, Any] = {"per_gw": gw_rows}
    for horizon in (1, 2, 3, 5):
        subset = gw_rows[:horizon]
        if any(row.get("status") != "READY" for row in subset):
            out[str(horizon)] = {
                "status": "UNAVAILABLE",
                "reason": "INCOMPLETE_P1_7_HORIZON",
                "missing_gws": [
                    row.get("gw") for row in subset if row.get("status") != "READY"
                ],
            }
            continue
        out[str(horizon)] = {
            "status": "READY",
            "gross_route_utility": round(
                sum(_f(row.get("route_utility")) for row in subset), 6
            ),
            "expected_fpl_points": round(
                sum(_f(row.get("expected_fpl_points")) for row in subset), 6
            ),
            "distributional_downside": round(
                sum(_f(row.get("distributional_downside")) for row in subset), 6
            ),
            "supportable_upside": round(
                sum(_f(row.get("supportable_upside")) for row in subset), 6
            ),
            "expected_autosub_value": round(
                sum(_f(row.get("expected_autosub_value")) for row in subset), 6
            ),
            "cameo_blocking_cost": round(
                sum(_f(row.get("cameo_blocking_cost")) for row in subset), 6
            ),
        }
    return out


def _hit_economics(
    *,
    transfer_count: int,
    free_transfers: int | None,
    hit_cost_per_extra_transfer: int | None,
) -> dict[str, Any]:
    if transfer_count <= 0:
        return {
            "status": "RESOLVED",
            "free_transfers": free_transfers,
            "ft_consumed": 0,
            "hit_transfers": 0,
            "hit_points": 0,
        }
    if free_transfers is None:
        return {
            "status": "UNRESOLVED_FREE_TRANSFERS",
            "free_transfers": None,
            "ft_consumed": None,
            "hit_transfers": None,
            "hit_points": None,
        }
    free = max(0, int(free_transfers))
    hit_transfers = max(0, int(transfer_count) - free)
    if hit_transfers and hit_cost_per_extra_transfer is None:
        return {
            "status": "UNRESOLVED_HIT_COST",
            "free_transfers": free,
            "ft_consumed": min(int(transfer_count), free),
            "hit_transfers": hit_transfers,
            "hit_points": None,
        }
    hit_unit = 0 if hit_transfers == 0 else int(hit_cost_per_extra_transfer or 0)
    return {
        "status": "RESOLVED",
        "free_transfers": free,
        "ft_consumed": min(int(transfer_count), free),
        "hit_transfers": hit_transfers,
        "hit_points": hit_transfers * hit_unit,
    }


def _ft_shadow(
    route_id: str,
    *,
    transfer_count: int,
    future_frontier_by_route: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if transfer_count <= 0:
        return {
            "status": "PASS",
            "method": "HOLD_NO_FT_CONSUMED",
            "ft_shadow_value": 0.0,
            "fixed_universal_ft_value": False,
            "frontier_snapshot_id": "HOLD",
        }
    row = dict(future_frontier_by_route.get(route_id) or {})
    required = (
        "best_future_utility_with_ft",
        "best_future_utility_with_ft_consumed",
        "frontier_snapshot_id",
    )
    if not all(row.get(key) is not None for key in required):
        return {
            "status": "UNAVAILABLE",
            "method": "FUTURE_OPTIMIZATION_OPPORTUNITY_DIFFERENCE",
            "ft_shadow_value": None,
            "fixed_universal_ft_value": False,
            "frontier_snapshot_id": row.get("frontier_snapshot_id"),
        }
    return derive_dynamic_ft_shadow_value(
        best_future_utility_with_ft=row["best_future_utility_with_ft"],
        best_future_utility_with_ft_consumed=row[
            "best_future_utility_with_ft_consumed"
        ],
        frontier_snapshot_id=str(row["frontier_snapshot_id"]),
    )


def _information_value(
    route_id: str,
    information_value_by_route: Mapping[str, Any],
) -> dict[str, Any]:
    raw = information_value_by_route.get(route_id)
    if raw is None:
        return {
            "status": "UNAVAILABLE",
            "value": None,
            "drivers": {},
        }
    if isinstance(raw, Mapping):
        value = raw.get("value")
        if value is None:
            return {
                "status": str(raw.get("status") or "UNAVAILABLE"),
                "value": None,
                "drivers": {
                    str(k): deepcopy(v)
                    for k, v in raw.items()
                    if k not in {"value", "status"}
                },
            }
        numeric = _f(value)
        return {
            "status": "AVAILABLE",
            "value": round(max(0.0, numeric), 6),
            "drivers": {
                str(k): deepcopy(v)
                for k, v in raw.items()
                if k not in {"value", "status"}
            },
        }
    return {
        "status": "AVAILABLE",
        "value": round(max(0.0, _f(raw)), 6),
        "drivers": {},
    }


def _price_risk(route_id: str, price_risk_by_route: Mapping[str, Any]) -> dict[str, Any]:
    raw = price_risk_by_route.get(route_id)
    if raw is None:
        return {
            "status": "UNAVAILABLE",
            "football_authority": False,
            "detail": None,
        }
    return {
        "status": "AVAILABLE",
        "football_authority": False,
        "detail": deepcopy(raw),
    }


def _build_resolved_transfer_economics(
    route: Mapping[str, Any],
    *,
    hit: Mapping[str, Any],
    shadow: Mapping[str, Any],
) -> dict[str, Any]:
    transfer_count = int(route.get("transfer_count") or 0)
    if (
        route.get("economics_status") != "RESOLVED"
        or route.get("affordable") is not True
        or hit.get("status") != "RESOLVED"
        or shadow.get("status") != "PASS"
    ):
        return {
            "status": "PARTIAL",
            "decision_chain_stage": "TRANSFER_ECONOMICS",
            "included_in_football_score": False,
            "transfer_count": transfer_count,
            "hit": dict(hit),
            "ft_shadow": dict(shadow),
            "bank_after": route.get("bank_after"),
            "affordable": route.get("affordable"),
            "reason": "UNRESOLVED_EXECUTION_ECONOMICS",
        }
    return build_transfer_economics(
        ft_used=int(hit.get("ft_consumed") or 0),
        hit_points=float(hit.get("hit_points") or 0.0),
        buy_back_cost=0.0,
        sell_value_loss=0.0,
        price_movement_effect=0.0,
        affordability_after=True,
        itb_after=route.get("bank_after"),
        concentration_risk=None,
        correlation_risk="COVARIANCE_NOT_MODELLED_YET",
        exit_route=None,
        reacquisition_plan=None,
        ft_shadow=shadow,
        possible_future_ft=None,
        possible_future_hit=None,
        exit_security="NOT_ASSESSED",
    )


def _route_net_horizons(
    route_horizons: Mapping[str, Any],
    hold_horizons: Mapping[str, Any],
    *,
    execution_economics: Mapping[str, Any],
    rental: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    hit = (
        _f(execution_economics.get("hit_points"))
        if execution_economics.get("status") == "PASS"
        else None
    )
    shadow = (
        _f(execution_economics.get("future_ft_shadow_value"))
        if execution_economics.get("status") == "PASS"
        else None
    )
    labels = ((1, "GW+1"), (2, "2GW"), (3, "3GW"), (5, "5GW"))
    output: dict[str, Any] = {}
    canonical_inputs: dict[str, Any] = {}
    for horizon, label in labels:
        if horizon == 2 and not rental:
            continue
        route_row = dict(route_horizons.get(str(horizon)) or {})
        hold_row = dict(hold_horizons.get(str(horizon)) or {})
        if route_row.get("status") != "READY" or hold_row.get("status") != "READY":
            output[label] = {
                "status": "UNAVAILABLE",
                "gross_delta_vs_hold": None,
                "net_delta_vs_hold": None,
            }
            canonical_inputs[label] = {"expected_points_delta": 0.0, "status": "UNAVAILABLE"}
            continue
        gross_delta = _f(route_row.get("gross_route_utility")) - _f(
            hold_row.get("gross_route_utility")
        )
        expected_points_delta = _f(route_row.get("expected_fpl_points")) - _f(
            hold_row.get("expected_fpl_points")
        )
        net_delta = (
            gross_delta - float(hit) - float(shadow)
            if hit is not None and shadow is not None
            else None
        )
        output[label] = {
            "status": "READY" if net_delta is not None else "ECONOMICS_PARTIAL",
            "gross_route_utility": route_row.get("gross_route_utility"),
            "hold_gross_route_utility": hold_row.get("gross_route_utility"),
            "gross_delta_vs_hold": round(gross_delta, 6),
            "expected_points_delta_vs_hold": round(expected_points_delta, 6),
            "execution_cost_points": (
                round(float(hit) + float(shadow), 6)
                if hit is not None and shadow is not None
                else None
            ),
            "net_delta_vs_hold": (
                round(net_delta, 6) if net_delta is not None else None
            ),
            "distributional_downside": route_row.get("distributional_downside"),
            "supportable_upside": route_row.get("supportable_upside"),
        }
        canonical_inputs[label] = {
            "expected_points_delta": round(expected_points_delta, 6),
            "gross_utility_delta": round(gross_delta, 6),
            "net_utility_delta": (
                round(net_delta, 6) if net_delta is not None else None
            ),
        }
    analysis = build_horizon_analysis(
        one_gw=canonical_inputs["GW+1"],
        two_gw=canonical_inputs.get("2GW"),
        three_gw=canonical_inputs["3GW"],
        five_gw=canonical_inputs["5GW"],
        rental_or_exit=bool(rental),
    )
    return output, analysis


def _lineup_impact(
    route_horizons: Mapping[str, Any],
    hold_horizons: Mapping[str, Any],
) -> dict[str, Any]:
    route = (route_horizons.get("per_gw") or [{}])[0]
    hold = (hold_horizons.get("per_gw") or [{}])[0]
    if route.get("status") != "READY" or hold.get("status") != "READY":
        return {"status": "UNAVAILABLE"}
    route_xi = set(int(value) for value in route.get("starting_xi") or [])
    hold_xi = set(int(value) for value in hold.get("starting_xi") or [])
    return {
        "status": "READY",
        "formation": route.get("formation"),
        "hold_formation": hold.get("formation"),
        "xi_in": sorted(route_xi - hold_xi),
        "xi_out": sorted(hold_xi - route_xi),
        "bench_gk": route.get("bench_gk"),
        "bench_order": list(route.get("bench_order") or []),
        "hold_bench_order": list(hold.get("bench_order") or []),
        "bench_autosub_value_delta": round(
            _f(route.get("expected_autosub_value"))
            - _f(hold.get("expected_autosub_value")),
            6,
        ),
        "cameo_blocking_cost_delta": round(
            _f(route.get("cameo_blocking_cost"))
            - _f(hold.get("cameo_blocking_cost")),
            6,
        ),
        "captain": route.get("captain"),
        "hold_captain": hold.get("captain"),
        "vice_captain": route.get("vice_captain"),
        "hold_vice_captain": hold.get("vice_captain"),
        "captain_changed": route.get("captain") != hold.get("captain"),
        "vice_changed": route.get("vice_captain") != hold.get("vice_captain"),
        "captain_safe_pool_count": route.get("captain_safe_pool_count"),
    }


def _structural_impact(
    route: Mapping[str, Any],
    *,
    hit: Mapping[str, Any],
    lineup_impact: Mapping[str, Any],
) -> dict[str, Any]:
    free = hit.get("free_transfers")
    consumed = hit.get("ft_consumed")
    remaining = (
        max(0, int(free) - int(consumed))
        if free is not None and consumed is not None
        else None
    )
    return {
        "bank_after": route.get("bank_after"),
        "clubs_after": deepcopy(route.get("clubs_after") or {}),
        "position_structure_legal": True,
        "team_slots_preserved": True,
        "free_transfers_remaining_if_known": remaining,
        "future_transfer_flexibility": {
            "bank_after": route.get("bank_after"),
            "free_transfers_remaining": remaining,
            "numeric_composite_score": None,
        },
        "bench_quality": {
            "autosub_value_delta": lineup_impact.get("bench_autosub_value_delta"),
            "cameo_blocking_cost_delta": lineup_impact.get(
                "cameo_blocking_cost_delta"
            ),
        },
        "captaincy_options": {
            "captain_changed": lineup_impact.get("captain_changed"),
            "vice_changed": lineup_impact.get("vice_changed"),
            "safe_pool_count": lineup_impact.get("captain_safe_pool_count"),
        },
        "buy_back_difficulty": {
            "status": "FACTUAL_PRICE_GAP_ONLY",
            "outgoing_sell_values": [
                row.get("sell_value") for row in route.get("players_out") or []
            ],
            "no_future_price_prediction_embedded": True,
        },
    }


def _frontier(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    comparable = [
        dict(row)
        for row in rows
        if all(
            (row.get("horizons") or {}).get(label, {}).get("net_delta_vs_hold")
            is not None
            for label in ("GW+1", "3GW", "5GW")
        )
    ]
    keep: list[dict[str, Any]] = []
    for row in comparable:
        h = row.get("horizons") or {}
        dims = (
            _f(h["GW+1"].get("net_delta_vs_hold")),
            _f(h["3GW"].get("net_delta_vs_hold")),
            _f(h["5GW"].get("net_delta_vs_hold")),
            -int(row.get("transfer_count") or 0),
            -_f(h["GW+1"].get("distributional_downside")),
            _f(row.get("bank_after")),
        )
        dominated = False
        for other in comparable:
            if other.get("route_id") == row.get("route_id"):
                continue
            oh = other.get("horizons") or {}
            odims = (
                _f(oh["GW+1"].get("net_delta_vs_hold")),
                _f(oh["3GW"].get("net_delta_vs_hold")),
                _f(oh["5GW"].get("net_delta_vs_hold")),
                -int(other.get("transfer_count") or 0),
                -_f(oh["GW+1"].get("distributional_downside")),
                _f(other.get("bank_after")),
            )
            if all(left >= right - 1e-12 for left, right in zip(odims, dims)) and any(
                left > right + 1e-12 for left, right in zip(odims, dims)
            ):
                dominated = True
                break
        if not dominated:
            keep.append(
                {
                    "route_id": row.get("route_id"),
                    "dimensions": {
                        "gw_plus_1_net": dims[0],
                        "three_gw_net": dims[1],
                        "five_gw_net": dims[2],
                        "transfer_count": int(row.get("transfer_count") or 0),
                        "gw_plus_1_downside": _f(
                            h["GW+1"].get("distributional_downside")
                        ),
                        "bank_after": row.get("bank_after"),
                    },
                }
            )
    keep.sort(
        key=lambda row: (
            -_f((row.get("dimensions") or {}).get("gw_plus_1_net")),
            str(row.get("route_id") or ""),
        )
    )
    return {
        "authority": "REPRESENTATION_ONLY",
        "scoring_authority": False,
        "route_set_mutated": False,
        "dimensions": list((load_config().get("frontier") or {}).get("dimensions") or []),
        "count": len(keep),
        "routes": keep,
    }


def _selection_key(row: Mapping[str, Any]) -> tuple[float, float, float, float, float]:
    horizons = row.get("horizons") or {}
    gw1 = _f((horizons.get("GW+1") or {}).get("net_delta_vs_hold"), -1e12)
    gw3 = _f((horizons.get("3GW") or {}).get("net_delta_vs_hold"), -1e12)
    gw5 = _f((horizons.get("5GW") or {}).get("net_delta_vs_hold"), -1e12)
    return (
        gw1,
        min(gw3, gw5),
        gw3,
        gw5,
        -float(int(row.get("transfer_count") or 0)),
    )


def _qualifies_change(row: Mapping[str, Any]) -> bool:
    if int(row.get("transfer_count") or 0) <= 0:
        return False
    horizons = row.get("horizons") or {}
    required = [horizons.get(label) or {} for label in ("GW+1", "3GW", "5GW")]
    if any(item.get("net_delta_vs_hold") is None for item in required):
        return False
    return (
        _f(required[0].get("net_delta_vs_hold")) > 0.0
        and _f(required[1].get("net_delta_vs_hold")) >= 0.0
        and _f(required[2].get("net_delta_vs_hold")) >= 0.0
    )


def _action(selected: Mapping[str, Any]) -> dict[str, Any]:
    if str(selected.get("route_id")) == "HOLD":
        return {
            "football_action": "HOLD",
            "operational_action": "WAIT",
            "reason": "NO_CANONICAL_CHANGE_ROUTE_DOMINATES_HOLD_MAPPING",
        }
    economics = selected.get("transfer_economics") or {}
    if economics.get("status") != "PASS":
        return {
            "football_action": "CHANGE_CANDIDATE",
            "operational_action": "PREPARE",
            "reason": "EXECUTION_ECONOMICS_UNRESOLVED",
        }
    info = selected.get("information_value") or {}
    if info.get("status") != "AVAILABLE" or info.get("value") is None:
        return {
            "football_action": "CHANGE_CANDIDATE",
            "operational_action": "PREPARE",
            "reason": "INFORMATION_VALUE_UNAVAILABLE",
        }
    gw1_edge = _f(
        ((selected.get("horizons") or {}).get("GW+1") or {}).get(
            "net_delta_vs_hold"
        )
    )
    if _f(info.get("value")) > gw1_edge:
        return {
            "football_action": "CHANGE_CANDIDATE",
            "operational_action": "WAIT",
            "reason": "VALUE_OF_WAITING_EXCEEDS_CURRENT_GW_PLUS_1_EDGE",
        }
    return {
        "football_action": "CHANGE",
        "operational_action": "ACT",
        "reason": "RESOLVED_CANONICAL_EDGE_EXCEEDS_INFORMATION_VALUE",
    }


def _model_evidence_binding(
    *,
    search_result: Mapping[str, Any],
    projections: Mapping[str, Any],
    output_core: Mapping[str, Any],
    planning_gw: int,
    generated_at: str,
) -> dict[str, Any]:
    cfg = load_config()
    search_fp = fingerprint(
        {
            "model_owner": search_result.get("model_owner"),
            "search_authority": search_result.get("search_authority"),
            "eligible_universe_count": search_result.get("eligible_universe_count"),
            "searched_universe_count": search_result.get("searched_universe_count"),
            "routes": [
                {
                    "route_id": row.get("route_id"),
                    "final_squad_elements": row.get("final_squad_elements"),
                    "bank_after": row.get("bank_after"),
                    "affordable": row.get("affordable"),
                    "economics_status": row.get("economics_status"),
                }
                for row in search_result.get("routes") or []
            ],
        }
    )
    projection_fp = fingerprint(
        {
            "planning_gw": planning_gw,
            "generated_at": projections.get("generated_at"),
            "players": [
                {
                    "element": row.get("element"),
                    "xmins": row.get("xmins"),
                    "xpts_by_gw": row.get("xpts_by_gw"),
                    "tactical_role_component": row.get("tactical_role_component"),
                }
                for row in projections.get("players") or []
            ],
        }
    )
    binding = build_model_run_binding(
        input_snapshot_id=f"p1.2b:{search_fp[:12]}:{projection_fp[:12]}",
        factual_snapshot_timestamps={
            "projections_generated_at": projections.get("generated_at") or generated_at,
        },
        factual_artifact_fingerprints={
            "p1_2a_search": search_fp,
            "projections": projection_fp,
        },
        deterministic_factual_inputs={
            "planning_gw": int(planning_gw),
            "search_fingerprint": search_fp,
            "projection_fingerprint": projection_fp,
        },
        model_version=str(cfg.get("model_version")),
        feature_version=str(cfg.get("feature_version")),
        parameter_version=str(cfg.get("parameter_version")),
        parameters={
            "horizons": cfg.get("horizons"),
            "economics": cfg.get("economics"),
            "action": cfg.get("action"),
        },
        calibration_version=str(cfg.get("calibration_version")),
        calibration_cutoff=cfg.get("calibration_cutoff"),
        calibration_parameters={
            "automatic_retuning": False,
            "hidden_horizon_weights": False,
        },
        generated_at=generated_at,
        planning_gw=int(planning_gw),
        canonical_v12_revision=_canonical_sha256(),
    )
    bound = bind_deterministic_output(binding, output_core)
    return {
        "authority": False,
        **binding,
        "output_fingerprint": bound["output_fingerprint"],
        "raw_v6_payload_duplicated": False,
        "repository_python_execution_claimed": False,
    }


def evaluate_packages(
    *,
    search_result: Mapping[str, Any],
    projections: Mapping[str, Any],
    free_transfers: int | None,
    hit_cost_per_extra_transfer: int | None,
    future_frontier_by_route: Mapping[str, Mapping[str, Any]] | None = None,
    information_value_by_route: Mapping[str, Any] | None = None,
    price_risk_by_route: Mapping[str, Any] | None = None,
    rental_route_ids: Sequence[str] | None = None,
    explicit_exit_routes: Mapping[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    cfg = load_config()
    generated = generated_at or _now()
    routes = _validate_search(search_result)
    planning_gw = int(projections.get("planning_gw") or 1)
    future = future_frontier_by_route or {}
    info_map = information_value_by_route or {}
    price_map = price_risk_by_route or {}
    rentals = {str(value) for value in (rental_route_ids or [])}
    exits = explicit_exit_routes or {}

    hold_route = next(row for row in routes if row.get("route_id") == "HOLD")
    hold_squad = _route_squad(hold_route)
    lineup_cache: dict[tuple[tuple[int, ...], int], dict[str, Any]] = {}

    def route_lineups(route: Mapping[str, Any]) -> dict[str, Any]:
        squad = _route_squad(route)
        key_base = tuple(squad)
        rows = []
        for offset in range(5):
            key = (key_base, planning_gw + offset)
            if key not in lineup_cache:
                lineup_cache[key] = _lineup_decision(
                    projections,
                    squad,
                    gw=planning_gw + offset,
                    generated_at=generated,
                )
            rows.append(lineup_cache[key])
        output: dict[str, Any] = {"per_gw": rows}
        for horizon in (1, 2, 3, 5):
            subset = rows[:horizon]
            if any(row.get("status") != "READY" for row in subset):
                output[str(horizon)] = {
                    "status": "UNAVAILABLE",
                    "reason": "INCOMPLETE_P1_7_HORIZON",
                    "missing_gws": [
                        row.get("gw")
                        for row in subset
                        if row.get("status") != "READY"
                    ],
                }
            else:
                output[str(horizon)] = {
                    "status": "READY",
                    "gross_route_utility": round(
                        sum(_f(row.get("route_utility")) for row in subset), 6
                    ),
                    "expected_fpl_points": round(
                        sum(_f(row.get("expected_fpl_points")) for row in subset), 6
                    ),
                    "distributional_downside": round(
                        sum(_f(row.get("distributional_downside")) for row in subset), 6
                    ),
                    "supportable_upside": round(
                        sum(_f(row.get("supportable_upside")) for row in subset), 6
                    ),
                    "expected_autosub_value": round(
                        sum(_f(row.get("expected_autosub_value")) for row in subset), 6
                    ),
                    "cameo_blocking_cost": round(
                        sum(_f(row.get("cameo_blocking_cost")) for row in subset), 6
                    ),
                }
        return output

    hold_lineups = route_lineups(hold_route)
    evaluated: list[dict[str, Any]] = []
    for route in routes:
        route_id = str(route.get("route_id"))
        transfer_count = int(route.get("transfer_count") or 0)
        lineups = hold_lineups if route_id == "HOLD" else route_lineups(route)
        hit = _hit_economics(
            transfer_count=transfer_count,
            free_transfers=free_transfers,
            hit_cost_per_extra_transfer=hit_cost_per_extra_transfer,
        )
        shadow = _ft_shadow(
            route_id,
            transfer_count=transfer_count,
            future_frontier_by_route=future,
        )
        economics = _build_resolved_transfer_economics(
            route,
            hit=hit,
            shadow=shadow,
        )
        rental = route_id in rentals
        horizons, canonical_horizon_analysis = _route_net_horizons(
            lineups,
            hold_lineups,
            execution_economics=economics,
            rental=rental,
        )
        lineup_impact = _lineup_impact(lineups, hold_lineups)
        information_value = _information_value(route_id, info_map)
        price_risk = _price_risk(route_id, price_map)
        row = {
            "route_id": route_id,
            "classification": "HOLD" if transfer_count == 0 else "CHANGE",
            "players_out": deepcopy(route.get("players_out") or []),
            "players_in": deepcopy(route.get("players_in") or []),
            "transfer_count": transfer_count,
            "ft_usage": {
                "free_transfers": hit.get("free_transfers"),
                "ft_consumed": hit.get("ft_consumed"),
                "hit_transfers": hit.get("hit_transfers"),
            },
            "hit": hit.get("hit_points"),
            "hit_status": hit.get("status"),
            "bank_after": route.get("bank_after"),
            "affordable": route.get("affordable"),
            "search_authority": route.get("search_authority"),
            "football_route_utility": {
                "source": "P1.7_V12_LINEUP_OPTIMIZER",
                "per_gw": deepcopy(lineups.get("per_gw") or []),
                "does_not_include_transfer_economics": True,
            },
            "horizons": horizons,
            "canonical_horizon_analysis": canonical_horizon_analysis,
            "lineup_impact": lineup_impact,
            "bench_impact": {
                "autosub_value_delta": lineup_impact.get("bench_autosub_value_delta"),
                "cameo_blocking_cost_delta": lineup_impact.get(
                    "cameo_blocking_cost_delta"
                ),
            },
            "captain_impact": {
                "captain": lineup_impact.get("captain"),
                "hold_captain": lineup_impact.get("hold_captain"),
                "vice_captain": lineup_impact.get("vice_captain"),
                "hold_vice_captain": lineup_impact.get("hold_vice_captain"),
                "captain_changed": lineup_impact.get("captain_changed"),
                "vice_changed": lineup_impact.get("vice_changed"),
            },
            "structural_impact": _structural_impact(
                route,
                hit=hit,
                lineup_impact=lineup_impact,
            ),
            "uncertainty": {
                "source": "GENUINE_P1_7_DISTRIBUTIONAL_SURFACE",
                "p_beats_hold": "NOT_COMPUTED",
                "monte_carlo": "NOT_RUN",
                "cross_route_covariance": "COVARIANCE_NOT_MODELLED_YET",
                "gw_plus_1_downside": (
                    (horizons.get("GW+1") or {}).get("distributional_downside")
                ),
                "gw_plus_1_upside": (
                    (horizons.get("GW+1") or {}).get("supportable_upside")
                ),
            },
            "robustness": {
                "mean_only": False,
                "lineup_distribution_consumed": True,
                "autosub_option_value_consumed": True,
                "cameo_blocking_consumed": True,
                "captain_vice_consumed": True,
                "p_beats_hold_not_fabricated": True,
            },
            "expected_regret": None,
            "information_value": information_value,
            "price_economic_risk": price_risk,
            "execution_confidence": (
                "HIGH"
                if economics.get("status") == "PASS"
                and information_value.get("status") == "AVAILABLE"
                else "PARTIAL"
            ),
            "reversal_triggers": {
                "fresh_lineup_information": True,
                "injury_news": True,
                "material_role_change": True,
                "price_or_affordability_change": True,
                "future_ft_frontier_change": True,
            },
            "transfer_economics": economics,
            "dynamic_ft_shadow": shadow,
            "rental": {
                "is_rental": rental,
                "two_gw_published": rental,
                "fresh_reoptimization_next_gw": rental,
                "precommitted_exit": route_id in exits,
                "explicit_exit_route": deepcopy(exits.get(route_id)),
                "automatic_exit_assumed": False,
            },
            "governance": {
                "search_route_consumed_exactly": True,
                "legacy_horizon_weight_used": False,
                "legacy_change_penalty_0_20_used": False,
                "price_predictor_is_football_authority": False,
                "mini_league_consumed": False,
                "monte_carlo_used": False,
            },
        }
        evaluated.append(row)

    resolved_gw1 = [
        _f(((row.get("horizons") or {}).get("GW+1") or {}).get("net_delta_vs_hold"))
        for row in evaluated
        if ((row.get("horizons") or {}).get("GW+1") or {}).get("net_delta_vs_hold")
        is not None
    ]
    best_gw1 = max(resolved_gw1, default=0.0)
    for row in evaluated:
        value = ((row.get("horizons") or {}).get("GW+1") or {}).get(
            "net_delta_vs_hold"
        )
        row["expected_regret"] = (
            None
            if value is None
            else round(max(0.0, best_gw1 - _f(value)), 6)
        )

    hold_eval = next(row for row in evaluated if row.get("route_id") == "HOLD")
    candidates = [row for row in evaluated if _qualifies_change(row)]
    candidates.sort(key=_selection_key, reverse=True)
    selected = candidates[0] if candidates else hold_eval
    action = _action(selected)
    package_frontier = _frontier(evaluated)

    output_core = {
        "schema_version": 1,
        "model": cfg.get("model_id"),
        "model_owner": MODEL_OWNER,
        "planning_gw": planning_gw,
        "search_authority": search_result.get("search_authority"),
        "search_route_denominator": search_result.get("route_denominator"),
        "hold_route_id": "HOLD",
        "routes": evaluated,
        "package_frontier": package_frontier,
        "selected_route_id": selected.get("route_id"),
        "selected_route": deepcopy(selected),
        "decision": action,
        "selection_mapping": (
            (cfg.get("horizons") or {}).get("selection_mapping")
        ),
        "methodology": {
            "canonical_authority": CANONICAL_AUTHORITY,
            "weights": dict(CANONICAL_WEIGHTS),
            "weights_unchanged": True,
            "horizons_collapsed": False,
            "legacy_10_15gw_used": False,
            "legacy_fixed_change_penalty_used": False,
            "dynamic_ft_shadow_method": (
                "FUTURE_OPTIMIZATION_OPPORTUNITY_DIFFERENCE"
            ),
            "p_beats_hold": "NOT_COMPUTED",
            "monte_carlo": "NOT_RUN",
            "mini_league": "NOT_CONSUMED",
        },
        "governance": {
            "p1_2a_search_owner": SEARCH_OWNER,
            "p1_2b_utility_owner": MODEL_OWNER,
            "search_and_utility_separate": True,
            "hold_mandatory": True,
            "p1_1_math_mutated": False,
            "p1_3_math_mutated": False,
            "p1_6_math_mutated": False,
            "p1_7_math_mutated": False,
            "methodology_weights_20_25_30_25_unchanged": True,
            "v6_mutated": False,
            "scheduler_changed": False,
            "authority_added": False,
            "monte_carlo_started": False,
            "mini_league_overlay_started": False,
        },
    }
    evidence = _model_evidence_binding(
        search_result=search_result,
        projections=projections,
        output_core=output_core,
        planning_gw=planning_gw,
        generated_at=generated,
    )
    return {
        "generated_at": generated,
        **output_core,
        "model_evidence_binding": evidence,
    }


def build_package_frontier(utility_output: Mapping[str, Any]) -> dict[str, Any]:
    return _frontier(utility_output.get("routes") or [])


def freeze_package_decision(
    decision: Mapping[str, Any],
    *,
    deadline_time: Any,
    frozen_at: Any,
    existing_record: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    binding = dict(decision.get("model_evidence_binding") or {})
    selected = dict(decision.get("selected_route") or {})
    snapshot = {
        "captured_at": decision.get("generated_at"),
        "decision_kind": "P1.2_PACKAGE_DECISION",
        "selected_route_id": decision.get("selected_route_id"),
        "decision": deepcopy(decision.get("decision")),
        "hold_route_id": decision.get("hold_route_id"),
        "selected_route": selected,
        "alternatives_considered": [
            {
                "route_id": row.get("route_id"),
                "players_out": deepcopy(row.get("players_out") or []),
                "players_in": deepcopy(row.get("players_in") or []),
                "horizons": deepcopy(row.get("horizons") or {}),
                "expected_regret": row.get("expected_regret"),
                "information_value": deepcopy(row.get("information_value")),
                "transfer_economics": deepcopy(row.get("transfer_economics")),
            }
            for row in decision.get("routes") or []
        ],
        "package_frontier": deepcopy(decision.get("package_frontier")),
        "model_evidence_output_fingerprint": binding.get("output_fingerprint"),
    }
    return freeze_prediction(
        model_binding=binding,
        deadline_time=deadline_time,
        forecast_generated_at=decision.get("generated_at"),
        frozen_at=frozen_at,
        forecast_rows=[],
        decision_snapshot=snapshot,
        existing_record=existing_record,
    )


def settle_package_decision(
    frozen_record: Mapping[str, Any],
    *,
    decision_outcome_evidence: Mapping[str, Any],
    event_finished: bool,
    settled_at: Any,
    actual_rows: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    return settle_frozen_record(
        frozen_record,
        actual_rows=actual_rows,
        decision_outcome_evidence=decision_outcome_evidence,
        event_finished=event_finished,
        settled_at=settled_at,
    )


def compare_legacy_package(
    *,
    native_search: Mapping[str, Any],
    native_utility: Mapping[str, Any],
    legacy_optimizer: Mapping[str, Any],
) -> dict[str, Any]:
    native_ids = {
        str(row.get("route_id"))
        for row in native_search.get("routes") or []
    }
    legacy_rows = [legacy_optimizer.get("hold")] + list(
        legacy_optimizer.get("packages") or []
    )
    legacy_ids = {
        str(row.get("id"))
        for row in legacy_rows
        if isinstance(row, Mapping) and row.get("id") is not None
    }
    regressions: list[str] = []
    if "HOLD" not in native_ids:
        regressions.append("NATIVE_HOLD_MISSING")
    selected = dict(native_utility.get("selected_route") or {})
    if selected.get("route_id") not in native_ids:
        regressions.append("SELECTED_ROUTE_NOT_IN_NATIVE_SEARCH")
    if selected.get("affordable") is False:
        regressions.append("SELECTED_ROUTE_UNAFFORDABLE")

    same_domain = bool(legacy_ids) and legacy_ids <= native_ids
    if regressions:
        classification = "UNEXPECTED_REGRESSION"
    elif legacy_ids and native_ids == legacy_ids:
        classification = "SEARCH_EQUIVALENT"
    elif same_domain:
        classification = "CANONICAL_UTILITY_REPLACEMENT"
    elif any(
        (row.get("dynamic_ft_shadow") or {}).get("status") == "PASS"
        and int(row.get("transfer_count") or 0) > 0
        for row in native_utility.get("routes") or []
    ):
        classification = "FT_ECONOMICS_IMPROVEMENT"
    else:
        classification = "HORIZON_SEPARATION_IMPROVEMENT"
    return {
        "classification": classification,
        "unexpected_regressions": regressions,
        "unexpected_regression_count": len(regressions),
        "search_common_domain_legacy_subset_of_native": same_domain,
        "native_route_count": len(native_ids),
        "legacy_published_route_count": len(legacy_ids),
        "legacy_utility_equivalence_required": False,
        "classification_taxonomy": [
            "SEARCH_EQUIVALENT",
            "CANONICAL_UTILITY_REPLACEMENT",
            "FT_ECONOMICS_IMPROVEMENT",
            "HORIZON_SEPARATION_IMPROVEMENT",
            "LINEUP_INTEGRATION_IMPROVEMENT",
            "BUG_FIX",
            "UNEXPECTED_REGRESSION",
        ],
    }
