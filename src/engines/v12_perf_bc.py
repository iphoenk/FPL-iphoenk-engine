from __future__ import annotations

"""Non-authoritative PERF-B / PERF-C exploratory harness.

This module is deliberately isolated from production runtime selection.  It
benchmarks exact canonical code paths and emits public-safe timing/fingerprint
evidence only.  It never publishes a decision or writes to the private repo.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from copy import deepcopy
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import pickle
import platform
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "performance" / "v12_perf_bc.json"

NORMALIZED_DISABLE = (
    "X86_V4,AVX512F,AVX512CD,AVX512_KNL,AVX512_KNM,"
    "AVX512_SKX,AVX512_CLX,AVX512_CNL,AVX512_ICL,AVX512_SPR"
)
EPHEMERAL_KEYS = {
    "elapsed_seconds",
    "wall_seconds",
    "path_throughput_per_second",
    "load_or_build_seconds",
    "generated_at",
    "observed_at",
    "created_at",
    "updated_at",
    "started_at",
    "completed_at",
}


def _config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    if isinstance(value, str):
        payload = value.encode("utf-8")
    elif isinstance(value, bytes):
        payload = value
    else:
        payload = _canonical_json(value)
    return hashlib.sha256(payload).hexdigest()


def _semantic_strip(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(k): _semantic_strip(v)
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
            if str(k) not in EPHEMERAL_KEYS
            and not str(k).endswith("_seconds")
            and "timing" not in str(k).lower()
        }
    if isinstance(value, list):
        return [_semantic_strip(v) for v in value]
    return value


def _runtime_identity() -> dict[str, Any]:
    from src.engines.v12_cache_runtime_identity import runtime_cache_identity
    ident = dict(runtime_cache_identity())
    cpu_model = "UNKNOWN"
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                cpu_model = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "cpu_model": cpu_model,
        "runner_os": os.getenv("RUNNER_OS"),
        "runner_arch": os.getenv("RUNNER_ARCH"),
        "runner_image_os": os.getenv("ImageOS"),
        "runner_image_version": os.getenv("ImageVersion"),
        "numeric_runtime": ident,
    }


def _peak_memory_mb() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        return value / (1024.0 * 1024.0)
    return value / 1024.0


def _normalized_env() -> dict[str, str]:
    env = dict(os.environ)
    env["OPENBLAS_CORETYPE"] = "Haswell"
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["OMP_NUM_THREADS"] = "1"
    env["NPY_DISABLE_CPU_FEATURES"] = NORMALIZED_DISABLE
    env["V12_PRIVATE_CACHE_PROFILE"] = "SECURE_NO_PERSONAL_CACHE"
    env.pop("FPL_V12_PRIVATE_CACHE_KEY_B64", None)
    return env


def _native_mc_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("OPENBLAS_CORETYPE", None)
    env.pop("NPY_DISABLE_CPU_FEATURES", None)
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["OMP_NUM_THREADS"] = "1"
    env["V12_PRIVATE_CACHE_PROFILE"] = "SECURE_NO_PERSONAL_CACHE"
    env.pop("FPL_V12_PRIVATE_CACHE_KEY_B64", None)
    return env


def _median(rows: Sequence[float]) -> float:
    return float(statistics.median(float(v) for v in rows))


def select_occurrence(private_root: Path, output: Path) -> int:
    rows: list[tuple[str, Path, dict[str, Any]]] = []
    for path in private_root.glob("reports/**/delivery_receipt.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(payload.get("report_mode") or "").upper() != "DEEP":
            continue
        slot = str(payload.get("report_slot") or "")
        runtime_sha = str(payload.get("runtime_sha") or "")
        if slot and len(runtime_sha) == 40:
            rows.append((slot, path.parent, payload))
    if not rows:
        raise RuntimeError("no private DEEP delivery receipt found")
    rows.sort(key=lambda item: item[0])
    slot, report_dir, payload = rows[-1]
    previous_dir = rows[-2][1] if len(rows) > 1 else None
    result = {
        "report_slot": slot,
        "runtime_sha": str(payload["runtime_sha"]),
        "source_receipt_sha256": _sha((report_dir / "delivery_receipt.json").read_bytes()),
        "previous_deep_dir": str(previous_dir.resolve()) if previous_dir is not None else None,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("PERF_BC_OCCURRENCE=" + json.dumps(result, sort_keys=True))
    return 0


def _decision_fingerprint(bundle: Mapping[str, Any]) -> str:
    watched = {
        "selected_route_id", "final_captain", "captain", "vice", "vice_captain",
        "xi", "bench_order", "bench_gk", "decision_state", "stage3_action",
        "action_contract",
    }
    found: list[tuple[str, Any]] = []
    def walk(value: Any, prefix: str = "") -> None:
        if isinstance(value, Mapping):
            for key, child in sorted(value.items(), key=lambda item: str(item[0])):
                key_s = str(key)
                path = f"{prefix}.{key_s}" if prefix else key_s
                if key_s in watched:
                    found.append((path, _semantic_strip(child)))
                walk(child, path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{prefix}[{index}]")
    walk(bundle.get("report") or {})
    walk(bundle.get("execution_proof") or {})
    return _sha(found)


def _stage_seconds(bundle: Mapping[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in bundle.get("stage_ledger") or []:
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("stage") or "")
        elapsed = row.get("elapsed_seconds")
        if name and elapsed is not None:
            try:
                out[name] = float(elapsed)
            except (TypeError, ValueError):
                pass
    return out

        name = str(row.get("stage") or "")
        elapsed = row.get("elapsed_seconds")
        if name and elapsed is not None:
            try:
                out[name] = float(elapsed)
            except (TypeError, ValueError):
                pass
    return out


def _mc_native_child(input_path: Path, output_path: Path) -> int:
    from src.engines.v12_monte_carlo import run_correlated_monte_carlo

    with input_path.open("rb") as fh:
        payload = pickle.load(fh)
    started = time.perf_counter()
    result = run_correlated_monte_carlo(*payload["args"], **payload["kwargs"])
    compute = time.perf_counter() - started
    safe = {
        "result": result,
        "child_compute_seconds": compute,
        "runtime_identity": _runtime_identity(),
        "peak_memory_mb": _peak_memory_mb(),
    }
    with output_path.open("wb") as fh:
        pickle.dump(safe, fh, protocol=pickle.HIGHEST_PROTOCOL)
    return 0


def _build_mc_wrapper(
    *,
    runtime_class: str,
    temp_root: Path,
    records: list[dict[str, Any]],
):
    from src.engines import v12_monte_carlo as mc

    original = mc.run_correlated_monte_carlo
    counter = {"value": 0}

    if runtime_class == "NORMALIZED":
        def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            counter["value"] += 1
            started = time.perf_counter()
            result = original(*args, **kwargs)
            elapsed = time.perf_counter() - started
            records.append(
                {
                    "sequence": counter["value"],
                    "runtime_class": "NORMALIZED",
                    "wall_seconds": elapsed,
                    "child_compute_seconds": elapsed,
                    "serialization_seconds": 0.0,
                    "deserialization_seconds": 0.0,
                    "spawn_overhead_seconds": 0.0,
                    "output_fingerprint": result.get("output_fingerprint"),
                    "actual_paths": result.get("actual_paths"),
                    "canonical_pass": result.get("canonical_pass"),
                    "cache_hit": (
                        (result.get("performance") or {}).get(
                            "simulation_cache_hit"
                        )
                    ),
                }
            )
            return result
        return wrapper

    if runtime_class != "NATIVE_MC_SUBPROCESS":
        raise ValueError(runtime_class)

    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        counter["value"] += 1
        seq = counter["value"]
        input_path = temp_root / f"mc-native-{seq}.input.pkl"
        output_path = temp_root / f"mc-native-{seq}.output.pkl"
        ser_started = time.perf_counter()
        with input_path.open("wb") as fh:
            pickle.dump({"args": args, "kwargs": kwargs}, fh, protocol=pickle.HIGHEST_PROTOCOL)
        ser_seconds = time.perf_counter() - ser_started

        spawn_started = time.perf_counter()
        subprocess.run(
            [
                sys.executable,
                "-m",
                "src.engines.v12_perf_bc",
                "_mc-native-child",
                "--input",
                str(input_path),
                "--output",
                str(output_path),
            ],
            cwd=ROOT,
            env=_native_mc_env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        spawn_wall = time.perf_counter() - spawn_started
        deser_started = time.perf_counter()
        with output_path.open("rb") as fh:
            child = pickle.load(fh)
        deser_seconds = time.perf_counter() - deser_started
        result = child["result"]
        child_compute = float(child["child_compute_seconds"])
        records.append(
            {
                "sequence": seq,
                "runtime_class": "NATIVE_MC_SUBPROCESS",
                "wall_seconds": spawn_wall + ser_seconds + deser_seconds,
                "child_compute_seconds": child_compute,
                "serialization_seconds": ser_seconds,
                "deserialization_seconds": deser_seconds,
                "spawn_overhead_seconds": max(0.0, spawn_wall - child_compute),
                "output_fingerprint": result.get("output_fingerprint"),
                "actual_paths": result.get("actual_paths"),
                "canonical_pass": result.get("canonical_pass"),
                "cache_hit": (
                    (result.get("performance") or {}).get("simulation_cache_hit")
                ),
                "native_runtime_identity": child.get("runtime_identity"),
                "native_peak_memory_mb": child.get("peak_memory_mb"),
            }
        )
        try:
            input_path.unlink()
            output_path.unlink()
        except OSError:
            pass
        return result

    return wrapper


def _teammate_contexts(
    *,
    bootstrap: Mapping[str, Any],
    strength: Mapping[str, Any],
    prior_payload: Mapping[str, Any],
) -> dict[int, tuple[dict[str, Any], dict[str, Any]]]:
    team_rows = {
        int(team["team_id"]): team
        for team in strength.get("teams") or []
        if isinstance(team, Mapping) and team.get("team_id") is not None
    }
    historical_map = prior_payload.get("players") or {}
    out: dict[int, tuple[dict[str, Any], dict[str, Any]]] = {}
    for raw in bootstrap.get("elements") or []:
        player = dict(raw)
        element = int(player.get("id") or -1)
        if element <= 0:
            continue
        team_id = int(player.get("team") or -1)
        matches_played = int(
            (team_rows.get(team_id) or {}).get("matches_played") or 0
        )
        historical = historical_map.get(str(element)) or {}
        context: dict[str, Any] = {"team_matches_played": matches_played}
        if historical:
            context.update(
                {
                    "prior_start_probability": historical.get(
                        "start_probability"
                    ),
                    "starter_minutes_prior": historical.get(
                        "avg_minutes_when_start"
                    ),
                    "prior_evidence_minutes": historical.get("minutes"),
                }
            )
        out[element] = (player, context)
    return out


def _optimized_projection_builder(original_build, workers: int, metrics: dict[str, Any]):
    from src.models import historical_projection as hp

    original_estimate = hp.estimate_xmins

    def build(*args: Any, **kwargs: Any):
        bootstrap = args[0] if len(args) > 0 else kwargs["bootstrap"]
        strength = args[1] if len(args) > 1 else kwargs["strength"]
        prior_payload = args[3] if len(args) > 3 else kwargs["prior_payload"]
        calibration_summary = kwargs.get("calibration_summary")
        model_evidence_binding = kwargs.get("model_evidence_binding")
        contexts = _teammate_contexts(
            bootstrap=bootstrap,
            strength=strength,
            prior_payload=prior_payload,
        )
        pre_started = time.perf_counter()

        def compute(item: tuple[int, tuple[dict[str, Any], dict[str, Any]]]):
            element, (player, context) = item
            value = original_estimate(
                player,
                context,
                calibration_summary=calibration_summary,
                model_evidence_binding=model_evidence_binding,
            )
            return element, deepcopy(value), _sha(context)

        items = sorted(contexts.items(), key=lambda item: item[0])
        if workers <= 1:
            computed = [compute(item) for item in items]
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                computed = list(executor.map(compute, items))
        cache = {element: value for element, value, _ in computed}
        context_hashes = {element: ctx_hash for element, _, ctx_hash in computed}
        metrics["precompute_seconds"] = time.perf_counter() - pre_started
        metrics["precomputed_players"] = len(cache)
        metrics["workers"] = workers
        metrics["cache_hits"] = 0
        metrics["cache_misses"] = 0

        def cached_estimate(
            player: Mapping[str, Any],
            context: Mapping[str, Any],
            calibration_summary: Mapping[str, Any] | None = None,
            model_evidence_binding: Mapping[str, Any] | None = None,
        ):
            element = int(player.get("id") or -1)
            if (
                element in cache
                and _sha(context) == context_hashes[element]
            ):
                metrics["cache_hits"] += 1
                return deepcopy(cache[element])
            metrics["cache_misses"] += 1
            return original_estimate(
                player,
                context,
                calibration_summary=calibration_summary,
                model_evidence_binding=model_evidence_binding,
            )

        hp.estimate_xmins = cached_estimate
        try:
            return original_build(*args, **kwargs)
        finally:
            hp.estimate_xmins = original_estimate

    return build


def _prepare_cold_cache_dirs(root: Path) -> None:
    for name in ("stage2", "p17", "mc"):
        path = root / name
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True, exist_ok=True)
    os.environ["V12_STAGE2_DERIVED_CACHE_DIR"] = str(root / "stage2")
    os.environ["V12_P17_DECISION_CACHE_DIR"] = str(root / "p17")
    os.environ["V12_MC_SIM_CACHE_DIR"] = str(root / "mc")
    os.environ["V12_PRIVATE_CACHE_PROFILE"] = "SECURE_NO_PERSONAL_CACHE"
    os.environ.pop("FPL_V12_PRIVATE_CACHE_KEY_B64", None)


def _full_child(args: argparse.Namespace) -> int:
    process_started = time.perf_counter()
    os.environ.update(_normalized_env())
    os.environ.pop("FPL_V12_PRIVATE_CACHE_KEY_B64", None)
    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    cache_root = work / "cache"
    _prepare_cold_cache_dirs(cache_root)

    # Import after normalized runtime env is locked.
    from src.engines import v12_integrated_report_runner as runner
    from src.engines import v12_mini_league_overlay as mini
    from src.engines import v12_monte_carlo as mc
    from src.engines.v12_private_publisher import publish_private_output

    mc_records: list[dict[str, Any]] = []
    original_mc = mc.run_correlated_monte_carlo
    original_mini_mc = mini.run_correlated_monte_carlo
    wrapper = _build_mc_wrapper(
        runtime_class=args.runtime_class,
        temp_root=work,
        records=mc_records,
    )
    mc.run_correlated_monte_carlo = wrapper
    mini.run_correlated_monte_carlo = wrapper

    stage2_metrics: dict[str, Any] = {}
    original_runner_projection = runner.build_player_projections
    if int(args.stage2_workers or 0) > 0:
        runner.build_player_projections = _optimized_projection_builder(
            original_runner_projection,
            int(args.stage2_workers),
            stage2_metrics,
        )

    output_dir = work / "canonical"
    output_dir.mkdir(parents=True, exist_ok=True)
    compute_started = time.perf_counter()
    try:
        bundle = runner.run_deep(
            runtime_data_root=Path(args.runtime_data_root),
            report_slot=args.report_slot,
            output_dir=output_dir,
            previous_visible_deep_dir=(
                Path(args.previous_deep_dir)
                if args.previous_deep_dir
                else None
            ),
            private_data_root=Path(args.private_root),
            allow_legacy_private_sources=False,
            require_private_personal=True,
        )
    finally:
        runner.build_player_projections = original_runner_projection
        mc.run_correlated_monte_carlo = original_mc
        mini.run_correlated_monte_carlo = original_mini_mc
    compute_seconds = time.perf_counter() - compute_started

    # External Stage3 acceptance is part of governed QA but remains local.
    stage3_started = time.perf_counter()
    stage3_path = output_dir / "stage3_acceptance.json"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "src.engines.v12_stage3_acceptance",
            "--bundle",
            str(output_dir / "report_bundle.json"),
            "--runtime-data-root",
            str(args.runtime_data_root),
            "--private-data-root",
            str(args.private_root),
            "--model-sha",
            args.model_sha,
            "--runtime-sha",
            args.runtime_sha,
            "--canonical",
            str(ROOT / "control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt"),
            "--output",
            str(stage3_path),
        ],
        cwd=ROOT,
        env=_normalized_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    stage3_seconds = time.perf_counter() - stage3_started
    stage3 = json.loads(stage3_path.read_text(encoding="utf-8"))

    # Safe publish-equivalent: copy into a runner-local temporary root only.
    publish_root = work / "publish-equivalent"
    publish_started = time.perf_counter()
    receipt = publish_private_output(
        canonical_dir=output_dir,
        private_root=publish_root,
        run_id="PERF_BC_EXPLORATORY",
        season=None,
        model_sha=args.model_sha,
        runtime_sha=args.runtime_sha,
    )
    publish_seconds = time.perf_counter() - publish_started

    stage2_proof = (
        (bundle.get("execution_proof") or {}).get("stage2_derived_cache") or {}
    )
    report_hash = _sha(_semantic_strip(bundle.get("report") or {}))
    body_hash = _sha(str(bundle.get("visible_body") or ""))
    decision_hash = _decision_fingerprint(bundle)
    safe = {
        "runtime_class": args.runtime_class,
        "cache_state": str(stage2_proof.get("status") or "UNKNOWN"),
        "runner_status": bundle.get("runner_status"),
        "pre_render_qa": (bundle.get("pre_render_qa") or {}).get("status"),
        "post_render_qa": (bundle.get("post_render_qa") or {}).get("status"),
        "human_facing_qa": (bundle.get("human_facing_qa") or {}).get("status"),
        "stage3_status": stage3.get("status"),
        "publish_equivalent_status": receipt.get("private_delivery_status"),
        "compute_seconds": compute_seconds,
        "stage3_seconds": stage3_seconds,
        "publish_equivalent_seconds": publish_seconds,
        "process_total_seconds": time.perf_counter() - process_started,
        "stage_seconds": _stage_seconds(bundle),
        "stage2_experiment": stage2_metrics,
        "mc": mc_records,
        "mc_total_wall_seconds": sum(float(r["wall_seconds"]) for r in mc_records),
        "mc_total_compute_seconds": sum(float(r["child_compute_seconds"]) for r in mc_records),
        "mc_spawn_serialization_overhead_seconds": sum(
            float(r["spawn_overhead_seconds"])
            + float(r["serialization_seconds"])
            + float(r["deserialization_seconds"])
            for r in mc_records
        ),
        "mc_output_fingerprints": [r.get("output_fingerprint") for r in mc_records],
        "mc_actual_paths": [r.get("actual_paths") for r in mc_records],
        "mc_all_canonical_pass": all(r.get("canonical_pass") is True for r in mc_records),
        "mc_any_cache_hit": any(r.get("cache_hit") is True for r in mc_records),
        "report_semantic_fingerprint": report_hash,
        "visible_body_fingerprint": body_hash,
        "decision_semantic_fingerprint": decision_hash,
        "runtime_identity": _runtime_identity(),
        "peak_memory_mb": _peak_memory_mb(),
    }
    Path(args.output).write_text(
        json.dumps(safe, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


def _spawn_full(
    *,
    runtime_class: str,
    runtime_data_root: Path,
    private_root: Path,
    report_slot: str,
    runtime_sha: str,
    model_sha: str,
    previous_deep_dir: Path | None,
    work_dir: Path,
    output: Path,
    stage2_workers: int = 0,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "-m",
        "src.engines.v12_perf_bc",
        "_full-child",
        "--runtime-class",
        runtime_class,
        "--runtime-data-root",
        str(runtime_data_root),
        "--private-root",
        str(private_root),
        "--report-slot",
        report_slot,
        "--runtime-sha",
        runtime_sha,
        "--model-sha",
        model_sha,
        "--work-dir",
