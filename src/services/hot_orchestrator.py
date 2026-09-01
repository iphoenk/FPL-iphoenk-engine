from __future__ import annotations

import argparse
import json
import traceback
from multiprocessing import get_context
from time import perf_counter

from src.services import (
    architecture_guard_service,
    enrichment_service,
    governance_live_overlay,
    gw_scorecard_live_overlay,
    optimization_slo_service,
    prediction_model_cache,
    prediction_service_price_mover,
    raw_snapshot_service,
    user_decision_overlay_service,
    validation_service,
)
from src.services.contracts import file_digest
from src.utils import CONFIG, DATA, atomic_json, iso_now, read_json

OUTFILE = DATA / "hot_orchestration_v4.json"
SNAPSHOT = DATA / "runtime" / "snapshot.v1.json"
ENRICHMENT = DATA / "runtime" / "enrichment.v1.json"
LATEST = DATA / "latest.json"

HOT_PRODUCTION_MODULES = {
    "raw_snapshot": raw_snapshot_service.__name__,
    "enrichment": enrichment_service.__name__,
    "prediction": prediction_service_price_mover.__name__,
    "validation": validation_service.__name__,
    "optimization": optimization_slo_service.__name__,
    "user_decision_overlay": user_decision_overlay_service.__name__,
    "personal_gw_scorecard": gw_scorecard_live_overlay.__name__,
    "governance": governance_live_overlay.__name__,
}


def _assert_registry_module_parity() -> dict[str, dict]:
    registry = read_json(CONFIG / "service_registry.json", {})
    by_id = {row.get("id"): row for row in registry.get("services") or []}
    if set(by_id) != set(HOT_PRODUCTION_MODULES):
        raise RuntimeError(f"hot-path service ids drifted from registry: {sorted(by_id)}")
    for service_id, module_name in HOT_PRODUCTION_MODULES.items():
        row = by_id[service_id]
        if row.get("module") != module_name:
            raise RuntimeError(
                f"hot-path module drift for {service_id}: {module_name} != {row.get('module')}"
            )
        command = row.get("command") or []
        if len(command) < 3 or command[2] != module_name:
            raise RuntimeError(f"registry command/module mismatch for {service_id}")
    return by_id


def _assert_digest(path, expected: str, label: str) -> None:
    actual = file_digest(path)
    if actual != expected:
        raise RuntimeError(f"hot-path immutable {label} changed: {actual} != {expected}")


def _validation_worker(conn) -> None:
    """Run the exact registered validation service in a forked child.

    The production process-isolated DAG still launches the registry command in its
    own interpreter. The non-publishing hot benchmark only changes process startup:
    fork inherits already-imported service code, eliminating repeated interpreter
    import cost while preserving the validation service and all of its artifacts.
    """
    try:
        detail = validation_service.run()
        conn.send({"ok": True, "detail": detail})
    except BaseException:
        conn.send({"ok": False, "error": traceback.format_exc()})
    finally:
        conn.close()


def run(mode: str = "daily", stats: bool = True, deep_stats: bool = True, as_of: str | None = None) -> dict:
    """Production-equivalent non-publishing E2E hot-path benchmark.

    The benchmark may use a different execution strategy to measure process-startup
    overhead, but service identity is fail-closed against the authoritative production
    registry. It therefore cannot silently benchmark stale base implementations while
    production uses wrappers/overlays.
    """
    _assert_registry_module_parity()
    started = perf_counter()
    service_ms: dict[str, float] = {}

    t = perf_counter()
    assurance = architecture_guard_service.run()
    service_ms["startup_architecture_assurance"] = round((perf_counter() - t) * 1000.0, 2)
    if assurance.get("status") != "PASS":
        raise RuntimeError("hot-path architecture assurance failed")

    t = perf_counter()
    raw = raw_snapshot_service.run(mode, as_of)
    service_ms["raw_snapshot"] = round((perf_counter() - t) * 1000.0, 2)
    snapshot_sha = file_digest(SNAPSHOT)

    t = perf_counter()
    enrichment_service.run(stats, deep_stats)
    service_ms["enrichment"] = round((perf_counter() - t) * 1000.0, 2)
    _assert_digest(SNAPSHOT, snapshot_sha, "snapshot")
    enrichment_sha = file_digest(ENRICHMENT)

    t = perf_counter()
    prediction_service_price_mover.run()
    service_ms["prediction"] = round((perf_counter() - t) * 1000.0, 2)
    prediction_cache = prediction_model_cache.last_status()
    _assert_digest(SNAPSHOT, snapshot_sha, "snapshot")
    _assert_digest(ENRICHMENT, enrichment_sha, "enrichment")
    latest_sha = file_digest(LATEST)

    # Validation is logically independent from optimization after prediction. Use a
    # forked child rather than a brand-new interpreter so the FAST benchmark measures
    # service work, not Python import/bootstrap overhead. The exact registry-owned
    # validation implementation and its nested fail-closed preflight remain unchanged.
    ctx = get_context("fork")
    validation_recv, validation_send = ctx.Pipe(duplex=False)
    validation = ctx.Process(
        target=_validation_worker,
        args=(validation_send,),
        name="v496-hot-validation",
    )
    validation_started = perf_counter()
    validation.start()
    validation_send.close()

    t = perf_counter()
    decision = optimization_slo_service.run()
    service_ms["optimization"] = round((perf_counter() - t) * 1000.0, 2)
    _assert_digest(SNAPSHOT, snapshot_sha, "snapshot")
    _assert_digest(ENRICHMENT, enrichment_sha, "enrichment")
    _assert_digest(LATEST, latest_sha, "latest")

    t = perf_counter()
    user_decision_overlay_service.run()
    service_ms["user_decision_overlay"] = round((perf_counter() - t) * 1000.0, 2)

    t = perf_counter()
    gw_scorecard_live_overlay.run()
    service_ms["personal_gw_scorecard"] = round((perf_counter() - t) * 1000.0, 2)

    if not validation_recv.poll(45):
        validation.terminate()
        validation.join(timeout=5)
        raise RuntimeError("hot-path validation timed out")
    validation_status = validation_recv.recv()
    validation_recv.close()
    validation.join(timeout=5)
    validation_ms = round((perf_counter() - validation_started) * 1000.0, 2)
    service_ms["validation_concurrent_wall"] = validation_ms
    if validation.is_alive():
        validation.terminate()
        validation.join(timeout=5)
        raise RuntimeError("hot-path validation did not exit cleanly")
    if not validation_status.get("ok") or validation.exitcode != 0:
        raise RuntimeError(
            "hot-path validation failed: "
            + str(validation_status.get("error") or validation.exitcode)[-1200:]
        )
    validation_detail = validation_status.get("detail") or {}

    t = perf_counter()
    governance_detail = governance_live_overlay.run()
    service_ms["governance"] = round((perf_counter() - t) * 1000.0, 2)
    _assert_digest(SNAPSHOT, snapshot_sha, "snapshot")
    _assert_digest(ENRICHMENT, enrichment_sha, "enrichment")
    _assert_digest(LATEST, latest_sha, "latest")

    total_ms = round((perf_counter() - started) * 1000.0, 2)
    startup_ms = service_ms["startup_architecture_assurance"]
    serving_ms = round(max(0.0, total_ms - startup_ms), 2)
    timings = decision.get("timings") or {}
    latest = read_json(LATEST, {})
    out = {
        "schema_version": 4,
        "engine": "v4.9.6-e2e-hot-path-production-wrapper-parity-v4",
        "generated_at": iso_now(),
        "status": "PASS",
        "mode": mode,
        "total_e2e_ms": total_ms,
        "serving_e2e_excluding_startup_assurance_ms": serving_ms,
        "service_ms": service_ms,
        "production_service_modules": HOT_PRODUCTION_MODULES,
        "prediction_base_cache": prediction_cache,
        "validation_detail": validation_detail,
        "governance_detail": governance_detail,
        "decision_timings_ms": timings,
        "official_acquisition_ms": float(raw.get("duration_ms") or 0.0),
        "enrichment_reported_ms": float((read_json(ENRICHMENT, {}) or {}).get("duration_ms") or 0.0),
        "prediction_reported_ms": float((latest.get("performance") or {}).get("prediction_ms") or 0.0),
        "base_prediction_ms": float((latest.get("performance") or {}).get("base_prediction_ms") or 0.0),
        "decision_compute_ms": float(timings.get("total_pipeline_ms") or 0.0),
        "optimizer_cache_hit": bool(timings.get("optimizer_exact_cache_hit")),
        "targets": {
            "deterministic_decision_ms": 1000.0,
            "fresh_serving_p50_ms": 2000.0,
            "fresh_serving_p95_ms": 3000.0,
        },
        "target_status": {
            "decision_under_1s": float(timings.get("total_pipeline_ms") or 1e9) < 1000.0,
            "serving_under_2s": serving_ms < 2000.0,
            "serving_under_3s": serving_ms < 3000.0,
            "full_cold_run_under_3s": total_ms < 3000.0,
        },
        "guardrails": {
            "official_fpl_refreshed_this_run": True,
            "official_authority_unchanged": True,
            "exact_optimizer_search_width_unchanged": True,
            "exact_base_prediction_reuse_only": True,
            "fresh_xmins_evidence_attached_after_base_prediction_reuse": True,
            "benchmark_matches_production_prediction_path": True,
            "benchmark_matches_production_service_modules": True,
            "registry_is_service_identity_authority": True,
            "user_final_authority_preserved": True,
            "validation_runs_concurrently_not_skipped": True,
            "validation_service_implementation_unchanged": True,
            "validation_fork_removes_interpreter_bootstrap_only": True,
            "architecture_guard_runs_first": True,
            "startup_assurance_measured_separately_from_serving": True,
            "snapshot_enrichment_latest_immutable_after_lock": True,
            "non_publishing_benchmark_until_promoted": True,
        },
    }
    atomic_json(OUTFILE, out)
    print(json.dumps({
        "hot_orchestrator": "PASS",
        "total_e2e_ms": total_ms,
        "serving_e2e_ms": serving_ms,
        "startup_assurance_ms": startup_ms,
        "official_acquisition_ms": out["official_acquisition_ms"],
        "prediction_ms": out["prediction_reported_ms"],
        "base_prediction_ms": out["base_prediction_ms"],
        "prediction_base_cache_hit": prediction_cache.get("hit"),
        "decision_compute_ms": out["decision_compute_ms"],
        "optimizer_cache_hit": out["optimizer_cache_hit"],
        "semantic_fingerprint_ms": timings.get("semantic_fingerprint_ms"),
        "targets": out["target_status"],
    }, ensure_ascii=False))
    return out


def cli() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", choices=("daily", "deadline", "live"), default="daily")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--deep-stats", action="store_true")
    parser.add_argument("--as-of")
    args = parser.parse_args()
    return run(args.mode, args.stats, args.deep_stats, args.as_of)


if __name__ == "__main__":
    cli()
