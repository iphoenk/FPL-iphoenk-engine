from __future__ import annotations

from src.v5 import cluster_health
from src.v5.service_registry import service_specs
from src.v5.services import orchestrator


def _remote_row(spec, *, ready: bool = True):
    return {
        "service_id": spec.service_id,
        "critical": spec.critical,
        "reachable": ready,
        "ready": ready,
        "status": "UP" if ready else "UNAVAILABLE",
        "elapsed_ms": 1.0,
        "health": {"ready": ready} if ready else None,
        "error_type": None if ready else "ConnectTimeout",
        "error": None if ready else "synthetic outage",
    }


def _local_ready(service_id: str):
    return {
        "service_id": service_id,
        "status": "UP",
        "ready": True,
        "critical": True,
        "bounded_context": "synthetic",
        "owned_module_count": 1,
        "modules": [],
        "registry_errors": [],
        "local_errors": [],
    }


def test_cluster_health_is_on_demand_only_and_green_when_all_ready(monkeypatch):
    monkeypatch.setattr(cluster_health, "local_service_health", _local_ready)
    monkeypatch.setattr(cluster_health, "_probe_remote", lambda spec: _remote_row(spec, ready=True))

    report = cluster_health.cluster_health()

    assert report["mode"] == "ON_DEMAND_ONLY"
    assert report["overall"] == "GREEN"
    assert report["ready_for_run"] is True
    assert report["all_services_ready"] is True
    assert report["service_count"] == len(service_specs())
    assert report["policy"]["normal_run_probe_enabled"] is False
    assert report["policy"]["health_probe_mutates_business_circuits"] is False


def test_noncritical_price_outage_is_amber_but_still_ready_for_run(monkeypatch):
    monkeypatch.setattr(cluster_health, "local_service_health", _local_ready)

    def probe(spec):
        return _remote_row(spec, ready=spec.service_id != "price")

    monkeypatch.setattr(cluster_health, "_probe_remote", probe)
    report = cluster_health.cluster_health()

    assert report["overall"] == "AMBER"
    assert report["ready_for_run"] is True
    assert report["all_services_ready"] is False
    assert report["critical_failure_count"] == 0
    assert report["noncritical_failures"] == ["price"]


def test_critical_prediction_outage_is_red_and_not_ready_for_run(monkeypatch):
    monkeypatch.setattr(cluster_health, "local_service_health", _local_ready)

    def probe(spec):
        return _remote_row(spec, ready=spec.service_id != "prediction")

    monkeypatch.setattr(cluster_health, "_probe_remote", probe)
    report = cluster_health.cluster_health()

    assert report["overall"] == "RED"
    assert report["ready_for_run"] is False
    assert report["critical_failures"] == ["prediction"]


def test_orchestrator_exposes_cluster_health_without_running_business_pipeline(monkeypatch):
    expected = {"mode": "ON_DEMAND_ONLY", "overall": "GREEN", "ready_for_run": True}
    monkeypatch.setattr(orchestrator, "cluster_health", lambda service_id: {**expected, "service_id": service_id})

    report = orchestrator.handle("cluster_health", {})

    assert report["overall"] == "GREEN"
    assert report["service_id"] == "orchestrator"
