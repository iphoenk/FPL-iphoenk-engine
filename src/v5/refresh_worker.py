from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from threading import Event, RLock, Thread
from time import perf_counter
from typing import Any, Callable, Mapping

from src.v5.execution_plane import refresh_schedule, registry

Handler = Callable[[str, dict[str, Any]], Any]
_TRUTHY = {"1", "true", "yes", "on"}


def _deployment() -> dict[str, Any]:
    scheduling = registry().get("refresh_scheduling")
    if not isinstance(scheduling, dict):
        raise RuntimeError("V5 refresh scheduling registry unavailable")
    deployment = scheduling.get("deployment")
    if not isinstance(deployment, dict):
        raise RuntimeError("V5 refresh worker deployment contract unavailable")
    return deployment


def resolve_refresh_worker_spec(
    *,
    service_id: str,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    deployment = _deployment()
    enabled_env = str(deployment.get("enabled_env") or "")
    mode_env = str(deployment.get("mode_env") or "")
    if not enabled_env or not mode_env:
        raise RuntimeError("V5 refresh worker deployment env names must be registry-owned")

    default_enabled = bool(deployment.get("enabled_default", False))
    raw_enabled = str(env.get(enabled_env, "true" if default_enabled else "false")).strip().lower()
    enabled = raw_enabled in _TRUTHY
    if str(service_id) != "orchestrator":
        return {
            "enabled": False,
            "service_id": str(service_id),
            "reason": "NON_ORCHESTRATOR_SERVICE",
            "enabled_env": enabled_env,
            "mode_env": mode_env,
        }
    if not enabled:
        return {
            "enabled": False,
            "service_id": "orchestrator",
            "reason": "EXPLICITLY_DISABLED",
            "enabled_env": enabled_env,
            "mode_env": mode_env,
        }

    mode = str(env.get(mode_env) or "").strip()
    if not mode:
        raise RuntimeError(f"V5 refresh worker enabled but {mode_env} is not set")
    schedule = refresh_schedule(mode)
    if schedule["scheduler_class"] == "EXPLICIT_PREWARM_REQUIRED":
        raise RuntimeError("V5 on-demand mode requires explicit prewarm, not a continuous refresh worker")

    return {
        "enabled": True,
        "service_id": "orchestrator",
        "mode": mode,
        "interval_seconds": int(schedule["target_interval_seconds"]),
        "schedule": schedule,
        "enabled_env": enabled_env,
        "mode_env": mode_env,
        "startup_behavior": deployment.get("startup_behavior"),
        "shutdown_behavior": deployment.get("shutdown_behavior"),
        "failure_behavior": deployment.get("failure_behavior"),
    }


class RefreshWorker:
    def __init__(self, handler: Handler, spec: dict[str, Any]) -> None:
        if not spec.get("enabled"):
            raise ValueError("RefreshWorker requires an enabled worker spec")
        self._handler = handler
        self._spec = dict(spec)
        self._stop = Event()
        self._thread: Thread | None = None
        self._state_lock = RLock()
        self._state: dict[str, Any] = {
            "enabled": True,
            "running": False,
            "mode": self._spec["mode"],
            "interval_seconds": self._spec["interval_seconds"],
            "iterations": 0,
            "successes": 0,
            "failures": 0,
            "last_started_at": None,
            "last_completed_at": None,
            "last_success_at": None,
            "last_elapsed_ms": None,
            "last_error": None,
            "last_materialization_status": None,
        }

    def start(self) -> None:
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = Thread(
                target=self._loop,
                name=f"v5-refresh-{self._spec['mode']}",
                daemon=True,
            )
            self._state["running"] = True
            self._thread.start()

    def stop(self, *, timeout_seconds: float = 10.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(0.0, float(timeout_seconds)))
        with self._state_lock:
            self._state["running"] = bool(thread is not None and thread.is_alive())

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                **self._state,
                "scheduler_class": (self._spec.get("schedule") or {}).get("scheduler_class"),
                "activation": (self._spec.get("schedule") or {}).get("activation"),
                "freshness_budget_seconds": (self._spec.get("schedule") or {}).get("freshness_budget_seconds"),
                "failure_behavior": self._spec.get("failure_behavior"),
            }

    def _loop(self) -> None:
        interval = float(self._spec["interval_seconds"])
        mode = str(self._spec["mode"])
        while not self._stop.is_set():
            iteration_started = perf_counter()
            started_at = datetime.now(timezone.utc).isoformat()
            with self._state_lock:
                self._state["iterations"] += 1
                self._state["last_started_at"] = started_at
                iteration = int(self._state["iterations"])

            try:
                result = self._handler(
                    "run",
                    {
                        "mode": mode,
                        "persist": True,
                        "_refresh_origin": "worker",
                        "correlation_id": f"refresh-worker-{mode}-{iteration}-{uuid.uuid4().hex}",
                    },
                )
                execution = result.get("execution_plane") if isinstance(result, dict) else {}
                materialization_status = (
                    execution.get("hot_materialization") if isinstance(execution, dict) else None
                )
                if materialization_status != "READY":
                    raise RuntimeError("V5 refresh worker did not produce a READY hot materialization")
                elapsed_ms = round((perf_counter() - iteration_started) * 1000.0, 3)
                completed_at = datetime.now(timezone.utc).isoformat()
                with self._state_lock:
                    self._state["successes"] += 1
                    self._state["last_completed_at"] = completed_at
                    self._state["last_success_at"] = completed_at
                    self._state["last_elapsed_ms"] = elapsed_ms
                    self._state["last_error"] = None
                    self._state["last_materialization_status"] = materialization_status
            except Exception as exc:
                elapsed_ms = round((perf_counter() - iteration_started) * 1000.0, 3)
                completed_at = datetime.now(timezone.utc).isoformat()
                with self._state_lock:
                    self._state["failures"] += 1
                    self._state["last_completed_at"] = completed_at
                    self._state["last_elapsed_ms"] = elapsed_ms
                    self._state["last_error"] = f"{type(exc).__name__}: {exc}"

            remaining = max(0.0, interval - (perf_counter() - iteration_started))
            self._stop.wait(remaining)

        with self._state_lock:
            self._state["running"] = False


def start_refresh_worker(
    *,
    service_id: str,
    handler: Handler,
    environ: Mapping[str, str] | None = None,
) -> RefreshWorker | None:
    spec = resolve_refresh_worker_spec(service_id=service_id, environ=environ)
    if not spec.get("enabled"):
        return None
    worker = RefreshWorker(handler, spec)
    worker.start()
    return worker
