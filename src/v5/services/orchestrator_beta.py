from __future__ import annotations

import uuid
from threading import Lock
from time import perf_counter
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.execution_plane import (
    build_hot_bundle,
    current_runtime_fingerprint,
    evaluate_hot_materialization,
    materialization,
    plane,
)
from src.v5.replay_executor import execute_replay
from src.v5.service_client import invoke_envelope, invoke_parallel_envelopes
from src.v5.services.orchestrator import handle as core_handle

CONFIG = "config/v5_orchestrator_registry.json"
_REFRESH_LOCK = Lock()


def _route(name: str) -> tuple[str, str]:
    row = (load_json_config(CONFIG).get("routing") or {}).get(name)
    if not isinstance(row, dict):
        raise KeyError(name)
    return str(row["service"]), str(row["operation"])


def _invoke(name: str, payload: dict[str, Any], cid: str) -> dict[str, Any]:
    service, operation = _route(name)
    return invoke_envelope(service, operation, payload, correlation_id=cid)


def _metric(envelope: dict[str, Any]) -> dict[str, Any]:
    return {
        "service_compute_ms": envelope.get("elapsed_ms"),
        "round_trip_ms": envelope.get("round_trip_ms"),
        "transport_overhead_ms": envelope.get("transport_overhead_ms"),
    }


def _hot_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Serve a fresh, fingerprint-matched materialized decision without refresh.

    The hot path is intentionally forbidden from calling ingestion, external
    providers, prediction, optimizer, or hidden synchronous refresh. Full
    analytical work is performed by the refresh plane before this operation.
    """
    started = perf_counter()
    cid = str(payload.get("correlation_id") or uuid.uuid4().hex)
    materialization_name, _ = materialization()
    read_env = _invoke(
        "artifact_read",
        {"name": materialization_name, "default": {}},
        cid,
    )
    bundle = read_env.get("data") if isinstance(read_env.get("data"), dict) else {}
    mode = str(payload.get("mode") or bundle.get("mode") or "daily")

    requested_team = payload.get("team_id")
    if requested_team is not None and int(requested_team) != int(bundle.get("team_id") or -1):
        raise RuntimeError("V5 HOT FAIL CLOSED: materialized decision belongs to a different team")

    freshness = evaluate_hot_materialization(
        bundle,
        mode=mode,
        current_runtime_fingerprint=current_runtime_fingerprint(),
    )
    if not freshness.get("eligible"):
        raise RuntimeError(
            "V5 HOT FAIL CLOSED: decision materialization is not eligible: "
            f"{freshness.get('reason')}"
        )

    result = {
        "schema_version": bundle.get("schema_version"),
        "contract": bundle.get("contract"),
        "mode": bundle.get("mode"),
        "team_id": bundle.get("team_id"),
        "phase": bundle.get("phase"),
        "squad_authority": bundle.get("squad_authority"),
        "source_fusion_health": bundle.get("source_fusion_health") or {},
        "prediction_summary": bundle.get("prediction_summary") or {},
        "evaluation_summary": bundle.get("evaluation_summary") or {},
        "decision_summary": bundle.get("decision_summary") or {},
        "framework_health": bundle.get("framework_health") or {},
        "watchlist_summary": bundle.get("watchlist_summary") or {},
        "user_report": bundle.get("user_report") or {},
        "technical_appendix": bundle.get("technical_appendix") or {},
        "report_state": bundle.get("report_state") or {},
        "governance": {
            "execution_plane": "hot",
            "materialized_from_full_refresh": True,
            "hidden_synchronous_refresh": False,
            "network_refresh_allowed": False,
            "freshness": freshness,
        },
    }
    elapsed_ms = round((perf_counter() - started) * 1000.0, 3)
    hard_ms = int(plane("hot")["hard_limit_ms"])
    result["service_performance"] = {
        "execution_plane": "hot",
        "materialization_read": _metric(read_env),
        "hot_path_wall_ms": elapsed_ms,
        "hard_limit_ms": hard_ms,
        "pass": elapsed_ms <= hard_ms,
    }
    if elapsed_ms > hard_ms:
        raise RuntimeError(f"V5 HOT SLA BREACH: {elapsed_ms:.1f}ms > {hard_ms}ms")
    return result


def _replay_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Re-execute a captured decision strictly from point-in-time replay inputs."""
    cid = str(payload.get("correlation_id") or f"replay-{uuid.uuid4().hex}")
    supplied = payload.get("replay_bundle")
    if isinstance(supplied, dict):
        bundle = supplied
    else:
        mapping = load_json_config(CONFIG).get("artifact_mapping") or {}
        read_env = _invoke(
            "artifact_read",
            {"name": mapping["replay_bundle"], "default": {}},
            cid,
        )
        bundle = read_env.get("data") if isinstance(read_env.get("data"), dict) else {}

    requested_team = payload.get("team_id")
    if requested_team is not None and int(requested_team) != int(bundle.get("team_id") or -1):
        raise RuntimeError("V5 REPLAY FAIL CLOSED: replay bundle belongs to a different team")

    return execute_replay(
        bundle,
        invoke_route=_invoke,
        correlation_id=cid,
    )


def _refresh_run(payload: dict[str, Any]) -> dict[str, Any]:
    full_started = perf_counter()
    run_payload = {
        key: value
        for key, value in payload.items()
        if not str(key).startswith("_refresh_")
    }
    run_payload["persist"] = True
    snapshot = core_handle("run", run_payload)
    cid = str(snapshot.get("correlation_id") or payload.get("correlation_id") or "")

    read_service, read_operation = _route("artifact_read")
    states = invoke_parallel_envelopes(
        {
            "prediction": (read_service, read_operation, {"name": "predictions", "default": {}}),
            "report_state": (read_service, read_operation, {"name": "report_state", "default": {}}),
        },
        correlation_id=cid,
    )
    prediction = states["prediction"]["data"] or {}
    truth = {"team": snapshot.get("team_summary") or {}, "context": snapshot.get("phase") or {}}
    price = {"alerts": {"alerts": ((snapshot.get("price_summary") or {}).get("alerts") or [])}}
    decision = snapshot.get("decision_summary") or {}
    governance = snapshot.get("framework_health") or {}

    watch_env = _invoke(
        "watchlist_build",
        {"truth": truth, "price": price, "prediction": prediction, "dss": decision.get("dss") or {}},
        cid,
    )
    watchlist = watch_env["data"]

    comparator_env = _invoke(
        "challenger_compare",
        {
            "truth": truth,
            "price": price,
            "prediction": prediction,
            "watchlist": watchlist,
            "decision": decision,
        },
        cid,
    )
    comparator = comparator_env["data"]
    decision = {**decision, "challenger_comparator": comparator}
    snapshot["decision_summary"] = decision
    snapshot["challenger_comparator_summary"] = {
        "status": comparator.get("status"),
        "operating_status": comparator.get("operating_status"),
        "comparison_count": comparator.get("comparison_count", 0),
        "governed_watchlist_challengers": comparator.get("governed_watchlist_challengers", 0),
        "emerging_full_comparison_eligible": comparator.get("emerging_full_comparison_eligible", 0),
        "decision_counts": comparator.get("decision_counts", {}),
    }

    report_payload = {
        "truth": truth,
        "price": price,
        "prediction": prediction,
        "decision": decision,
        "governance": governance,
        "watchlist": watchlist,
        "challenger_comparator": comparator,
        "previous_report_state": states["report_state"]["data"] or {},
        "performance": snapshot.get("service_performance") or {},
        "force_full_report": bool(payload.get("force_full_report", False)),
        "report_request": payload.get("report_request") if isinstance(payload.get("report_request"), dict) else {},
    }
    report_env = _invoke("reporting_build", report_payload, cid)
    report = report_env["data"]

    hot_bundle = build_hot_bundle(snapshot, watchlist, report)
    write_service, write_operation = _route("artifact_write")
    mapping = load_json_config(CONFIG).get("artifact_mapping") or {}

    # Supporting artifacts must commit first. The decision hot bundle is the
    # final materialization commit marker and must never become visible from a
    # refresh that failed part-way through supporting persistence.
    support_writes = invoke_parallel_envelopes(
        {
            "watchlist": (write_service, write_operation, {"name": mapping["watchlist"], "data": watchlist}),
            "challenger_comparator": (
                write_service,
                write_operation,
                {"name": mapping["challenger_comparator"], "data": comparator},
            ),
            "user_report": (write_service, write_operation, {"name": mapping["user_report"], "data": report["user_report"]}),
            "technical_appendix": (
                write_service,
                write_operation,
                {"name": mapping["technical_appendix"], "data": report["technical_appendix"]},
            ),
            "report_state": (write_service, write_operation, {"name": mapping["report_state"], "data": report["report_state"]}),
        },
        correlation_id=cid,
    )
    hot_write_env = _invoke(
        "artifact_write",
        {"name": mapping["decision_hot_bundle"], "data": hot_bundle},
        cid,
    )

    snapshot["watchlist_summary"] = hot_bundle["watchlist_summary"]
    snapshot["user_report"] = report["user_report"]
    snapshot["technical_appendix"] = report["technical_appendix"]
    snapshot["report_state"] = report["report_state"]
    snapshot["execution_plane"] = {
        "current": "refresh",
        "hot_materialization": "READY",
        "hot_materialization_contract": hot_bundle.get("contract"),
        "hot_materialization_commit_order": "AFTER_SUPPORTING_ARTIFACTS",
    }

    performance = snapshot.setdefault("service_performance", {})
    persistence_metrics = {
        key: {"service_compute_ms": value.get("elapsed_ms"), "round_trip_ms": value.get("round_trip_ms")}
        for key, value in support_writes.items()
    }
    persistence_metrics["decision_hot_bundle"] = _metric(hot_write_env)
    performance["beta_composition"] = {
        "state_hydration": {
            key: {"service_compute_ms": value.get("elapsed_ms"), "round_trip_ms": value.get("round_trip_ms")}
            for key, value in states.items()
        },
        "watchlist": _metric(watch_env),
        "challenger_comparator": _metric(comparator_env),
        "reporting": _metric(report_env),
        "persistence": persistence_metrics,
    }
    performance["full_beta_end_to_end_ms"] = round((perf_counter() - full_started) * 1000.0, 3)
    performance["full_beta_contract"] = {
        "execution_plane": "refresh",
        "scope": "core+watchlist+challenger_comparator+reporting+persistence+hot_materialization",
        "includes_core_orchestrator": True,
        "includes_watchlist": True,
        "includes_challenger_comparator": True,
        "includes_reporting": True,
        "includes_persistence": True,
        "latency_release_blocking": False,
        "hot_path_is_measured_separately": True,
        "hot_materialization_is_final_commit_marker": True,
        "challenger_comparator_advisory_only": True,
    }
    return snapshot


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation == "hot_run":
        return _hot_run(payload)
    if operation == "replay":
        return _replay_run(payload)
    if operation != "run":
        return core_handle(operation, payload)

    origin = str(payload.get("_refresh_origin") or "request")
    blocking = origin != "worker"
    acquired = _REFRESH_LOCK.acquire(blocking=blocking)
    if not acquired:
        raise RuntimeError("V5 REFRESH SKIPPED: another refresh is already in progress")
    try:
        return _refresh_run(payload)
    finally:
        _REFRESH_LOCK.release()
