from threading import Event

import pytest

from src.v5.refresh_worker import RefreshWorker, resolve_refresh_worker_spec, start_refresh_worker


def test_refresh_worker_is_default_off_for_orchestrator():
    spec = resolve_refresh_worker_spec(service_id="orchestrator", environ={})
    assert spec["enabled"] is False
    assert spec["reason"] == "EXPLICITLY_DISABLED"


def test_refresh_worker_never_starts_on_non_orchestrator_service():
    spec = resolve_refresh_worker_spec(
        service_id="prediction",
        environ={"V5_REFRESH_WORKER_ENABLED": "true", "V5_REFRESH_WORKER_MODE": "live"},
    )
    assert spec["enabled"] is False
    assert spec["reason"] == "NON_ORCHESTRATOR_SERVICE"


def test_enabled_deadline_worker_uses_registry_owned_subminute_schedule():
    spec = resolve_refresh_worker_spec(
        service_id="orchestrator",
        environ={"V5_REFRESH_WORKER_ENABLED": "true", "V5_REFRESH_WORKER_MODE": "deadline"},
    )
    assert spec["enabled"] is True
    assert spec["mode"] == "deadline"
    assert spec["interval_seconds"] == 20
    assert spec["schedule"]["scheduler_class"] == "SUBMINUTE_WORKER_REQUIRED"
    assert spec["schedule"]["github_actions_authoritative"] is False


def test_enabled_worker_requires_explicit_mode():
    with pytest.raises(RuntimeError, match="V5_REFRESH_WORKER_MODE is not set"):
        resolve_refresh_worker_spec(
            service_id="orchestrator",
            environ={"V5_REFRESH_WORKER_ENABLED": "true"},
        )


def test_on_demand_cannot_be_enabled_as_continuous_worker():
    with pytest.raises(RuntimeError, match="explicit prewarm"):
        resolve_refresh_worker_spec(
            service_id="orchestrator",
            environ={"V5_REFRESH_WORKER_ENABLED": "true", "V5_REFRESH_WORKER_MODE": "on_demand"},
        )


def test_worker_immediately_refreshes_and_exposes_success_status():
    invoked = Event()
    payloads = []

    def handler(operation, payload):
        payloads.append((operation, payload))
        invoked.set()
        return {"execution_plane": {"hot_materialization": "READY"}}

    worker = start_refresh_worker(
        service_id="orchestrator",
        handler=handler,
        environ={"V5_REFRESH_WORKER_ENABLED": "true", "V5_REFRESH_WORKER_MODE": "live"},
    )
    assert isinstance(worker, RefreshWorker)
    assert invoked.wait(1.0) is True
    worker.stop(timeout_seconds=1.0)
    status = worker.status()
    assert status["successes"] >= 1
    assert status["failures"] == 0
    assert status["last_materialization_status"] == "READY"
    assert status["running"] is False
    assert payloads[0][0] == "run"
    assert payloads[0][1]["mode"] == "live"
    assert payloads[0][1]["persist"] is True
    assert payloads[0][1]["_refresh_origin"] == "worker"


def test_worker_failure_is_observable_and_does_not_crash_thread_owner():
    invoked = Event()

    def handler(operation, payload):
        invoked.set()
        raise RuntimeError("refresh failed")

    worker = start_refresh_worker(
        service_id="orchestrator",
        handler=handler,
        environ={"V5_REFRESH_WORKER_ENABLED": "true", "V5_REFRESH_WORKER_MODE": "deadline"},
    )
    assert worker is not None
    assert invoked.wait(1.0) is True
    worker.stop(timeout_seconds=1.0)
    status = worker.status()
    assert status["failures"] >= 1
    assert "refresh failed" in str(status["last_error"])
    assert status["failure_behavior"] == "KEEP_LAST_HEALTHY_MATERIALIZATION"
