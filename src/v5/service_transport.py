from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from src.v5.config_cache import load_json_config

CONFIG = "config/v5_service_transport_registry.json"


class CircuitOpenError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetryPolicy:
    name: str
    max_attempts: int
    backoff_ms: int
    retry_http_statuses: frozenset[int]
    retry_exception_names: frozenset[str]


@dataclass
class CircuitState:
    failures: int = 0
    opened_at: float | None = None


_thread_local = threading.local()
_circuit_lock = threading.Lock()
_circuits: dict[str, CircuitState] = {}


def _cfg() -> dict[str, Any]:
    data = load_json_config(CONFIG)
    if not isinstance(data.get("retry"), dict) or not isinstance(data.get("circuit_breaker"), dict):
        raise RuntimeError("invalid V5 service transport registry")
    return data


def _session() -> requests.Session:
    session = getattr(_thread_local, "session", None)
    if session is not None:
        return session
    cfg = _cfg().get("connection_pool") or {}
    session = requests.Session()
    if bool(cfg.get("enabled", True)):
        adapter = HTTPAdapter(
            pool_connections=int(cfg["pool_connections"]),
            pool_maxsize=int(cfg["pool_maxsize"]),
            max_retries=0,
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
    _thread_local.session = session
    return session


def retry_policy(service_id: str, operation: str) -> RetryPolicy:
    retry = _cfg()["retry"]
    key = f"{service_id}.{operation}"
    policy_name = str((retry.get("operation_policy") or {}).get(key) or retry["default_policy"])
    raw = (retry.get("policies") or {}).get(policy_name)
    if not isinstance(raw, dict):
        raise RuntimeError(f"unknown V5 transport retry policy: {policy_name}")
    attempts = int(raw["max_attempts"])
    if attempts < 1:
        raise RuntimeError(f"invalid max_attempts for V5 transport policy {policy_name}")
    return RetryPolicy(
        name=policy_name,
        max_attempts=attempts,
        backoff_ms=int(raw["backoff_ms"]),
        retry_http_statuses=frozenset(int(value) for value in raw.get("retry_http_statuses") or []),
        retry_exception_names=frozenset(str(value) for value in raw.get("retry_exception_names") or []),
    )


def _circuit_key(service_id: str, operation: str) -> str:
    return f"{service_id}.{operation}"


def _circuit_cfg() -> dict[str, Any]:
    return _cfg()["circuit_breaker"]


def circuit_snapshot(service_id: str, operation: str, *, now: float | None = None) -> dict[str, Any]:
    cfg = _circuit_cfg()
    key = _circuit_key(service_id, operation)
    current = time.monotonic() if now is None else float(now)
    cooldown = float(cfg["cooldown_seconds"])
    with _circuit_lock:
        state = _circuits.get(key, CircuitState())
        open_now = bool(state.opened_at is not None and current - state.opened_at < cooldown)
        return {
            "enabled": bool(cfg.get("enabled", True)),
            "state": "OPEN" if open_now else "CLOSED",
            "failures": int(state.failures),
            "cooldown_seconds": cooldown,
        }


def before_call(service_id: str, operation: str, *, now: float | None = None) -> None:
    cfg = _circuit_cfg()
    if not bool(cfg.get("enabled", True)):
        return
    key = _circuit_key(service_id, operation)
    current = time.monotonic() if now is None else float(now)
    cooldown = float(cfg["cooldown_seconds"])
    with _circuit_lock:
        state = _circuits.get(key)
        if state is None or state.opened_at is None:
            return
        if current - state.opened_at >= cooldown:
            state.failures = 0
            state.opened_at = None
            return
        raise CircuitOpenError(f"V5 circuit open for {key}")


def record_success(service_id: str, operation: str) -> None:
    key = _circuit_key(service_id, operation)
    with _circuit_lock:
        _circuits[key] = CircuitState()


def record_failure(service_id: str, operation: str, *, now: float | None = None) -> None:
    cfg = _circuit_cfg()
    if not bool(cfg.get("enabled", True)):
        return
    key = _circuit_key(service_id, operation)
    threshold = int(cfg["failure_threshold"])
    if threshold < 1:
        raise RuntimeError("invalid V5 circuit-breaker failure threshold")
    current = time.monotonic() if now is None else float(now)
    with _circuit_lock:
        state = _circuits.setdefault(key, CircuitState())
        state.failures += 1
        if state.failures >= threshold and state.opened_at is None:
            state.opened_at = current


def reset_circuits() -> None:
    with _circuit_lock:
        _circuits.clear()


def is_retryable_exception(exc: BaseException, policy: RetryPolicy) -> bool:
    return type(exc).__name__ in policy.retry_exception_names


def is_retryable_status(status_code: int | None, policy: RetryPolicy) -> bool:
    return status_code is not None and int(status_code) in policy.retry_http_statuses


def should_count_failure(exc: BaseException | None = None, status_code: int | None = None) -> bool:
    cfg = _circuit_cfg()
    if status_code is not None and int(status_code) in {int(value) for value in cfg.get("count_http_statuses") or []}:
        return True
    return exc is not None and type(exc).__name__ in {str(value) for value in cfg.get("count_exception_names") or []}


def post(
    service_id: str,
    operation: str,
    url: str,
    *,
    json_body: dict[str, Any],
    timeout: tuple[float, float],
) -> tuple[requests.Response, int, dict[str, Any]]:
    policy = retry_policy(service_id, operation)
    last_exc: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        before_call(service_id, operation)
        try:
            response = _session().post(url, json=json_body, timeout=timeout)
            retryable_status = is_retryable_status(response.status_code, policy)
            if retryable_status:
                if should_count_failure(status_code=response.status_code):
                    record_failure(service_id, operation)
                if attempt < policy.max_attempts:
                    if policy.backoff_ms > 0:
                        time.sleep((policy.backoff_ms * attempt) / 1000.0)
                    continue
                return response, attempt, circuit_snapshot(service_id, operation)
            record_success(service_id, operation)
            return response, attempt, circuit_snapshot(service_id, operation)
        except requests.RequestException as exc:
            last_exc = exc
            retryable = is_retryable_exception(exc, policy)
            if should_count_failure(exc=exc):
                record_failure(service_id, operation)
            if not retryable or attempt >= policy.max_attempts:
                raise
            if policy.backoff_ms > 0:
                time.sleep((policy.backoff_ms * attempt) / 1000.0)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"V5 transport failed without response: {service_id}.{operation}")
