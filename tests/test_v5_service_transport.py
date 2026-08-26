from __future__ import annotations

import requests
import pytest

from src.v5 import service_client, service_transport


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = int(status_code)
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return dict(self._payload)


class SequenceSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def post(self, url, *, json, timeout):
        self.calls += 1
        if not self.outcomes:
            raise AssertionError("unexpected transport call")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@pytest.fixture(autouse=True)
def _clean_circuits():
    service_transport.reset_circuits()
    yield
    service_transport.reset_circuits()


def test_retry_policy_keeps_persistence_non_idempotent():
    assert service_transport.retry_policy("prediction", "build").max_attempts == 2
    assert service_transport.retry_policy("snapshot", "write").name == "non_idempotent"
    assert service_transport.retry_policy("snapshot", "write").max_attempts == 1
    assert service_transport.retry_policy("snapshot", "snapshot").max_attempts == 1


def test_idempotent_503_is_retried_then_recovers(monkeypatch):
    session = SequenceSession([FakeResponse(503), FakeResponse(200)])
    monkeypatch.setattr(service_transport, "_session", lambda: session)
    monkeypatch.setattr(service_transport.time, "sleep", lambda _: None)

    response, attempts, circuit = service_transport.post(
        "prediction",
        "build",
        "http://prediction/v1/invoke/build",
        json_body={},
        timeout=(0.1, 0.1),
    )

    assert response.status_code == 200
    assert attempts == 2
    assert session.calls == 2
    assert circuit["state"] == "CLOSED"
    assert circuit["failures"] == 0


def test_non_idempotent_write_is_never_retried(monkeypatch):
    session = SequenceSession([FakeResponse(503), FakeResponse(200)])
    monkeypatch.setattr(service_transport, "_session", lambda: session)

    response, attempts, circuit = service_transport.post(
        "snapshot",
        "write",
        "http://snapshot/v1/invoke/write",
        json_body={"name": "artifact"},
        timeout=(0.1, 0.1),
    )

    assert response.status_code == 503
    assert attempts == 1
    assert session.calls == 1
    assert circuit["failures"] == 1


def test_circuit_opens_after_repeated_retryable_failures(monkeypatch):
    session = SequenceSession([FakeResponse(503), FakeResponse(503), FakeResponse(503), FakeResponse(200)])
    monkeypatch.setattr(service_transport, "_session", lambda: session)
    monkeypatch.setattr(service_transport.time, "sleep", lambda _: None)

    first, attempts, _ = service_transport.post(
        "prediction",
        "build",
        "http://prediction/v1/invoke/build",
        json_body={},
        timeout=(0.1, 0.1),
    )
    assert first.status_code == 503
    assert attempts == 2

    with pytest.raises(service_transport.CircuitOpenError):
        service_transport.post(
            "prediction",
            "build",
            "http://prediction/v1/invoke/build",
            json_body={},
            timeout=(0.1, 0.1),
        )

    assert session.calls == 3
    snapshot = service_transport.circuit_snapshot("prediction", "build")
    assert snapshot["state"] == "OPEN"
    assert snapshot["failures"] == 3

    with pytest.raises(service_transport.CircuitOpenError):
        service_transport.before_call("prediction", "build")
    assert session.calls == 3


def test_circuit_recovers_after_registry_cooldown():
    service_transport.record_failure("truth", "assemble", now=10.0)
    service_transport.record_failure("truth", "assemble", now=10.0)
    service_transport.record_failure("truth", "assemble", now=10.0)

    with pytest.raises(service_transport.CircuitOpenError):
        service_transport.before_call("truth", "assemble", now=15.0)

    service_transport.before_call("truth", "assemble", now=21.0)
    snapshot = service_transport.circuit_snapshot("truth", "assemble", now=21.0)
    assert snapshot["state"] == "CLOSED"
    assert snapshot["failures"] == 0


def test_connection_exception_retries_for_idempotent_operation(monkeypatch):
    session = SequenceSession([requests.ConnectTimeout("synthetic"), FakeResponse(200)])
    monkeypatch.setattr(service_transport, "_session", lambda: session)
    monkeypatch.setattr(service_transport.time, "sleep", lambda _: None)

    response, attempts, _ = service_transport.post(
        "price",
        "build",
        "http://price/v1/invoke/build",
        json_body={},
        timeout=(0.1, 0.1),
    )

    assert response.status_code == 200
    assert attempts == 2
    assert session.calls == 2


def test_service_client_exposes_transport_observability(monkeypatch):
    response = FakeResponse(
        200,
        {
            "ok": True,
            "contract_version": "v1",
            "service_id": "prediction",
            "operation": "build",
            "elapsed_ms": 4.0,
            "data": {"status": "READY"},
        },
    )
    monkeypatch.setattr(
        service_client,
        "transport_post",
        lambda *args, **kwargs: (response, 2, {"state": "CLOSED", "failures": 0}),
    )

    envelope = service_client.invoke_envelope(
        "prediction",
        "build",
        {"synthetic": True},
        correlation_id="transport-test",
    )

    assert envelope["data"]["status"] == "READY"
    assert envelope["transport_attempts"] == 2
    assert envelope["transport_retry_policy"] == "idempotent"
    assert envelope["transport_circuit"]["state"] == "CLOSED"
    assert envelope["round_trip_ms"] >= 0.0


def test_parallel_outcomes_preserve_independent_failure_without_raising(monkeypatch):
    def fake_invoke(service_id, operation, payload, *, correlation_id=None):
        if service_id == "price":
            raise requests.ConnectTimeout("synthetic price outage")
        return {
            "ok": True,
            "service_id": service_id,
            "operation": operation,
            "elapsed_ms": 1.0,
            "data": {"status": "READY"},
        }

    monkeypatch.setattr(service_client, "invoke_envelope", fake_invoke)
    outcomes = service_client.invoke_parallel_outcomes(
        {
            "price": ("price", "build", {}),
            "prediction": ("prediction", "build", {}),
        },
        correlation_id="parallel-outcome-test",
    )

    assert outcomes["price"]["ok"] is False
    assert outcomes["price"]["error_type"] == "ConnectTimeout"
    assert outcomes["price"]["envelope"] is None
    assert outcomes["prediction"]["ok"] is True
    assert outcomes["prediction"]["envelope"]["data"]["status"] == "READY"
