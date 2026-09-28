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
        str(work_dir),
        "--output",
        str(output),
        "--stage2-workers",
        str(stage2_workers),
    ]
    if previous_deep_dir is not None:
        cmd.extend(["--previous-deep-dir", str(previous_deep_dir)])
    started = time.perf_counter()
    subprocess.run(
        cmd,
        cwd=ROOT,
        env=_normalized_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    process_wall = time.perf_counter() - started
    row = json.loads(output.read_text(encoding="utf-8"))
    row["outer_process_wall_seconds"] = process_wall
    row["startup_teardown_seconds"] = max(
        0.0,
        process_wall - float(row["process_total_seconds"]),
    )
    return row


def run_perf_b(args: argparse.Namespace) -> int:
    cfg = _config()["perf_b"]
    order = list(cfg["order"])
    if order != ["NORMALIZED", "NATIVE_MC_SUBPROCESS", "NORMALIZED", "NATIVE_MC_SUBPROCESS"]:
        raise RuntimeError("PERF-B order contract must remain ABAB")
    root = Path(args.work_dir)
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for index, runtime_class in enumerate(order, 1):
        rows.append(
            _spawn_full(
                runtime_class=runtime_class,
                runtime_data_root=Path(args.runtime_data_root),
                private_root=Path(args.private_root),
                report_slot=args.report_slot,
                runtime_sha=args.runtime_sha,
                model_sha=args.model_sha,
                previous_deep_dir=(
                    Path(args.previous_deep_dir)
                    if args.previous_deep_dir
                    else None
                ),
                work_dir=root / f"run-{index:02d}",
                output=root / f"run-{index:02d}.json",
            )
        )
    norm = [r for r in rows if r["runtime_class"] == "NORMALIZED"]
    native = [r for r in rows if r["runtime_class"] == "NATIVE_MC_SUBPROCESS"]
    semantic_fields = (
        "report_semantic_fingerprint",
        "visible_body_fingerprint",
        "decision_semantic_fingerprint",
    )
    semantic_equal = all(len({str(r[field]) for r in rows}) == 1 for field in semantic_fields)
    mc_fingerprint_equal = len(
        {
            tuple(str(v) for v in (r.get("mc_output_fingerprints") or []))
            for r in rows
        }
    ) == 1
    gates_pass = all(
        r.get("runner_status") == "PASS"
        and r.get("pre_render_qa") == "PASS"
        and r.get("post_render_qa") == "PASS"
        and r.get("human_facing_qa") == "PASS"
        and r.get("stage3_status") == "PASS"
        and r.get("publish_equivalent_status") == "PASS"
        and r.get("cache_state") == "MISS"
        and r.get("mc_all_canonical_pass") is True
        and r.get("mc_any_cache_hit") is False
        for r in rows
    )
    norm_total = _median([r["compute_seconds"] for r in norm])
    native_total = _median([r["compute_seconds"] for r in native])
    norm_mc = _median([r["mc_total_wall_seconds"] for r in norm])
    native_mc = _median([r["mc_total_wall_seconds"] for r in native])
    norm_mc_kernel = _median([r["mc_total_compute_seconds"] for r in norm])
    native_mc_kernel = _median([r["mc_total_compute_seconds"] for r in native])
    e2e_ratio = native_total / norm_total if norm_total else None
    mc_ratio = native_mc / norm_mc if norm_mc else None
    mc_kernel_ratio = native_mc_kernel / norm_mc_kernel if norm_mc_kernel else None
    mc_kernel_seconds_saved = norm_mc_kernel - native_mc_kernel
    seconds_saved = norm_total - native_total
    failures: list[str] = []
    if not semantic_equal or not mc_fingerprint_equal:
        failures.append("SEMANTIC_DRIFT")
    if not gates_pass:
        failures.append("CANONICAL_OR_QA_GATE_FAILED")
    if failures:
        decision = "REJECT"
        promotion_state = "NO_PROMOTION"
    elif (
        e2e_ratio is not None
        and e2e_ratio <= float(cfg["material_e2e_ratio_lte"])
        and seconds_saved >= float(cfg["minimum_e2e_seconds_saved"])
    ):
        decision = "PROMOTE"
        promotion_state = "PROMOTION_CANDIDATE"
    else:
        decision = "NO_MATERIAL_GAIN"
        promotion_state = "NO_PROMOTION"
    result = {
        "schema_version": 1,
        "authority": "FPL_V12_PERF_B_EXPLORATORY",
        "status": "PASS" if not failures else "FAIL",
        "terminal_decision": decision,
        "promotion_state": promotion_state,
        "failures": failures,
        "cache_class": "COLD",
        "same_host_abab": True,
        "order": order,
        "normalized_median_total_compute_seconds": norm_total,
        "native_mc_subprocess_median_total_compute_seconds": native_total,
        "e2e_ratio": e2e_ratio,
        "e2e_seconds_saved": seconds_saved,
        "normalized_median_mc_wall_seconds": norm_mc,
        "native_subprocess_median_mc_wall_seconds": native_mc,
        "mc_ratio": mc_ratio,
        "normalized_median_mc_kernel_seconds": norm_mc_kernel,
        "native_median_mc_kernel_seconds": native_mc_kernel,
        "mc_kernel_ratio": mc_kernel_ratio,
        "mc_kernel_seconds_saved": mc_kernel_seconds_saved,
        "semantic_fingerprint_equal": semantic_equal,
        "mc_output_fingerprint_equal": mc_fingerprint_equal,
        "report_semantic_fingerprint": rows[0]["report_semantic_fingerprint"],
        "mc_output_fingerprints": rows[0]["mc_output_fingerprints"],
        "material_e2e_ratio_lte": cfg["material_e2e_ratio_lte"],
        "minimum_e2e_seconds_saved": cfg["minimum_e2e_seconds_saved"],
        "samples": [
            {
                "sequence": i + 1,
                "runtime_class": row["runtime_class"],
                "total_compute_seconds": row["compute_seconds"],
                "mc_wall_seconds": row["mc_total_wall_seconds"],
                "mc_compute_seconds": row["mc_total_compute_seconds"],
                "mc_spawn_serialization_overhead_seconds": row[
                    "mc_spawn_serialization_overhead_seconds"
                ],
                "stage_seconds": row["stage_seconds"],
                "stage3_seconds": row["stage3_seconds"],
                "publish_equivalent_seconds": row["publish_equivalent_seconds"],
                "process_startup_teardown_seconds": row["startup_teardown_seconds"],
                "native_mc_runtime_identities": [
                    mc_row.get("native_runtime_identity")
                    for mc_row in (row.get("mc") or [])
                    if mc_row.get("native_runtime_identity") is not None
                ],
                "peak_memory_mb": row["peak_memory_mb"],
                "runtime_identity": row["runtime_identity"],
            }
            for i, row in enumerate(rows)
        ],
        "perf_a_frozen_result": "KEEP_NORMALIZED_RUNTIME",
        "perf_a_frozen_threshold_ratio": _config()["perf_a_frozen"][
            "native_material_speedup_ratio_lte"
        ],
    }
    Path(args.output).write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("PERF_B_RESULT=" + json.dumps(result, sort_keys=True))
    return 0 if decision != "REJECT" else 2


def _preallocated_parallel_candidate(mc, original_parallel, projections, route_defs, *, actual_paths, seed, horizons, worker_count):
    workers = max(1, min(int(worker_count), int(os.cpu_count() or 1), int(actual_paths)))
    if workers <= 1 or not sys.platform.startswith("linux"):
        return original_parallel(
            projections,
            route_defs,
            actual_paths=actual_paths,
            seed=seed,
            horizons=horizons,
            worker_count=worker_count,
        )
    base = int(actual_paths) // workers
    remainder = int(actual_paths) % workers
    path_counts = [base + (1 if i < remainder else 0) for i in range(workers)]
    children = mc.np.random.SeedSequence(int(seed)).spawn(workers)
    child_seeds = [
        int(child.generate_state(1, dtype=mc.np.uint64)[0])
        for child in children
    ]
    work = [(i, path_counts[i], child_seeds[i]) for i in range(workers)]
    fork_context = mp.get_context("fork")
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=fork_context,
        initializer=mc._init_mc_parallel_worker,
        initargs=(projections, route_defs, tuple(int(v) for v in horizons)),
    ) as executor:
        results = list(executor.map(mc._mc_parallel_worker, work, chunksize=1))
    results.sort(key=lambda row: int(row[0]))
    first_arrays = results[0][2]
    route_ids = list(first_arrays)
    resolved_horizons = sorted(
        {
            int(h)
            for route_arrays in first_arrays.values()
            for h in route_arrays
        }
    )
    combined = {
        route_id: {
            h: mc.np.empty(int(actual_paths), dtype=mc.np.float64)
            for h in resolved_horizons
        }
        for route_id in route_ids
    }
    offset = 0
    for _, count, arrays, _ in results:
        stop = offset + int(count)
        for route_id in route_ids:
            for h in resolved_horizons:
                combined[route_id][h][offset:stop] = arrays[route_id][h]
        offset = stop
    if offset != int(actual_paths):
        raise RuntimeError("preallocated MC combine path mismatch")
    diagnostics = mc._merge_parallel_sampling_diagnostics(
        results,
        actual_paths=actual_paths,
        worker_count=workers,
        child_seeds=child_seeds,
    )
    return combined, diagnostics


def _mc_candidate_child(args: argparse.Namespace) -> int:
    os.environ.update(_normalized_env())
    os.environ.pop("V12_MC_SIM_CACHE_DIR", None)
    from src.engines import v12_monte_carlo as mc
    from src.engines.v12_monte_carlo_acceptance import build_acceptance_fixture

    original_parallel = mc._simulate_route_arrays_parallel
    if args.variant == "PREALLOCATED_PARALLEL_COMBINE":
        mc._simulate_route_arrays_parallel = (
            lambda projections, route_defs, *, actual_paths, seed, horizons, worker_count:
            _preallocated_parallel_candidate(
                mc,
                original_parallel,
                projections,
                route_defs,
                actual_paths=actual_paths,
                seed=seed,
                horizons=horizons,
                worker_count=worker_count,
            )
        )
    projections, package = build_acceptance_fixture()
    route_defs = mc.package_route_definitions(package, route_ids=["R1"])
    started = time.perf_counter()
    try:
        result = mc.run_correlated_monte_carlo(
            projections,
            route_defs,
            actual_paths=500_000,
            seed=14_092_026,
            input_snapshot_id="P1_4_ACCEPTANCE_FIXTURE_V1",
            canonical=True,
            horizons=(1, 3, 5),
            selected_route_id="R1",
            generated_at="2026-09-20T01:09:04Z",
            factual_snapshot_timestamps={
                "acceptance_fixture": "2026-09-20T01:09:04Z"
            },
        )
    finally:
        mc._simulate_route_arrays_parallel = original_parallel
    elapsed = time.perf_counter() - started
    safe = {
        "variant": args.variant,
        "elapsed_seconds": elapsed,
        "output_fingerprint": result.get("output_fingerprint"),
        "run_fingerprint": result.get("run_fingerprint"),
        "canonical_pass": result.get("canonical_pass"),
        "actual_paths": result.get("actual_paths"),
        "cache_hit": (result.get("performance") or {}).get("simulation_cache_hit"),
        "execution_mode": (result.get("performance") or {}).get("execution_mode"),
        "peak_memory_mb": _peak_memory_mb(),
        "runtime_identity": _runtime_identity(),
    }
    Path(args.output).write_text(json.dumps(safe, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return 0


def run_perf_c_mc(args: argparse.Namespace) -> int:
    cfg = _config()["perf_c_mc"]
    order = list(cfg["order"])
    root = Path(args.work_dir)
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, variant in enumerate(order, 1):
        output = root / f"{index:02d}-{variant}.json"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "src.engines.v12_perf_bc",
                "_mc-candidate-child",
                "--variant",
                variant,
                "--output",
                str(output),
            ],
            cwd=ROOT,
            env=_normalized_env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        row = json.loads(output.read_text(encoding="utf-8"))
        row["sequence"] = index
        rows.append(row)
    base = [r for r in rows if r["variant"] == "BASELINE"]
    cand = [r for r in rows if r["variant"] != "BASELINE"]
    base_med = _median([r["elapsed_seconds"] for r in base])
    cand_med = _median([r["elapsed_seconds"] for r in cand])
    ratio = cand_med / base_med if base_med else None
    saved = base_med - cand_med
    semantic_equal = len({str(r["output_fingerprint"]) for r in rows}) == 1
    reproducible = len(base) >= 2 and len(cand) >= 2
    gates = all(
        r.get("canonical_pass") is True
        and int(r.get("actual_paths") or 0) == 500_000
        and r.get("cache_hit") is False
        for r in rows
    )
    if not semantic_equal or not gates:
        decision = "REJECT"
    elif not reproducible:
        decision = "INCONCLUSIVE"
    elif (
        ratio is not None
        and ratio <= float(cfg["material_ratio_lte"])
        and saved >= float(cfg["minimum_seconds_saved"])
    ):
        decision = "PROMOTE"
    else:
        decision = "NO_MATERIAL_GAIN"
    result = {
        "schema_version": 1,
        "authority": "FPL_V12_PERF_C_MC_EXPLORATORY",
        "terminal_decision": decision,
        "candidate": "PREALLOCATED_PARALLEL_COMBINE",
        "cache_class": "COLD_DIRECT_NO_CACHE",
        "actual_paths": 500_000,
        "baseline_median_seconds": base_med,
        "candidate_median_seconds": cand_med,
        "ratio": ratio,
        "seconds_saved": saved,
        "semantic_fingerprint_equal": semantic_equal,
        "output_fingerprint": rows[0]["output_fingerprint"],
        "reproducible_samples": reproducible,
        "samples": rows,
        "material_ratio_lte": cfg["material_ratio_lte"],
        "minimum_seconds_saved": cfg["minimum_seconds_saved"],
    }
    Path(args.output).write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("PERF_C_MC_RESULT=" + json.dumps(result, sort_keys=True))
    return 0 if decision != "REJECT" else 2


def _stage2_child(args: argparse.Namespace) -> int:
    os.environ.update(_normalized_env())
    from src.engines import v12_stage2_acceptance as acceptance
    from src.models import historical_projection as hp

    original_alias = acceptance.build_player_projections
    capture: dict[str, Any] = {}
    stage2_metrics: dict[str, Any] = {}

    if args.variant == "BASELINE":
        def wrapped(*build_args: Any, **build_kwargs: Any):
            started = time.perf_counter()
            out = original_alias(*build_args, **build_kwargs)
            capture["projection_seconds"] = time.perf_counter() - started
            capture["projection_fingerprint"] = _sha(_semantic_strip(out))
            return out
    else:
        workers = int(args.workers)
        optimized = _optimized_projection_builder(
            hp.build,
            workers,
            stage2_metrics,
        )
        def wrapped(*build_args: Any, **build_kwargs: Any):
            started = time.perf_counter()
            out = optimized(*build_args, **build_kwargs)
            capture["projection_seconds"] = time.perf_counter() - started
            capture["projection_fingerprint"] = _sha(_semantic_strip(out))
            return out

    acceptance.build_player_projections = wrapped
    total_started = time.perf_counter()
    try:
        proof = acceptance.run_acceptance(
            Path(args.runtime_data_root),
            output_path=Path(args.private_output),
        )
    finally:
        acceptance.build_player_projections = original_alias
    total_seconds = time.perf_counter() - total_started
    safe = {
        "variant": args.variant,
        "workers": int(args.workers),
        "projection_seconds": capture.get("projection_seconds"),
        "total_acceptance_seconds": total_seconds,
        "projection_fingerprint": capture.get("projection_fingerprint"),
        "acceptance_semantic_fingerprint": _sha(_semantic_strip(proof)),
        "acceptance_status": proof.get("status"),
        "stage2_engine_status": proof.get("stage2_engine_status"),
        "stage2_experiment": stage2_metrics,
        "peak_memory_mb": _peak_memory_mb(),
        "runtime_identity": _runtime_identity(),
    }
    Path(args.output).write_text(json.dumps(safe, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return 0


def run_perf_c_stage2(args: argparse.Namespace) -> int:
    cfg = _config()["perf_c_stage2"]
    variants = [("BASELINE", 0)] + [
        (f"PRECOMPUTE_XMINS_W{w}", int(w))
        for w in cfg["workers"]
    ]
    repetitions = int(cfg["repetitions"])
    root = Path(args.work_dir)
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    rows = []
    sequence = 0
    # Interleave by repetition to limit host drift.
    for rep in range(1, repetitions + 1):
        for variant, workers in variants:
            sequence += 1
            safe_out = root / f"{sequence:02d}-{variant}.safe.json"
            private_out = root / f"{sequence:02d}-{variant}.private.json"
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "src.engines.v12_perf_bc",
                    "_stage2-child",
                    "--variant",
                    variant,
                    "--workers",
                    str(workers),
                    "--runtime-data-root",
                    str(args.runtime_data_root),
                    "--private-output",
                    str(private_out),
                    "--output",
                    str(safe_out),
                ],
                cwd=ROOT,
                env=_normalized_env(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            row = json.loads(safe_out.read_text(encoding="utf-8"))
            row["sequence"] = sequence
            row["repetition"] = rep
            rows.append(row)
            try:
                private_out.unlink()
            except OSError:
                pass
    baseline = [r for r in rows if r["variant"] == "BASELINE"]
    baseline_med = _median([r["projection_seconds"] for r in baseline])
    baseline_total = _median([r["total_acceptance_seconds"] for r in baseline])
    fingerprint_equal = len({str(r["projection_fingerprint"]) for r in rows}) == 1
    acceptance_equal = len({str(r["acceptance_semantic_fingerprint"]) for r in rows}) == 1
    all_pass = all(
        str(r.get("acceptance_status") or "").upper() == "GREEN"
        and str(r.get("stage2_engine_status") or "").upper() == "PASS"
        for r in rows
    )

    candidates: list[dict[str, Any]] = []
    for workers in cfg["workers"]:
        variant = f"PRECOMPUTE_XMINS_W{int(workers)}"
        subset = [r for r in rows if r["variant"] == variant]
        med = _median([r["projection_seconds"] for r in subset])
        total_med = _median([r["total_acceptance_seconds"] for r in subset])
        ratio = med / baseline_med if baseline_med else None
        saved = baseline_med - med
        if not fingerprint_equal or not acceptance_equal or not all_pass:
            decision = "REJECT"
        elif len(subset) < 2:
            decision = "INCONCLUSIVE"
        elif (
            ratio is not None
            and ratio <= float(cfg["material_ratio_lte"])
            and saved >= float(cfg["minimum_seconds_saved"])
        ):
            decision = "PROMOTE"
        else:
            decision = "NO_MATERIAL_GAIN"
        candidates.append(
            {
                "variant": variant,
                "workers": int(workers),
                "projection_median_seconds": med,
                "total_acceptance_median_seconds": total_med,
                "ratio": ratio,
                "seconds_saved": saved,
                "terminal_decision": decision,
            }
        )
    promotions = [c for c in candidates if c["terminal_decision"] == "PROMOTE"]
    rejects = [c for c in candidates if c["terminal_decision"] == "REJECT"]
    if rejects:
        overall = "REJECT"
    elif promotions:
        overall = "PROMOTE"
    elif any(c["terminal_decision"] == "INCONCLUSIVE" for c in candidates):
        overall = "INCONCLUSIVE"
    else:
        overall = "NO_MATERIAL_GAIN"
    result = {
        "schema_version": 1,
        "authority": "FPL_V12_PERF_C_STAGE2_EXPLORATORY",
        "terminal_decision": overall,
        "cache_class": "COLD_DIRECT_NO_CACHE",
        "baseline_projection_median_seconds": baseline_med,
        "baseline_total_acceptance_median_seconds": baseline_total,
        "projection_semantic_fingerprint_equal": fingerprint_equal,
        "acceptance_semantic_fingerprint_equal": acceptance_equal,
        "projection_fingerprint": rows[0]["projection_fingerprint"],
        "candidates": candidates,
        "samples": rows,
        "material_ratio_lte": cfg["material_ratio_lte"],
        "minimum_seconds_saved": cfg["minimum_seconds_saved"],
    }
    Path(args.output).write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("PERF_C_STAGE2_RESULT=" + json.dumps(result, sort_keys=True))
    return 0 if overall != "REJECT" else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("select-occurrence")
    p.add_argument("--private-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)

    p = sub.add_parser("perf-b")
    p.add_argument("--runtime-data-root", required=True)
    p.add_argument("--private-root", required=True)
    p.add_argument("--report-slot", required=True)
    p.add_argument("--runtime-sha", required=True)
    p.add_argument("--model-sha", required=True)
    p.add_argument("--previous-deep-dir", default="")
    p.add_argument("--work-dir", required=True)
    p.add_argument("--output", required=True)

    p = sub.add_parser("perf-c-mc")
    p.add_argument("--work-dir", required=True)
    p.add_argument("--output", required=True)

    p = sub.add_parser("perf-c-stage2")
    p.add_argument("--runtime-data-root", required=True)
    p.add_argument("--work-dir", required=True)
    p.add_argument("--output", required=True)

    p = sub.add_parser("_full-child")
    p.add_argument("--runtime-class", choices=("NORMALIZED", "NATIVE_MC_SUBPROCESS"), required=True)
    p.add_argument("--runtime-data-root", required=True)
    p.add_argument("--private-root", required=True)
    p.add_argument("--report-slot", required=True)
    p.add_argument("--runtime-sha", required=True)
    p.add_argument("--model-sha", required=True)
    p.add_argument("--previous-deep-dir", default="")
    p.add_argument("--work-dir", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--stage2-workers", type=int, default=0)

    p = sub.add_parser("_mc-native-child")
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)

    p = sub.add_parser("_mc-candidate-child")
    p.add_argument("--variant", choices=("BASELINE", "PREALLOCATED_PARALLEL_COMBINE"), required=True)
    p.add_argument("--output", required=True)

    p = sub.add_parser("_stage2-child")
    p.add_argument("--variant", required=True)
    p.add_argument("--workers", type=int, required=True)
    p.add_argument("--runtime-data-root", required=True)
    p.add_argument("--private-output", required=True)
    p.add_argument("--output", required=True)

    args = parser.parse_args()
    if args.command == "select-occurrence":
        return select_occurrence(args.private_root, args.output)
    if args.command == "perf-b":
        return run_perf_b(args)
    if args.command == "perf-c-mc":
        return run_perf_c_mc(args)
    if args.command == "perf-c-stage2":
        return run_perf_c_stage2(args)
    if args.command == "_full-child":
        return _full_child(args)
    if args.command == "_mc-native-child":
        return _mc_native_child(args.input, args.output)
    if args.command == "_mc-candidate-child":
        return _mc_candidate_child(args)
    if args.command == "_stage2-child":
        return _stage2_child(args)
    raise RuntimeError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
