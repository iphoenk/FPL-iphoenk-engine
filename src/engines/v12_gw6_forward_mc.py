from __future__ import annotations

"""Private gross-football GW6 forward what-if: P1.7 plus canonical 500K P1.4.

Consumes same-occurrence warm projections without changing CURRENT15, decisions,
security, finance, or publisher state. No baseline-MC numbers are reused.
"""
import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

MC_PATHS = 500_000
FORWARDS = (346, 249, 569)
GW_HORIZONS = (1, 3, 5)


class WhatIfMCError(RuntimeError):
    pass


def _element(row: Any) -> int:
    if not isinstance(row, Mapping):
        raise WhatIfMCError("expected element object")
    return int(row.get("element") or row.get("element_id") or 0)


def _lineup_route(lineup: Mapping[str, Any], gw: int) -> dict[str, Any]:
    xi = [_element(p) for p in lineup.get("starting_xi") or []]
    order = [_element(p) for p in (lineup.get("bench") or {}).get("order") or []]
    bench_gk = _element((lineup.get("bench") or {}).get("gk"))
    captain = _element(lineup.get("captain"))
    vice = _element(lineup.get("vice_captain"))
    if len(xi) != 11 or len(set(xi)) != 11 or len(order) != 3:
        raise WhatIfMCError("P1.7 failed XI/bench completeness")
    if len({*xi, *order, bench_gk}) != 15:
        raise WhatIfMCError("P1.7 failed CURRENT15 partition")
    if captain not in xi or vice not in xi or captain == vice:
        raise WhatIfMCError("P1.7 captain/vice legality failed")
    return {
        "gw": int(gw), "starting_xi": xi, "bench_order": order,
        "bench_gk": bench_gk, "captain": captain, "vice_captain": vice,
    }


def _forced_343_route(
    lineup: Mapping[str, Any],
    gw: int,
    *,
    materializer: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Re-materialize the exact P1.7 best 3-4-3, including bench and C/VC.

    A compact formation comparison is NOT an MC lineup. Use the unchanged
    P1.7 route evaluator to recover all first-XI, bench and captain semantics.
    """
    matches = [
        row for row in lineup.get("formation_comparison") or []
        if row.get("formation") == "3-4-3"
    ]
    if len(matches) != 1:
        raise WhatIfMCError("P1.7 3-4-3 winner missing or duplicated")
    summary = matches[0]
    ids = {int(value) for value in summary.get("element_ids") or []}
    if len(ids) != 11:
        raise WhatIfMCError("P1.7 3-4-3 XI identity incomplete")

    if materializer is not None:
        route = materializer(lineup, summary, gw)
    else:
        # Import only the EXISTING canonical owner. Never approximate
        # autosub priority, C/VC, or replace its ranking mathematics.
        from src.engines.v12_lineup_optimizer import _lineup_route
        players = list(lineup.get("squad_rows") or [])
        indices = [
            i for i, row in enumerate(players)
            if int(row.get("element") or 0) in ids
        ]
        if len(players) != 15 or len(indices) != 11:
            raise WhatIfMCError("P1.7 3-4-3 squad surface incomplete")
        full = _lineup_route(players, indices, compact=False)
        if full.get("formation") != "3-4-3":
            raise WhatIfMCError("P1.7 3-4-3 route materialization mismatch")
        expected = summary.get("expected_fpl_points_with_captain_vice")
        actual = full.get("expected_fpl_points_with_captain_vice")
        if (
            expected is None or actual is None
            or abs(float(expected) - float(actual)) > 1e-5
        ):
            raise WhatIfMCError("P1.7 3-4-3 exact numerical winner drift")
        bench = full.get("bench") or {}
        cvc = full.get("captain_vice") or {}
        route = {
            "gw": int(gw),
            "starting_xi": [int(x["element"]) for x in full["starters"]],
            "bench_order": [int(x) for x in bench.get("order") or []],
            "bench_gk": int((bench.get("reserve_gk") or {}).get("element") or 0),
            "captain": int(cvc.get("captain_element") or 0),
            "vice_captain": int(cvc.get("vice_element") or 0),
        }

    xi = [int(x) for x in route.get("starting_xi") or []]
    order = [int(x) for x in route.get("bench_order") or []]
    gk = int(route.get("bench_gk") or 0)
    captain = int(route.get("captain") or 0)
    vice = int(route.get("vice_captain") or 0)
    if len(xi) != 11 or len(order) != 3 or set(xi) != ids:
        raise WhatIfMCError("3-4-3 MC route differs from P1.7 formation XI")
    if len(set(xi + order + [gk])) != 15:
        raise WhatIfMCError("3-4-3 MC route loses XI/bench partition")
    if captain not in xi or vice not in xi or captain == vice:
        raise WhatIfMCError("3-4-3 MC captain/vice illegal")
    return {
        "gw": int(gw), "starting_xi": xi, "bench_order": order,
        "bench_gk": gk, "captain": captain, "vice_captain": vice,
    }


def run_forward_mc(
    config: Mapping[str, Any],
    warm: Mapping[str, Any],
    *,
    optimizer: Callable[..., dict[str, Any]] | None = None,
    simulator: Callable[..., dict[str, Any]] | None = None,
    formation_materializer: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if warm.get("schema") != "FPL_MASTER_V12_PRIVATE_WARM_STATE_V1":
        raise WhatIfMCError("private canonical warm state required")
    gw = int(config.get("target_gw") or 0)
    if gw != 6 or int(warm.get("planning_gw") or 0) != gw:
        raise WhatIfMCError("GW6 model and warm evidence mismatch")
    slot = str((config.get("baseline") or {}).get("slot") or "")
    if slot != str(warm.get("report_slot") or ""):
        raise WhatIfMCError("same-occurrence model warm slot required")
    owned = [int(row["element_id"]) for row in config.get("owned") or []]
    active = [_element(row) for row in warm.get("owned") or []]
    if len(owned) != 15 or set(owned) != set(active) or len(set(owned)) != 15:
        raise WhatIfMCError("actual owned CURRENT15 not verified against manifest")
    if FORWARDS[0] not in owned or any(x in owned for x in FORWARDS[1:]):
        raise WhatIfMCError("striker scenario baseline identity mismatch")
    projections = warm.get("projections")
    if not isinstance(projections, Mapping):
        raise WhatIfMCError("canonical P1.1/P1.3 projection unavailable")
    by_id = {int(x.get("element") or 0): x for x in projections.get("players") or []}
    if any(element not in by_id for element in set(owned) | set(FORWARDS)):
        raise WhatIfMCError("full canonical projection missing what-if player")
    if optimizer is None:
        from src.engines.v12_lineup_optimizer import optimize_lineup
        optimizer = optimize_lineup
    if simulator is None:
        from src.engines.v12_monte_carlo import run_correlated_monte_carlo
        simulator = run_correlated_monte_carlo

    definitions: list[dict[str, Any]] = []
    p17_rows = {}
    forced_343: dict[str, list[dict[str, Any]]] = {}
    for forward, route_id in zip(FORWARDS, ("HOLD", "DCL_TO_BARRY", "DCL_TO_GONZALO")):
        ids = [forward if x == FORWARDS[0] else x for x in owned]
        per_gw = []
        forced_343[route_id] = []
        for offset in range(5):
            lineup = optimizer(projections, sorted(ids), planning_gw=gw + offset)
            per_gw.append(_lineup_route(lineup, gw + offset))
            forced_343[route_id].append(_forced_343_route(
                lineup, gw + offset, materializer=formation_materializer,
            ))
            if offset == 0:
                rows = [dict(x) for x in lineup.get("formation_comparison") or []]
                if len(rows) != 8 or len({x.get("formation") for x in rows}) != 8:
                    raise WhatIfMCError(f"incomplete P1.7 legal formations for {route_id}")
                p17_rows[route_id] = {
                    "chosen_formation": lineup.get("formation"),
                    "formation_comparison": rows,
                    "captain_element": per_gw[0]["captain"],
                    "vice_element": per_gw[0]["vice_captain"],
                }
        definitions.append({
            "route_id": route_id,
            "classification": "CURRENT15" if forward == FORWARDS[0] else "HYPOTHETICAL_FORWARD_SWAP",
            "per_gw": per_gw,
            "execution_cost_points": 0.0,
            "execution_cost_status": "HOLD_ZERO" if forward == FORWARDS[0] else "UNAVAILABLE_NOT_APPLIED",
            "decision_net_supported": forward == FORWARDS[0],
        })

    # Explicit formation-fixed MC routes: do not reuse the MC result of an
    # optimized XI for the distinct P1.7 3-4-3 winner.
    for route_id in ("HOLD", "DCL_TO_BARRY", "DCL_TO_GONZALO"):
        is_hold = route_id == "HOLD"
        definitions.append({
            "route_id": route_id + "_343",
            "classification": (
                "FORMATION_343_WHAT_IF" if is_hold
                else "FORWARD_SWAP_FORMATION_343_WHAT_IF"
            ),
            "per_gw": forced_343[route_id],
            "execution_cost_points": 0.0,
            "execution_cost_status": (
                "FORMATION_CHANGE_ZERO" if is_hold
                else "UNAVAILABLE_NOT_APPLIED"
            ),
            "decision_net_supported": is_hold,
        })

    # Paired event-world captain challenger on the SAME P1.7 HOLD lineup.
    # Only compare if both attacking players are legally in the first XI;
    # this does not change canonical S06/S08/S18/S19 or make a captain LOCK.
    if {426, 411}.issubset(set(definitions[0]["per_gw"][0]["starting_xi"])):
        cvc_per_gw = [dict(row) for row in definitions[0]["per_gw"]]
        for row in cvc_per_gw:
            if {426, 411}.issubset(set(row["starting_xi"])):
                row["captain"], row["vice_captain"] = 426, 411
        definitions.append({
            "route_id": "BRUNO_C_HAALAND_VC",
            "classification": "CAPTAIN_REVIEW_NOT_LOCK",
            "per_gw": cvc_per_gw,
            "execution_cost_points": 0.0,
            "execution_cost_status": "CAPTAIN_CHANGE_ZERO",
            "decision_net_supported": True,
        })

    projection_binding = str(
        (projections.get("model_evidence_binding") or {}).get("output_fingerprint") or ""
    )
    if not projection_binding:
        # The canonical full-universe projection contract predates the optional
        # top-level evidence wrapper. Bind the what-if run to the exact
        # same-occurrence payload bytes rather than inventing a second model
        # evidence source or mutating P1.1/P1.3 output.
        projection_binding = hashlib.sha256(
            json.dumps(projections, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
    if not projection_binding:
        raise WhatIfMCError("canonical projection model evidence missing")
    route_digest = hashlib.sha256(
        json.dumps(definitions, sort_keys=True).encode()
    ).hexdigest()
    seed = int(
        hashlib.sha256((projection_binding + route_digest).encode()).hexdigest()[:8], 16
    )
    mc = simulator(
        projections, definitions,
        actual_paths=MC_PATHS, seed=seed,
        input_snapshot_id="GW6_OWNER_FORWARD_WHAT_IF:" + projection_binding,
        canonical=True, horizons=GW_HORIZONS,
        selected_route_id="DCL_TO_BARRY",
        factual_snapshot_timestamps={"canonical_warm_slot": slot},
        factual_artifact_fingerprints={
            "canonical_projection": projection_binding,
            "route_definitions": route_digest,
        },
    )
    if not (
        mc.get("execution_state") == "EXECUTED"
        and mc.get("canonical_pass") is True
        and int(mc.get("actual_paths") or 0) >= MC_PATHS
    ):
        raise WhatIfMCError("P1.4 canonical convergence/execution did not PASS")
    metrics = mc.get("metrics") or {}
    if any(route["route_id"] not in metrics for route in definitions):
        raise WhatIfMCError("P1.4 missing route-level Monte Carlo result")
    return {
        "contract": "GW6_OWNER_FORWARD_CANONICAL_GROSS_MC_V1",
        "status": "PASS",
        "decision_authority": "WHAT_IF_ONLY_NOT_EXECUTABLE",
        "report_slot": slot,
        "scenarios": p17_rows,
        "mc_paths_each_route": MC_PATHS,
        "mc_seed": seed,
        "mc_output_fingerprint": mc.get("output_fingerprint"),
        "mc_fixed_formation": "3-4-3",
        "mc_fixed_formation_route_ids": ["HOLD_343", "DCL_TO_BARRY_343", "DCL_TO_GONZALO_343"],
        "mc_route_metrics": {
            route["route_id"]: metrics[route["route_id"]]
            for route in definitions
        },
        "finance": "UNAVAILABLE_NOT_APPLIED_TO_GROSS_FOOTBALL_SIMULATION",
        "official_current15_unchanged": True,
        "private_publisher_called": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--warm-state", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--report-slot",
        default=None,
        help="Occurrence slot to bind to the ephemeral warm state.",
    )
    args = parser.parse_args()
    config = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if args.report_slot:
        config.setdefault("baseline", {})["slot"] = args.report_slot
    warm = json.loads(Path(args.warm_state).read_text(encoding="utf-8"))
    result = run_forward_mc(config, warm)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "status": result["status"],
        "scenarios": list(result["scenarios"]),
        "actual_paths": result["mc_paths_each_route"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
