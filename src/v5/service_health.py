from __future__ import annotations

import importlib.util
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.module_registry import module_specs
from src.v5.service_registry import get_service, validate_registry


def local_service_health(service_id: str) -> dict[str, Any]:
    spec = get_service(service_id)
    modules = {module.name: module for module in module_specs()}
    registry_errors = list(validate_registry())
    module_rows: list[dict[str, Any]] = []
    local_errors: list[str] = []

    for module_name in spec.owns_modules:
        module = modules.get(module_name)
        if module is None:
            local_errors.append(f"owned module missing from module registry: {module_name}")
            continue

        entrypoint_ok = bool(module.entrypoint) and importlib.util.find_spec(module.entrypoint) is not None
        config_ok = False
        config_error: str | None = None
        if module.config:
            try:
                load_json_config(module.config)
                config_ok = True
            except Exception as exc:
                config_error = f"{type(exc).__name__}: {exc}"

        if not entrypoint_ok:
            local_errors.append(f"module entrypoint unavailable: {module_name} -> {module.entrypoint}")
        if not config_ok:
            local_errors.append(f"module config unavailable: {module_name} -> {module.config}: {config_error}")

        module_rows.append(
            {
                "module": module_name,
                "status": module.status,
                "entrypoint": module.entrypoint,
                "entrypoint_ok": entrypoint_ok,
                "config": module.config,
                "config_ok": config_ok,
                "config_error": config_error,
            }
        )

    errors = [*registry_errors, *local_errors]
    ready = not errors
    return {
        "service_id": spec.service_id,
        "status": "UP" if ready else "DEGRADED",
        "ready": ready,
        "critical": spec.critical,
        "bounded_context": spec.bounded_context,
        "owned_module_count": len(spec.owns_modules),
        "modules": module_rows,
        "registry_errors": registry_errors,
        "local_errors": local_errors,
    }
