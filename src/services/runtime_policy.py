from __future__ import annotations

from src.utils import CONFIG, read_json

SERVICE_REGISTRY = CONFIG / "service_registry.json"
SERVING_REGISTRY = CONFIG / "serving_improvement_registry.json"


def decision_compute_slo_ms() -> float:
    """Return the authoritative decision-compute SLO and fail on config drift."""
    services = read_json(SERVICE_REGISTRY, {})
    serving = read_json(SERVING_REGISTRY, {})
    authoritative = (services.get("guardrails") or {}).get("decision_compute_slo_ms")
    mirror = (serving.get("performance") or {}).get("decision_compute_hard_limit_ms")
    if authoritative is None:
        raise RuntimeError("service registry is missing decision_compute_slo_ms")
    value = float(authoritative)
    if mirror is not None and float(mirror) != value:
        raise RuntimeError(
            f"decision SLO registry drift: service_registry={value} serving_registry={mirror}"
        )
    return value


def quick_serving_target_ms() -> float:
    serving = read_json(SERVING_REGISTRY, {})
    value = (serving.get("performance") or {}).get("quick_serving_target_ms")
    if value is None:
        raise RuntimeError("serving registry is missing quick_serving_target_ms")
    return float(value)
