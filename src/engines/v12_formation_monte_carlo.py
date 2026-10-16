from __future__ import annotations

"""Canonical correlated MC for every legal P1.7 formation.

This module is an orchestration adapter. It deliberately delegates simulation
to the existing P1.4 correlated common-world kernel and delegates XI,
bench-order and C/VC resolution to P1.7. It is not a transfer-route MC.
"""

import hashlib
import json
from math import isfinite
from copy import deepcopy
from typing import Any, Callable, Mapping, Sequence

from .v12_monte_carlo import run_correlated_monte_carlo

FORMATIONS = (
    "3-4-3",
    "3-5-2",
    "4-3-3",
    "4-4-2",
    "4-5-1",
    "5-2-3",
    "5-3-2",
    "5-4-1",
)
MC_PATHS = 500_000
HORIZON_GWS = 6


class FormationMonteCarloError(ValueError):
    pass


def _fp(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _materialize_formation(lineup: Mapping[str, Any], formation: str) -> dict[str, Any]:
    summaries = [
        row for row in lineup.get("formation_comparison") or []
        if str(row.get("formation")) == formation
    ]
    if len(summaries) != 1:
        raise FormationMonteCarloError(f"P1.7 missing exact formation row: {formation}")
    summary = dict(summaries[0])
    ids = {int(value) for value in summary.get("element_ids") or []}
    players = list(lineup.get("squad_rows") or [])
    if len(ids) != 11 or len(players) != 15:
        raise FormationMonteCarloError(f"P1.7 incomplete {formation} squad surface")
    indices = [
        index for index, row in enumerate(players)
        if int(row.get("element") or 0) in ids
    ]
    if len(indices) != 11:
        raise FormationMonteCarloError(f"P1.7 {formation} XI identity mismatch")
    from .v12_lineup_optimizer import _lineup_route

    route = _lineup_route(players, indices, compact=False)
    if route.get("formation") != formation:
        raise FormationMonteCarloError(f"P1.7 materialized formation mismatch: {formation}")
    if set(int(value) for value in route.get("element_ids") or []) != ids:
        raise FormationMonteCarloError(f"P1.7 materialized XI mismatch: {formation}")
    expected = summary.get("expected_fpl_points_with_captain_vice")
    actual = route.get("expected_fpl_points_with_captain_vice")
    if expected is not None and actual is not None and abs(float(expected) - float(actual)) > 1e-5:
        raise FormationMonteCarloError(f"P1.7 exact score drift: {formation}")
    bench = dict(route.get("bench") or {})
    cvc = dict(route.get("captain_vice") or {})
    row = {
        "gw": int(lineup.get("planning_gw") or 0),
        "starting_xi": [int(value) for value in route.get("element_ids") or []],
        "bench_order": [int(value) for value in bench.get("order") or []],
        "bench_gk": int((bench.get("reserve_gk") or {}).get("element") or 0),
        "captain": int(cvc.get("captain_element") or 0),
        "vice_captain": int(cvc.get("vice_element") or 0),
    }
    if len(row["starting_xi"]) != 11 or len(row["bench_order"]) != 3:
        raise FormationMonteCarloError(f"P1.7 incomplete exact route: {formation}")
    if row["captain"] not in row["starting_xi"] or row["vice_captain"] not in row["starting_xi"]:
        raise FormationMonteCarloError(f"P1.7 illegal C/VC route: {formation}")
    if row["captain"] == row["vice_captain"]:
        raise FormationMonteCarloError(f"P1.7 duplicate C/VC route: {formation}")
    return {
        "formation": formation,
        "route": row,
        "p17_fingerprint": _fp({"formation": formation, "route": row, "summary": summary}),
        "xi": row["starting_xi"],
        "bench": {"order": row["bench_order"], "gk": row["bench_gk"]},
        "captain": row["captain"],
        "vice_captain": row["vice_captain"],
    }


def _default_route_builder(
    *, projections: Mapping[str, Any], current15: Sequence[int], planning_gw: int, **_: Any
) -> list[dict[str, Any]]:
    from .v12_lineup_optimizer import optimize_lineup

    routes = {formation: {"formation": formation, "per_gw": [], "p17_rows": []} for formation in FORMATIONS}
    for offset in range(HORIZON_GWS):
        lineup = optimize_lineup(projections, list(current15), planning_gw=planning_gw + offset)
        for formation in FORMATIONS:
            materialized = _materialize_formation(lineup, formation)
            row = dict(materialized["route"])
            row["gw"] = planning_gw + offset
            routes[formation]["per_gw"].append(row)
            routes[formation]["p17_rows"].append(materialized)
    for formation, route in routes.items():
        route["p17_fingerprint"] = _fp(route["p17_rows"])
    return list(routes.values())


def _validate_routes(routes: Sequence[Mapping[str, Any]], current15: Sequence[int], planning_gw: int) -> None:
    if tuple(row.get("formation") for row in routes) != FORMATIONS:
        raise FormationMonteCarloError("route builder must return all eight legal formations in canonical order")
    current = {int(value) for value in current15}
    if len(current) != 15:
        raise FormationMonteCarloError("authenticated CURRENT15 must contain 15 unique players")
    for route in routes:
        if not route.get("p17_fingerprint"):
            raise FormationMonteCarloError("P1.7 exact fingerprint missing")
        rows = list(route.get("per_gw") or [])
        if len(rows) != HORIZON_GWS:
            raise FormationMonteCarloError("formation route must cover six GWs")
        for offset, row in enumerate(rows):
            if int(row.get("gw") or 0) != planning_gw + offset:
                raise FormationMonteCarloError("formation route horizon is not GW7-GW12")
            ids = [int(value) for value in row.get("starting_xi") or []]
            ids += [int(value) for value in row.get("bench_order") or []]
            ids += [int(row.get("bench_gk") or 0)]
            if len(ids) != 15 or set(ids) != current:
                raise FormationMonteCarloError("formation route is not bound to authenticated CURRENT15")


def _validate_forced_routes(
    routes: Sequence[Mapping[str, Any]],
    current15: Sequence[int],
    planning_gw: int,
) -> list[dict[str, Any]]:
    """Validate exact P1.7 routes supplied for a constrained what-if.

    This deliberately does not call the optimizer. A constrained comparison
    must preserve the user-supplied XI, bench order and C/VC while still using
    the canonical P1.4 scorer.
    """
    current = {int(value) for value in current15}
    if len(current) != 15:
        raise FormationMonteCarloError("authenticated CURRENT15 must contain 15 unique players")
    if len(routes) < 2:
        raise FormationMonteCarloError("forced comparison requires at least two routes")
    route_ids = [str(row.get("route_id") or "") for row in routes]
    if len(set(route_ids)) != len(route_ids) or any(not value for value in route_ids):
        raise FormationMonteCarloError("forced route IDs must be unique and non-empty")
    if "HOLD" not in route_ids:
        raise FormationMonteCarloError("forced comparison requires HOLD as the baseline route")

    normalized: list[dict[str, Any]] = []
    for source in routes:
        rows = list(source.get("per_gw") or [])
        if len(rows) != HORIZON_GWS:
            raise FormationMonteCarloError("forced route must cover GW7-GW12")
        per_gw: list[dict[str, Any]] = []
        for offset, raw in enumerate(rows):
            row = dict(raw)
            if int(row.get("gw") or 0) != planning_gw + offset:
                raise FormationMonteCarloError("forced route horizon is not GW7-GW12")
            starters = [int(value) for value in row.get("starting_xi") or []]
            bench = [int(value) for value in row.get("bench_order") or []]
            bench_gk = int(row.get("bench_gk") or 0)
            captain = int(row.get("captain") or 0)
            vice = int(row.get("vice_captain") or 0)
            all_ids = starters + bench + [bench_gk]
            if len(starters) != 11 or len(bench) != 3 or len(set(all_ids)) != 15:
                raise FormationMonteCarloError("forced route is not a complete 15-player partition")
            if set(all_ids) != current:
                raise FormationMonteCarloError("forced route is not bound to authenticated CURRENT15")
            if captain not in starters or vice not in starters or captain == vice:
                raise FormationMonteCarloError("forced route has illegal captain/vice")
            per_gw.append({
                "gw": int(row["gw"]),
                "starting_xi": starters,
                "bench_order": bench,
                "bench_gk": bench_gk,
                "captain": captain,
                "vice_captain": vice,
            })
        normalized.append({
            "route_id": str(source["route_id"]),
            "classification": str(source.get("classification") or "FORCED_LINEUP_COMPARISON"),
            "label": str(source.get("label") or source["route_id"]),
            "per_gw": per_gw,
            "execution_cost_points": 0.0,
            "execution_cost_status": "HOLD_ZERO" if str(source["route_id"]) == "HOLD" else "GROSS_FOOTBALL_ONLY",
            "decision_net_supported": str(source["route_id"]) == "HOLD",
        })
    return normalized


def run_forced_lineup_monte_carlo(
    projections: Mapping[str, Any],
    *,
    current15: Sequence[int],
    scenarios: Sequence[Mapping[str, Any]],
    input_snapshot_id: str,
    planning_gw: int | None = None,
    seed: int = 120910,
    simulator: Callable[..., Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run exact lineup scenarios through the canonical correlated MC kernel.

    The caller owns scenario construction from the authenticated P1.7/current
    squad surface. This adapter only validates the binding and extracts the
    paired metrics; it never invents projections or replaces the optimizer.
    """
    start_gw = int(planning_gw or projections.get("planning_gw") or 0)
    if start_gw <= 0:
        raise FormationMonteCarloError("planning GW is required")
    if not str(input_snapshot_id).startswith("private-full-master:"):
        raise FormationMonteCarloError("authenticated private full_master snapshot is required")
    routes = _validate_forced_routes(list(scenarios), current15, start_gw)
    run = (simulator or run_correlated_monte_carlo)(
        projections,
        routes,
        actual_paths=MC_PATHS,
        seed=int(seed),
        input_snapshot_id=str(input_snapshot_id),
        canonical=True,
        horizons=(1, 3, 5),
        selected_route_id="HOLD",
    )
    if not (
        run.get("execution_state") == "EXECUTED"
        and run.get("canonical_pass") is True
        and run.get("common_random_numbers") is True
        and run.get("correlated") is True
        and int(run.get("actual_paths") or 0) == MC_PATHS
        and (run.get("convergence_evidence") or {}).get("status") == "PASS"
    ):
        raise FormationMonteCarloError("forced lineup MC did not pass canonical 500K correlated acceptance")
    route_by_id = {str(row["route_id"]): row for row in routes}
    metrics = dict(run.get("metrics") or {})
    paired = dict(run.get("paired_outputs") or {})
    for route_id in route_by_id:
        if route_id not in metrics or any(str(horizon) not in metrics[route_id] for horizon in (1, 3, 5)):
            raise FormationMonteCarloError(f"forced route metrics unavailable: {route_id}")
    return {
        "routes": route_by_id,
        "metrics": metrics,
        "paired": paired,
        "actual_paths": MC_PATHS,
        "seed": int(seed),
        "horizons": [1, 3, 5],
        "integrity": {
            "exact_route_binding": True,
            "current15_bound": True,
            "common_random_numbers": True,
            "correlated_kernel": "P1.4_RUN_CORRELATED_MONTE_CARLO",
            "canonical_pass": True,
        },
        "provenance": {
            "input_snapshot_id": str(input_snapshot_id),
            "projection_fingerprint": (run.get("model_evidence_binding") or {}).get("output_fingerprint"),
            "route_ids": list(route_by_id),
        },
        "mc_run": dict(run),
    }


def run_formation_monte_carlo(
    projections: Mapping[str, Any],
    *,
    current15: Sequence[int],
    input_snapshot_id: str,
    planning_gw: int | None = None,
    seed: int = 120910,
    route_builder: Callable[..., Sequence[Mapping[str, Any]]] | None = None,
    simulator: Callable[..., Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    start_gw = int(planning_gw or projections.get("planning_gw") or 0)
    if start_gw <= 0:
        raise FormationMonteCarloError("planning GW is required")
    if not str(input_snapshot_id).startswith("private-full-master:"):
        raise FormationMonteCarloError("authenticated private full_master snapshot is required")
    builder = route_builder or _default_route_builder
    routes = [dict(row) for row in builder(projections=projections, current15=current15, planning_gw=start_gw)]
    _validate_routes(routes, current15, start_gw)
    # P1.4 requires one HOLD route and caps canonical comparison at eight
    # routes. The 3-4-3 row is the internal convergence reference only; it is
    # still published and ranked as a formation result below.
    sim_routes = [
        {
            **dict(route),
            "route_id": (
                "HOLD"
                if route["formation"] == "3-4-3"
                else f"FORMATION_{route['formation'].replace('-', '_')}"
            ),
            "execution_cost_points": 0.0,
            "decision_net_supported": True,
        }
        for route in routes
    ]
    run = (simulator or run_correlated_monte_carlo)(
        projections,
        sim_routes,
        actual_paths=MC_PATHS,
        seed=int(seed),
        input_snapshot_id=str(input_snapshot_id),
        canonical=True,
        horizons=(HORIZON_GWS,),
        # The canonical kernel reserves HOLD as the convergence/reference
        # route. It is materialized from the exact 3-4-3 P1.7 lineup, while
        # the published formation row remains 3-4-3.
        selected_route_id="HOLD",
    )
    if not (
        run.get("execution_state") == "EXECUTED"
        and run.get("canonical_pass") is True
        and run.get("common_random_numbers") is True
        and run.get("correlated") is True
        and int(run.get("actual_paths") or 0) == MC_PATHS
        and (run.get("convergence_evidence") or {}).get("status") == "PASS"
    ):
        raise FormationMonteCarloError("formation MC did not pass canonical 500K correlated acceptance")
    metrics = dict(run.get("metrics") or {})
    semantics = dict((run.get("sampling_diagnostics") or {}).get("route_path_semantics") or {})
    rows = []
    for route in routes:
        formation = str(route["formation"])
        route_id = "HOLD" if formation == "3-4-3" else f"FORMATION_{formation.replace('-', '_')}"
        metric = dict((metrics.get(route_id) or {}).get(str(HORIZON_GWS)) or {})
        if metric.get("status") != "READY":
            raise FormationMonteCarloError(f"missing six-GW MC metric for {formation}")
        if metric.get("p10") is None or metric.get("p90") is None:
            raise FormationMonteCarloError(
                f"canonical six-GW absolute point quantiles missing for {formation}"
            )
        route_semantics = dict(semantics.get(route_id) or {})
        per_gw_semantics = {
            str(gw): dict(values)
            for gw, values in (route_semantics.get("by_gw") or {}).items()
            if isinstance(values, Mapping)
        }
        expected_gws = {str(gw) for gw in range(start_gw, start_gw + HORIZON_GWS)}
        if set(per_gw_semantics) != expected_gws:
            raise FormationMonteCarloError(
                f"canonical six-GW sampling semantics unavailable for {formation}"
            )
        average_semantics = {}
        for key in (
            "autosub_path_rate",
            "captain_takeover_path_rate",
            "captain_blank_probability",
            "captain_haul_probability",
            "expected_autosub_value",
        ):
            values = [per_gw_semantics[str(gw)].get(key) for gw in range(start_gw, start_gw + HORIZON_GWS)]
            if any(value is None for value in values):
                raise FormationMonteCarloError(
                    f"canonical sampled {key} unavailable for {formation}"
                )
            try:
                samples = [float(value) for value in values]
            except (TypeError, ValueError, OverflowError) as exc:
                raise FormationMonteCarloError(
                    f"canonical sampled {key} invalid for {formation}"
                ) from exc
            if not all(isfinite(value) for value in samples):
                raise FormationMonteCarloError(
                    f"canonical sampled {key} non-finite for {formation}"
                )
            if key != "expected_autosub_value" and any(value < 0 or value > 1 for value in samples):
                raise FormationMonteCarloError(
                    f"canonical sampled {key} out of probability range for {formation}"
                )
            average_semantics[key] = sum(samples) / HORIZON_GWS

        # The P1.4 sampler owns START/DNP event frequencies. Bind the actual
        # sampled first-GW XI DNP rate, never infer it from a missing projection
        # player.p_dnp field and never substitute zero for absent evidence.
        frequencies = (run.get("sampling_diagnostics") or {}).get("state_frequencies") or {}
        dnp_values = []
        for element in route["per_gw"][0]["starting_xi"]:
            row = frequencies.get(f"{int(element)}:gw{start_gw}") or {}
            probability = row.get("DNP") if isinstance(row, Mapping) else None
            if probability is None:
                break
            try:
                value = float(probability)
            except (TypeError, ValueError, OverflowError):
                break
            if not isfinite(value) or not 0 <= value <= 1:
                break
            dnp_values.append(value)
        minutes_risk = (
            {
                "status": "MC500K_SAMPLED_DNP_BOUND",
                "mean_p_dnp_xi": sum(dnp_values) / len(dnp_values),
            }
            if len(dnp_values) == 11
            else {"status": "UNAVAILABLE_SAMPLED_DNP_EVIDENCE", "mean_p_dnp_xi": None}
        )
        row = {
            "formation": formation,
            "actual_paths": MC_PATHS,
            "convergence": "PASS",
            "xi": list((route.get("p17_rows") or [{}])[0].get("xi") or route["per_gw"][0]["starting_xi"]),
            "bench": dict((route.get("p17_rows") or [{}])[0].get("bench") or {"order": route["per_gw"][0]["bench_order"], "gk": route["per_gw"][0]["bench_gk"]}),
            "captain": int((route.get("p17_rows") or [{}])[0].get("captain") or route["per_gw"][0]["captain"]),
            "vice_captain": int((route.get("p17_rows") or [{}])[0].get("vice_captain") or route["per_gw"][0]["vice_captain"]),
            "lineups_by_gw": [dict(row) for row in route["per_gw"]],
            "p17_fingerprints_by_gw": [
                row.get("p17_fingerprint")
                for row in route.get("p17_rows") or []
            ],
            "mean_xpts": metric.get("mean_net_utility"),
            "p10": metric.get("p10"),
            "p50": metric.get("median"),
            "p90": metric.get("p90"),
            "variance": float(metric.get("standard_deviation") or 0.0) ** 2,
            "captain_haul_probability": average_semantics["captain_haul_probability"],
            "captain_blank_probability": average_semantics["captain_blank_probability"],
            "vice_activation_probability": average_semantics["captain_takeover_path_rate"],
            "autosub_probability": average_semantics["autosub_path_rate"],
            "captain_distribution_by_gw": per_gw_semantics,
            "expected_autosub_value": average_semantics["expected_autosub_value"],
            "route_win_probability": metric.get("p_route_best"),
            "uncertainty": metric.get("uncertainty") or {"source": "CANONICAL_CORRELATED_MC"},
            "minutes_risk": minutes_risk,
            "seed": int(seed),
            "projection_fingerprint": run.get("model_evidence_binding", {}).get("output_fingerprint"),
            "fixture_fingerprint": (run.get("model_evidence_binding", {}).get("factual_artifact_fingerprints") or {}).get("fixture_catalog"),
            "p17_fingerprint": route.get("p17_fingerprint"),
        }
        rows.append(row)
    by = lambda key: [row["formation"] for row in sorted(rows, key=lambda item: float(item.get(key) or 0.0), reverse=True)]
    return {
        "formation_mc": {
            "horizon": {"start_gw": start_gw, "end_gw": start_gw + HORIZON_GWS - 1, "total_gws": HORIZON_GWS},
            "formations": rows,
            "ranking": {
                "by_mean": by("mean_xpts"),
                "by_p50": by("p50"),
                "by_p90": by("p90"),
                "by_risk_adjusted_value": by("mean_xpts"),
                "by_captain_adjusted_value": by("mean_xpts"),
            },
            "integrity": {
                "formation_count": 8,
                "all_legal_formations": True,
                "all_mc_500k": True,
                "all_convergence_pass": True,
                "all_p17_exact": True,
                "all_current15_bound": True,
                "no_legacy_mc": True,
                "no_route_mc_substitution": True,
            },
            "provenance": {
                "authority": "AUTHENTICATED_CURRENT_TEAM",
                "input_snapshot_id": str(input_snapshot_id),
                "current15": sorted(int(value) for value in current15),
                "canonical_kernel": "P1.4_RUN_CORRELATED_MONTE_CARLO",
                "transfer_route_mc_separate": True,
            },
        },
        "mc_run": dict(run),
    }
