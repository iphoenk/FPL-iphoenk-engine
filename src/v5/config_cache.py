from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _project_source_runtime(data: dict[str, Any]) -> dict[str, Any]:
    spec = data.get("source_runtime_projection")
    if not isinstance(spec, dict):
        return data

    registry_path = str(spec.get("registry_path") or data.get("source_registry") or "").strip()
    if not registry_path:
        raise RuntimeError("source runtime projection registry_path missing")
    registry = load_json_config(registry_path)
    rows = registry.get("sources") if isinstance(registry.get("sources"), list) else []
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        source_id = str(row.get("id") or "").strip()
        if not source_id:
            continue
        if source_id in by_id:
            raise RuntimeError(f"duplicate source id in canonical registry: {source_id}")
        by_id[source_id] = row

    runtime_field = str(spec.get("runtime_field") or "ingestion")
    source_ids = [str(value) for value in spec.get("source_ids") or [] if str(value).strip()]
    if not source_ids:
        raise RuntimeError("source runtime projection source_ids missing")

    projected = dict(data)
    for source_id in source_ids:
        source = by_id.get(source_id)
        if source is None:
            raise RuntimeError(f"source runtime projection missing canonical source: {source_id}")
        runtime_raw = source.get(runtime_field)
        if runtime_raw is None:
            runtime_raw = {}
        if not isinstance(runtime_raw, dict):
            raise RuntimeError(f"source runtime projection field must be object: {source_id}.{runtime_field}")
        runtime = dict(runtime_raw)
        runtime["source_id"] = source_id
        runtime["enabled"] = bool(source.get("enabled"))
        runtime["critical"] = bool(source.get("critical"))
        runtime["class"] = source.get("class")
        runtime["tier"] = source.get("tier")
        runtime["adapter"] = source.get("adapter")
        runtime["capabilities"] = list(source.get("capabilities") or [])
        credential_env = source.get("credential_env")
        if credential_env:
            credential_alias = str(spec.get("credential_env_alias") or "credential_env")
            runtime[credential_alias] = str(credential_env)
        projected[source_id] = runtime
    return projected


@lru_cache(maxsize=None)
def load_json_config(relative_path: str) -> dict:
    path = ROOT / relative_path
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise RuntimeError(f"V5 config must be a JSON object: {relative_path}")
    return _project_source_runtime(data)


def clear_config_cache() -> None:
    load_json_config.cache_clear()
