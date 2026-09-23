from __future__ import annotations

"""P1.2B V12-native canonical package utility.

P1.2A owns what legal routes exist. This module owns how those routes are
evaluated under existing Canonical V12 methodology. It does not enumerate a
candidate universe, implement Monte Carlo, or consume mini-league leverage.
"""

from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence

from src.engines.canonical_decision_methodology import (
    CANONICAL_AUTHORITY,
    CANONICAL_WEIGHTS,
    build_horizon_analysis,
    build_transfer_economics,
    derive_dynamic_ft_shadow_value,
    validate_methodology_weights,
)
from src.engines.v12_lineup_optimizer import optimize_lineup, prime_player_surface_cache
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
    _perf_sink: list[float] | None = None,
) -> dict[str, Any]:
    gw_rows: list[dict[str, Any]] = []
    for offset in range(5):
        started = time.perf_counter()
        gw_rows.append(
            _lineup_decision(
                projections,
                squad_ids,
                gw=int(planning_gw) + offset,
                generated_at=generated_at,
            )
        )
        if _perf_sink is not None:
            _perf_sink.append(time.perf_counter() - started)
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
    projection_by_id: Mapping[int, Mapping[str, Any]],
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
    reacquisition_now = 0.0
    sell_total = 0.0
    for outgoing in route.get("players_out") or []:
        element = int(outgoing.get("element") or 0)
        projection = projection_by_id.get(element) or {}
        reacquisition_now += _f(projection.get("now_cost"))
        sell_total += _f(outgoing.get("sell_value"))
    buy_back_gap = max(0.0, reacquisition_now - sell_total)
    economics = build_transfer_economics(
        ft_used=int(hit.get("ft_consumed") or 0),
        hit_points=float(hit.get("hit_points") or 0.0),
        buy_back_cost=buy_back_gap,
        sell_value_loss=buy_back_gap,
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
    economics["buy_back_cost_semantics"] = (
        "CURRENT_OFFICIAL_REACQUISITION_PRICE_MINUS_AUTHENTICATED_SELL_VALUE"
    )
    economics["price_movement_effect_semantics"] = (
        "NO_FUTURE_PRICE_PREDICTION_EMBEDDED"
    )
    return economics


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



_P1_2B_WORKER_CONTEXT: tuple[Mapping[str, Any], int, str] | None = None


def _init_p1_2b_lineup_worker(
    projections: Mapping[str, Any],
    planning_gw: int,
    generated_at: str,
    material_elements: Sequence[int],
) -> None:
    """Bind immutable read-only P1.7 inputs once per worker process."""
    global _P1_2B_WORKER_CONTEXT
    prime_player_surface_cache(
        projections,
        planning_gws=range(
            int(planning_gw),
            int(planning_gw) + 5,
        ),
        material_elements=material_elements,
    )
    _P1_2B_WORKER_CONTEXT = (
        projections,
        int(planning_gw),
        str(generated_at),
    )


def _p1_2b_route_lineups_worker(
    item: tuple[str, tuple[int, ...]],
) -> tuple[
    str,
    tuple[int, ...],
    dict[str, Any],
    float,
    tuple[float, ...],
]:
    """Evaluate one exact route and return non-authoritative timing proof."""
    if _P1_2B_WORKER_CONTEXT is None:
        raise PackageUtilityError("P1.2B lineup worker context is not initialized")
    route_id, squad = item
    projections, planning_gw, generated_at = _P1_2B_WORKER_CONTEXT
    gw_elapsed: list[float] = []
    started = time.perf_counter()
    output = _cumulative_lineup_horizons(
        projections,
        squad,
        planning_gw=planning_gw,
        generated_at=generated_at,
        _perf_sink=gw_elapsed,
    )
    elapsed = time.perf_counter() - started
    return (
        str(route_id),
        tuple(squad),
        output,
        elapsed,
        tuple(gw_elapsed),
    )


def _perf_distribution(values: Sequence[float]) -> dict[str, Any]:
    rows = sorted(float(value) for value in values)
    if not rows:
        return {"count": 0}
    def percentile(fraction: float) -> float:
        index = min(
            len(rows) - 1,
            max(0, int(round((len(rows) - 1) * fraction))),
        )
        return rows[index]
    return {
        "count": len(rows),
        "min": round(rows[0], 6),
        "p50": round(percentile(0.50), 6),
        "p95": round(percentile(0.95), 6),
        "max": round(rows[-1], 6),
        "mean": round(sum(rows) / len(rows), 6),
    }


def _materialize_route_lineups(
    routes: Sequence[Mapping[str, Any]],
    projections: Mapping[str, Any],
    *,
    planning_gw: int,
    generated_at: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Materialize every P1.2A route with exact P1.7 math.

    Large full-universe route sets are split across bounded Linux worker
    processes. Each worker calls the same canonical P1.7 owner; this is only an
    execution strategy and never a second lineup model, lossy route pruning, or
    alternate decision authority.
    """
    cfg = load_config()
    perf_cfg = dict(cfg.get("performance") or {})
    min_routes = max(
        1,
        int(perf_cfg.get("parallel_lineup_min_routes") or 64),
    )
    max_workers = max(
        1,
        int(perf_cfg.get("parallel_lineup_max_workers") or 4),
    )
    requested_chunks_per_worker = max(
        1,
        int(perf_cfg.get("parallel_chunks_per_worker") or 8),
    )

    route_squads = [
        (str(route.get("route_id") or ""), _route_squad(route))
        for route in routes
    ]
    if any(not route_id for route_id, _ in route_squads):
        raise PackageUtilityError("P1.2B route lost route_id")

    # Preserve every route while avoiding duplicate P1.7 work if two exact
    # search routes happen to resolve to the same final 15-player squad.
    unique_by_squad: dict[tuple[int, ...], str] = {}
    for route_id, squad in route_squads:
        unique_by_squad.setdefault(tuple(squad), route_id)
    unique_items = [
        (route_id, squad)
        for squad, route_id in unique_by_squad.items()
    ]
    material_elements = tuple(
        sorted(
            {
                int(element)
                for _, squad in unique_items
                for element in squad
            }
        )
    )

    cpu_count = max(1, int(os.cpu_count() or 1))
    workers = min(max_workers, cpu_count, max(1, len(unique_items)))
    use_parallel = bool(
        sys.platform.startswith("linux")
        and workers > 1
        and len(unique_items) >= min_routes
    )

    by_squad: dict[tuple[int, ...], dict[str, Any]] = {}
    squad_elapsed: list[float] = []
    gw_elapsed: list[float] = []
    materialization_started = time.perf_counter()
    if use_parallel:
        fork_context = mp.get_context("fork")
        chunksize = max(
            1,
            len(unique_items)
            // max(1, workers * requested_chunks_per_worker),
        )
        print(
            "[P1_2B_PERF] exact P1.7 route materialization "
            f"mode=process_pool routes={len(route_squads)} "
            f"unique_squads={len(unique_items)} workers={workers} "
            f"chunksize={chunksize}",
            flush=True,
        )
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=fork_context,
            initializer=_init_p1_2b_lineup_worker,
            initargs=(
                projections,
                planning_gw,
                generated_at,
                material_elements,
            ),
        ) as executor:
            for _, squad, output, elapsed, route_gw_elapsed in executor.map(
                _p1_2b_route_lineups_worker,
                unique_items,
                chunksize=chunksize,
            ):
                by_squad[tuple(squad)] = output
                squad_elapsed.append(float(elapsed))
                gw_elapsed.extend(float(value) for value in route_gw_elapsed)
        execution_mode = "PROCESS_POOL_EXACT_P1_7"
    else:
        print(
            "[P1_2B_PERF] exact P1.7 route materialization "
            f"mode=sequential routes={len(route_squads)} "
            f"unique_squads={len(unique_items)} workers=1",
            flush=True,
        )
        prime_player_surface_cache(
            projections,
            planning_gws=range(
                int(planning_gw),
                int(planning_gw) + 5,
            ),
            material_elements=material_elements,
        )
        for _, squad in unique_items:
            route_gw_elapsed: list[float] = []
            route_started = time.perf_counter()
            by_squad[tuple(squad)] = _cumulative_lineup_horizons(
                projections,
                squad,
                planning_gw=planning_gw,
                generated_at=generated_at,
                _perf_sink=route_gw_elapsed,
            )
            squad_elapsed.append(time.perf_counter() - route_started)
            gw_elapsed.extend(route_gw_elapsed)
        execution_mode = "SEQUENTIAL_EXACT_P1_7"

    if len(by_squad) != len(unique_items):
        raise PackageUtilityError(
            "P1.2B exact P1.7 route materialization lost a squad"
        )

    lineups_by_route = {
        route_id: by_squad[tuple(squad)]
        for route_id, squad in route_squads
    }
    if len(lineups_by_route) != len(route_squads):
        raise PackageUtilityError(
            "P1.2B exact P1.7 route materialization lost route identity"
        )

    materialization_elapsed = time.perf_counter() - materialization_started
    effective_workers = workers if use_parallel else 1
    utilization = (
        sum(squad_elapsed)
        / max(materialization_elapsed * effective_workers, 1e-12)
    )
    coordination_upper_bound = max(
        0.0,
        materialization_elapsed
        - (
            sum(squad_elapsed)
            / max(effective_workers, 1)
        ),
    )
    print(
        "[P1_2B_PERF] completed exact P1.7 route materialization "
        f"elapsed_seconds={materialization_elapsed:.3f} "
        f"squad_p50={(_perf_distribution(squad_elapsed).get('p50') or 0):.3f} "
        f"squad_p95={(_perf_distribution(squad_elapsed).get('p95') or 0):.3f} "
        f"worker_utilization={min(1.0, utilization):.3f} "
        f"coordination_upper_bound_seconds={coordination_upper_bound:.3f}",
        flush=True,
    )

    proof = {
        "execution_mode": execution_mode,
        "elapsed_seconds": round(materialization_elapsed, 6),
        "unique_squad_elapsed_seconds": _perf_distribution(squad_elapsed),
        "per_gw_elapsed_seconds": _perf_distribution(gw_elapsed),
        "worker_utilization_estimate": round(min(1.0, utilization), 6),
        "coordination_serialization_upper_bound_seconds": round(
            coordination_upper_bound, 6
        ),
        "route_count": len(route_squads),
        "unique_squad_count": len(unique_items),
        "worker_count": workers if use_parallel else 1,
        "parallel_min_routes": min_routes,
        "parallel_chunks_per_worker": requested_chunks_per_worker,
        "p1_7_owner": "V12_LINEUP_OPTIMIZER",
        "shared_player_surface_catalog": True,
        "material_element_count": len(material_elements),
        "exact_route_identity_preserved": True,
        "lossy_pruning": False,
        "p1_7_math_mutated": False,
        "decision_authority_changed": False,
    }
    return lineups_by_route, proof


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
    supplied_future = future_frontier_by_route
    info_map = information_value_by_route or {}
    price_map = price_risk_by_route or {}
    rentals = {str(value) for value in (rental_route_ids or [])}
    exits = explicit_exit_routes or {}

    hold_route = next(row for row in routes if row.get("route_id") == "HOLD")
    hold_squad = _route_squad(hold_route)
    projection_by_id = _projection_map(projections)

    lineups_by_route, lineup_execution = _materialize_route_lineups(
        routes,
        projections,
        planning_gw=planning_gw,
        generated_at=generated,
    )
    hold_lineups = lineups_by_route["HOLD"]
    if supplied_future is None:
        future = derive_bounded_future_frontier(
            {
                "model_owner": MODEL_OWNER,
                "routes": [
                    {
                        "route_id": str(route.get("route_id")),
                        "final_squad_elements": list(
                            route.get("final_squad_elements") or []
                        ),
                        "football_route_utility": {
                            "per_gw": deepcopy(
                                lineups_by_route[
                                    str(route.get("route_id"))
                                ].get("per_gw")
                                or []
                            )
                        },
                    }
                    for route in routes
                ],
            }
        )
    else:
        future = dict(supplied_future)

    evaluated: list[dict[str, Any]] = []
    for route in routes:
        route_id = str(route.get("route_id"))
        transfer_count = int(route.get("transfer_count") or 0)
        lineups = lineups_by_route[route_id]
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
            projection_by_id=projection_by_id,
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
            "legal": route.get("legal"),
            "final_squad_elements": list(route.get("final_squad_elements") or []),
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
            "bounded_future_frontier_auto_derived": supplied_future is None,
            "p_beats_hold": "NOT_COMPUTED",
            "monte_carlo": "NOT_RUN",
            "mini_league": "NOT_CONSUMED",
            "lineup_execution": deepcopy(lineup_execution),
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
            "p1_7_execution_parallelized_only": (
                lineup_execution.get("execution_mode")
                == "PROCESS_POOL_EXACT_P1_7"
            ),
            "p1_7_execution_proof": deepcopy(lineup_execution),
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




def derive_bounded_future_frontier(
    preliminary_package_utility: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """One-step future FT opportunity frontier over already-evaluated routes.

    State transition approximation:
    current final squad -> next-GW reoptimization among package states reachable
    by at most one player replacement. This uses P1.7 next-GW football utility
    already produced for each route. It creates no player xPts or hidden horizon
    weights.
    """
    if preliminary_package_utility.get("model_owner") != MODEL_OWNER:
        raise PackageUtilityError(
            "future frontier requires V12_PACKAGE_UTILITY preliminary output"
        )
    routes = [
        dict(row)
        for row in preliminary_package_utility.get("routes") or []
        if isinstance(row, Mapping)
    ]
    states = {}
    for row in routes:
        route_id = str(row.get("route_id") or "")
        squad = frozenset(
            int(x) for x in row.get("final_squad_elements") or []
        )
        per_gw = list(
            (row.get("football_route_utility") or {}).get("per_gw")
            or []
        )
        next_row = per_gw[1] if len(per_gw) > 1 else None
        next_utility = (
            None
            if not isinstance(next_row, Mapping)
            or next_row.get("status") != "READY"
            else _f(next_row.get("route_utility"))
        )
        states[route_id] = {
            "squad": squad,
            "next_gw_utility": next_utility,
        }

    snapshot_id = fingerprint(
        {
            route_id: {
                "squad": sorted(state["squad"]),
                "next_gw_utility": state["next_gw_utility"],
            }
            for route_id, state in sorted(states.items())
        }
    )
    out: dict[str, dict[str, Any]] = {}
    for route_id, state in states.items():
        own = state["next_gw_utility"]
        if own is None:
            out[route_id] = {
                "status": "UNAVAILABLE",
                "frontier_snapshot_id": snapshot_id,
                "reason": "NEXT_GW_P1_7_UTILITY_UNAVAILABLE",
            }
            continue
        reachable = []
        for other_id, other in states.items():
            other_utility = other["next_gw_utility"]
            if other_utility is None:
                continue
            outgoing = len(state["squad"] - other["squad"])
            incoming = len(other["squad"] - state["squad"])
            if outgoing == incoming and outgoing <= 1:
                reachable.append(
                    {
                        "route_id": other_id,
                        "next_gw_utility": other_utility,
                        "transfer_distance": outgoing,
                    }
                )
        best = max(
            reachable,
            key=lambda row: (
                _f(row["next_gw_utility"]),
                -int(row["transfer_distance"]),
                str(row["route_id"]),
            ),
            default={
                "route_id": route_id,
                "next_gw_utility": own,
                "transfer_distance": 0,
            },
        )
        out[route_id] = {
            "status": "READY",
            "best_future_utility_with_ft": _f(
                best["next_gw_utility"]
            ),
            "best_future_utility_with_ft_consumed": _f(own),
            "frontier_snapshot_id": snapshot_id,
            "best_reachable_route_id": best["route_id"],
            "bounded_rollout": {
                "lookahead_gw": 1,
                "reachable_transfer_distance": 1,
                "fresh_p1_7_lineup_utility": True,
                "future_transfer_precommitted": False,
                "approximation": (
                    "ONE_STEP_ROUTE_GRAPH_VALUE_OF_ONE_EXTRA_FT"
                ),
            },
        }
    return out


def _football_horizon_delta(
    route: Mapping[str, Any],
    hold: Mapping[str, Any],
    horizon: int,
) -> float | None:
    route_rows = list(
        (route.get("football_route_utility") or {}).get("per_gw")
        or []
    )
    hold_rows = list(
        (hold.get("football_route_utility") or {}).get("per_gw")
        or []
    )
    if len(route_rows) < int(horizon) or len(hold_rows) < int(horizon):
        return None
    route_subset = route_rows[: int(horizon)]
    hold_subset = hold_rows[: int(horizon)]
    if any(
        row.get("status") != "READY"
        for row in route_subset + hold_subset
    ):
        return None
    return round(
        sum(_f(row.get("expected_fpl_points")) for row in route_subset)
        - sum(_f(row.get("expected_fpl_points")) for row in hold_subset),
        6,
    )


def select_stage3_material_mc_routes(
    package_utility: Mapping[str, Any],
    *,
    max_routes: int = 8,
) -> dict[str, Any]:
    """Select material P1.2 routes for P1.4 without creating a score authority.

    The selector uses only existing football horizon deltas and structural
    lineup-change flags. It does not rerank the full universe, recompute xPts,
    or decide transfers.
    """
    if package_utility.get("model_owner") != MODEL_OWNER:
        raise PackageUtilityError(
            "Stage3 material route selector requires V12_PACKAGE_UTILITY"
        )
    limit = max(2, int(max_routes))
    routes = [
        dict(row) for row in package_utility.get("routes") or []
        if isinstance(row, Mapping)
    ]
    hold = next(
        (row for row in routes if row.get("route_id") == "HOLD"),
        None,
    )
    if hold is None:
        raise PackageUtilityError("Stage3 MC route selection requires HOLD")
    candidates = []
    for route in routes:
        route_id = str(route.get("route_id") or "")
        if route_id == "HOLD":
            continue
        deltas = {
            label: _football_horizon_delta(route, hold, horizon)
            for label, horizon in (("1GW", 1), ("3GW", 3), ("5GW", 5))
        }
        resolved = [
            abs(float(value))
            for value in deltas.values()
            if value is not None
        ]
        impact = dict(route.get("lineup_impact") or {})
        structural = any(
            bool(impact.get(key))
            for key in (
                "captain_changed",
                "vice_changed",
                "bench_order_changed",
                "formation_changed",
            )
        )
        candidates.append(
            {
                "route_id": route_id,
                "football_horizon_deltas": deltas,
                "max_absolute_horizon_delta": max(resolved, default=0.0),
                "structural_lineup_change": structural,
                "transfer_count": int(route.get("transfer_count") or 0),
                "economics_status": (
                    (route.get("transfer_economics") or {}).get("status")
                ),
            }
        )
    candidates.sort(
        key=lambda row: (
            bool(row["structural_lineup_change"]),
            float(row["max_absolute_horizon_delta"]),
            -int(row["transfer_count"]),
            str(row["route_id"]),
        ),
        reverse=True,
    )

    # Preserve the existing materiality ordering while guaranteeing that
    # supportable direct and funded package depths can both reach canonical
    # Monte Carlo. This is route-surface coverage, not a new decision score.
    mandatory: list[dict[str, Any]] = []
    for transfer_count in (1, 2):
        representative = next(
            (
                row for row in candidates
                if int(row.get("transfer_count") or 0) == transfer_count
            ),
            None,
        )
        if representative is not None:
            mandatory.append(representative)

    selected_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in mandatory + candidates:
        route_id = str(row.get("route_id") or "")
        if not route_id or route_id in seen:
            continue
        selected_rows.append(row)
        seen.add(route_id)
        if len(selected_rows) >= limit - 1:
            break
    selected = ["HOLD"] + [
        str(row["route_id"]) for row in selected_rows
    ]
    return {
        "status": "READY",
        "route_ids": selected,
        "candidate_evidence": selected_rows,
        "max_routes": limit,
        "selection_purpose": "MC_MATERIALITY_ONLY_NOT_DECISION_RANKING",
        "transfer_depth_coverage": {
            "direct_1_transfer": any(
                int(row.get("transfer_count") or 0) == 1
                for row in selected_rows
            ),
            "funded_2_transfer": any(
                int(row.get("transfer_count") or 0) == 2
                for row in selected_rows
            ),
            "coverage_is_not_decision_preference": True,
        },
        "full_package_route_denominator": len(routes),
        "full_universe_search_authority": package_utility.get(
            "search_authority"
        ),
        "no_package_specific_xpts": True,
        "no_new_player_score": True,
    }



def select_material_funding_legs(
    package_utility: Mapping[str, Any],
) -> dict[str, Any]:
    """Select direct P1.7-evaluated legs for bounded funded composition.

    This delegates ordering to the existing Stage3 materiality selector. It
    creates no player score, no package score, and no decision authority.
    """
    cfg = load_config()
    perf_cfg = dict(cfg.get("performance") or {})
    leg_limit = max(
        2,
        int(perf_cfg.get("funded_material_direct_leg_limit") or 32),
    )
    selected = select_stage3_material_mc_routes(
        package_utility,
        max_routes=leg_limit + 1,
    )
    routes_by_id = {
        str(row.get("route_id") or ""): dict(row)
        for row in package_utility.get("routes") or []
        if isinstance(row, Mapping)
    }
    route_ids = [
        str(route_id)
        for route_id in selected.get("route_ids") or []
        if str(route_id) != "HOLD"
        and int((routes_by_id.get(str(route_id)) or {}).get("transfer_count") or 0)
        == 1
    ][:leg_limit]
    return {
        "status": "READY",
        "route_ids": route_ids,
        "direct_leg_limit": leg_limit,
        "source": "P1_4_EXISTING_MATERIALITY_SELECTOR",
        "selection_purpose": "FUNDED_COMPOSITION_INPUT_ONLY_NOT_DECISION_RANKING",
        "direct_search_authority": package_utility.get("search_authority"),
        "no_new_player_score": True,
        "no_new_package_score": True,
    }


def combine_package_utility_surfaces(
    direct_package_utility: Mapping[str, Any],
    funded_package_utility: Mapping[str, Any],
    *,
    funded_search_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Combine exact direct and exact bounded-funded P1.2B owner outputs.

    Both inputs have already been evaluated with the canonical P1.7 owner.
    Combination only re-applies existing P1.2B selection/frontier/action
    functions over the union. No projection, lineup, horizon, economics or
    Monte Carlo math is recomputed here.
    """
    if direct_package_utility.get("model_owner") != MODEL_OWNER:
        raise PackageUtilityError("direct package utility owner drift")
    if funded_package_utility.get("model_owner") != MODEL_OWNER:
        raise PackageUtilityError("funded package utility owner drift")
    if direct_package_utility.get("search_authority") != "FULL":
        raise PackageUtilityError(
            "combined package utility requires FULL direct search authority"
        )

    direct_routes = [
        deepcopy(dict(row))
        for row in direct_package_utility.get("routes") or []
        if isinstance(row, Mapping)
    ]
    funded_routes = [
        deepcopy(dict(row))
        for row in funded_package_utility.get("routes") or []
        if isinstance(row, Mapping)
        and str(row.get("route_id") or "") != "HOLD"
    ]
    if not any(str(row.get("route_id") or "") == "HOLD" for row in direct_routes):
        raise PackageUtilityError("combined package utility requires direct HOLD")

    combined_by_id: dict[str, dict[str, Any]] = {}
    for row in direct_routes + funded_routes:
        route_id = str(row.get("route_id") or "")
        if not route_id:
            raise PackageUtilityError("combined package route lost route_id")
        combined_by_id.setdefault(route_id, row)
    evaluated = list(combined_by_id.values())

    resolved_gw1 = [
        _f(((row.get("horizons") or {}).get("GW+1") or {}).get("net_delta_vs_hold"))
        for row in evaluated
        if ((row.get("horizons") or {}).get("GW+1") or {}).get(
            "net_delta_vs_hold"
        )
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

    hold_eval = next(
        row for row in evaluated if str(row.get("route_id") or "") == "HOLD"
    )
    candidates = [row for row in evaluated if _qualifies_change(row)]
    candidates.sort(key=_selection_key, reverse=True)
    selected = candidates[0] if candidates else hold_eval
    action = _action(selected)
    package_frontier = _frontier(evaluated)

    output = deepcopy(dict(direct_package_utility))
    output["search_authority"] = "FULL_DIRECT_MATERIAL_FUNDED"
    output["search_route_denominator"] = len(evaluated)
    output["routes"] = evaluated
    output["package_frontier"] = package_frontier
    output["selected_route_id"] = selected.get("route_id")
    output["selected_route"] = deepcopy(selected)
    output["decision"] = action
    output["search_scope"] = {
        "direct": {
            "authority": "FULL",
            "route_count": len(direct_routes),
            "global_direct_complete": True,
        },
        "funded_two_transfer": {
            "authority": "MATERIAL_FUNDED",
            "route_count": len(funded_routes),
            "global_two_transfer_complete": False,
            "scope": "P1_7_MATERIAL_DIRECT_LEG_CROSS_PRODUCT",
            "search_proof": deepcopy(
                dict((funded_search_result or {}).get("search_proof") or {})
            ),
        },
        "global_two_transfer_exhaustive_claim": False,
    }
    output.setdefault("methodology", {})["funded_expansion"] = {
        "source": "EXACT_P1_7_EVALUATED_DIRECT_LEGS",
        "selection": "EXISTING_MATERIALITY_SELECTOR",
        "funded_routes_exact_p1_7": True,
        "global_two_transfer_exhaustive_claim": False,
        "decision_mapping_reused": True,
    }
    output.setdefault("governance", {})["funded_materialization"] = {
        "direct_full_search_preserved": True,
        "funded_search_bounded": True,
        "funded_route_p1_7_exact": True,
        "p1_7_math_mutated": False,
        "new_player_score_created": False,
        "new_package_score_created": False,
        "decision_authority_changed": False,
        "global_two_transfer_exhaustive_claim": False,
    }
    output["model_evidence_binding"] = {
        "status": "COMPOSED_FROM_BOUND_P1_2B_OWNER_OUTPUTS",
        "direct_binding_fingerprint": fingerprint(
            direct_package_utility.get("model_evidence_binding") or {}
        ),
        "funded_binding_fingerprint": fingerprint(
            funded_package_utility.get("model_evidence_binding") or {}
        ),
        "route_union_fingerprint": fingerprint(
            sorted(str(row.get("route_id") or "") for row in evaluated)
        ),
        "model_owner": MODEL_OWNER,
        "decision_authority_changed": False,
    }
    return output


def _pair_vs_hold(
    monte_carlo: Mapping[str, Any],
    route_id: str,
) -> dict[str, Any]:
    if route_id == "HOLD":
        return {
            "status": "BASELINE",
            "mean_difference": 0.0,
            "p_route_gt_hold": 0.5,
            "p_route_gt_hold_standard_error": 0.0,
            "Q10": 0.0,
            "Q25": 0.0,
            "median": 0.0,
            "Q75": 0.0,
            "Q90": 0.0,
        }
    pairs = dict(monte_carlo.get("paired_outputs") or {})
    direct = pairs.get(f"{route_id}__VS__HOLD__H1")
    reverse = False
    if not isinstance(direct, Mapping):
        direct = pairs.get(f"HOLD__VS__{route_id}__H1")
        reverse = isinstance(direct, Mapping)
    if not isinstance(direct, Mapping):
        return {
            "status": "UNAVAILABLE",
            "reason": "PAIR_NOT_SIMULATED",
        }
    row = dict(direct)
    if not reverse:
        return {
            "status": row.get("status"),
            "mean_difference": row.get("mean_difference"),
            "p_route_gt_hold": row.get("p_a_gt_b"),
            "p_route_gt_hold_standard_error": row.get(
                "p_a_gt_b_standard_error"
            ),
            "p_delta_ge_meaningful_threshold": row.get(
                "p_delta_ge_meaningful_threshold"
            ),
            "meaningful_threshold_points": row.get(
                "meaningful_threshold_points"
            ),
            "Q10": row.get("Q10"),
            "Q25": row.get("Q25"),
            "median": row.get("median"),
            "Q75": row.get("Q75"),
            "Q90": row.get("Q90"),
            "paired_difference_standard_error": row.get(
                "paired_difference_standard_error"
            ),
        }
    return {
        "status": row.get("status"),
        "mean_difference": (
            None
            if row.get("mean_difference") is None
            else -_f(row.get("mean_difference"))
        ),
        "p_route_gt_hold": (
            None
            if row.get("p_a_gt_b") is None
            else 1.0 - _f(row.get("p_a_gt_b"))
        ),
        "p_route_gt_hold_standard_error": row.get(
            "p_a_gt_b_standard_error"
        ),
        "p_delta_ge_meaningful_threshold": None,
        "meaningful_threshold_points": row.get(
            "meaningful_threshold_points"
        ),
        "Q10": (
            None if row.get("Q90") is None else -_f(row.get("Q90"))
        ),
        "Q25": (
            None if row.get("Q75") is None else -_f(row.get("Q75"))
        ),
        "median": (
            None if row.get("median") is None else -_f(row.get("median"))
        ),
        "Q75": (
            None if row.get("Q25") is None else -_f(row.get("Q25"))
        ),
        "Q90": (
            None if row.get("Q10") is None else -_f(row.get("Q10"))
        ),
        "paired_difference_standard_error": row.get(
            "paired_difference_standard_error"
        ),
    }


def finalize_stage3_decision(
    package_utility: Mapping[str, Any],
    monte_carlo: Mapping[str, Any],
    *,
    price_uncertainty_by_route: Mapping[str, Any] | None = None,
    projections: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Close the P1.2 decision downstream of canonical P1.4 evidence.

    This stays inside the existing V12_PACKAGE_UTILITY owner. It does not
    change P1.1/P1.3/Stage-2 distributions and never fabricates private
    transfer economics or a probability of a price move.
    """
    if package_utility.get("model_owner") != MODEL_OWNER:
        raise PackageUtilityError(
            "Stage3 decision closure requires V12_PACKAGE_UTILITY"
        )
    mc = dict(monte_carlo or {})
    mc_ready = (
        mc.get("model_owner") == "V12_MONTE_CARLO"
        and mc.get("execution_state") == "EXECUTED"
        and mc.get("canonical_pass") is True
        and int(mc.get("actual_paths") or 0) >= 500_000
        and (mc.get("convergence_evidence") or {}).get("status") == "PASS"
    )
    routes = {
        str(row.get("route_id")): dict(row)
        for row in package_utility.get("routes") or []
        if isinstance(row, Mapping)
    }
    hold = routes.get("HOLD")
    if hold is None:
        raise PackageUtilityError("Stage3 decision closure requires HOLD")
    price_map = dict(price_uncertainty_by_route or {})
    metrics = dict(mc.get("metrics") or {})
    projection_map = _projection_map(projections or {})
    stage3_cfg = dict(load_config().get("stage3") or {})
    robust_cfg = dict(stage3_cfg.get("robustness") or {})
    confidence_z = _f(robust_cfg.get("confidence_z"), 1.96)
    min_mean_lcb = _f(
        robust_cfg.get("minimum_mean_delta_lower_bound_points"),
        0.0,
    )
    min_p_lcb = _f(
        robust_cfg.get(
            "minimum_outperform_probability_lower_bound"
        ),
        0.50,
    )

    def sensitivity_for_route(
        route: Mapping[str, Any],
        price: Mapping[str, Any],
    ) -> dict[str, Any]:
        involved = sorted(
            {
                int(row.get("element") or 0)
                for row in (
                    list(route.get("players_out") or [])
                    + list(route.get("players_in") or [])
                )
                if int(row.get("element") or 0) > 0
            }
        )
        player_rows = [
            projection_map[element]
            for element in involved
            if element in projection_map
        ]
        pstart_ranges = {
            str(int(row.get("element") or 0)): (
                (row.get("xmins") or {}).get(
                    "start_probability_interval"
                )
            )
            for row in player_rows
        }
        xmins_ranges = {
            str(int(row.get("element") or 0)): (
                (row.get("xmins") or {}).get(
                    "expected_minutes_interval"
                )
            )
            for row in player_rows
        }
        price_scenarios = [
            {
                "element": signal.get("element"),
                "projection": signal.get("price_change_projections"),
                "locked_until": signal.get(
                    "price_change_locked_until"
                ),
            }
            for signal in price.get("signals") or []
            if isinstance(signal, Mapping)
        ]
        dimensions = {
            "P_start": {
                "status": (
                    "GOVERNED_INTERVAL"
                    if any(pstart_ranges.values())
                    else "UNAVAILABLE"
                ),
                "ranges": pstart_ranges,
                "perturbation": "LOW_AND_HIGH_P1_1_INTERVAL_ENDPOINTS",
            },
            "xMins": {
                "status": (
                    "GOVERNED_INTERVAL"
                    if any(xmins_ranges.values())
                    else "UNAVAILABLE"
                ),
                "ranges": xmins_ranges,
                "perturbation": "LOW_AND_HIGH_P1_1_INTERVAL_ENDPOINTS",
            },
            "role": {
                "status": "FRESH_REPROJECTION_REQUIRED",
                "perturbation": "ROLE_CHANGE_IS_DISCRETE_STAGE2_STATE_NOT_ARBITRARY_SCALAR",
            },
            "formation": {
                "status": "FRESH_REPROJECTION_REQUIRED",
                "perturbation": "FORMATION_CHANGE_REQUIRES_DYNAMIC_FDR_AND_ROLE_REBUILD",
            },
            "fixture_strength": {
                "status": "FRESH_REPROJECTION_REQUIRED",
                "perturbation": "DYNAMIC_FDR_VECTOR_HAS_NO_CALIBRATED_LOCAL_CONFIDENCE_BAND",
            },
            "DefCon_rate": {
                "status": "ALEATORIC_COUNT_DISTRIBUTION_IN_MC",
                "perturbation": "STAGE2_SELECTED_COUNT_FAMILY_SAMPLED_PATHWISE",
            },
            "finishing": {
                "status": "BAYESIAN_EVENT_DISTRIBUTION_IN_MC",
                "perturbation": "STAGE2_SHRUNK_GOAL_PROCESS_SAMPLED_PATHWISE",
            },
            "creator_availability": {
                "status": (
                    "PATH_CONDITIONED_IN_MC"
                    if (
                        (mc.get("match_state_contract") or {}).get(
                            "stage2_linkup_conditioned_on_sampled_material_teammate_appearance"
                        )
                    )
                    else "UNAVAILABLE"
                ),
                "perturbation": "P1_1_APPEARANCE_STATE_CHANGES_STAGE2_LINKUP_RATIO",
            },
            "opponent_lineup": {
                "status": "FRESH_REPROJECTION_REQUIRED",
                "perturbation": "EXPECTED_PERSONNEL_CHANGE_REQUIRES_DYNAMIC_FDR_REBUILD",
            },
            "price": {
                "status": (
                    "PREDICTOR_SCENARIO_ONLY_UNCALIBRATED_PROBABILITY"
                    if price_scenarios
                    else "UNAVAILABLE"
                ),
                "scenarios": price_scenarios,
                "perturbation": "PUBLISHED_PREDICTOR_SCENARIOS_ONLY",
            },
        }
        unresolved = sorted(
            key
            for key, value in dimensions.items()
            if value.get("status")
            in {"FRESH_REPROJECTION_REQUIRED", "UNAVAILABLE"}
        )
        return {
            "method": "GOVERNED_ONE_AT_A_TIME_ENVELOPE_PLUS_PATH_STRESS",
            "dimensions": dimensions,
            "unresolved_material_dimensions": unresolved,
            "all_material_dimensions_resolved": not unresolved,
            "arbitrary_percentage_shocks_used": False,
            "fresh_reprojection_required_for_structural_state_change": True,
        }

    rows = []
    for route_id in sorted(routes):
        route = routes[route_id]
        pair = _pair_vs_hold(mc, route_id)
        horizon_deltas = {
            "1GW": _football_horizon_delta(route, hold, 1),
            "3GW": _football_horizon_delta(route, hold, 3),
            "5GW": _football_horizon_delta(route, hold, 5),
        }
        mc_route = dict((metrics.get(route_id) or {}).get("1") or {})
        expected_regret = mc_route.get("expected_regret")
        evpi_upper_bound = (
            None
            if expected_regret is None
            else max(0.0, _f(expected_regret))
        )
        price = dict(price_map.get(route_id) or {})
        expected_wait_cost_points = price.get(
            "expected_cost_of_waiting_points"
        )
        if expected_wait_cost_points is None:
            voi_comparison = {
                "status": "UNRESOLVED",
                "reason": (
                    price.get("probability_reason")
                    or "PRICE_MOVE_PROBABILITY_OR_POINTS_EQUIVALENT_UNAVAILABLE"
                ),
                "voi_upper_bound_points": evpi_upper_bound,
                "expected_cost_of_waiting_points": None,
                "act_now_dominates_waiting": False,
            }
        else:
            wait_cost = max(0.0, _f(expected_wait_cost_points))
            voi_comparison = {
                "status": "BOUND_RESOLVED",
                "method": (
                    "EVPI_UPPER_BOUND_FROM_P1_4_EXPECTED_REGRET_VS_"
                    "EXPECTED_PRICE_WAIT_COST"
                ),
                "voi_upper_bound_points": evpi_upper_bound,
                "expected_cost_of_waiting_points": wait_cost,
                "act_now_dominates_waiting": (
                    evpi_upper_bound is not None
                    and evpi_upper_bound <= wait_cost
                ),
                "actual_voi_not_overclaimed": True,
            }

        mean = pair.get("mean_difference")
        mean_se = pair.get("paired_difference_standard_error")
        probability = pair.get("p_route_gt_hold")
        probability_se = pair.get(
            "p_route_gt_hold_standard_error"
        )
        mean_lcb = (
            None
            if mean is None or mean_se is None
            else _f(mean) - confidence_z * _f(mean_se)
        )
        p_lcb = (
            None
            if probability is None or probability_se is None
            else max(
                0.0,
                _f(probability)
                - confidence_z * _f(probability_se),
            )
        )
        long_noninferior = all(
            value is not None and _f(value) >= 0.0
            for value in (
                horizon_deltas["3GW"],
                horizon_deltas["5GW"],
            )
        )
        statistically_robust = bool(
            mc_ready
            and route_id != "HOLD"
            and mean_lcb is not None
            and mean_lcb > min_mean_lcb
            and p_lcb is not None
            and p_lcb > min_p_lcb
            and long_noninferior
        )
        economics = dict(route.get("transfer_economics") or {})
        sensitivity = sensitivity_for_route(route, price)
        if bool(
            robust_cfg.get(
                "require_all_material_sensitivity_dimensions_resolved",
                True,
            )
        ):
            statistically_robust = bool(
                statistically_robust
                and sensitivity.get(
                    "all_material_dimensions_resolved"
                )
                is True
            )
        rows.append(
            {
                "route_id": route_id,
                "classification": route.get("classification"),
                "horizon_deltas": horizon_deltas,
                "mc_pair_vs_hold": pair,
                "expected_regret": expected_regret,
                "value_of_information": {
                    "method": (
                        "P1_4_EXPECTED_REGRET_AS_PERFECT_INFORMATION_UPPER_BOUND"
                    ),
                    "upper_bound_points": evpi_upper_bound,
                    "actual_information_revelation_model": (
                        "NOT_CALIBRATED_NOT_FABRICATED"
                    ),
                },
                "price_uncertainty": price,
                "voi_vs_cost_of_waiting": voi_comparison,
                "sensitivity": sensitivity,
                "robustness": {
                    "classification": (
                        "ROBUST"
                        if statistically_robust
                        else "FRAGILE"
                        if route_id != "HOLD"
                        else "BASELINE"
                    ),
                    "mean_delta_95pct_lower_bound": mean_lcb,
                    "p_outperform_95pct_lower_bound": p_lcb,
                    "three_and_five_gw_noninferior": long_noninferior,
                    "convergence_pass": (
                        (mc.get("convergence_evidence") or {}).get(
                            "status"
                        )
                        == "PASS"
                    ),
                    "rules": {
                        "confidence_z": confidence_z,
                        "minimum_mean_delta_lower_bound_points": min_mean_lcb,
                        "minimum_outperform_probability_lower_bound": min_p_lcb,
                        "require_3gw_noninferior": bool(
                            robust_cfg.get(
                                "require_3gw_noninferior", True
                            )
                        ),
                        "require_5gw_noninferior": bool(
                            robust_cfg.get(
                                "require_5gw_noninferior", True
                            )
                        ),
                        "require_all_material_sensitivity_dimensions_resolved": bool(
                            robust_cfg.get(
                                "require_all_material_sensitivity_dimensions_resolved",
                                True,
                            )
                        ),
                        "calibration_status": robust_cfg.get(
                            "calibration_status"
                        ),
                        "settled_predeadline_sample_size_at_introduction": robust_cfg.get(
                            "settled_predeadline_sample_size_at_introduction"
                        ),
                        "automatic_retuning": robust_cfg.get(
                            "automatic_retuning"
                        ),
                    },
                },
                "stress_coverage": {
                    "unexpected_bench": "IN_DISTRIBUTION_P1_1",
                    "cameo": "IN_DISTRIBUTION_P1_1",
                    "early_sub": "IN_DISTRIBUTION_P1_1",
                    "rotation": "IN_DISTRIBUTION_P1_1",
                    "injury": "P1_1_AVAILABILITY_ONLY_NO_CLUSTER_MODEL",
                    "creator_absent": (
                        "PATH_CONDITIONED_STAGE2_LINKUP_FOR_MATERIAL_TEAMMATE"
                        if (
                            (mc.get("match_state_contract") or {}).get(
                                "stage2_linkup_conditioned_on_sampled_material_teammate_appearance"
                            )
                        )
                        else "NOT_MODELLED"
                    ),
                    "early_cs_loss": "IN_SCORELINE_DISTRIBUTION_TIMING_NOT_MODELLED",
                    "fixture_strength": "STAGE2_POSTERIOR_AND_DYNAMIC_FDR_FIXED_SNAPSHOT",
                    "finishing": "STAGE2_BAYESIAN_POSTERIOR_FIXED_SNAPSHOT",
                    "defcon_rate": "STAGE2_COUNT_POSTERIOR_FIXED_SNAPSHOT",
                    "role_formation_opponent_shape": (
                        "OUT_OF_DISTRIBUTION_REQUIRES_FRESH_REOPTIMIZATION"
                    ),
                    "penalty_taker_change": (
                        "OUT_OF_DISTRIBUTION_REQUIRES_FRESH_REOPTIMIZATION"
                    ),
                    "price_move": (
                        "EXTERNAL_MODEL_SIGNAL_REVERSAL_TRIGGER_NOT_FOOTBALL_MC"
                    ),
                },
                "transfer_economics": economics,
            }
        )

    viable = [
        row for row in rows
        if row["route_id"] != "HOLD"
        and row["mc_pair_vs_hold"].get("status") == "READY"
        and row["mc_pair_vs_hold"].get("mean_difference") is not None
        and _f(row["mc_pair_vs_hold"].get("mean_difference")) > 0.0
        and row["horizon_deltas"]["3GW"] is not None
        and _f(row["horizon_deltas"]["3GW"]) >= 0.0
        and row["horizon_deltas"]["5GW"] is not None
        and _f(row["horizon_deltas"]["5GW"]) >= 0.0
    ]
    viable.sort(
        key=lambda row: (
            _f(row["horizon_deltas"].get("3GW")),
            _f(row["mc_pair_vs_hold"].get("mean_difference")),
            _f(row["horizon_deltas"].get("5GW")),
            str(row["route_id"]),
        ),
        reverse=True,
    )
    candidate = viable[0] if viable else None

    if candidate is None:
        action = "WAIT"
        reason = "NO_POSITIVE_MC_SUPPORTED_ROUTE_CLEARS_1_3_5GW_VECTOR"
        selected_route_id = "HOLD"
    else:
        selected_route_id = str(candidate["route_id"])
        economics_pass = (
            (candidate.get("transfer_economics") or {}).get("status")
            == "PASS"
        )
        robust = (
            (candidate.get("robustness") or {}).get("classification")
            == "ROBUST"
        )
        info = candidate.get("voi_vs_cost_of_waiting") or {}
        if not economics_pass:
            action = "PREPARE"
            reason = (
                "FOOTBALL_ROUTE_VIABLE_BUT_EXECUTION_ECONOMICS_UNRESOLVED"
            )
        elif not mc_ready or not robust:
            action = "PREPARE"
            reason = (
                "ROUTE_VIABLE_BUT_MC_ROBUSTNESS_THRESHOLD_NOT_CLEARED"
            )
        elif info.get("status") != "BOUND_RESOLVED":
            action = "PREPARE"
            reason = (
                "ROUTE_VIABLE_BUT_VOI_VS_WAIT_COST_NOT_RESOLVED"
            )
        elif info.get("act_now_dominates_waiting") is not True:
            action = "WAIT"
            reason = "VALUE_OF_INFORMATION_CAN_EXCEED_COST_OF_WAITING"
        else:
            action = "ACT"
            reason = (
                "POSITIVE_EXPECTED_UTILITY_OUTPERFORM_PROBABILITY_"
                "ROBUSTNESS_ECONOMICS_AND_WAIT_COST_ALL_CLEAR"
            )

    return {
        "status": "READY" if mc_ready else "PARTIAL",
        "model_owner": MODEL_OWNER,
        "decision_layer": "P1_2B_STAGE3_DOWNSTREAM_CLOSURE",
        "selected_route_id": selected_route_id,
        "operational_action": action,
        "reason": reason,
        "routes": rows,
        "monte_carlo": {
            "execution_state": mc.get("execution_state"),
            "canonical_pass": mc.get("canonical_pass"),
            "actual_paths": mc.get("actual_paths"),
            "seed": mc.get("seed"),
            "convergence": mc.get("convergence_evidence"),
            "output_fingerprint": mc.get("output_fingerprint"),
        },
        "sequential_decision": {
            "method": "BOUNDED_SHARED_WORLD_ROLLOUT",
            "state": [
                "squad",
                "bank",
                "FT",
                "prices",
                "chips",
                "availability",
                "fixtures",
            ],
            "actions": [
                "HOLD",
                "TRANSFER_ROUTE",
                "LINEUP",
                "CAPTAIN_VICE",
            ],
            "horizons": [1, 3, 5],
            "per_gw_lineup_reoptimized_by_p1_7": True,
            "future_transfer_route_precommitment": False,
            "future_state_transition_model": (
                "CURRENT_STAGE2_POSTERIOR_ROLLOUT_WITH_FRESH_REOPT_REQUIRED_"
                "AFTER_NEW_INFORMATION"
            ),
            "approximation": (
                "Current transfer package is rolled through shared football "
                "worlds; later transfer decisions are not precommitted. "
                "This is bounded rollout, not an infinite-horizon MDP."
            ),
            "independent_gw_sum_decision_rule": False,
        },
        "action_contract": {
            "states": ["WAIT", "PREPARE", "ACT"],
            "act_requires_positive_expected_utility": True,
            "act_requires_outperform_probability_lcb_gt_0_5": True,
            "act_requires_robustness": True,
            "act_requires_resolved_transfer_economics": True,
            "act_requires_voi_vs_wait_cost_resolved": True,
        },
        "governance": {
            "same_p1_2_owner_extended": True,
            "new_decision_authority_created": False,
            "p1_1_mutated": False,
            "p1_3_mutated": False,
            "stage2_position_engine_mutated": False,
            "20_25_30_25_mutated": False,
            "full_universe_mutated": False,
            "watchlist_mutated": False,
            "horizon_distributions_mutated": False,
            "private_finance_fabricated": False,
        },
    }


def attach_stage3_decision(
    package_utility: Mapping[str, Any],
    stage3_decision: Mapping[str, Any],
) -> dict[str, Any]:
    if package_utility.get("model_owner") != MODEL_OWNER:
        raise PackageUtilityError(
            "Stage3 decision attaches only to V12_PACKAGE_UTILITY"
        )
    if stage3_decision.get("model_owner") != MODEL_OWNER:
        raise PackageUtilityError("Stage3 decision owner mismatch")
    out = deepcopy(dict(package_utility))
    out["stage3_decision"] = deepcopy(dict(stage3_decision))
    out.setdefault("governance", {})[
        "stage3_decision_same_owner"
    ] = True
    return out


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
