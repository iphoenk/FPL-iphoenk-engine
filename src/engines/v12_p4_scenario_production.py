from __future__ import annotations

"""Production P4 scenario package materializer.

The package is generated only from the canonical V12 integrated evaluator.
Scenario overrides enter through the authorized P1.1 availability path; no
post-hoc xPts/xMins/Pstart mutation is permitted here.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import get_context
from datetime import datetime
import gzip
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .v12_integrated_report_runner import run_deep
from .v12_p6_runtime import _identity
from .v12_scenario_package import (
    REQUIRED_DECISION_SURFACES,
    build_scenario_package,
)


class P4ScenarioProductionError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise P4ScenarioProductionError(f"expected JSON object: {path}")
    return payload


def _decision_result(bundle: Mapping[str, Any]) -> dict[str, Any]:
    report = dict(bundle.get("report") or {})
    sections = report.get("sections") or []
    surfaces: dict[str, Any] = {}
    if isinstance(sections, list):
        for row in sections:
            if not isinstance(row, Mapping):
                continue
            sid = str(
                row.get("section_id")
                or row.get("id")
                or ""
            ).upper()
            if sid:
                surfaces[sid] = row.get("content", row)
    elif isinstance(sections, Mapping):
        for raw_sid, value in sections.items():
            sid = str(raw_sid or "").upper()
            if sid:
                surfaces[sid] = value
    missing = [
        sid
        for sid in REQUIRED_DECISION_SURFACES
        if sid not in surfaces
    ]
    if missing:
        raise P4ScenarioProductionError(
            f"canonical DEEP bundle missing P4 decision surfaces: {missing}"
        )
    proof = dict(bundle.get("execution_proof") or {})
    stage3_action = str(proof.get("stage3_action") or "").strip()
    if not stage3_action:
        raise P4ScenarioProductionError(
            "canonical DEEP bundle missing Stage3 action"
        )
    return {
        "decision_surfaces": surfaces,
        "stage3_action": stage3_action,
    }

def _owned_context(private_root: Path) -> tuple[list[int], int | None, int | None]:
    current = _read_json(private_root / "personal/current_team.json")
    players = [row for row in current.get("players") or [] if isinstance(row, Mapping)]
    owned = [int(row.get("element_id") or 0) for row in players]
    if len(owned) != 15 or len(set(owned)) != 15 or any(value <= 0 for value in owned):
        raise P4ScenarioProductionError(
            "private current_team must contain exactly 15 unique owned elements"
        )
    captain = next(
        (
            int(row.get("element_id") or 0)
            for row in players
            if row.get("captain") is True
        ),
        None,
    )
    vice = next(
        (
            int(row.get("element_id") or 0)
            for row in players
            if row.get("vice_captain") is True
        ),
        None,
    )
    return owned, captain, vice



def _override_key(overrides: Mapping[str, Mapping[str, Any]]) -> str:
    return json.dumps(
        overrides,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _scenario_override_specs(
    owned: list[int],
    captain: int | None,
    vice: int | None,
) -> list[tuple[str, dict[str, dict[str, Any]]]]:
    rows: list[tuple[str, dict[str, dict[str, Any]]]] = []
    for element in owned:
        rows.append(
            (
                f"UNAVAILABLE_{element}",
                {
                    str(element): {
                        "override_type": "OWNED_UNAVAILABLE",
                        "p_available": 0.0,
                    }
                },
            )
        )
    if captain is not None:
        rows.append(
            (
                "CAPTAIN_UNAVAILABLE",
                {
                    str(captain): {
                        "override_type": "CAPTAIN_UNAVAILABLE",
                        "p_available": 0.0,
                    }
                },
            )
        )
    if vice is not None:
        rows.append(
            (
                "VICE_UNAVAILABLE",
                {
                    str(vice): {
                        "override_type": "VICE_UNAVAILABLE",
                        "p_available": 0.0,
                    }
                },
            )
        )
    keys = [_override_key(overrides) for _, overrides in rows]
    if len(keys) != len(set(keys)):
        raise P4ScenarioProductionError("P4 scenario override keys are not unique")
    return rows


def _configured_workers(scenario_count: int) -> int:
    raw = str(os.environ.get("V12_P4_MAX_WORKERS") or "2").strip()
    try:
        workers = int(raw)
    except ValueError as exc:
        raise P4ScenarioProductionError(
            f"invalid V12_P4_MAX_WORKERS: {raw!r}"
        ) from exc
    if workers < 1 or workers > 2:
        raise P4ScenarioProductionError(
            "V12_P4_MAX_WORKERS must remain within governed range 1..2"
        )
    return min(workers, max(1, int(scenario_count)))



def _safe_failure_token(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or len(text) > 160:
        return None
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-.=:+/")
    if any(ch not in allowed for ch in text):
        return None
    return text


def _sha256_only(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        return None
    return text


def _safe_scenario_failure_diagnostic(
    *,
    bundle: Mapping[str, Any],
    scenario_id: str,
    overrides: Mapping[str, Mapping[str, Any]],
    report_slot: str,
    warm_state_path: Path,
) -> dict[str, Any]:
    """Return a privacy-safe, bounded diagnostic for a failed P4 child."""
    proof = dict(bundle.get("execution_proof") or {})
    p4 = dict(proof.get("p4_scenario_override") or {})
    override_rows = [
        (str(element_id), dict(value))
        for element_id, value in overrides.items()
        if isinstance(value, Mapping)
    ]
    element_id = override_rows[0][0] if len(override_rows) == 1 else None
    override_type = (
        str(override_rows[0][1].get("override_type") or "")
        if len(override_rows) == 1
        else ("BASE" if not overrides else "MULTI")
    )

    failed_gates: list[str] = []
    for qa_name in ("pre_render_qa", "post_render_qa", "human_facing_qa"):
        qa = bundle.get(qa_name) or {}
        if not isinstance(qa, Mapping):
            continue
        raw = qa.get("hard_failures") or qa.get("failures") or []
        if isinstance(raw, (list, tuple)):
            for value in raw:
                token = _safe_failure_token(value)
                if token and token not in failed_gates:
                    failed_gates.append(token)

    failed_stages: list[str] = []
    raw_stages = proof.get("stages") or bundle.get("stage_ledger") or []
    if isinstance(raw_stages, list):
        for row in raw_stages:
            if not isinstance(row, Mapping):
                continue
            status = str(row.get("status") or "").upper()
            if status in {"PASS", "COMPLETE", "SKIPPED"}:
                continue
            name = _safe_failure_token(row.get("stage") or row.get("name"))
            if name and name not in failed_stages:
                failed_stages.append(name)

    stage2 = dict(proof.get("stage2_derived_cache") or {})
    cache_state: dict[str, Any] = {
        "stage2_status": _safe_failure_token(stage2.get("status")) or "UNKNOWN",
        "stage2_cache_hit": bool(stage2.get("cache_hit") is True),
        "stage2_cache_miss": bool(stage2.get("cache_miss") is True),
        "stage2_cache_write": bool(stage2.get("cache_write") is True),
    }

    execution_state = "UNKNOWN"
    fingerprints: dict[str, str] = {}
    try:
        if warm_state_path.exists():
            warm = _read_json(warm_state_path)
            package = dict(warm.get("package_with_stage3") or {})
            governance = dict(package.get("governance") or {})
            p17 = dict(governance.get("p1_7_execution_proof") or {})
            monte_carlo = dict(warm.get("monte_carlo") or {})
            performance = dict(monte_carlo.get("performance") or {})
            execution_state = (
                _safe_failure_token(monte_carlo.get("execution_state"))
                or execution_state
            )
            cache_state.update(
                {
                    "p17_cache_hits": int(p17.get("p17_cache_hits") or 0),
                    "p17_cache_misses": int(p17.get("p17_cache_misses") or 0),
                    "mc_simulation_cache_hit": bool(
                        performance.get("simulation_cache_hit") is True
                    ),
                }
            )
            candidates = {
                "package_output": (
                    (package.get("model_evidence_binding") or {}).get(
                        "output_fingerprint"
                    )
                ),
                "mc_output": monte_carlo.get("output_fingerprint"),
                "stage2_input": stage2.get("input_fingerprint"),
            }
            fingerprints = {
                key: value
                for key, raw in candidates.items()
                if (value := _sha256_only(raw)) is not None
            }
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass

    return {
        "scenario_id": _safe_failure_token(scenario_id) or "UNKNOWN",
        "override_type": _safe_failure_token(override_type) or "UNKNOWN",
        "element_id": _safe_failure_token(element_id) if element_id else None,
        "runner_status": (
            _safe_failure_token(bundle.get("runner_status")) or "UNKNOWN"
        ),
        "failed_gates": failed_gates[:12],
        "failed_stages": failed_stages[:12],
        "execution_state": execution_state,
        "cache_state": cache_state,
        "stage2_cache_bypassed": bool(p4.get("stage2_cache_bypassed") is True),
        "production_sha": _sha256_only(os.environ.get("GITHUB_SHA")),
        "runtime_data_sha": _sha256_only(os.environ.get("P4_RUNTIME_DATA_SHA")),
        "report_slot": _safe_failure_token(report_slot) or "UNKNOWN",
        "semantic_fingerprints": fingerprints,
    }


def _compact_p1_8_rebind_inputs(
    warm_state: Mapping[str, Any],
) -> dict[str, Any]:
    """Persist only the canonical fields P1.8 consumes for a later overlay rebind."""
    package = dict(warm_state.get("package_with_stage3") or {})
    monte_carlo = dict(warm_state.get("monte_carlo") or {})
    selected_route_id = str(package.get("selected_route_id") or "")
    raw_routes = [
        row for row in package.get("routes") or [] if isinstance(row, Mapping)
    ]
    if (
        package.get("model_owner") != "V12_PACKAGE_UTILITY"
        or not selected_route_id
        or not raw_routes
        or not monte_carlo
    ):
        raise P4ScenarioProductionError(
            "canonical scenario evaluator missing P1.8 rebind inputs"
        )

    routes: list[dict[str, Any]] = []
    route_ids: set[str] = set()
    for raw in raw_routes:
        route_id = str(raw.get("route_id") or "")
        if not route_id:
            continue
        per_gw = ((raw.get("football_route_utility") or {}).get("per_gw") or [])
        first_lineup = dict(per_gw[0]) if per_gw else {}
        routes.append(
            {
                "route_id": route_id,
                "classification": raw.get("classification"),
                "players_out": raw.get("players_out") or [],
                "players_in": raw.get("players_in") or [],
                "football_route_utility": {
                    "per_gw": [
                        {
                            "starting_xi": first_lineup.get("starting_xi") or [],
                            "bench_gk": first_lineup.get("bench_gk"),
                            "bench_order": first_lineup.get("bench_order") or [],
                            "captain": first_lineup.get("captain"),
                            "vice_captain": first_lineup.get("vice_captain"),
                        }
                    ]
                },
                "horizons": {
                    label: {
                        "net_delta_vs_hold": (
                            (raw.get("horizons") or {}).get(label) or {}
                        ).get("net_delta_vs_hold")
                    }
                    for label in ("GW+1", "3GW", "5GW")
                },
                "robustness": raw.get("robustness") or {},
                "expected_regret": raw.get("expected_regret"),
            }
        )
        route_ids.add(route_id)

    if selected_route_id not in route_ids:
        raise P4ScenarioProductionError(
            "P1.8 selected route missing from compact scenario package"
        )

    metrics: dict[str, Any] = {}
    raw_metrics = monte_carlo.get("metrics") or {}
    for route_id in route_ids:
        row = ((raw_metrics.get(route_id) or {}).get("1") or {})
        if isinstance(row, Mapping) and row:
            metrics[route_id] = {"1": dict(row)}

    paired_outputs: dict[str, Any] = {}
    raw_pairs = monte_carlo.get("paired_outputs") or {}
    for route_id in route_ids:
        for key in (
            f"{route_id}__VS__{selected_route_id}__H1",
            f"{selected_route_id}__VS__{route_id}__H1",
        ):
            row = raw_pairs.get(key)
            if isinstance(row, Mapping):
                paired_outputs[key] = {
                    "p_a_gt_b": row.get("p_a_gt_b"),
                }

    compact_package = {
        "model_owner": package.get("model_owner"),
        "selected_route_id": selected_route_id,
        "decision": package.get("decision") or {},
        "model_evidence_binding": {
            "output_fingerprint": (
                (package.get("model_evidence_binding") or {}).get(
                    "output_fingerprint"
                )
            )
        },
        "planning_gw": package.get("planning_gw"),
        "routes": routes,
    }
    compact_mc = {
        "model_owner": monte_carlo.get("model_owner"),
        "execution_state": monte_carlo.get("execution_state"),
        "canonical_pass": monte_carlo.get("canonical_pass"),
        "actual_paths": monte_carlo.get("actual_paths"),
        "output_fingerprint": monte_carlo.get("output_fingerprint"),
        "metrics": metrics,
        "paired_outputs": paired_outputs,
    }
    return {
        "package_with_stage3": compact_package,
        "monte_carlo": compact_mc,
    }


def _evaluate_scenario_worker(
    runtime_data_root_raw: str,
    private_root_raw: str,
    report_slot: str,
    output_dir_raw: str,
    cache_root_raw: str | None,
    overrides: Mapping[str, Mapping[str, Any]],
    scenario_id: str = "BASE",
) -> dict[str, Any]:
    runtime_data_root = Path(runtime_data_root_raw)
    private_root = Path(private_root_raw)
    output = Path(output_dir_raw)
    if cache_root_raw:
        cache_root = Path(cache_root_raw)
        cache_paths = {
            "V12_STAGE2_DERIVED_CACHE_DIR": cache_root / "stage2",
            "V12_P17_DECISION_CACHE_DIR": cache_root / "p17",
            "V12_MC_SIM_CACHE_DIR": cache_root / "mc",
        }
        for env_name, path in cache_paths.items():
            path.mkdir(parents=True, exist_ok=True)
            os.environ[env_name] = str(path)

    warm_state_path = output / "p4-warm-state.json"
    bundle = run_deep(
        runtime_data_root=runtime_data_root,
        report_slot=report_slot,
        output_dir=output,
        private_data_root=private_root,
        allow_legacy_private_sources=False,
        require_private_personal=True,
        scenario_overrides=overrides,
        warm_state_out=warm_state_path,
    )
    if str(bundle.get("runner_status") or "").upper() != "PASS":
        diagnostic = _safe_scenario_failure_diagnostic(
            bundle=bundle,
            scenario_id=scenario_id,
            overrides=overrides,
            report_slot=report_slot,
            warm_state_path=warm_state_path,
        )
        raise P4ScenarioProductionError(
            "P4_SCENARIO_FAIL "
            + json.dumps(diagnostic, sort_keys=True, separators=(",", ":"))
        )
    proof = dict(bundle.get("execution_proof") or {})
    p4 = dict(proof.get("p4_scenario_override") or {})
    if overrides:
        if p4.get("applied") is not True:
            raise P4ScenarioProductionError(
                "canonical evaluator did not acknowledge P4 override"
            )
        if p4.get("stage2_cache_bypassed") is not True:
            raise P4ScenarioProductionError(
                "P4 override must bypass Stage2 derived cache"
            )
    warm_state = _read_json(warm_state_path)
    result = _decision_result(bundle)
    result["p1_8_rebind_inputs"] = _compact_p1_8_rebind_inputs(warm_state)
    warm_state_path.unlink(missing_ok=True)
    return result


def materialize_p4_package(
    *,
    app_root: Path,
    runtime_data_root: Path,
    private_root: Path,
    report_slot: str,
    workspace: Path,
) -> dict[str, Any]:
    identity = _identity(app_root, runtime_data_root, private_root)
    owned, captain, vice = _owned_context(private_root)
    workspace.mkdir(parents=True, exist_ok=True)

    base = _evaluate_scenario_worker(
        str(runtime_data_root),
        str(private_root),
        report_slot,
        str(workspace / "scenario-000-base"),
        None,
        {},
    )

    scenario_specs = _scenario_override_specs(owned, captain, vice)
    scenario_results: dict[str, Mapping[str, Any]] = {}
    workers = _configured_workers(len(scenario_specs))
    executor = ProcessPoolExecutor(
        max_workers=workers,
        mp_context=get_context("spawn"),
        max_tasks_per_child=1,
    )
    futures = {}
    try:
        for index, (scenario_id, overrides) in enumerate(
            scenario_specs,
            start=1,
        ):
            key = _override_key(overrides)
            future = executor.submit(
                _evaluate_scenario_worker,
                str(runtime_data_root),
                str(private_root),
                report_slot,
                str(workspace / f"scenario-{index:03d}-{scenario_id}"),
                str(workspace / "parallel-cache" / scenario_id),
                overrides,
                scenario_id,
            )
            futures[future] = key
        for future in as_completed(futures):
            key = futures[future]
            scenario_results[key] = future.result()
    except Exception as exc:
        for future in futures:
            future.cancel()
        raise P4ScenarioProductionError(
            f"parallel canonical P4 scenario evaluation failed: {exc}"
        ) from exc
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    def evaluate(overrides: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
        key = _override_key(overrides)
        if key not in scenario_results:
            raise P4ScenarioProductionError(
                "canonical P4 scenario result was not precomputed"
            )
        return scenario_results[key]

    package = build_scenario_package(
        dependencies=identity.p4_dependencies(),
        base_result=base,
        owned_elements=owned,
        evaluate=evaluate,
        generated_at=datetime.now().astimezone().isoformat(),
        captain_element=captain,
        vice_element=vice,
    )
    if int(package.get("scenario_count") or 0) < 16:
        raise P4ScenarioProductionError("P4 package scenario coverage is incomplete")
    if package.get("private_only") is not True:
        raise P4ScenarioProductionError("P4 package lost private-only governance")
    return package


MAX_P4_SHARD_BYTES = 95 * 1024 * 1024


def write_sharded_package(package: Mapping[str, Any], output: Path) -> dict[str, Any]:
    """Persist a tiny manifest plus independently compressed scenario shards."""
    output.parent.mkdir(parents=True, exist_ok=True)
    package_fingerprint = str(package.get("package_fingerprint") or "").strip()
    if not package_fingerprint:
        raise P4ScenarioProductionError("P4 package fingerprint unavailable")
    shard_root = output.parent / "shards" / package_fingerprint
    shard_root.mkdir(parents=True, exist_ok=True)

    index: list[dict[str, Any]] = []
    total_compressed = 0
    for raw in package.get("scenarios") or []:
        if not isinstance(raw, Mapping):
            raise P4ScenarioProductionError("P4 scenario row is not an object")
        row = dict(raw)
        scenario_id = str(row.get("scenario_id") or "").strip()
        if not scenario_id or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for ch in scenario_id):
            raise P4ScenarioProductionError(f"unsafe P4 scenario id: {scenario_id!r}")

        # delta_vs_base duplicated the already-authoritative base and scenario
        # surfaces and is not consumed by serving. Exclude it from persisted
        # storage while preserving the canonical output fingerprint.
        shard_payload = dict(row)
        shard_payload.pop("delta_vs_base", None)
        relative = Path("shards") / package_fingerprint / f"{scenario_id}.json.gz"
        shard_path = output.parent / relative
        with gzip.open(shard_path, "wt", encoding="utf-8", compresslevel=9) as fh:
            json.dump(
                shard_payload,
                fh,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            fh.write("\n")
        compressed_bytes = shard_path.stat().st_size
        if compressed_bytes >= MAX_P4_SHARD_BYTES:
            raise P4ScenarioProductionError(
                f"P4 shard exceeds governed GitHub-safe limit: {scenario_id}={compressed_bytes}"
            )
        total_compressed += compressed_bytes
        index.append(
            {
                "scenario_id": scenario_id,
                "base_fingerprint": row.get("base_fingerprint"),
                "override_type": row.get("override_type"),
                "override_input": row.get("override_input"),
                "output_fingerprint": row.get("output_fingerprint"),
                "storage_path": relative.as_posix(),
                "storage_encoding": "gzip-json-v1",
                "compressed_bytes": compressed_bytes,
            }
        )

    manifest = {k: v for k, v in dict(package).items() if k != "scenarios"}
    manifest["scenarios"] = index
    manifest["storage"] = {
        "format": "SHARDED_GZIP_JSON_V1",
        "scenario_count": len(index),
        "total_compressed_bytes": total_compressed,
        "max_shard_bytes": max((int(row["compressed_bytes"]) for row in index), default=0),
        "monolithic_package_persisted": False,
        "git_lfs_required": False,
    }
    output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize governed private P4 package")
    parser.add_argument("--app-root", default=".")
    parser.add_argument("--runtime-data-root", required=True)
    parser.add_argument("--private-root", required=True)
    parser.add_argument("--report-slot", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    package = materialize_p4_package(
        app_root=Path(args.app_root).resolve(),
        runtime_data_root=Path(args.runtime_data_root).resolve(),
        private_root=Path(args.private_root).resolve(),
        report_slot=args.report_slot,
        workspace=Path(args.workspace).resolve(),
    )
    output = Path(args.output)
    manifest = write_sharded_package(package, output)
    print(
        json.dumps(
            {
                "status": "PASS",
                "scenario_count": manifest["scenario_count"],
                "package_fingerprint": manifest["package_fingerprint"],
                "private_only": manifest["private_only"],
                "storage_format": manifest["storage"]["format"],
                "total_compressed_bytes": manifest["storage"]["total_compressed_bytes"],
                "max_shard_bytes": manifest["storage"]["max_shard_bytes"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
