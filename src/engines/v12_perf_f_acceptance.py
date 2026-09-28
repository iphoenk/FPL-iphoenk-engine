from __future__ import annotations

"""Controlled production-real PERF-F executor.

Each case uses exact production code plus copies of the current runtime/private
planes. Controlled mutations never touch authoritative runtime-data-v6 or
personal files. Warm and canonical-cold paths consume the same case input.
Only the governed acceptance namespace may be published back to the private
repository.
"""

import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Mapping

from .v12_cache_operational import LAYERS
from .v12_p6_runtime import (
    CanonicalPipeline,
    _full_recompute_states,
    _identity,
    _load_scenario_package,
)
from .v12_p6_warm_worker import CanonicalCallbacks, WarmWorker
from .v12_perf_f import REQUIRED_CASES
from .v12_perf_f_production import validate_production_sample
from .v12_semantic_oracle import semantic_fingerprint


class PerfFAcceptanceError(RuntimeError):
    pass


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PerfFAcceptanceError(f"expected JSON object: {path}")
    return value


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _copy_repo(source: Path, destination: Path) -> Path:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, symlinks=True)
    return destination


def _owned(private_root: Path) -> tuple[list[int], int | None, int | None]:
    payload = _read(private_root / "personal/current_team.json")
    players = [row for row in payload.get("players") or [] if isinstance(row, Mapping)]
    ids = [int(row.get("element_id") or 0) for row in players]
    if len(ids) != 15 or len(set(ids)) != 15 or any(value <= 0 for value in ids):
        raise PerfFAcceptanceError("controlled PERF-F requires exact private CURRENT15")
    captain = next(
        (int(row["element_id"]) for row in players if row.get("captain") is True),
        None,
    )
    vice = next(
        (int(row["element_id"]) for row in players if row.get("vice_captain") is True),
        None,
    )
    return ids, captain, vice


def _bootstrap_elements(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        payload.get("bootstrap"),
        (payload.get("official") or {}).get("bootstrap")
        if isinstance(payload.get("official"), Mapping)
        else None,
        (payload.get("payload") or {}).get("bootstrap")
        if isinstance(payload.get("payload"), Mapping)
        else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, Mapping) and isinstance(candidate.get("elements"), list):
            return candidate["elements"]
    raise PerfFAcceptanceError("official_fpl bootstrap elements unavailable")


def _controlled_fingerprint(runtime: Path, private: Path, case: str) -> str:
    digest = hashlib.sha256()
    digest.update(case.encode("utf-8"))
    for root, rel in (
        (runtime, "data/v6/current/official_fpl.json"),
        (runtime, "data/v6/current/official_price_predictor.json"),
        (runtime, "data/v6/mini_leagues/9477/standings.json"),
        (private, "personal/current_team.json"),
        (private, "personal/memberships.json"),
    ):
        path = root / rel
        digest.update(rel.encode("utf-8"))
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _mutate_mini(runtime: Path) -> list[str]:
    path = runtime / "data/v6/mini_leagues/9477/standings.json"
    payload = _read(path)
    managers = payload.get("managers") or []
    target = next(
        (
            row for row in managers
            if isinstance(row, dict) and int(row.get("entry_id") or 0) == 3462711
        ),
        None,
    )
    if target is None:
        raise PerfFAcceptanceError("owned mini-league entry unavailable")
    target["gw_score"] = int(target.get("gw_score") or 0) + 1
    target["league_total"] = int(target.get("league_total") or 0) + 1
    _write(path, payload)
    return ["mini_league:9477:entry:3462711"]


def _mutate_price(runtime: Path, owned_ids: list[int]) -> list[str]:
    path = runtime / "data/v6/current/official_price_predictor.json"
    payload = _read(path)
    players = ((payload.get("data") or {}).get("players") or [])
    target = next(
        (
            row for row in players
            if isinstance(row, dict) and int(row.get("id") or 0) in set(owned_ids)
        ),
        None,
    )
    if target is None:
        raise PerfFAcceptanceError("owned player missing from official price predictor")
    element = int(target["id"])
    current = float(target.get("price_change_percent") or 0.0)
    changed = current + (7.3 if current <= 90.0 else -7.3)
    target["price_change_percent"] = f"{changed:.1f}"
    projections = target.get("price_change_projections") or []
    if projections and isinstance(projections[0], dict):
        projections[0]["projected_percent"] = f"{changed:.1f}"
    _write(path, payload)
    return [f"price:{element}"]


def _mutate_role(private: Path, *, captain: bool) -> list[str]:
    path = private / "personal/current_team.json"
    payload = _read(path)
    players = [row for row in payload.get("players") or [] if isinstance(row, dict)]
    current_c = next((row for row in players if row.get("captain") is True), None)
    current_v = next((row for row in players if row.get("vice_captain") is True), None)
    blocked = {
        int((current_c or {}).get("element_id") or 0),
        int((current_v or {}).get("element_id") or 0),
    }
    replacement = next(
        (
            row for row in players
            if int(row.get("element_id") or 0) not in blocked
        ),
        None,
    )
    if replacement is None:
        raise PerfFAcceptanceError("no controlled captain/vice replacement available")
    field = "captain" if captain else "vice_captain"
    for row in players:
        row[field] = False
    replacement[field] = True
    _write(path, payload)
    return ["captain" if captain else "vice_captain"]


def _mutate_material_projection(runtime: Path, owned_ids: list[int]) -> list[str]:
    path = runtime / "data/v6/current/official_fpl.json"
    payload = _read(path)
    elements = _bootstrap_elements(payload)
    target = next(
        (
            row for row in elements
            if isinstance(row, dict) and int(row.get("id") or 0) in set(owned_ids)
        ),
        None,
    )
    if target is None:
        raise PerfFAcceptanceError("owned element missing from official bootstrap")
    element = int(target["id"])
    current = target.get("chance_of_playing_next_round")
    target["chance_of_playing_next_round"] = 0 if current != 0 else 100
    _write(path, payload)
    return [f"projection:{element}:availability"]


def _scenario_override_from_row(row: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = dict(row.get("override_input") or {})
    element = int(raw.get("element_id") or 0)
    if element <= 0:
        raise PerfFAcceptanceError("P4 scenario row has no controlled element")
    return {
        str(element): {
            "override_type": str(row.get("override_type") or "OWNED_UNAVAILABLE"),
            "p_available": float(raw.get("p_available") or 0.0),
        }
    }


def _case_inputs(
    *,
    case: str,
    runtime: Path,
    private: Path,
    baseline_identity: Any,
    scenario_package: Mapping[str, Any] | None,
) -> tuple[list[str], dict[str, dict[str, Any]], dict[str, Any]]:
    owned_ids, _, _ = _owned(private)
    overrides: dict[str, dict[str, Any]] = {}
    extra: dict[str, Any] = {}

    if case == "NO_CHANGE":
        keys: list[str] = []
    elif case == "MINI_LEAGUE_ONLY":
        keys = _mutate_mini(runtime)
    elif case == "PRICE_ONLY":
        keys = _mutate_price(runtime, owned_ids)
    elif case == "OUR15_AVAILABILITY":
        element = owned_ids[0]
        overrides = {
            str(element): {
                "override_type": "OWNED_UNAVAILABLE",
                "p_available": 0.0,
            }
        }
        keys = [f"owned:{element}:availability"]
    elif case == "CAPTAIN_CHANGE":
        keys = _mutate_role(private, captain=True)
    elif case == "VICE_CAPTAIN_CHANGE":
        keys = _mutate_role(private, captain=False)
    elif case == "MATERIAL_PROJECTION":
        keys = _mutate_material_projection(runtime, owned_ids)
    elif case == "P4_SCENARIO_HIT":
        if not scenario_package:
            raise PerfFAcceptanceError("P4_SCENARIO_HIT requires private scenario package")
        row = next(
            (
                item for item in scenario_package.get("scenarios") or []
                if isinstance(item, Mapping)
                and str(item.get("override_type") or "") == "OWNED_UNAVAILABLE"
            ),
            None,
        )
        if row is None:
            raise PerfFAcceptanceError("P4 package has no OWNED_UNAVAILABLE scenario")
        overrides = _scenario_override_from_row(row)
        keys = []
        extra["scenario_id"] = str(row.get("scenario_id") or "")
    elif case == "P4_SCENARIO_MISS":
        if not scenario_package:
            raise PerfFAcceptanceError("P4_SCENARIO_MISS requires private scenario package")
        keys = ["projection_lineage_fingerprint"]
        deps = dict(baseline_identity.p4_dependencies())
        deps["projection_lineage_fingerprint"] = (
            deps["projection_lineage_fingerprint"] + ":CONTROLLED_MISS"
        )
        extra["scenario_dependencies"] = deps
    else:
        raise PerfFAcceptanceError(f"unsupported PERF-F case: {case}")
    return keys, overrides, extra


def execute_case(
    *,
    app: Path,
    runtime_source: Path,
    private_source: Path,
    private_publisher: Path,
    workspace: Path,
    report_slot: str,
    case: str,
    run_id: str,
) -> dict[str, Any]:
    case = str(case).upper()
    if case not in REQUIRED_CASES:
        raise PerfFAcceptanceError(f"case not in PERF-F contract: {case}")

    case_runtime = _copy_repo(runtime_source, workspace / "case-runtime")
    case_private = _copy_repo(private_source, workspace / "case-private-input")
    baseline_runtime = _copy_repo(runtime_source, workspace / "baseline-runtime")
    baseline_private = _copy_repo(private_source, workspace / "baseline-private-input")

    baseline_identity = _identity(app, baseline_runtime, baseline_private)
    scenario_package = _load_scenario_package(baseline_private)
    keys, overrides, extra = _case_inputs(
        case=case,
        runtime=case_runtime,
        private=case_private,
        baseline_identity=baseline_identity,
        scenario_package=scenario_package,
    )
    final_identity = _identity(app, case_runtime, case_private)
    controlled_fingerprint = _controlled_fingerprint(case_runtime, case_private, case)

    baseline_pipeline = CanonicalPipeline(
        app=app,
        runtime=baseline_runtime,
        private=baseline_private,
        workspace=workspace / "warm-baseline",
        report_kind="full_master",
        logical_slot=report_slot,
        run_id=f"{run_id}-baseline",
        publisher_private=private_publisher,
        private_destination_relpath=f"acceptance/perf-f/{run_id}/{case}/warm",
        update_latest=False,
    )
    frozen_state = baseline_pipeline.compute(baseline_identity)

    cold_pipeline = CanonicalPipeline(
        app=app,
        runtime=case_runtime,
        private=case_private,
        workspace=workspace / "canonical-cold",
        report_kind="full_master",
        logical_slot=report_slot,
        run_id=f"{run_id}-cold",
        publisher_private=private_publisher,
        private_destination_relpath=f"acceptance/perf-f/{run_id}/{case}/cold",
        update_latest=False,
    )
    cold_state = cold_pipeline.compute(
        final_identity,
        scenario_overrides=overrides or None,
    )
    cold_fingerprint = semantic_fingerprint(cold_state["bundle"])

    warm_pipeline = CanonicalPipeline(
        app=app,
        runtime=case_runtime,
        private=case_private,
        workspace=workspace / "warm-change",
        report_kind="full_master",
        logical_slot=report_slot,
        run_id=f"{run_id}-{case.lower()}",
        publisher_private=private_publisher,
        private_destination_relpath=f"acceptance/perf-f/{run_id}/{case}/warm",
        update_latest=False,
    )
    current_state: dict[str, Any] = dict(frozen_state)

    def load_canonical(identity: Any, private_state: Mapping[str, Any]) -> Mapping[str, Any]:
        return current_state

    def recompute(
        state: Mapping[str, Any],
        change: Mapping[str, Any],
        plan: Any,
    ) -> tuple[Mapping[str, Any], Mapping[str, str], Mapping[str, list[str]]]:
        nonlocal current_state
        change_class = str(change.get("change_class") or "").upper()
        if change_class == "NO_CHANGE":
            current_state = dict(state)
            return current_state, dict(plan.expected), {}
        current_state = warm_pipeline.compute(
            final_identity,
            scenario_overrides=overrides or None,
        )
        return current_state, _full_recompute_states(plan.expected), {}

    def stage3(state: Mapping[str, Any]) -> Mapping[str, Any]:
        return dict(state["stage3_acceptance"])

    def render(
        state: Mapping[str, Any],
        stage3_state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return dict(state["bundle"])

    def qa(
        rendered: Mapping[str, Any],
        stage3_state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        for key in ("pre_render_qa", "post_render_qa", "human_facing_qa"):
            if str((rendered.get(key) or {}).get("status") or "").upper() != "PASS":
                return {"status": "FAIL", "failed_key": key}
        return {"status": "PASS"}

    def private_publish(
        rendered: Mapping[str, Any],
        qa_state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return warm_pipeline.publish(current_state)

    worker = WarmWorker(
        identity=baseline_identity,
        private_state={
            "owner_context_fingerprint": baseline_identity.owner_context_fingerprint,
            "current15_fingerprint": baseline_identity.current15_fingerprint,
        },
        scenario_package=scenario_package,
        callbacks=CanonicalCallbacks(
            load_canonical_state=load_canonical,
            recompute=recompute,
            stage3=stage3,
            render=render,
            qa=qa,
            private_publish=private_publish,
        ),
        ttl_seconds=5 * 60 * 60 + 45 * 60,
    )
    worker.start()
    change = {
        "change_class": case,
        "affected_dependency_keys": keys,
        "scope_certain": True,
        **extra,
    }
    result = worker.apply_change(change)
    worker.shutdown()
    result["final_identity"] = {
        **asdict(final_identity),
        "controlled_input_fingerprint": controlled_fingerprint,
        "controlled_acceptance": True,
    }

    verdict = validate_production_sample(
        case=case,
        worker_result=result,
        execution_proof=cold_state["execution_proof"],
        cold_semantic_fingerprint=cold_fingerprint,
        target_seconds=15.0,
    )
    return {
        "case": case,
        "status": verdict["status"],
        "reason": verdict["reason"],
        "total_seconds": verdict["total_seconds"],
        "latency_pass": verdict["latency_pass"],
        "semantic_equal": verdict["semantic_equal"],
        "cache_correctness_pass": verdict["cache_correctness_pass"],
        "cache_performance": verdict["cache_performance"],
        "private_publish_pass": verdict["private_publish_pass"],
        "expected_cache_state": result["expected_cache_state"],
        "actual_cache_state": result["actual_cache_state"],
        "timings": verdict["timings"],
        "production_sha": final_identity.production_sha,
        "runtime_data_sha": final_identity.runtime_data_sha,
        "controlled_input_fingerprint": controlled_fingerprint,
        "warm_semantic_fingerprint": result["warm_semantic_fingerprint"],
        "cold_semantic_fingerprint": cold_fingerprint,
        "private_remote_sha": result["private_remote_sha"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one controlled production PERF-F case")
    parser.add_argument("--app-root", default=".")
    parser.add_argument("--runtime-data-root", required=True)
    parser.add_argument("--private-input-root", required=True)
    parser.add_argument("--private-publisher-root", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--report-slot", required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--result-out", required=True)
    args = parser.parse_args()

    result = execute_case(
        app=Path(args.app_root).resolve(),
        runtime_source=Path(args.runtime_data_root).resolve(),
        private_source=Path(args.private_input_root).resolve(),
        private_publisher=Path(args.private_publisher_root).resolve(),
        workspace=Path(args.workspace).resolve(),
        report_slot=args.report_slot,
        case=args.case,
        run_id=args.run_id,
    )
    out = Path(args.result_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
