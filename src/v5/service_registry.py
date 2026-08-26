from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.module_registry import module_specs

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


def module_owners() -> dict[str, str]:
    owners: dict[str, str] = {}
    for spec in service_specs():
        for module in spec.owns_modules:
            if module in owners:
                raise RuntimeError(f"V5 module has duplicate service owners: {module}")
            owners[module] = spec.service_id
    return owners


def _dependency_cycle(specs: tuple[ServiceSpec, ...]) -> bool:
    graph = {spec.service_id: tuple(spec.dependencies) for spec in specs}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for dep in graph.get(node, ()):
            if visit(dep):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def validate_registry() -> list[str]:
    errors: list[str] = []
    specs = service_specs()
    ids = {s.service_id for s in specs}
    ports = [s.port for s in specs]
    if len(ports) != len(set(ports)):
        errors.append("duplicate service ports")
    ownership_count: dict[str, int] = {}
    for spec in specs:
        if not spec.handler or ":" not in spec.handler:
            errors.append(f"{spec.service_id}: invalid handler")
        if not spec.owns_modules:
            errors.append(f"{spec.service_id}: owns no modules")
        for module in spec.owns_modules:
            ownership_count[module] = ownership_count.get(module, 0) + 1
        for dep in spec.dependencies:
            if dep not in ids:
                errors.append(f"{spec.service_id}: unknown dependency {dep}")
            if dep == spec.service_id:
                errors.append(f"{spec.service_id}: self dependency")
    registered_modules = {m.name for m in module_specs()}
    for module in sorted(registered_modules):
        count = ownership_count.get(module, 0)
        if count == 0:
            errors.append(f"unowned module: {module}")
        elif count > 1:
            errors.append(f"multiply-owned module: {module}")
    for module in sorted(set(ownership_count) - registered_modules):
        errors.append(f"service owns unregistered module: {module}")
    if _dependency_cycle(specs):
        errors.append("service dependency graph contains cycle")
    return errors
