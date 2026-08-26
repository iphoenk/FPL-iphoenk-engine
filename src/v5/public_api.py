from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Mapping

import requests

from src.utils import iso_now
from src.v5.config_cache import load_json_config

REGISTRY_CONFIG = "config/v5_public_api_registry.json"
ENGINE_CONFIG = "config/engine.json"


@dataclass(frozen=True)
class FetchSpec:
    route: str
    params: Mapping[str, Any]


def _registry() -> dict[str, Any]:
    data = load_json_config(REGISTRY_CONFIG)
    if not isinstance(data.get("transport"), dict) or not isinstance(data.get("endpoints"), dict):
        raise RuntimeError("invalid V5 public API registry")
    return data


def _transport() -> tuple[str, int, int, float, int, bool]:
    cfg = _registry()["transport"]
    engine = load_json_config(str(cfg.get("retries_config") or ENGINE_CONFIG))
    base = os.getenv(str(cfg["api_base_env"]), str(cfg["api_base_default"])).rstrip("/")
    timeout = int(os.getenv(str(cfg["timeout_env"]), str(cfg["timeout_seconds_default"])))
    retries = int(engine[str(cfg["retries_key"])])
    backoff = float(engine[str(cfg["backoff_key"])])
    workers = int(cfg["parallel_max_workers"])
    allow_redirects = bool(cfg.get("allow_redirects", True))
    return base, timeout, retries, backoff, workers, allow_redirects


def route_path(route: str, **params: Any) -> str:
    template = _registry()["endpoints"].get(route)
    if not isinstance(template, str):
        raise KeyError(f"unknown V5 public API route: {route}")
    try:
        return template.format(**params)
    except KeyError as exc:
        raise ValueError(f"missing parameter for route {route}: {exc.args[0]}") from exc


def _get_path(path: str) -> tuple[Any | None, dict]:
    base, timeout, retries, backoff, _, allow_redirects = _transport()
    url = f"{base}/{path.lstrip('/')}"
    started = time.perf_counter()
    status_code = None
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(
                url,
                timeout=timeout,
                allow_redirects=allow_redirects,
                headers={"Accept": "application/json"},
            )
            status_code = response.status_code
            response.raise_for_status()
            return response.json(), {
                "status": "LIVE",
                "http_status": status_code,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "attempts": attempt,
                "fetched_at": iso_now(),
                "error": None,
                "path": path,
            }
        except Exception as exc:
            last_error = type(exc).__name__
            if attempt < retries:
                time.sleep(backoff * attempt)
    return None, {
        "status": "FAILED",
        "http_status": status_code,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "attempts": retries,
        "fetched_at": iso_now(),
        "error": last_error,
        "path": path,
    }


def get(route: str, **params: Any) -> tuple[Any | None, dict]:
    return _get_path(route_path(route, **params))


def fetch_many(specs: Mapping[str, FetchSpec]) -> tuple[dict[str, Any | None], dict[str, dict]]:
    """Fetch named Official endpoints concurrently, deduplicating identical resolved paths."""
    _, _, _, _, workers, _ = _transport()
    resolved = {name: route_path(spec.route, **dict(spec.params)) for name, spec in specs.items()}
    names_by_path: dict[str, list[str]] = {}
    for name, path in resolved.items():
        names_by_path.setdefault(path, []).append(name)

    unique_results: dict[str, tuple[Any | None, dict]] = {}
    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(names_by_path)))) as pool:
        future_map = {pool.submit(_get_path, path): path for path in names_by_path}
        for future in as_completed(future_map):
            path = future_map[future]
            unique_results[path] = future.result()

    payloads: dict[str, Any | None] = {}
    health: dict[str, dict] = {}
    for path, names in names_by_path.items():
        payload, meta = unique_results[path]
        for name in names:
            payloads[name] = payload
            health[name] = {**meta, "deduplicated": len(names) > 1}
    return payloads, health


def collection_group(name: str) -> tuple[str, ...]:
    groups = _registry().get("collection_groups") or {}
    items = groups.get(name)
    if not isinstance(items, list):
        raise KeyError(f"unknown V5 collection group: {name}")
    return tuple(str(x) for x in items)
