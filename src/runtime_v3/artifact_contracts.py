from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.utils import ROOT

CONFIG_PATH = ROOT / "config" / "runtime" / "artifact_contracts.json"
EXPECTED_REGISTRY = "RUNTIME_ARTIFACT_CONTRACTS_V2"


@lru_cache(maxsize=1)
def load_registry() -> dict[str, Any]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if payload.get("registry") != EXPECTED_REGISTRY:
        raise RuntimeError(f"invalid runtime artifact contract registry: {payload.get('registry')} != {EXPECTED_REGISTRY}")
    if not isinstance(payload.get("policy"), dict) or not isinstance(payload.get("contracts"), dict):
        raise RuntimeError("runtime artifact contract registry must define policy and contracts")
    return payload


def _strict_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"malformed JSON artifact {path.name}: {type(exc).__name__}: {exc}") from exc


def _matches_type(value: Any, expected: str) -> bool:
    mapping = {
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


def validate_artifact(path: Path, artifact_name: str) -> dict[str, Any]:
    """Validate one service output before it is accepted into canonical runtime state."""
    if not path.exists() or not path.is_file():
        raise RuntimeError(f"required artifact missing: {artifact_name}")

    registry = load_registry()
    policy = registry.get("policy") or {}
    contract = (registry.get("contracts") or {}).get(artifact_name) or (registry.get("contracts") or {}).get(path.name)

    if path.suffix.lower() != ".json":
        return {"artifact": artifact_name, "validation": "EXISTS_ONLY"}
    if not policy.get("validate_declared_json_before_acceptance", True):
        return {"artifact": artifact_name, "validation": "JSON_VALIDATION_DISABLED"}

    payload = _strict_json(path)
    if not contract:
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
            raise RuntimeError(f"artifact {artifact_name} field {field} mismatch: {payload.get(field)!r} != {expected!r}")
    for field, expected_type in (contract.get("types") or {}).items():
        if field in payload and not _matches_type(payload.get(field), str(expected_type)):
            raise RuntimeError(f"artifact {artifact_name} field {field} must be {expected_type}")

    return {"artifact": artifact_name, "validation": "CONTRACT_VALID", "contract_registry": registry.get("registry")}


def validate_latest_sidecar(path: Path) -> dict[str, Any] | None:
    registry = load_registry()
    if not (registry.get("policy") or {}).get("validate_latest_sidecar_when_present", True):
        return None
    if not path.exists():
        return None
    payload = _strict_json(path)
    if not isinstance(payload, dict):
        raise RuntimeError("latest.json sidecar must be a JSON object")
    return {"artifact": "latest.json", "validation": "PARSE_ONLY"}
