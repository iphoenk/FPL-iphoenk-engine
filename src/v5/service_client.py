from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import perf_counter
from typing import Any, Mapping

import msgpack

from src.v5.config_cache import load_json_config
from src.v5.runtime_payloads import compact_payload
from src.v5.service_registry import get_service, registry
from src.v5.service_transport import post as transport_post, post_bytes as transport_post_bytes, retry_policy

TRANSPORT_CONFIG = "config/v5_service_transport_registry.json"
WIRE_CONFIG = "config/v5_service_wire_registry.json"

_executor_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None


def _env_name(service_id: str) -> str:
    return f"V5_SERVICE_{service_id.upper().replace('-', '_')}_URL"


def service_url(service_id: str) -> str:
    spec = get_service(service_id)
    default = f"http://{service_id}:{spec.port}"
    return os.getenv(_env_name(service_id), default).rstrip("/")


def _wire_profile() -> tuple[str, dict[str, Any]]:
    cfg = load_json_config(WIRE_CONFIG)
    env_name = str(cfg.get("profile_env") or "").strip()
    default_name = str(cfg.get("default_profile") or "").strip()
    name = str(os.getenv(env_name, default_name) if env_name else default_name).strip()
    profiles = cfg.get("profiles") if isinstance(cfg.get("profiles"), dict) else {}
    profile = profiles.get(name)
    if not isinstance(profile, dict):
        raise RuntimeError(f"unknown V5 internal wire profile: {name}")
    codec = str(profile.get("codec") or "")
    allowed = {str(value) for value in cfg.get("allowed_codecs") or []}
    if codec not in allowed:
        raise RuntimeError(f"V5 wire profile {name} uses disallowed codec: {codec}")
    return name, profile


def _shared_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is not None:
        return _executor
    with _executor_lock:
        if _executor is None:
            cfg = load_json_config(TRANSPORT_CONFIG).get("client_worker_pool") or {}
            workers = max(1, int(cfg.get("max_workers") or 16))
            prefix = str(cfg.get("thread_name_prefix") or "v5-service-client")
            _executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=prefix)
    return _executor


def reset_worker_pool_for_tests() -> None:
    global _executor
    with _executor_lock:
        executor = _executor
        _executor = None
    if executor is not None:
        executor.shutdown(wait=True, cancel_futures=True)


def _decode_envelope(response: Any, codec: str) -> dict[str, Any]:
    if codec == "json":
        decoded = response.json()
    elif codec == "msgpack":
        decoded = msgpack.unpackb(response.content, raw=False, strict_map_key=False)
    else:
        raise RuntimeError(f"unsupported V5 internal wire codec: {codec}")
    if not isinstance(decoded, dict):
        raise RuntimeError("V5 service response envelope must be an object")
    return decoded


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
    profile_name, profile = _wire_profile()
    codec = str(profile["codec"])
    invoke_path = str(profile["invoke_path"]).format(operation=operation)
    policy = retry_policy(service_id, operation)
    started = perf_counter()
    if codec == "json":
        response, attempts, circuit = transport_post(
            service_id,
            operation,
            f"{service_url(service_id)}{invoke_path}",
            json_body=body,
            timeout=(connect, read),
        )
    elif codec == "msgpack":
        encoded = msgpack.packb(body, use_bin_type=True)
        response, attempts, circuit = transport_post_bytes(
            service_id,
            operation,
            f"{service_url(service_id)}{invoke_path}",
            body=encoded,
            headers={
                "Content-Type": str(profile["content_type"]),
                "Accept": str(profile["accept"]),
            },
            timeout=(connect, read),
        )
    else:
        raise RuntimeError(f"unsupported V5 internal wire codec: {codec}")
    round_trip_ms = round((perf_counter() - started) * 1000.0, 3)
    response.raise_for_status()
    envelope = _decode_envelope(response, codec)
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
    envelope["transport_codec"] = codec
    envelope["transport_profile"] = profile_name
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
    pool = _shared_executor()
    return {
        pool.submit(
            invoke_envelope,
            service_id,
            operation,
            payload,
            correlation_id=correlation_id,
        ): name
        for name, (service_id, operation, payload) in calls.items()
    }


def invoke_parallel_envelopes(
    calls: Mapping[str, tuple[str, str, dict[str, Any]]],
    *,
    correlation_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    if not calls:
        return {}
    correlation = correlation_id or uuid.uuid4().hex
    results: dict[str, dict[str, Any]] = {}
    futures = _parallel_futures(calls, correlation_id=correlation)
    for future in as_completed(futures):
        results[futures[future]] = future.result()
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
    futures = _parallel_futures(calls, correlation_id=correlation)
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
