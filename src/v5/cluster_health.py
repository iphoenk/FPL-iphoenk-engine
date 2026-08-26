from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.service_client import service_url
from src.v5.service_health import local_service_health
from src.v5.service_registry import ServiceSpec, service_specs
from src.v5.service_transport import diagnostic_get

CONFIG = "config/v5_cluster_health_registry.json"


def _cfg() -> dict[str, Any]:
    data = load_json_config(CONFIG)
    if data.get("mode") != "ON_DEMAND_ONLY":
        raise RuntimeError("V5 cluster health must remain ON_DEMAND_ONLY")
    if not isinstance(data.get("policy"), dict) or not isinstance(data.get("transport"), dict):
        raise RuntimeError("invalid V5 cluster health registry")
    return data


def _probe_remote(spec: ServiceSpec) -> dict[str, Any]:
    cfg = _cfg()
    transport = cfg["transport"]
    defaults = load_json_config("config/v5_service_registry.json")["defaults"]
    timeout = (
        float(transport["connect_timeout_ms"]) / 1000.0,
        float(transport["read_timeout_ms"]) / 1000.0,
    )
    started = perf_counter()
    try:
        response = diagnostic_get(f"{service_url(spec.service_id)}{defaults['health_path']}", timeout=timeout)
        elapsed_ms = round((perf_counter() - started) * 1000.0, 3)
        response.raise_for_status()
        payload = response.json()
        ready = bool(payload.get("ready")) and payload.get("status") == "UP"
        return {
            "service_id": spec.service_id,
            "critical": spec.critical,
            "reachable": True,
            "ready": ready,
            "status": payload.get("status"),
            "elapsed_ms": elapsed_ms,
            "health": payload,
            "error_type": None,
            "error": None,
        }
    except Exception as exc:
        return {
            "service_id": spec.service_id,
            "critical": spec.critical,
            "reachable": False,
            "ready": False,
            "status": "UNAVAILABLE",
            "elapsed_ms": round((perf_counter() - started) * 1000.0, 3),
            "health": None,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def cluster_health(local_service_id: str = "orchestrator") -> dict[str, Any]:
    cfg = _cfg()
    policy = cfg["policy"]
    specs = service_specs()
    local_spec = next((spec for spec in specs if spec.service_id == local_service_id), None)
    if local_spec is None:
        raise KeyError(f"unknown local V5 service for cluster health: {local_service_id}")

    rows: list[dict[str, Any]] = []
    if bool(policy.get("include_local_orchestrator_readiness", True)):
        local = local_service_health(local_service_id)
        rows.append(
            {
                "service_id": local_service_id,
                "critical": local_spec.critical,
                "reachable": True,
                "ready": bool(local.get("ready")),
                "status": local.get("status"),
                "elapsed_ms": 0.0,
                "health": local,
                "error_type": None,
                "error": None,
            }
        )

    remote_specs = [spec for spec in specs if spec.service_id != local_service_id]
    max_workers = min(len(remote_specs), int(cfg["transport"]["max_workers"])) if remote_specs else 0
    if remote_specs and max_workers < 1:
        raise RuntimeError("V5 cluster health max_workers must be positive")
    if remote_specs:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_probe_remote, spec): spec.service_id for spec in remote_specs}
            for future in as_completed(futures):
                rows.append(future.result())

    rows.sort(key=lambda row: str(row["service_id"]))
    critical_failures = [row for row in rows if row["critical"] and not row["ready"]]
    noncritical_failures = [row for row in rows if not row["critical"] and not row["ready"]]
    if critical_failures:
        overall = str(policy["critical_unavailable_status"])
    elif noncritical_failures:
        overall = str(policy["noncritical_unavailable_status"])
    else:
        overall = str(policy["all_ready_status"])

    return {
        "schema_version": int(cfg["schema_version"]),
        "mode": cfg["mode"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "ready_for_run": not critical_failures,
        "all_services_ready": not critical_failures and not noncritical_failures,
        "service_count": len(rows),
        "critical_failure_count": len(critical_failures),
        "noncritical_failure_count": len(noncritical_failures),
        "critical_failures": [row["service_id"] for row in critical_failures],
        "noncritical_failures": [row["service_id"] for row in noncritical_failures],
        "services": rows,
        "policy": {
            "on_demand_only": True,
            "normal_run_probe_enabled": not bool(policy.get("do_not_probe_on_normal_run", True)),
            "health_probe_mutates_business_circuits": not bool(
                policy.get("health_probe_must_not_mutate_business_circuits", True)
            ),
        },
    }
