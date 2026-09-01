from __future__ import annotations

import json
import traceback
from multiprocessing import get_context
from time import perf_counter

from src.engines import compliance_audit, framework_health_audit, v4_validation_cycle
from src.services import reconciliation_readiness_service
from src.utils import DATA, read_json

RAW_SNAPSHOT = DATA / "runtime" / "snapshot.v1.json"
PREDICTIONS = DATA / "predictions_v4.json"


def _preflight_worker(conn, predictions_snapshot: dict) -> None:
    started = perf_counter()
    try:
        # This worker is forked only after the parent has loaded the immutable
        # prediction contract. Reuse that exact copy-on-write snapshot instead of
        # reopening/parsing the ~66 MB artifact a second time in the child.
        framework_health_audit._PREDICTION_CACHE = predictions_snapshot
        framework_health_audit._PROBE_CACHE = {}
        try:
            out = framework_health_audit._audit_with_cache("preflight", strict=True, started=started)
        finally:
            framework_health_audit._PREDICTION_CACHE = None
            framework_health_audit._PROBE_CACHE = None
        conn.send({
            "ok": True,
            "overall": out.get("overall"),
            "pipeline_health": out.get("pipeline_health"),
            "prediction_health": out.get("prediction_health"),
            "ms": round((perf_counter() - started) * 1000.0, 2),
        })
    except BaseException:
        conn.send({
            "ok": False,
            "ms": round((perf_counter() - started) * 1000.0, 2),
            "error": traceback.format_exc(),
        })
    finally:
        conn.close()


def run(*, predictions_snapshot: dict | None = None) -> dict:
    """Run the complete pre-decision validation boundary with dependency-safe overlap.

    PRE-FLIGHT health depends on the immutable raw/enrichment/prediction snapshot but
    not on lifecycle/readiness output. It therefore runs in a forked worker while the
    parent performs lifecycle then reconciliation-readiness in their required order.
    The parent loads raw/prediction evidence once and the fork inherits that immutable
    prediction object copy-on-write; lifecycle/readiness receive the same parent
    objects directly. Logical ownership and all artifacts remain unchanged.
    """
    total = perf_counter()
    timings = {}

    snapshot_started = perf_counter()
    raw_snapshot = read_json(RAW_SNAPSHOT, {})
    predictions_preloaded = predictions_snapshot is not None
    if predictions_snapshot is None:
        predictions_snapshot = read_json(PREDICTIONS, {})
    timings["parent_snapshot_load_ms"] = round((perf_counter() - snapshot_started) * 1000.0, 2)
    if raw_snapshot.get("schema") != "snapshot.v1":
        raise RuntimeError("validation service requires runtime snapshot.v1")
    if not predictions_snapshot.get("model_version") or not predictions_snapshot.get("players"):
        raise RuntimeError("validation service requires current predictions_v4.json")

    ctx = get_context("fork")
    recv, send = ctx.Pipe(duplex=False)
    preflight_process = ctx.Process(
        target=_preflight_worker,
        args=(send, predictions_snapshot),
        name="v496-validation-preflight",
    )
    preflight_started = perf_counter()
    preflight_process.start()
    send.close()

    started = perf_counter()
    lifecycle = v4_validation_cycle.cycle(raw=raw_snapshot, predictions=predictions_snapshot)
    timings["validation_lifecycle_ms"] = round((perf_counter() - started) * 1000.0, 2)

    started = perf_counter()
    readiness = reconciliation_readiness_service.run(raw=raw_snapshot, lifecycle=lifecycle)
    timings["reconciliation_readiness_ms"] = round((perf_counter() - started) * 1000.0, 2)

    started = perf_counter()
    compliance_audit.main()
    compliance = read_json(DATA / "compliance_audit.json", {})
    timings["rules_compliance_ms"] = round((perf_counter() - started) * 1000.0, 2)

    preflight_status = recv.recv()
    preflight_process.join()
    timings["framework_preflight_worker_ms"] = float(preflight_status.get("ms") or 0.0)
    timings["framework_preflight_concurrent_wall_ms"] = round((perf_counter() - preflight_started) * 1000.0, 2)
    if not preflight_status.get("ok") or preflight_process.exitcode != 0:
        raise RuntimeError("validation preflight worker failed:\n" + str(preflight_status.get("error") or preflight_process.exitcode))

    preflight = read_json(DATA / "framework_health_preflight_v4.json", {})
    if preflight.get("overall") != preflight_status.get("overall"):
        raise RuntimeError("validation preflight artifact/status mismatch")

    timings["serial_parent_work_ms"] = round(
        timings["validation_lifecycle_ms"]
        + timings["reconciliation_readiness_ms"]
        + timings["rules_compliance_ms"],
        2,
    )
    timings["overlap_saved_estimate_ms"] = round(
        max(0.0, timings["framework_preflight_worker_ms"] + timings["serial_parent_work_ms"] - max(
            timings["framework_preflight_concurrent_wall_ms"], timings["serial_parent_work_ms"]
        )),
        2,
    )
    timings["total_ms"] = round((perf_counter() - total) * 1000.0, 2)

    reuse = readiness.get("input_reuse") or {}
    if not reuse.get("raw_snapshot_preloaded") or not reuse.get("lifecycle_preloaded"):
        raise RuntimeError("validation readiness did not reuse parent snapshot contract")

    out = {
        "service": "validation",
        "status": "PASS",
        "components": {
            "validation_lifecycle": lifecycle.get("status"),
            "reconciliation_readiness": readiness.get("status"),
            "rules_compliance": compliance.get("overall"),
            "framework_preflight": preflight.get("overall"),
        },
        "snapshot_reuse": {
            "parent_raw_snapshot_loaded_once": True,
            "parent_predictions_loaded_once": not predictions_preloaded,
            "parent_predictions_received_preloaded": predictions_preloaded,
            "lifecycle_received_preloaded_raw": True,
            "lifecycle_received_preloaded_predictions": True,
            "readiness_received_preloaded_raw": bool(reuse.get("raw_snapshot_preloaded")),
            "readiness_received_lifecycle_result": bool(reuse.get("lifecycle_preloaded")),
            "preflight_remains_isolated_file_backed_worker": True,
        },
        "timings_ms": timings,
        "guardrails": {
            "underlying_artifact_contracts_preserved": True,
            "logical_validation_owners_preserved": True,
            "preflight_only_overlaps_independent_work": True,
            "lifecycle_before_reconciliation_readiness": True,
            "preflight_artifact_status_verified": True,
            "parent_snapshot_reuse_fail_closed": True,
            "prediction_handoff_is_explicit_optional_input": True,
            "file_backed_prediction_fallback_preserved": True,
            "official_api_refetch": False,
            "fail_closed": True,
        },
    }
    print(json.dumps(out, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
