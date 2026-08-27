from __future__ import annotations

from typing import Any

from src.v5.config_cache import load_json_config

PAYLOAD_CONTRACT_CONFIG = "config/v5_payload_contract_registry.json"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _project(value: Any, spec: dict[str, Any]) -> Any:
    kind = str(spec.get("type") or "passthrough").strip().lower()

    if kind == "passthrough":
        return value

    if kind == "object":
        row = _dict(value)
        include = spec.get("include", "*")
        if include == "*":
            result: dict[str, Any] = dict(row)
        elif isinstance(include, list):
            result = {str(key): row[str(key)] for key in include if str(key) in row}
        else:
            raise RuntimeError(f"invalid object projection include: {include!r}")

        fields = spec.get("fields") or {}
        if not isinstance(fields, dict):
            raise RuntimeError("object projection fields must be an object")
        for key, child_spec in fields.items():
            if not isinstance(child_spec, dict):
                raise RuntimeError(f"projection field {key} must be an object")
            if key not in row:
                if bool(child_spec.get("required")):
                    raise RuntimeError(f"required payload projection field missing: {key}")
                result.pop(key, None)
                continue
            result[key] = _project(row[key], child_spec)
        return result

    if kind == "array":
        item_spec = spec.get("item") or {"type": "passthrough"}
        if not isinstance(item_spec, dict):
            raise RuntimeError("array projection item must be an object")
        return [_project(item, item_spec) for item in _list(value)]

    raise RuntimeError(f"unsupported payload projection type: {kind}")


def _registry() -> dict[str, Any]:
    cfg = load_json_config(PAYLOAD_CONTRACT_CONFIG)
    if not isinstance(cfg, dict):
        raise RuntimeError("V5 payload contract registry must be an object")
    return cfg


def compact_payload(service_id: str, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Apply the registry-selected network projection for a service operation.

    Projection mechanics are generic. Service/operation knowledge lives only in
    config/v5_payload_contract_registry.json. Unknown operations follow the
    registry default, preserving compatibility without hardcoded branches.
    """
    cfg = _registry()
    contracts = cfg.get("contracts") or {}
    if not isinstance(contracts, dict):
        raise RuntimeError("V5 payload contract registry contracts must be an object")

    key = f"{service_id}.{operation}"
    contract = contracts.get(key)
    if contract is None:
        action = str((cfg.get("defaults") or {}).get("unknown_contract_action") or "PASSTHROUGH").upper()
        if action == "PASSTHROUGH":
            return payload
        raise RuntimeError(f"no V5 payload projection contract registered for {key}")

    if not isinstance(contract, dict):
        raise RuntimeError(f"invalid V5 payload projection contract for {key}")
    projection = contract.get("projection")
    if not isinstance(projection, dict):
        raise RuntimeError(f"V5 payload projection contract missing projection for {key}")

    projected = _project(payload, projection)
    if not isinstance(projected, dict):
        raise RuntimeError(f"V5 payload projection root must remain an object for {key}")
    return projected
