from __future__ import annotations

import os
import threading
import time
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


def get_json(path: str, retries: int = 3, backoff: float = 0.8):
    url = f"{BASE_URL}/{path.lstrip('/')}"
    start = time.perf_counter()
    last_error = None
    status_code = None
    for attempt in range(1, retries + 1):
        try:
            response = _session().get(url, timeout=TIMEOUT)
            status_code = response.status_code
            response.raise_for_status()
            return response.json(), {
                "status": "LIVE",
                "http_status": status_code,
                "latency_ms": round((time.perf_counter() - start) * 1000),
                "attempts": attempt,
                "fetched_at": iso_now(),
                "error": None,
                "url": url,
                "connection_pool_reused": True,
            }
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
        "connection_pool_reused": True,
    }
