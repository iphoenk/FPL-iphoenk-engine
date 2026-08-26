from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import requests

from src.utils import iso_now
from src.v5.config_cache import ROOT, load_json_config

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


def _cache_cfg() -> dict[str, Any]:
    raw = _registry().get("cache")
    return raw if isinstance(raw, dict) else {}


def _cache_root() -> Path | None:
    cfg = _cache_cfg()
    if not bool(cfg.get("enabled", False)):
        return None
    value = os.getenv(str(cfg.get("directory_env") or ""), str(cfg.get("directory_default") or "")).strip()
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _cache_ttl(route: str | None) -> float:
    cfg = _cache_cfg()
    route_ttls = cfg.get("route_ttl_seconds") if isinstance(cfg.get("route_ttl_seconds"), dict) else {}
    value = route_ttls.get(str(route)) if route is not None else None
    if value is None:
        value = cfg.get("default_ttl_seconds", 0)
    return max(0.0, float(value))


def _cache_paths(base: str, path: str) -> tuple[Path | None, Path | None]:
    root = _cache_root()
    if root is None:
        return None, None
    digest = hashlib.sha256(f"{base}|{path}".encode("utf-8")).hexdigest()
    return root / f"{digest}.json", root / f"{digest}.lock"


def _read_cache(base: str, path: str, route: str | None) -> tuple[Any, dict[str, Any]] | None:
    cache_path, _ = _cache_paths(base, path)
    if cache_path is None or not cache_path.exists():
        return None
    ttl = _cache_ttl(route)
    if ttl <= 0:
        return None
    try:
        age = max(0.0, time.time() - cache_path.stat().st_mtime)
        if age > ttl:
            return None
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        health = dict(cached.get("health") or {})
        health.update(
            {
                "cache_hit": True,
                "cache_age_ms": round(age * 1000.0, 3),
                "cache_ttl_seconds": ttl,
                "latency_ms": 0,
                "path": path,
            }
        )
        return cached.get("payload"), health
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _write_cache(base: str, path: str, route: str | None, payload: Any, health: dict[str, Any]) -> None:
    cache_path, _ = _cache_paths(base, path)
    if cache_path is None or _cache_ttl(route) <= 0:
        return
    tmp = cache_path.with_suffix(f".{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps({"base": base, "path": path, "route": route, "payload": payload, "health": health}, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, cache_path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _singleflight_cfg() -> dict[str, Any]:
    raw = _cache_cfg().get("singleflight")
    return raw if isinstance(raw, dict) else {}


def _recover_stale_lock(lock_path: Path) -> None:
    cfg = _singleflight_cfg()
    stale_after = max(0.0, float(cfg.get("stale_lock_seconds", 0)))
    if stale_after <= 0:
        return
    try:
        age = max(0.0, time.time() - lock_path.stat().st_mtime)
        if age >= stale_after:
            lock_path.unlink()
    except FileNotFoundError:
        return


def _acquire_lock(base: str, path: str) -> int | None:
    cfg = _singleflight_cfg()
    if not bool(cfg.get("enabled", False)):
        return None
    _, lock_path = _cache_paths(base, path)
    if lock_path is None:
        return None
    _recover_stale_lock(lock_path)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, f"pid={os.getpid()} created={time.time()}".encode("utf-8"))
        return fd
    except FileExistsError:
        return None


def _release_lock(base: str, path: str, fd: int | None) -> None:
    _, lock_path = _cache_paths(base, path)
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass
    if lock_path is not None:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def route_path(route: str, **params: Any) -> str:
    template = _registry()["endpoints"].get(route)
    if not isinstance(template, str):
        raise KeyError(f"unknown V5 public API route: {route}")
    try:
        return template.format(**params)
    except KeyError as exc:
        raise ValueError(f"missing parameter for route {route}: {exc.args[0]}") from exc


def _get_path(path: str, *, route: str | None = None) -> tuple[Any | None, dict]:
    base, timeout, retries, backoff, _, allow_redirects = _transport()
    cached = _read_cache(base, path, route)
    if cached is not None:
        return cached

    cache_enabled = _cache_root() is not None and _cache_ttl(route) > 0
    singleflight = cache_enabled and bool(_singleflight_cfg().get("enabled", False))
    lock_fd = _acquire_lock(base, path) if singleflight else None
    wait_started = time.perf_counter()
    lock_contended = bool(singleflight and lock_fd is None)
    if lock_contended:
        wait_seconds = max(0.0, float(_singleflight_cfg().get("wait_seconds", 0)))
        poll_seconds = max(0.001, float(_singleflight_cfg().get("poll_ms", 50)) / 1000.0)
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            time.sleep(poll_seconds)
            cached = _read_cache(base, path, route)
            if cached is not None:
                payload, health = cached
                health["singleflight_contended"] = True
                health["singleflight_wait_ms"] = round((time.perf_counter() - wait_started) * 1000.0, 3)
                return payload, health
            _, lock_path = _cache_paths(base, path)
            if lock_path is not None:
                _recover_stale_lock(lock_path)
                if not lock_path.exists():
                    lock_fd = _acquire_lock(base, path)
                    if lock_fd is not None:
                        break

    url = f"{base}/{path.lstrip('/')}"
    started = time.perf_counter()
    last_error = None
    status_code = None
    try:
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
                health = {
                    "status": "LIVE",
                    "http_status": status_code,
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                    "attempts": attempt,
                    "fetched_at": iso_now(),
                    "error": None,
                    "path": path,
                    "cache_hit": False,
                    "cache_ttl_seconds": _cache_ttl(route),
                    "singleflight_contended": lock_contended,
                    "singleflight_wait_ms": round((started - wait_started) * 1000.0, 3) if lock_contended else 0.0,
                }
                payload = response.json()
                _write_cache(base, path, route, payload, health)
                return payload, health
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
            "cache_hit": False,
            "cache_ttl_seconds": _cache_ttl(route),
            "singleflight_contended": lock_contended,
        }
    finally:
        if lock_fd is not None:
            _release_lock(base, path, lock_fd)


def get(route: str, **params: Any) -> tuple[Any | None, dict]:
    return _get_path(route_path(route, **params), route=route)


def fetch_many(specs: Mapping[str, FetchSpec]) -> tuple[dict[str, Any | None], dict[str, dict]]:
    """Fetch Official endpoints concurrently, deduplicating paths and sharing cross-run cache."""
    _, _, _, _, workers, _ = _transport()
    resolved = {name: route_path(spec.route, **dict(spec.params)) for name, spec in specs.items()}
    names_by_path: dict[str, list[str]] = {}
    route_by_path: dict[str, str] = {}
    for name, path in resolved.items():
        names_by_path.setdefault(path, []).append(name)
        route_by_path.setdefault(path, str(specs[name].route))

    unique_results: dict[str, tuple[Any | None, dict]] = {}
    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(names_by_path)))) as pool:
        future_map = {
            pool.submit(_get_path, path, route=route_by_path[path]): path
            for path in names_by_path
        }
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
