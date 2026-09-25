from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile

from src.engines import v12_stage2_derived_cache as stage2
from src.engines import v12_lineup_optimizer as lineup
from src.engines import v12_monte_carlo as mc
from src.engines.v12_model_evidence import fingerprint
from src.engines.v12_monte_carlo_acceptance import build_acceptance_fixture

GW = 6
GENERATED = "2026-09-25T00:00:00Z"
CHANGE_CLASSES = (
    "injury",
    "xmins",
    "role",
    "price",
    "team",
    "finance",
    "unchanged",
)
EXPECT = {
    "injury": {"stage2": "MISS", "p17": "MISS", "mc": "MISS"},
    "xmins": {"stage2": "MISS", "p17": "MISS", "mc": "MISS"},
    "role": {"stage2": "MISS", "p17": "MISS", "mc": "MISS"},
    "price": {"stage2": "MISS", "p17": "HIT", "mc": "MISS"},
    "team": {"stage2": "HIT", "p17": "MISS", "mc": "MISS"},
    "finance": {"stage2": "HIT", "p17": "HIT", "mc": "MISS"},
    "unchanged": {"stage2": "HIT", "p17": "HIT", "mc": "HIT"},
}


def stable(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    )


def fp(value):
    return hashlib.sha256(stable(value).encode("utf-8")).hexdigest()


def _stage2_inputs():
    return {
        "bootstrap": {
            "events": [{"id": 6, "is_next": True}],
            "elements": [
                {
                    "id": 1,
                    "team": 1,
                    "element_type": 3,
                    "now_cost": 70,
                    "chance_of_playing_next_round": 100,
                }
            ],
            "teams": [{"id": 1, "name": "A"}],
        },
        "strength": {"teams": [{"team_id": 1, "attack": 1.0}]},
        "planning_gw": 6,
        "historical_prior": {
            "model": "prior",
            "players": {"1": {"start_probability": 0.85}},
        },
        "player_features_payload": {
            "players": {
                "1": {
                    "tactical_role": {
                        "profile": "CREATOR",
                        "confidence": "HIGH",
                    },
                    "system_context": {
                        "dominant_shape": "4-3-3",
                        "confidence": "HIGH",
                    },
                }
            }
        },
        "player_match_rows": [],
        "opponent_history_rows": [],
        "opponent_history_scope": "PUBLIC",
    }


def _mutate_stage2(inputs, change_class):
    out = deepcopy(inputs)
    if change_class == "injury":
        out["bootstrap"]["elements"][0]["chance_of_playing_next_round"] = 50
    elif change_class == "xmins":
        out["historical_prior"]["players"]["1"]["start_probability"] = 0.55
    elif change_class == "role":
        out["player_features_payload"]["players"]["1"]["tactical_role"][
            "profile"
        ] = "BOX_RUNNER"
    elif change_class == "price":
        out["bootstrap"]["elements"][0]["now_cost"] = 71
    return out


def _stage2_payload(inputs):
    player = inputs["bootstrap"]["elements"][0]
    prior = inputs["historical_prior"]["players"]["1"]
    feature = inputs["player_features_payload"]["players"]["1"]
    marker = fp(
        {
            "availability": player.get("chance_of_playing_next_round"),
            "now_cost": player.get("now_cost"),
            "start_probability": prior.get("start_probability"),
            "tactical_role": feature.get("tactical_role"),
            "system_context": feature.get("system_context"),
        }
    )
    return {
        "model": "MATRIX_STAGE2_SYNTHETIC",
        "planning_gw": 6,
        "players": [{"element": 1, "marker": marker}],
    }


def _pmf(meanish, blank=0.10, upside=0.20):
    blank = max(0.0, min(0.8, blank))
    upside = max(0.0, min(0.8 - blank, upside))
    middle = 1.0 - blank - upside
    low = 2
    high = max(8, int(round(meanish + 5)))
    mid = max(
        3,
        int(
            round(
                (meanish - blank * low - upside * high)
                / max(middle, 1e-9)
            )
        ),
    )
    return {0: blank, mid: middle, high: upside}


def _projection(
    element,
    position,
    *,
    meanish,
    p_start=0.88,
    p_regular=0.05,
    p_late=0.02,
    p_dnp=0.05,
    tactical=60.0,
    now_cost=70,
):
    pmf = _pmf(meanish)
    mean = sum(points * probability for points, probability in pmf.items())
    second = sum(
        points * points * probability for points, probability in pmf.items()
    )
    variance = max(0.0, second - mean * mean)
    probs = {str(points): probability for points, probability in pmf.items()}
    expected_minutes = 90 * p_start + 18 * p_regular + 7 * p_late
    return {
        "element": element,
        "name": f"P{element}",
        "position": position,
        "team_id": (element % 10) + 1,
        "now_cost": now_cost,
        "projection_confidence": "HIGH",
        "xmins": {
            "start_probability": p_start,
            "cameo_probability": p_regular + p_late,
            "late_cameo_probability": p_late,
            "dnp_probability": p_dnp,
            "availability": 1.0 - p_dnp,
            "expected_minutes": expected_minutes,
            "confidence": "HIGH",
            "xmins_distribution": {
                "distribution": "FINITE_STATE_MINUTES_MIXTURE",
                "mean": expected_minutes,
                "std": 15.0,
                "states": [
                    {
                        "state": "START",
                        "probability": p_start,
                        "minutes_mean": 90,
                        "minutes_std": 0,
                    },
                    {
                        "state": "REGULAR_CAMEO",
                        "probability": p_regular,
                        "minutes_mean": 18,
                        "minutes_std": 0,
                    },
                    {
                        "state": "LATE_CAMEO",
                        "probability": p_late,
                        "minutes_mean": 7,
                        "minutes_std": 0,
                    },
                    {
                        "state": "ZERO_MINUTES",
                        "probability": p_dnp,
                        "minutes_mean": 0,
                        "minutes_std": 0,
                    },
                ],
            },
        },
        "tactical_role_component": {
            "canonical_tactical_role_score": tactical,
            "confidence": 0.9,
            "canonical_component": {
                "name": "TACTICAL_ROLE",
                "weight": 0.25,
                "weighted_component_points": 0.25 * tactical,
            },
        },
        "xpts_by_gw": [
            {
                "gw": GW,
                "mean": mean,
                "std": variance ** 0.5,
                "points_variance": variance,
                "point_distribution": {
                    "model": "FINITE_STATE_CONDITIONAL_CORE_POINT_PMF_V1",
                    "distribution_completeness": "PARTIAL_BONUS_RESIDUAL",
                    "bonus_incorporation": "EXPECTATION_ONLY_NOT_STOCHASTIC",
                    "probabilities": probs,
                },
                "fixtures": [],
            }
        ],
    }


def _p17_state():
    positions = ["GK", "GK"] + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 4
    means = [
        4.8, 3.9, 5.4, 5.2, 5.0, 4.7, 4.3, 7.4,
        7.0, 6.4, 5.8, 4.6, 8.1, 6.7, 5.9, 5.7,
    ]
    players = [
        _projection(
            index + 1,
            position,
            meanish=means[index],
            tactical=55 + (index % 6) * 5,
            now_cost=50 + index,
        )
        for index, position in enumerate(positions)
    ]
    return {
        "projections": {
            "planning_gw": GW,
            "generated_at": GENERATED,
            "players": players,
        },
        "ids": list(range(1, 16)),
    }


def _mutate_p17(state, change_class):
    out = deepcopy(state)
    p0 = out["projections"]["players"][0]
    if change_class == "injury":
        p0["xmins"]["start_probability"] = 0.55
        p0["xmins"]["dnp_probability"] = 0.35
        p0["xmins"]["availability"] = 0.65
        p0["xmins"]["xmins_distribution"]["states"][0]["probability"] = 0.55
        p0["xmins"]["xmins_distribution"]["states"][3]["probability"] = 0.35
    elif change_class == "xmins":
        p0["xmins"]["expected_minutes"] = 68.0
        p0["xmins"]["xmins_distribution"]["mean"] = 68.0
    elif change_class == "role":
        p0["tactical_role_component"][
            "canonical_tactical_role_score"
        ] += 7.0
    elif change_class == "price":
        p0["now_cost"] += 1
    elif change_class == "team":
        out["ids"][-1] = 16
    return out


def _p17_internal_key(state):
    pmap = {
        int(row["element"]): row
        for row in state["projections"]["players"]
    }
    surfaces = [
        lineup.build_player_surface(pmap[element], GW)
        for element in state["ids"]
    ]
    return lineup._decision_core_cache_key(surfaces)


def _mutate_mc(change_class):
    projections, package = build_acceptance_fixture()
    projections = deepcopy(projections)
    package = deepcopy(package)
    p0 = projections["players"][0]

    if change_class == "injury":
        xmins = p0.setdefault("xmins", {})
        xmins["start_probability"] = max(
            0.0, float(xmins.get("start_probability") or 0.8) - 0.20
        )
        xmins["dnp_probability"] = min(
            1.0, float(xmins.get("dnp_probability") or 0.05) + 0.20
        )
    elif change_class == "xmins":
        xmins = p0.setdefault("xmins", {})
        xmins["expected_minutes"] = float(
            xmins.get("expected_minutes") or 70.0
        ) - 5.0
    elif change_class == "role":
        tactical = p0.setdefault("tactical_role_component", {})
        tactical["canonical_tactical_role_score"] = float(
            tactical.get("canonical_tactical_role_score") or 50.0
        ) + 4.0
    elif change_class == "price":
        p0["now_cost"] = int(p0.get("now_cost") or 50) + 1

    if change_class in {"team", "finance"}:
        target = next(
            row
            for row in package["routes"]
            if str(row.get("route_id")) == "R1"
        )
        if change_class == "team":
            gwrow = target["football_route_utility"]["per_gw"][0]
            starters = list(gwrow["starting_xi"])
            bench = list(gwrow["bench_order"])
            pmap = {
                int(row["element"]): str(row.get("position") or "")
                for row in projections["players"]
            }
            swap = None
            for bench_index, bench_element in enumerate(bench):
                bench_position = pmap[int(bench_element)]
                if bench_position == "GK":
                    continue
                for starter_index, starter_element in enumerate(starters):
                    if pmap[int(starter_element)] == bench_position:
                        swap = (
                            starter_index,
                            bench_index,
                        )
                        break
                if swap is not None:
                    break
            if swap is None:
                raise RuntimeError(
                    "team fixture cannot find same-position outfield swap"
                )
            starter_index, bench_index = swap
            starters[starter_index], bench[bench_index] = (
                bench[bench_index],
                starters[starter_index],
            )
            gwrow["starting_xi"] = starters
            gwrow["bench_order"] = bench
        else:
            economics = target.setdefault("transfer_economics", {})
            economics["status"] = "PASS"
            economics["hit_points"] = float(
                economics.get("hit_points") or 0.0
            ) + 4.0
            economics["future_ft_shadow_value"] = float(
                economics.get("future_ft_shadow_value") or 0.0
            )

    return projections, package


def _mc_state(change_class, mutated):
    projections, package = build_acceptance_fixture()
    if mutated:
        projections, package = _mutate_mc(change_class)
    else:
        projections, package = deepcopy(projections), deepcopy(package)
    route_defs = mc.package_route_definitions(package, route_ids=["R1"])
    selected = "R1"
    return {
        "projections": projections,
        "route_defs": route_defs,
        "selected": selected,
    }


def _mc_internal_key(state):
    return mc._simulation_cache_key(
        projection_fp=fingerprint(state["projections"]),
        route_defs=state["route_defs"],
        actual_paths=5_000,
        seed=20260925,
        horizons=(1,),
        selected_route_id=state["selected"],
        canonical=False,
    )


def _configure_cache_root(root):
    root = Path(root)
    stage2_root = root / "stage2"
    p17_root = root / "p17"
    mc_root = root / "mc"
    for path in (stage2_root, p17_root, mc_root):
        path.mkdir(parents=True, exist_ok=True)
    os.environ[stage2.STAGE2_DERIVED_CACHE_ENV] = str(stage2_root)
    os.environ[lineup.P17_DECISION_CACHE_ENV] = str(p17_root)
    os.environ[mc.MC_SIM_CACHE_ENV] = str(mc_root)
    return {
        "stage2": stage2_root,
        "p17": p17_root,
        "mc": mc_root,
    }


def _run_layers(change_class, *, mutated, cache_root):
    _configure_cache_root(cache_root)

    base_s2 = _stage2_inputs()
    s2_inputs = (
        _mutate_stage2(base_s2, change_class)
        if mutated
        else base_s2
    )
    s2_payload, s2_proof = stage2.load_or_build_stage2_projections(
        **s2_inputs,
        builder=lambda: _stage2_payload(s2_inputs),
    )

    p17_state = _p17_state()
    if mutated:
        p17_state = _mutate_p17(p17_state, change_class)
    lineup.reset_p17_execution_observability()
    p17_out = lineup.optimize_lineup(
        p17_state["projections"],
        p17_state["ids"],
        planning_gw=GW,
        generated_at=GENERATED,
    )
    p17_stats = lineup.p17_execution_observability()

    mc_state = _mc_state(change_class, mutated)
    mc_out = mc.run_correlated_monte_carlo(
        mc_state["projections"],
        mc_state["route_defs"],
        actual_paths=5_000,
        seed=20260925,
        input_snapshot_id="CACHE_MATRIX",
        canonical=False,
        horizons=(1,),
        selected_route_id=mc_state["selected"],
        generated_at=GENERATED,
        factual_snapshot_timestamps={"fixture": GENERATED},
    )

    return {
        "stage2": {
            "output": s2_payload,
            "output_fingerprint": fp(s2_payload),
            "cache_hit": bool(s2_proof.get("cache_hit")),
            "cache_miss": bool(s2_proof.get("cache_miss")),
            "internal_key": stage2.stage2_derived_input_fingerprint(
                **s2_inputs
            ),
        },
        "p17": {
            "output_fingerprint": fp(p17_out),
            "cache_hit": int(p17_stats["p17_cache_hits"]) > 0,
            "cache_miss": int(p17_stats["p17_cache_misses"]) > 0,
            "internal_key": _p17_internal_key(p17_state),
        },
        "mc": {
            "output_fingerprint": str(mc_out["output_fingerprint"]),
            "cache_hit": bool(
                (mc_out.get("performance") or {}).get(
                    "simulation_cache_hit"
                )
            ),
            "cache_miss": not bool(
                (mc_out.get("performance") or {}).get(
                    "simulation_cache_hit"
                )
            ),
            "internal_key": _mc_internal_key(mc_state),
        },
    }


def _expected_key_relation(change_class, layer):
    return "SAME" if EXPECT[change_class][layer] == "HIT" else "DIFFERENT"


def prime(change_class, cache_root, output):
    result = _run_layers(
        change_class,
        mutated=False,
        cache_root=cache_root,
    )
    failures = []
    for layer in ("stage2", "p17", "mc"):
        if result[layer]["cache_hit"]:
            failures.append(f"prime A unexpectedly HIT: {layer}")
        if not result[layer]["cache_miss"]:
            failures.append(f"prime A did not MISS: {layer}")
    evidence = {
        "mode": "prime",
        "change_class": change_class,
        "result": result,
        "failures": failures,
    }
    Path(output).write_text(
        json.dumps(evidence, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(evidence, indent=2, sort_keys=True))
    if failures:
        raise SystemExit("\n".join(failures))


def verify(change_class, cache_root, output):
    # Compute A keys without touching the restored cache.
    with tempfile.TemporaryDirectory() as key_tmp:
        a = _run_layers(
            change_class,
            mutated=False,
            cache_root=key_tmp,
        )

    # Execute B against restored A cache.
    warm_b = _run_layers(
        change_class,
        mutated=True,
        cache_root=cache_root,
    )

    # Execute a no-reuse B reference in isolated empty directories.
    with tempfile.TemporaryDirectory() as cold_tmp:
        cold_b = _run_layers(
            change_class,
            mutated=True,
            cache_root=cold_tmp,
        )

    failures = []
    performance_findings = []
    rows = {}

    for layer in ("stage2", "p17", "mc"):
        expectation = EXPECT[change_class][layer]
        observed = "HIT" if warm_b[layer]["cache_hit"] else "MISS"
        relation = (
            "SAME"
            if a[layer]["internal_key"] == warm_b[layer]["internal_key"]
            else "DIFFERENT"
        )
        expected_relation = _expected_key_relation(
            change_class, layer
        )

        if relation != expected_relation:
            failures.append(
                f"{change_class}:{layer} internal-key relation "
                f"{relation} != {expected_relation}"
            )

        if observed == "HIT" and expectation == "MISS":
            failures.append(
                f"{change_class}:{layer} stale HIT where MISS required"
            )
        elif observed == "MISS" and expectation == "HIT":
            performance_findings.append(
                f"{change_class}:{layer} over-invalidation MISS where HIT expected"
            )

        if (
            warm_b[layer]["output_fingerprint"]
            != cold_b[layer]["output_fingerprint"]
        ):
            failures.append(
                f"{change_class}:{layer} warm-B output != cold-B output"
            )

        rows[layer] = {
            "expectation": expectation,
            "observed": observed,
            "a_internal_key": a[layer]["internal_key"],
            "b_internal_key": warm_b[layer]["internal_key"],
            "key_relation": relation,
            "warm_b_output_fingerprint": (
                warm_b[layer]["output_fingerprint"]
            ),
            "cold_b_output_fingerprint": (
                cold_b[layer]["output_fingerprint"]
            ),
        }

    evidence = {
        "mode": "verify",
        "change_class": change_class,
        "expectation": EXPECT[change_class],
        "layers": rows,
        "performance_findings": performance_findings,
        "failures": failures,
        "status": "PASS" if not failures else "FAIL",
    }
    Path(output).write_text(
        json.dumps(evidence, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(evidence, indent=2, sort_keys=True))
    if failures:
        raise SystemExit("\n".join(failures))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("prime", "verify"), required=True)
    parser.add_argument("--change-class", choices=CHANGE_CLASSES, required=True)
    parser.add_argument("--cache-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if args.mode == "prime":
        prime(args.change_class, args.cache_root, args.output)
    else:
        verify(args.change_class, args.cache_root, args.output)


if __name__ == "__main__":
    main()
