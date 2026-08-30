from __future__ import annotations

import os
import threading
import time
from email.utils import parsedate_to_datetime
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from src.utils import iso_now

BASE_URL = os.getenv("FPL_API_BASE", "https://fantasy.premierleague.com/api")
TIMEOUT = int(os.getenv("FPL_TIMEOUT", "20"))

# Official FPL is the sole volatile Tier-1 acquisition owner. Reusing one
# stateless GET session avoids paying a new TCP/TLS handshake for every endpoint
# in the same point-in-time snapshot wave. The session is created lazily and is
# never mutated after construction, so concurrent reads share only urllib3's
# connection pool.
_SESSION: requests.Session | None = None
_SESSION_LOCK = threading.Lock()

# These endpoints can change during a live match and must not inherit a stale
# intermediary/browser cache representation when the production runner asks for
# the current Official state.
_VOLATILE_PREFIXES = (
    "bootstrap-static/",
    "fixtures/",
    "event-status/",
    "event/",
    "entry/",
)


def _session() -> requests.Session:
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    with _SESSION_LOCK:
        if _SESSION is None:
            session = requests.Session()
            adapter = HTTPAdapter(pool_connections=16, pool_maxsize=16, max_retries=0, pool_block=False)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            session.headers.update({"Connection": "keep-alive", "User-Agent": "FPL-iphoenk-engine/4.9.6"})
            _SESSION = session
    return _SESSION


def _volatile(path: str) -> bool:
    normalized = path.lstrip("/")
    return any(normalized.startswith(prefix) for prefix in _VOLATILE_PREFIXES)


def _cache_age_seconds(response: requests.Response) -> int | None:
    raw_age = response.headers.get("Age")
    if raw_age is not None:
        try:
            return max(0, int(float(raw_age)))
        except (TypeError, ValueError):
            pass
    raw_date = response.headers.get("Date")
    if not raw_date:
        return None
    try:
        server_date = parsedate_to_datetime(raw_date)
        if server_date.tzinfo is None:
            return None
        return max(0, int(time.time() - server_date.timestamp()))
    except (TypeError, ValueError, OverflowError):
        return None


def _retry_delay(response: requests.Response | None, attempt: int, backoff: float) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, min(float(retry_after), 15.0))
            except ValueError:
                pass
    return min(backoff * attempt, 8.0)


def get_json(path: str, retries: int = 3, backoff: float = 0.8):
    url = f"{BASE_URL}/{path.lstrip('/')}"
    start = time.perf_counter()
    last_error = None
    status_code = None
    response: requests.Response | None = None
    volatile = _volatile(path)
    request_headers = {"Accept": "application/json"}
    if volatile:
        request_headers.update({"Cache-Control": "no-cache, no-store, max-age=0", "Pragma": "no-cache"})

    for attempt in range(1, retries + 1):
        try:
            response = _session().get(url, timeout=TIMEOUT, headers=request_headers)
            status_code = response.status_code
            response.raise_for_status()
            payload: Any = response.json()
            return payload, {
                "status": "LIVE",
                "http_status": status_code,
                "latency_ms": round((time.perf_counter() - start) * 1000),
                "attempts": attempt,
                "fetched_at": iso_now(),
                "error": None,
                "url": url,
                "connection_pool_reused": True,
                "volatile_endpoint": volatile,
                "cache_control": request_headers.get("Cache-Control"),
                "response_cache_age_seconds": _cache_age_seconds(response),
            }
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            transient = status_code is None or status_code in {408, 425, 429} or (500 <= status_code <= 599)
            if attempt < retries and transient:
                time.sleep(_retry_delay(response, attempt, backoff))
                continue
            break

    return None, {
        "status": "FAILED",
        "http_status": status_code,
        "latency_ms": round((time.perf_counter() - start) * 1000),
        "attempts": attempt,
        "fetched_at": iso_now(),
        "error": last_error,
        "url": url,
        "connection_pool_reused": True,
        "volatile_endpoint": volatile,
        "cache_control": request_headers.get("Cache-Control"),
        "response_cache_age_seconds": _cache_age_seconds(response) if response is not None else None,
    }
