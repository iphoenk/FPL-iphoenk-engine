
from __future__ import annotations
import time, os, requests
from typing import Any
from src.utils import iso_now

BASE_URL = os.getenv("FPL_API_BASE", "https://fantasy.premierleague.com/api")
TIMEOUT = int(os.getenv("FPL_TIMEOUT", "20"))

def get_json(path: str, retries: int = 3, backoff: float = 0.8):
    url = f"{BASE_URL}/{path.lstrip('/')}"
    start = time.perf_counter()
    last_error = None
    status_code = None
    for attempt in range(1, retries+1):
        try:
            r = requests.get(url, timeout=TIMEOUT)
            status_code = r.status_code
            r.raise_for_status()
            return r.json(), {
                "status":"LIVE","http_status":status_code,
                "latency_ms":round((time.perf_counter()-start)*1000),
                "attempts":attempt,"fetched_at":iso_now(),"error":None,"url":url
            }
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(backoff*attempt)
    return None, {
        "status":"FAILED","http_status":status_code,
        "latency_ms":round((time.perf_counter()-start)*1000),
        "attempts":retries,"fetched_at":iso_now(),"error":last_error,"url":url
    }
