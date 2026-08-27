from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import requests

from src.settings import API_BACKOFF_SECONDS, API_RETRIES, API_TIMEOUT_SECONDS
from src.sources.registry import source_config
from src.utils import iso_now
from src.version import ENGINE_VERSION


def _base_url() -> str:
    configured = str(source_config("official_fpl").get("api_base") or "").strip().rstrip("/")
    value = str(os.getenv("FPL_API_BASE") or configured).strip().rstrip("/")
    if not value:
        raise RuntimeError("official_fpl api_base missing from source registry")
    return value


TIMEOUT = API_TIMEOUT_SECONDS


def _cache_dir() -> Path | None:
    value = os.getenv("FPL_HTTP_CACHE_DIR")
    if not value:
        return None
    path = Path(value).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_paths(path: str):
    root = _cache_dir()
    if root is None:
        return None, None
    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()
    return root / f"{digest}.json", root / f"{digest}.lock"


def _cache_ttl_seconds() -> float:
    raw = os.getenv("FPL_HTTP_CACHE_TTL_SECONDS")
    if raw in {None, ""}:
        raise RuntimeError("FPL_HTTP_CACHE_TTL_SECONDS is required when shared HTTP cache is enabled")
    value = float(raw)
    if value <= 0:
        raise RuntimeError("FPL_HTTP_CACHE_TTL_SECONDS must be positive")
    return value


def _read_cache(path: str):
    cache_path, _ = _cache_paths(path)
    if cache_path is None or not cache_path.exists():
        return None
    ttl = _cache_ttl_seconds()
    try:
        age = max(0.0, time.time() - cache_path.stat().st_mtime)
        if age > ttl:
            return None
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        health = dict(cached.get("health") or {})
        health.update({"cache_hit": True, "cache_age_ms": round(age * 1000), "latency_ms": 0})
        return cached.get("payload"), health
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _write_cache(path: str, payload, health: dict) -> None:
    cache_path, _ = _cache_paths(path)
    if cache_path is None:
        return
    tmp = cache_path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"path": path, "payload": payload, "health": health}, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, cache_path)


def _acquire_lock(path: str):
    _, lock_path = _cache_paths(path)
    if lock_path is None:
        return None
    try:
        return os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None


def _release_lock(path: str, fd) -> None:
    _, lock_path = _cache_paths(path)
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


def get_json(path: str, retries: int | None = None, backoff: float | None = None):
    retries = API_RETRIES if retries is None else int(retries)
    backoff = API_BACKOFF_SECONDS if backoff is None else float(backoff)
    cached = _read_cache(path)
    if cached is not None:
        return cached

    cache_enabled = _cache_dir() is not None
    lock_fd = _acquire_lock(path) if cache_enabled else None
    if cache_enabled and lock_fd is None:
        wait_until = time.time() + min(5.0, float(TIMEOUT))
        while time.time() < wait_until:
            time.sleep(0.05)
            cached = _read_cache(path)
            if cached is not None:
                return cached
            _, lock_path = _cache_paths(path)
            if lock_path is not None and not lock_path.exists():
                lock_fd = _acquire_lock(path)
                if lock_fd is not None:
                    break

    url = f"{_base_url()}/{path.lstrip('/')}"
    start = time.perf_counter()
    last_error = None
    status_code = None
    headers = {"User-Agent": f"fpl-iphoenk-engine/{ENGINE_VERSION}"}
    try:
        for attempt in range(1, retries + 1):
            try:
                r = requests.get(url, timeout=TIMEOUT, headers=headers)
                status_code = r.status_code
                r.raise_for_status()
                health = {
                    "status": "LIVE",
                    "http_status": status_code,
                    "latency_ms": round((time.perf_counter() - start) * 1000),
                    "attempts": attempt,
                    "fetched_at": iso_now(),
                    "error": None,
                    "url": url,
                    "cache_hit": False,
                }
                payload = r.json()
                _write_cache(path, payload, health)
                return payload, health
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < retries:
                    time.sleep(backoff * attempt)
        return None, {
            "status": "FAILED",
            "http_status": status_code,
            "latency_ms": round((time.perf_counter() - start) * 1000),
            "attempts": retries,
            "fetched_at": iso_now(),
            "error": last_error,
            "url": url,
            "cache_hit": False,
        }
    finally:
        if cache_enabled and lock_fd is not None:
            _release_lock(path, lock_fd)
