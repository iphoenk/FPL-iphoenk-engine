from __future__ import annotations

from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/v5_artifact_contract_registry.json"


def _registry() -> dict[str, Any]:
    payload = load_json_config(CONFIG)
    if payload.get("registry") != "V5_ARTIFACT_CONTRACTS_V1":
        raise RuntimeError("invalid V5 artifact contract registry")
    if not isinstance(payload.get("policy"), dict) or not isinstance(payload.get("contracts"), dict):
        raise RuntimeError("V5 artifact contract registry must define policy and contracts")
    return payload


def _matches_type(value: Any, expected: str) -> bool:
    mapping: dict[str, Any] = {
        "object": dict,
        "list": list,
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
    }
    pytype = mapping.get(expected)
    if pytype is None:
        raise RuntimeError(f"unsupported artifact contract type: {expected}")
    if expected in {"number", "integer"} and isinstance(value, bool):
        return False
    return isinstance(value, pytype)


def validate_payload(artifact_name: str, payload: Any) -> dict[str, Any]:
    """Validate one logical V5 JSON artifact before canonical persistence."""
    registry = _registry()
    policy = registry.get("policy") or {}
    if not policy.get("validate_declared_json_before_acceptance", True):
        return {"artifact": artifact_name, "validation": "JSON_VALIDATION_DISABLED"}

    contract = (registry.get("contracts") or {}).get(str(artifact_name))
    if contract is None:
        return {"artifact": artifact_name, "validation": "PARSE_ONLY"}

    root_type = str(contract.get("root_type") or "object")
    if not _matches_type(payload, root_type):
        raise RuntimeError(f"artifact {artifact_name} root must be {root_type}")
    if not isinstance(payload, dict):
        raise RuntimeError(f"artifact {artifact_name} contract requires object root")

    for field in contract.get("required_fields") or []:
        if field not in payload:
            raise RuntimeError(f"artifact {artifact_name} missing required field {field}")
    for field, expected in (contract.get("equals") or {}).items():
        if payload.get(field) != expected:
            raise RuntimeError(
                f"artifact {artifact_name} field {field} mismatch: {payload.get(field)!r} != {expected!r}"
            )
    for field, expected_type in (contract.get("types") or {}).items():
        if field in payload and not _matches_type(payload.get(field), str(expected_type)):
            raise RuntimeError(f"artifact {artifact_name} field {field} must be {expected_type}")

    return {
        "artifact": artifact_name,
        "validation": "CONTRACT_VALID",
        "contract_registry": registry.get("registry"),
    }


def contract_metadata() -> dict[str, Any]:
    registry = _registry()
    return {
        "registry": registry.get("registry"),
        "schema_version": registry.get("schema_version"),
        "owner": registry.get("owner"),
        "declared_contracts": sorted((registry.get("contracts") or {}).keys()),
    }
