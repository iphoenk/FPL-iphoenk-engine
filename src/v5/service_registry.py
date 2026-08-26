from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.v5.config_cache import load_json_config

SERVICE_CONFIG = "config/v5_service_registry.json"


@dataclass(frozen=True)
class ServiceSpec:
    service_id: str
    port: int
    bounded_context: str
    handler: str
    owns_modules: tuple[str, ...]
    dependencies: tuple[str, ...]
    status: str
    critical: bool


def registry() -> dict[str, Any]:
    data = load_json_config(SERVICE_CONFIG)
    if data.get("mandatory") is not True or not isinstance(data.get("services"), dict):
        raise RuntimeError("invalid or non-mandatory V5 service registry")
    return data


def service_specs() -> tuple[ServiceSpec, ...]:
    out = []
    for service_id, raw in registry()["services"].items():
        out.append(
            ServiceSpec(
                service_id=str(service_id),
                port=int(raw["port"]),
                bounded_context=str(raw["bounded_context"]),
                handler=str(raw["handler"]),
                owns_modules=tuple(str(x) for x in raw.get("owns_modules", [])),
                dependencies=tuple(str(x) for x in raw.get("dependencies", [])),
                status=str(raw.get("status", "UNKNOWN")),
                critical=bool(raw.get("critical", False)),
            )
        )
    return tuple(out)


def get_service(service_id: str) -> ServiceSpec:
    for spec in service_specs():
        if spec.service_id == service_id:
            return spec
    raise KeyError(f"unknown V5 service: {service_id}")


def validate_registry() -> list[str]:
    errors: list[str] = []
    specs = service_specs()
    ids = {s.service_id for s in specs}
    ports = [s.port for s in specs]
    if len(ports) != len(set(ports)):
        errors.append("duplicate service ports")
    for spec in specs:
        if not spec.handler or ":" not in spec.handler:
            errors.append(f"{spec.service_id}: invalid handler")
        if not spec.owns_modules:
            errors.append(f"{spec.service_id}: owns no modules")
        for dep in spec.dependencies:
            if dep not in ids:
                errors.append(f"{spec.service_id}: unknown dependency {dep}")
            if dep == spec.service_id:
                errors.append(f"{spec.service_id}: self dependency")
    return errors
