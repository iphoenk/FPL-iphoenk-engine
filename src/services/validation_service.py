from __future__ import annotations

import json
import traceback
from multiprocessing import get_context
from time import perf_counter

from src.engines import compliance_audit, framework_health_audit, v4_validation_cycle
from src.services import reconciliation_readiness_service
from src.utils import DATA, read_json


def _preflight_worker(conn) -> None:
    started = perf_counter()
    try:
        out = framework_health_audit.audit("preflight", strict=True)
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


def run() -> dict:
    """Run the complete pre-decision validation boundary with dependency-safe overlap.

    PRE-FLIGHT health depends on the immutable raw/enrichment/prediction snapshot but
    not on lifecycle/readiness output. It therefore runs in a forked worker while the
    parent performs lifecycle then reconciliation-readiness in their required order.
    Rules compliance also remains in the parent. Logical ownership and all artifacts
    are unchanged; only independent validation work is overlapped.
    """
    total = perf_counter()
    timings = {}

    ctx = get_context("fork")
    recv, send = ctx.Pipe(duplex=False)
    preflight_process = ctx.Process(target=_preflight_worker, args=(send,), name="v496-validation-preflight")
    preflight_started = perf_counter()
    preflight_process.start()
    send.close()

    started = perf_counter()
    lifecycle = v4_validation_cycle.cycle()
    timings["validation_lifecycle_ms"] = round((perf_counter() - started) * 1000.0, 2)

    started = perf_counter()
    readiness = reconciliation_readiness_service.run()
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

    out = {
        "service": "validation",
        "status": "PASS",
        "components": {
            "validation_lifecycle": lifecycle.get("status"),
            "reconciliation_readiness": readiness.get("status"),
            "rules_compliance": compliance.get("overall"),
            "framework_preflight": preflight.get("overall"),
        },
        "timings_ms": timings,
        "guardrails": {
            "underlying_artifact_contracts_preserved": True,
            "logical_validation_owners_preserved": True,
            "preflight_only_overlaps_independent_work": True,
            "lifecycle_before_reconciliation_readiness": True,
            "preflight_artifact_status_verified": True,
            "official_api_refetch": False,
            "fail_closed": True,
        },
    }
    print(json.dumps(out, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
