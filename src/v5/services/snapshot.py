from __future__ import annotations

from collections import OrderedDict
from threading import RLock
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.persistence import persistence_metadata, read_artifact, write_artifact, write_snapshot

MATERIALIZATION_CONFIG = "config/v5_runtime_materialization_registry.json"
_MISS = object()
_cache_lock = RLock()
_cache: OrderedDict[str, Any] = OrderedDict()
_hits = 0
_misses = 0


def _cfg() -> dict[str, Any]:
    data = load_json_config(MATERIALIZATION_CONFIG)
    if not isinstance(data.get("artifacts"), dict) or not isinstance(data.get("governance"), dict):
        raise RuntimeError("invalid V5 runtime materialization registry")
    return data


def _policy(name: str) -> dict[str, Any]:
    cfg = _cfg()
    if not bool(cfg.get("enabled", True)):
        return {}
    row = cfg["artifacts"].get(name)
    return row if isinstance(row, dict) else {}


def _cache_get(name: str) -> Any:
    global _hits, _misses
    policy = _policy(name)
    if not bool(policy.get("serve_from_memory", False)):
        return _MISS
    with _cache_lock:
        if name not in _cache:
            _misses += 1
            return _MISS
        value = _cache.pop(name)
        _cache[name] = value
        _hits += 1
        return value


def _cache_publish(name: str, value: Any) -> None:
    policy = _policy(name)
    if not bool(policy.get("cache_on_write", False)):
        return
    max_entries = max(1, int(_cfg().get("max_entries") or 1))
    with _cache_lock:
        _cache.pop(name, None)
        _cache[name] = value
        while len(_cache) > max_entries:
            _cache.popitem(last=False)


def _materialization_status() -> dict[str, Any]:
    with _cache_lock:
        return {
            "enabled": bool(_cfg().get("enabled", True)),
            "contract": _cfg().get("contract"),
            "entries": len(_cache),
            "keys": list(_cache),
            "hits": int(_hits),
            "misses": int(_misses),
            "durable_store_authoritative": bool((_cfg().get("governance") or {}).get("durable_store_remains_authoritative")),
        }


def reset_materialization_for_tests() -> None:
    global _hits, _misses
    with _cache_lock:
        _cache.clear()
        _hits = 0
        _misses = 0


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation == "metadata":
        return persistence_metadata()
    if operation == "materialization_status":
        return _materialization_status()
    if operation == "read":
        name = str(payload["name"])
        cached = _cache_get(name)
        if cached is not _MISS:
            return cached
        return read_artifact(name, payload.get("default"))
    if operation == "write":
        name = str(payload["name"])
        data = payload.get("data")
        path = write_artifact(name, data)
        _cache_publish(name, data)
        return {"path": str(path), "materialized": name in _cache}
    if operation == "snapshot":
        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, dict):
            raise ValueError("snapshot service requires snapshot object")
        return {key: str(value) for key, value in write_snapshot(snapshot).items()}
    raise KeyError(f"unsupported snapshot operation: {operation}")
