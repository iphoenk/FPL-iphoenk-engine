from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Mapping

import requests

from src.v5.service_registry import get_service, registry


def _env_name(service_id: str) -> str:
    return f"V5_SERVICE_{service_id.upper().replace('-', '_')}_URL"


def service_url(service_id: str) -> str:
    spec = get_service(service_id)
    default = f"http://{service_id}:{spec.port}"
    return os.getenv(_env_name(service_id), default).rstrip("/")


def invoke(
    service_id: str,
    operation: str,
    payload: dict[str, Any] | None = None,
    *,
    correlation_id: str | None = None,
) -> Any:
    defaults = registry()["defaults"]
    correlation = correlation_id or uuid.uuid4().hex
    body = {**(payload or {}), "_correlation_id": correlation}
    connect = float(defaults["connect_timeout_ms"]) / 1000.0
    read = float(defaults["read_timeout_ms"]) / 1000.0
    response = requests.post(
        f"{service_url(service_id)}/v1/invoke/{operation}",
        json=body,
        timeout=(connect, read),
    )
    response.raise_for_status()
    envelope = response.json()
    if not envelope.get("ok"):
        raise RuntimeError(f"{service_id}.{operation} failed: {envelope.get('error')}")
    return envelope.get("data")


def invoke_parallel(
    calls: Mapping[str, tuple[str, str, dict[str, Any]]],
    *,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    if not calls:
        return {}
    correlation = correlation_id or uuid.uuid4().hex
    results: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = {
            pool.submit(invoke, service_id, operation, payload, correlation_id=correlation): name
            for name, (service_id, operation, payload) in calls.items()
        }
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return results
