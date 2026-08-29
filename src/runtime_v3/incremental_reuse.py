from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.runtime_v3.artifact_contracts import validate_artifact
from src.utils import DATA, ROOT, atomic_json, read_json

REGISTRY_PATH = ROOT / "config" / "runtime" / "incremental_reuse.json"
STATE_PATH = DATA / "incremental_reuse_state.json"

_VOLATILE_KEYS = {"generated_at", "runtime_architecture"}


def _registry() -> dict[str, Any]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if payload.get("registry") != "V3_INCREMENTAL_REUSE_V1":
        raise RuntimeError("unexpected incremental reuse registry")
    return payload


def _normalize(value: Any, *, top_level: bool = False) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key in sorted(value):
            if key in _VOLATILE_KEYS:
                continue
            if top_level and key in {"endpoint_health"}:
                continue
            out[str(key)] = _normalize(value[key])
        return out
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def _semantic_json(name: str, value: Any) -> Any:
    value = _normalize(value, top_level=True)
    if name == "official_snapshot.json" and isinstance(value, dict):
        return {
            "phase": value.get("phase"),
            "bootstrap": value.get("bootstrap"),
            "fixtures": value.get("fixtures"),
        }
    return value


def _digest_path(name: str) -> str | None:
    path = ROOT / name if name.startswith("config/") else DATA / name
    if not path.is_file():
        return None
    raw = path.read_bytes()
    if path.suffix == ".json":
        try:
            value = json.loads(raw.decode("utf-8"))
            raw = json.dumps(
                _semantic_json(name, value),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        except Exception:
            pass
    return hashlib.sha256(raw).hexdigest()


def fingerprint(service_name: str) -> str | None:
    spec = (_registry().get("services") or {}).get(service_name)
    if not isinstance(spec, dict):
        return None
    rows: list[tuple[str, str]] = []
    for name in spec.get("inputs") or []:
        digest = _digest_path(str(name))
        if digest is None:
            return None
        rows.append((str(name), digest))
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def try_reuse(service_name: str, service_spec: dict[str, Any], profile_name: str) -> dict[str, Any] | None:
    registry = _registry()
    if profile_name not in set((registry.get("policy") or {}).get("enabled_profiles") or []):
        return None
    if service_name not in (registry.get("services") or {}):
        return None
    artifacts = [str(name) for name in service_spec.get("artifacts") or []]
    if not artifacts:
        return None
    paths = [DATA / name for name in artifacts]
    if not all(path.is_file() for path in paths):
        return None
    current = fingerprint(service_name)
    if not current:
        return None
    state = read_json(STATE_PATH, {})
    row = (state.get("services") or {}).get(service_name) if isinstance(state, dict) else None
    if not isinstance(row, dict) or row.get("fingerprint") != current:
        return None
    validations = [validate_artifact(path, name) for path, name in zip(paths, artifacts)]
    return {
        "service": service_name,
        "status": "REUSED",
        "isolated": False,
        "data_dir": str(DATA),
        "elapsed_ms": 0.0,
        "queue_wait_ms": 0.0,
        "seed_input_ms": 0.0,
        "seed_input_bytes": 0,
        "validation_ms": 0.0,
        "promotion_ms": 0.0,
        "promoted_output_bytes": 0,
        "reuse_mode": "CONTENT_ADDRESSED",
        "input_fingerprint": current,
        "artifact_validation": validations,
        "commands": [],
    }


def record(service_name: str, profile_name: str) -> None:
    registry = _registry()
    if profile_name not in set((registry.get("policy") or {}).get("enabled_profiles") or []):
        return
    if service_name not in (registry.get("services") or {}):
        return
    current = fingerprint(service_name)
    if not current:
        return
    state = read_json(STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    state["schema_version"] = 1
    state["registry"] = "V3_INCREMENTAL_REUSE_STATE_V1"
    state.setdefault("services", {})[service_name] = {"fingerprint": current}
    atomic_json(STATE_PATH, state)
