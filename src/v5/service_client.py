from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import perf_counter
from typing import Any, Mapping

from src.v5.runtime_payloads import compact_payload
from src.v5.service_registry import get_service, registry
from src.v5.service_transport import post as transport_post, retry_policy


def _env_name(service_id: str) -> str:
    return f"V5_SERVICE_{service_id.upper().replace('-', '_')}_URL"


def service_url(service_id: str) -> str:
    spec = get_service(service_id)
    default = f"http://{service_id}:{spec.port}"
    return os.getenv(_env_name(service_id), default).rstrip("/")


def invoke_envelope(
    service_id: str,
    operation: str,
    payload: dict[str, Any] | None = None,
    *,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    defaults = registry()["defaults"]
    contract_version = str(defaults["contract_version"])
    correlation = correlation_id or uuid.uuid4().hex
    transport_payload = compact_payload(service_id, operation, payload or {})
    body = {
        **transport_payload,
        "_correlation_id": correlation,
        "_contract_version": contract_version,
    }
    connect = float(defaults["connect_timeout_ms"]) / 1000.0
    read = float(defaults["read_timeout_ms"]) / 1000.0
    invoke_path = str(defaults["invoke_path"]).format(operation=operation)
    policy = retry_policy(service_id, operation)
    started = perf_counter()
    response, attempts, circuit = transport_post(
        service_id,
        operation,
        f"{service_url(service_id)}{invoke_path}",
        json_body=body,
        timeout=(connect, read),
    )
    round_trip_ms = round((perf_counter() - started) * 1000.0, 3)
    response.raise_for_status()
    envelope = response.json()
    if str(envelope.get("contract_version")) != contract_version:
        raise RuntimeError(
            f"{service_id}.{operation} response contract mismatch: "
            f"{envelope.get('contract_version')} != {contract_version}"
        )
    envelope["round_trip_ms"] = round_trip_ms
    envelope["transport_overhead_ms"] = round(
        max(0.0, round_trip_ms - float(envelope.get("elapsed_ms") or 0.0)), 3
    )
    envelope["transport_attempts"] = int(attempts)
    envelope["transport_retry_policy"] = policy.name
    envelope["transport_circuit"] = circuit
    if not envelope.get("ok"):
        raise RuntimeError(f"{service_id}.{operation} failed: {envelope.get('error')}")
    return envelope


def invoke(
    service_id: str,
    operation: str,
    payload: dict[str, Any] | None = None,
    *,
    correlation_id: str | None = None,
) -> Any:
    return invoke_envelope(
        service_id,
        operation,
        payload,
        correlation_id=correlation_id,
    ).get("data")


def _parallel_futures(
    calls: Mapping[str, tuple[str, str, dict[str, Any]]],
    *,
    correlation_id: str,
):
    pool = ThreadPoolExecutor(max_workers=len(calls))
    futures = {
        pool.submit(
            invoke_envelope,
            service_id,
            operation,
            payload,
            correlation_id=correlation_id,
        ): name
        for name, (service_id, operation, payload) in calls.items()
    }
    return pool, futures


def invoke_parallel_envelopes(
    calls: Mapping[str, tuple[str, str, dict[str, Any]]],
    *,
    correlation_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    if not calls:
        return {}
    correlation = correlation_id or uuid.uuid4().hex
    results: dict[str, dict[str, Any]] = {}
    pool, futures = _parallel_futures(calls, correlation_id=correlation)
    try:
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    finally:
        pool.shutdown(wait=True)
    return results


def invoke_parallel_outcomes(
    calls: Mapping[str, tuple[str, str, dict[str, Any]]],
    *,
    correlation_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Collect independent service outcomes without masking failures.

    This is for orchestrator stages that have an explicit degraded-mode policy.
    Callers must still fail closed for critical or unregistered failures.
    """
    if not calls:
        return {}
    correlation = correlation_id or uuid.uuid4().hex
    results: dict[str, dict[str, Any]] = {}
    pool, futures = _parallel_futures(calls, correlation_id=correlation)
    try:
        for future in as_completed(futures):
            name = futures[future]
            try:
                envelope = future.result()
            except Exception as exc:
                service_id, operation, _ = calls[name]
                results[name] = {
                    "ok": False,
                    "service_id": service_id,
                    "operation": operation,
                    "envelope": None,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            else:
                results[name] = {
                    "ok": True,
                    "service_id": envelope.get("service_id"),
                    "operation": envelope.get("operation"),
                    "envelope": envelope,
                    "error_type": None,
                    "error": None,
                }
    finally:
        pool.shutdown(wait=True)
    return results


def invoke_parallel(
    calls: Mapping[str, tuple[str, str, dict[str, Any]]],
    *,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    return {
        name: envelope.get("data")
        for name, envelope in invoke_parallel_envelopes(
            calls,
            correlation_id=correlation_id,
        ).items()
    }
