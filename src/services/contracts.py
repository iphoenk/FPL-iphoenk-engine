from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.utils import ROOT

MISSING = object()


def value_at(payload: Any, dotted_path: str) -> Any:
    value = payload
    for part in dotted_path.split("."):
        if not isinstance(value, dict) or part not in value:
            return MISSING
        value = value[part]
    return value


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_contract(name: str, spec: dict, root: Path = ROOT) -> dict:
    path = root / str(spec.get("path") or "")
    errors: list[str] = []
    payload: dict = {}
    if not path.is_file():
        errors.append("artifact_missing")
    else:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                errors.append("artifact_not_object")
            else:
                payload = loaded
        except Exception as exc:
            errors.append(f"invalid_json:{type(exc).__name__}")

    minimum = spec.get("min_schema_version")
    if minimum is not None and int(payload.get("schema_version") or 0) < int(minimum):
        errors.append(f"schema_version_below:{minimum}")

    version_field = spec.get("version_field")
    version_prefix = spec.get("version_prefix")
    if version_field and version_prefix and not str(value_at(payload, version_field)).startswith(str(version_prefix)):
        errors.append(f"version_prefix_mismatch:{version_field}")

    for dotted in spec.get("required_paths") or []:
        value = value_at(payload, dotted)
        if value is MISSING or value is None:
            errors.append(f"required_path_missing:{dotted}")

    for dotted, expected in (spec.get("equals") or {}).items():
        if value_at(payload, dotted) != expected:
            errors.append(f"value_mismatch:{dotted}")

    for dotted, minimum_length in (spec.get("min_lengths") or {}).items():
        value = value_at(payload, dotted)
        if not hasattr(value, "__len__") or len(value) < int(minimum_length):
            errors.append(f"length_below:{dotted}:{minimum_length}")

    return {
        "contract": name,
        "path": str(spec.get("path")),
        "valid": not errors,
        "errors": errors,
        "sha256": file_digest(path) if path.is_file() else None,
        "bytes": path.stat().st_size if path.is_file() else None,
    }


def validate_contracts(names: list[str], registry: dict, root: Path = ROOT) -> list[dict]:
    specs = registry.get("contracts") or {}
    results = []
    for name in names:
        if name not in specs:
            results.append({"contract": name, "valid": False, "errors": ["contract_not_registered"]})
        else:
            results.append(validate_contract(name, specs[name], root=root))
    return results
