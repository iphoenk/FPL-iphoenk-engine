from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from src.utils import ROOT, _loads

MISSING = object()


def value_at(payload: Any, dotted_path: str) -> Any:
    value = payload
    for part in dotted_path.split("."):
        if not isinstance(value, dict) or part not in value:
            return MISSING
        value = value[part]
    return value


def file_digest(path: Path) -> str:
    """SHA-256 a file with a large-buffer fallback for older runtimes."""
    with path.open("rb") as handle:
        if hasattr(hashlib, "file_digest"):
            return hashlib.file_digest(handle, "sha256").hexdigest()
        digest = hashlib.sha256()
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        return digest.hexdigest()


def validate_contract(name: str, spec: dict, root: Path = ROOT) -> dict:
    path = root / str(spec.get("path") or "")
    errors: list[str] = []
    payload: dict = {}
    artifact_sha = None
    artifact_bytes = None
    if not path.is_file():
        errors.append("artifact_missing")
    else:
        try:
            # Contract validation previously read large artifacts twice and used
            # stdlib JSON even when the runtime fast codec was available. Read
            # once, hash the exact bytes, then parse those same bytes. This does
            # not alter the artifact or contract semantics.
            raw = path.read_bytes()
            artifact_bytes = len(raw)
            artifact_sha = hashlib.sha256(raw).hexdigest()
            loaded = _loads(raw)
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
        "sha256": artifact_sha,
        "bytes": artifact_bytes,
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
