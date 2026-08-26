from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.service_registry import get_service

CONFIG = "config/v5_degraded_mode_registry.json"


def _cfg() -> dict[str, Any]:
    data = load_json_config(CONFIG)
    if not isinstance(data.get("policy"), dict) or not isinstance(data.get("fallbacks"), dict):
        raise RuntimeError("invalid V5 degraded-mode registry")
    return data


def fallback_for(service_id: str, operation: str, outcome: dict[str, Any]) -> dict[str, Any]:
    spec = get_service(service_id)
    policy = _cfg()["policy"]
    if spec.critical:
        raise RuntimeError(
            f"critical service failure must fail closed: {service_id}.{operation}: {outcome.get('error')}"
        )

    key = f"{service_id}.{operation}"
    fallback = (_cfg().get("fallbacks") or {}).get(key)
    if not isinstance(fallback, dict):
        raise RuntimeError(
            f"non-critical service failure has no registered fallback: {key}: {outcome.get('error')}"
        )
    if str(fallback.get("service_id")) != service_id or str(fallback.get("operation")) != operation:
        raise RuntimeError(f"degraded-mode registry key mismatch: {key}")

    payload = copy.deepcopy(fallback.get("payload") or {})
    if not isinstance(payload, dict):
        raise RuntimeError(f"invalid degraded fallback payload: {key}")

    generated_at = datetime.now(timezone.utc).isoformat()
    if isinstance(payload.get("prices"), dict) and payload["prices"].get("generated_at") is None:
        payload["prices"]["generated_at"] = generated_at
    if isinstance(payload.get("alerts"), dict) and payload["alerts"].get("generated_at") is None:
        payload["alerts"]["generated_at"] = generated_at

    payload["degraded_context"] = {
        "service_id": service_id,
        "operation": operation,
        "behavior": fallback.get("behavior"),
        "blocks_unqualified_go": bool(
            fallback.get("blocks_unqualified_go", policy.get("degraded_context_blocks_unqualified_go", True))
        ),
        "error_type": outcome.get("error_type"),
        "error": outcome.get("error") if policy.get("record_error_provenance", True) else None,
        "generated_at": generated_at,
    }
    return payload


def validate_registry() -> list[str]:
    errors: list[str] = []
    cfg = _cfg()
    for key, fallback in (cfg.get("fallbacks") or {}).items():
        if not isinstance(fallback, dict):
            errors.append(f"invalid fallback row: {key}")
            continue
        service_id = str(fallback.get("service_id") or "")
        operation = str(fallback.get("operation") or "")
        if key != f"{service_id}.{operation}":
            errors.append(f"fallback key mismatch: {key}")
            continue
        try:
            spec = get_service(service_id)
        except KeyError:
            errors.append(f"fallback service not registered: {service_id}")
            continue
        if spec.critical:
            errors.append(f"critical service may not declare degraded fallback: {service_id}")
        if not isinstance(fallback.get("payload"), dict):
            errors.append(f"fallback payload must be an object: {key}")
    return errors
