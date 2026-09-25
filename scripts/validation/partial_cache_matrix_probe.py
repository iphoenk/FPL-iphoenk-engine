from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from src.engines import v12_lineup_optimizer as lineup
from src.engines import v12_monte_carlo as mc
from src.engines import v12_stage2_derived_cache as stage2
from src.engines.v12_monte_carlo_acceptance import build_acceptance_fixture


CHANGE_CLASSES = (
    "injury",
    "xmins",
    "role",
    "price",
    "team",
    "finance",
    "unchanged",
)

EXPECTATIONS = {
    "injury": {"stage2": "MISS", "p17": "MISS", "mc": "MISS"},
    "xmins": {"stage2": "MISS", "p17": "MISS", "mc": "MISS"},
    "role": {"stage2": "MISS", "p17": "MISS", "mc": "MISS"},
    "price": {"stage2": "MISS", "p17": "HIT", "mc": "MISS"},
    "team": {"stage2": "HIT", "p17": "MISS", "mc": "MISS"},
    "finance": {"stage2": "HIT", "p17": "HIT", "mc": "MISS"},
    "unchanged": {"stage2": "HIT", "p17": "HIT", "mc": "HIT"},
}


def stable(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    )


def fp(value: Any) -> str:
    return hashlib.sha256(stable(value).encode("utf-8")).hexdigest()


def stage2_inputs(change: str) -> dict[str, Any]:
    bootstrap = {
        "events": [{"id": 6, "is_next": True}],
        "elements": [
            {
                "id": 9,
                "team": 2,
                "element_type": 3,
                "now_cost": 70,
                "chance_of_playing_next_round": 100,
            }
        ],
        "teams": [{"id": 2, "strength": 3}],
    }
    strength = {"teams": {"2": {"attack": 1.0, "defence": 1.0}}}
    historical_prior = {
        "9": {
            "start_probability": 0.80,
            "avg_minutes_when_start": 78.0,
            "minutes": 900,
        }
    }
    player_features_payload = {
        "players": {
            "9": {
                "tactical_role": {
                    "profile": "WINGER",
                    "confidence": "HIGH",
                },
                "system_context": {
                    "dominant_shape": "4-3-3",
                    "confidence": "HIGH",
                },
            }
        }
    }
    player_match_rows = [
        {
            "player_id": 9,
            "gw": 5,
            "minutes": 80,
            "xgi": 0.35,
            "starter": True,
        }
    ]
    opponent_history_rows = [
        {"team_id": 2, "gw": 5, "opponent_id": 1, "xga": 1.1}
    ]
    opponent_history_scope = {"latest_completed_gw": 5}

    if change == "injury":
        bootstrap["elements"][0]["chance_of_playing_next_round"] = 50
    elif change == "xmins":
        historical_prior["9"]["start_probability"] = 0.55
    elif change == "role":
        player_features_payload["players"]["9"]["tactical_role"][
            "profile"
        ] = "PLAYMAKER"
        player_features_payload["players"]["9"]["system_context"][
            "dominant_shape"
        ] = "4-2-3-1"
    elif change == "price":
        bootstrap["elements"][0]["now_cost"] = 71
    elif change not in {"team", "finance", "unchanged"}:
        raise ValueError(change)

    return {
        "bootstrap": bootstrap,
        "strength": strength,
        "planning_gw": 6,
        "historical_prior": historical_prior,
        "player_features_payload": player_features_payload,
        "player_match_rows": player_match_rows,
        "opponent_history_rows": opponent_history_rows,
        "opponent_history_scope": opponent_history_scope,
    }


def stage2_material(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        "planning_gw": kwargs["planning_gw"],
        "players": [
            {
                "element": 9,
                "semantic_input_fingerprint": fp(kwargs),
            }
        ],
    }


def run_stage2(change: str, cache_dir: Path) -> dict[str, Any]:
    kwargs = stage2_inputs(change)
    os.environ[stage2.STAGE2_DERIVED_CACHE_ENV] = str(cache_dir)
    calls = {"count": 0}

    def builder() -> dict[str, Any]:
        calls["count"] += 1
        return stage2_material(kwargs)

    output, proof = stage2.load_or_build_stage2_projections(
        **kwargs,
        builder=builder,
    )
    return {
        "key": proof["input_fingerprint"],
        "hit": bool(proof["cache_hit"]),
        "miss": bool(proof["cache_miss"]),
        "builder_calls": calls["count"],
        "material_fingerprint": fp(output),
        "output": output,
    }


def mutated_projection_package(change: str) -> tuple[dict, dict, list[int]]:
    projections, package = build_acceptance_fixture()
    projections = deepcopy(projections)
    package = deepcopy(package)
    ids = list(range(1, 16))
    pmap = {
        int(row["element"]): row
        for row in projections["players"]
    }
    player = pmap[9]

    if change == "injury":
        states = player["xmins"]["xmins_distribution"]["states"]
        states[0]["probability"] = 0.50
        states[1]["probability"] = 0.12
        states[2]["probability"] = 0.08
        states[3]["probability"] = 0.30
    elif change == "xmins":
        player["xmins"]["expected_minutes"] = 52.0
    elif change == "role":
        player["tactical_role_component"] = {
            "canonical_tactical_role_score": 74.0,
            "confidence": 0.90,
            "canonical_component": {
                "name": "TACTICAL_ROLE",
                "weight": 0.25,
                "weighted_component_points": 18.5,
            },
        }
    elif change == "price":
        player["now_cost"] = 71
    elif change == "team":
        ids.remove(9)
        ids.append(16)
        ids.sort()
        for route in package["routes"]:
            if route["route_id"] != "HOLD":
                continue
            route["final_squad_elements"] = [
                16 if value == 9 else value
                for value in route["final_squad_elements"]
            ]
            for gw_row in route["football_route_utility"]["per_gw"]:
                gw_row["starting_xi"] = [
                    16 if value == 9 else value
                    for value in gw_row["starting_xi"]
                ]
    elif change == "finance":
        for route in package["routes"]:
            if route["route_id"] == "R1":
                route["transfer_economics"][
                    "future_ft_shadow_value"
                ] = 0.45
    elif change != "unchanged":
        raise ValueError(change)

    return projections, package, ids


def p17_internal_key(projections: dict, ids: list[int]) -> str:
    pmap = {
        int(row.get("element") or -1): row
        for row in projections["players"]
    }
    players = [
        lineup.build_player_surface(pmap[element], 6)
        for element in ids
    ]
    return lineup._decision_core_cache_key(players)


def run_p17(change: str, cache_dir: Path) -> dict[str, Any]:
    projections, _, ids = mutated_projection_package(change)
    os.environ[lineup.P17_DECISION_CACHE_ENV] = str(cache_dir)
    lineup.reset_p17_execution_observability()
    output = lineup.optimize_lineup(
        projections,
        ids,
        planning_gw=6,
        generated_at="2026-09-25T00:00:00Z",
    )
    stats = lineup.p17_execution_observability()
    return {
        "key": p17_internal_key(projections, ids),
        "hit": int(stats["p17_cache_hits"]) > 0,
        "miss": int(stats["p17_cache_misses"]) > 0,
        "hits": int(stats["p17_cache_hits"]),
        "misses": int(stats["p17_cache_misses"]),
        "material_fingerprint": (
            output["model_evidence_binding"]["output_fingerprint"]
        ),
    }


def mc_inputs(change: str):
    projections, package, _ = mutated_projection_package(change)
    route_defs = mc.package_route_definitions(
        package,
        route_ids=["R1"],
    )
    seed = mc.canonical_package_seed(
        projections,
        package,
        route_ids=["R1"],
    )
    projection_fp = mc.fingerprint(projections)
    key = mc._simulation_cache_key(
        projection_fp=projection_fp,
        route_defs=route_defs,
        actual_paths=5_000,
        seed=seed,
        horizons=(1,),
        selected_route_id="R1",
        canonical=False,
    )
    return projections, route_defs, seed, key


def run_mc(change: str, cache_dir: Path) -> dict[str, Any]:
    projections, route_defs, seed, key = mc_inputs(change)
    os.environ[mc.MC_SIM_CACHE_ENV] = str(cache_dir)
    output = mc.run_correlated_monte_carlo(
        projections,
        route_defs,
        actual_paths=5_000,
        seed=seed,
        input_snapshot_id=f"CACHE_MATRIX_{change.upper()}",
        canonical=False,
        horizons=(1,),
        selected_route_id="R1",
        generated_at="2026-09-25T00:00:00Z",
        factual_snapshot_timestamps={
            "fixture": "2026-09-25T00:00:00Z"
        },
    )
    return {
        "key": key,
        "hit": bool(output["performance"]["simulation_cache_hit"]),
        "miss": not bool(output["performance"]["simulation_cache_hit"]),
        "material_fingerprint": output["output_fingerprint"],
    }


def run_all(change: str, cache_root: Path) -> dict[str, Any]:
    return {
        "stage2": run_stage2(change, cache_root / "stage2"),
        "p17": run_p17(change, cache_root / "p17"),
        "mc": run_mc(change, cache_root / "mc"),
    }


def prime(output_path: Path, cache_root: Path) -> None:
    result = run_all("unchanged", cache_root)
    for layer, row in result.items():
        if row["hit"] or not row["miss"]:
            raise SystemExit(f"prime {layer} must be a cold miss")
    manifest = {
        "state": "A",
        "production_sha": (
            "156df38920896a7aa8cb9e7de759f279a726fe89"
        ),
        "runtime_identity": {
            "stage2": stage2._runtime_cache_identity(),
            "p17": lineup._runtime_cache_identity(),
            "mc": mc._runtime_cache_identity(),
        },
        "layers": result,
    }
    output_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


def matrix(
    change: str,
    prime_path: Path,
    cache_root: Path,
    output_path: Path,
) -> None:
    prime_manifest = json.loads(prime_path.read_text())
    expected = EXPECTATIONS[change]

    restored = run_all(change, cache_root)

    with tempfile.TemporaryDirectory(prefix="v12-cache-matrix-cold-") as tmp:
        cold = run_all(change, Path(tmp))

    failures = []
    performance_findings = []
    layer_report = {}

    for layer in ("stage2", "p17", "mc"):
        want = expected[layer]
        got = "HIT" if restored[layer]["hit"] else "MISS"
        prime_key = prime_manifest["layers"][layer]["key"]
        current_key = restored[layer]["key"]

        if restored[layer]["material_fingerprint"] != cold[layer][
            "material_fingerprint"
        ]:
            failures.append(
                f"{layer}: restore-enabled B output != cold B"
            )

        if want == "MISS":
            if got == "HIT":
                failures.append(
                    f"{layer}: HIT observed where MISS required"
                )
            if current_key == prime_key:
                failures.append(
                    f"{layer}: semantic key did not change where MISS required"
                )
        else:
            if got == "MISS":
                performance_findings.append(
                    f"{layer}: MISS observed where HIT expected"
                )
            if current_key != prime_key:
                performance_findings.append(
                    f"{layer}: key changed where HIT expected"
                )

        layer_report[layer] = {
            "expected": want,
            "observed": got,
            "prime_key": prime_key,
            "current_key": current_key,
            "key_equal_prime": current_key == prime_key,
            "restored_material_fingerprint": restored[layer][
                "material_fingerprint"
            ],
            "cold_material_fingerprint": cold[layer][
                "material_fingerprint"
            ],
        }

    report = {
        "status": "PASS" if not failures else "FAIL",
        "change_class": change,
        "production_sha": (
            "156df38920896a7aa8cb9e7de759f279a726fe89"
        ),
        "expectations": expected,
        "layers": layer_report,
        "correctness_failures": failures,
        "performance_findings": performance_findings,
    }
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if failures:
        raise SystemExit("\n".join(failures))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("prime")
    p.add_argument("--cache-root", required=True)
    p.add_argument("--output", required=True)

    m = sub.add_parser("matrix")
    m.add_argument("--change", choices=CHANGE_CLASSES, required=True)
    m.add_argument("--cache-root", required=True)
    m.add_argument("--prime-manifest", required=True)
    m.add_argument("--output", required=True)

    args = parser.parse_args()
    cache_root = Path(args.cache_root)
    cache_root.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.command == "prime":
        prime(output_path, cache_root)
    else:
        matrix(
            args.change,
            Path(args.prime_manifest),
            cache_root,
            output_path,
        )


if __name__ == "__main__":
    main()
