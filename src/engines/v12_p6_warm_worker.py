from __future__ import annotations

"""Bounded P6 warm-worker state machine for Canonical V12.

This module owns orchestration only. Canonical callbacks must be the existing V12
engine, Stage3, renderer, QA and private publisher. It never creates a second
model, optimizer, scheduler, factual plane or publication authority.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
import time
from typing import Any

from .v12_cache_operational import (
    CacheOperationalError,
    plan_cache_behavior,
    validate_actual_behavior,
)
from .v12_scenario_package import validate_package_for_dependencies
from .v12_semantic_oracle import semantic_fingerprint

MAX_TTL_SECONDS = 6 * 60 * 60 - 1
DEFAULT_TTL_SECONDS = 5 * 60 * 60 + 45 * 60
SCHEDULER_AUTHORITY = False
CRON_AUTHORITY = False
SECOND_MODEL_CREATED = False
CANONICAL_ENGINE_ONLY = True


class WarmWorkerError(RuntimeError):
    pass


class WorkerState(str, Enum):
    START = "START"
    LOAD_CANONICAL_STATE = "LOAD_CANONICAL_STATE"
    VALIDATE_DEPENDENCIES = "VALIDATE_DEPENDENCIES"
    WARM_READY = "WARM_READY"
    RECEIVE_CHANGE = "RECEIVE_CHANGE"
    CLASSIFY_CHANGE = "CLASSIFY_CHANGE"
    INVALIDATE_MINIMUM_REQUIRED = "INVALIDATE_MINIMUM_REQUIRED"
    RECOMPUTE = "RECOMPUTE"
    STAGE3 = "STAGE3"
    RENDER = "RENDER"
    QA = "QA"
    PRIVATE_PUBLISH = "PRIVATE_PUBLISH"
    CLEAN_SHUTDOWN = "CLEAN_SHUTDOWN"


@dataclass(frozen=True)
class WarmIdentity:
    production_sha: str
    runtime_data_sha: str
    model_version: str
    schema_version: str
    gw_fixture_fingerprint: str
    projection_lineage_fingerprint: str
    current15_fingerprint: str
    owner_context_fingerprint: str
    mc_authority: str
    runtime_class: str

    def p4_dependencies(self) -> dict[str, str]:
        return {
            "model_version": self.model_version,
            "our15_fingerprint": self.current15_fingerprint,
            "fixture_gw_fingerprint": self.gw_fixture_fingerprint,
            "projection_lineage_fingerprint": self.projection_lineage_fingerprint,
            "cache_schema_version": self.schema_version,
            "mc_authority": self.mc_authority,
            "owner_context_fingerprint": self.owner_context_fingerprint,
        }


@dataclass
class CanonicalCallbacks:
    load_canonical_state: Callable[[WarmIdentity, Mapping[str, Any]], Mapping[str, Any]]
    recompute: Callable[[Mapping[str, Any], Mapping[str, Any], Any], tuple[Mapping[str, Any], Mapping[str, str], Mapping[str, list[str]]]]
    stage3: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    render: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]
    qa: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]
    private_publish: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]


def _require_identity(identity: WarmIdentity) -> None:
    missing = [
        key for key, value in identity.__dict__.items()
        if not str(value or "").strip()
    ]
    if missing:
        raise WarmWorkerError(f"missing warm identity: {missing}")


class WarmWorker:
    def __init__(
        self,
        *,
        identity: WarmIdentity,
        private_state: Mapping[str, Any],
        scenario_package: Mapping[str, Any] | None,
        callbacks: CanonicalCallbacks,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        _require_identity(identity)
        if ttl_seconds <= 0 or ttl_seconds > MAX_TTL_SECONDS:
            raise WarmWorkerError("P6 lifetime must be positive and strictly below 6 hours")
        self.identity = identity
        self._private_state = dict(private_state)
        self._scenario_package = dict(scenario_package or {})
        self.callbacks = callbacks
        self.ttl_seconds = int(ttl_seconds)
        self.clock = clock
        self.started_at: float | None = None
        self.state = WorkerState.START
        self.trace: list[str] = [self.state.value]
        self.canonical_state: Mapping[str, Any] | None = None

    def _transition(self, state: WorkerState) -> None:
        self.state = state
        self.trace.append(state.value)

    def _expired(self) -> bool:
        return self.started_at is not None and self.clock() - self.started_at >= self.ttl_seconds

    def _ensure_live(self) -> None:
        if self._expired():
            self.shutdown()
            raise WarmWorkerError("P6 TTL expired")

    def start(self) -> None:
        if self.state != WorkerState.START:
            raise WarmWorkerError("P6 worker already started")
        self.started_at = self.clock()
        self._transition(WorkerState.LOAD_CANONICAL_STATE)
        state = self.callbacks.load_canonical_state(self.identity, self._private_state)
        observed_identity = dict(state.get("identity") or {})
        expected = dict(self.identity.__dict__)
        for key, value in expected.items():
            if str(observed_identity.get(key) or "") != str(value):
                raise WarmWorkerError(f"wrong/stale canonical state identity: {key}")

        self._transition(WorkerState.VALIDATE_DEPENDENCIES)
        if self._scenario_package:
            p4 = validate_package_for_dependencies(
                self._scenario_package,
                dependencies=self.identity.p4_dependencies(),
            )
            if not p4["current"]:
                raise WarmWorkerError("stale/wrong-base P4 package rejected")
        self.canonical_state = state
        self._transition(WorkerState.WARM_READY)

    def apply_change(self, change: Mapping[str, Any]) -> dict[str, Any]:
        self._ensure_live()
        if self.state != WorkerState.WARM_READY or self.canonical_state is None:
            raise WarmWorkerError("P6 worker is not WARM_READY")
        t0 = self.clock()
        self._transition(WorkerState.RECEIVE_CHANGE)
        change_class = str(change.get("change_class") or "").upper()
        if not change_class:
            raise WarmWorkerError("unsupported change: missing change_class")

        self._transition(WorkerState.CLASSIFY_CHANGE)
        try:
            plan = plan_cache_behavior(
                change_class,
                affected_dependency_keys=tuple(change.get("affected_dependency_keys") or ()),
                scope_certain=bool(change.get("scope_certain", True)),
            )
        except CacheOperationalError as exc:
            raise WarmWorkerError(f"unsupported change fails closed: {change_class}") from exc

        self._transition(WorkerState.INVALIDATE_MINIMUM_REQUIRED)
        self._transition(WorkerState.RECOMPUTE)
        recomputed, actual_states, reused_keys = self.callbacks.recompute(
            self.canonical_state,
            change,
            plan,
        )
        validation = validate_actual_behavior(
            plan,
            actual_states=actual_states,
            reused_dependency_keys=reused_keys,
        )
        if validation.correctness != "PASS":
            raise WarmWorkerError(
                "cache correctness failure: " + "; ".join(validation.findings)
            )

        self._transition(WorkerState.STAGE3)
        stage3 = self.callbacks.stage3(recomputed)
        if str(stage3.get("status") or "").upper() not in {"PASS", "NOT_APPLICABLE"}:
            raise WarmWorkerError("Stage3 failed closed")

        self._transition(WorkerState.RENDER)
        rendered = self.callbacks.render(recomputed, stage3)
        self._transition(WorkerState.QA)
        qa = self.callbacks.qa(rendered, stage3)
        if str(qa.get("status") or "").upper() != "PASS":
            raise WarmWorkerError("QA failed closed")

        self._transition(WorkerState.PRIVATE_PUBLISH)
        receipt = self.callbacks.private_publish(rendered, qa)
        if str(receipt.get("private_delivery_status") or "").upper() != "PASS":
            raise WarmWorkerError("private publication failed closed")
        t1 = self.clock()

        self.canonical_state = recomputed
        warm_fp = semantic_fingerprint(rendered)
        self._transition(WorkerState.WARM_READY)
        return {
            "t0": t0,
            "t1": t1,
            "total_seconds": t1 - t0,
            "change_class": change_class,
            "expected_cache_state": plan.expected,
            "actual_cache_state": dict(actual_states),
            "invalidated_dependency_keys": list(plan.affected_dependency_keys),
            "cache_correctness": validation.correctness,
            "cache_performance": validation.performance,
            "warm_semantic_fingerprint": warm_fp,
            "private_delivery_status": "PASS",
            "private_remote_sha": str(receipt.get("private_remote_sha") or ""),
            "trace": list(self.trace),
        }

    def shutdown(self) -> None:
        if self.state != WorkerState.CLEAN_SHUTDOWN:
            self.canonical_state = None
            self._private_state.clear()
            self._scenario_package.clear()
            self._transition(WorkerState.CLEAN_SHUTDOWN)
