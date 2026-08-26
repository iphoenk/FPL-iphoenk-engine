from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import perf_counter
from typing import Any, Mapping

import requests

from src.v5.service_registry import get_service, registry


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
    correlation = correlation_id or uuid.uuid4().hex
    body = {**(payload or {}), "_correlation_id": correlation}
    connect = float(defaults["connect_timeout_ms"]) / 1000.0
    read = float(defaults["read_timeout_ms"]) / 1000.0
    started = perf_counter()
    response = requests.post(
        f"{service_url(service_id)}/v1/invoke/{operation}",
        json=body,
        timeout=(connect, read),
    )
    round_trip_ms = round((perf_counter() - started) * 1000.0, 3)
    response.raise_for_status()
    envelope = response.json()
    envelope["round_trip_ms"] = round_trip_ms
    envelope["transport_overhead_ms"] = round(
        max(0.0, round_trip_ms - float(envelope.get("elapsed_ms") or 0.0)), 3
    )
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


def invoke_parallel_envelopes(
    calls: Mapping[str, tuple[str, str, dict[str, Any]]],
    *,
    correlation_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    if not calls:
        return {}
    correlation = correlation_id or uuid.uuid4().hex
    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = {
            pool.submit(
                invoke_envelope,
                service_id,
                operation,
                payload,
                correlation_id=correlation,
            ): name
            for name, (service_id, operation, payload) in calls.items()
        }
        for future in as_completed(futures):
            results[futures[future]] = future.result()
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
