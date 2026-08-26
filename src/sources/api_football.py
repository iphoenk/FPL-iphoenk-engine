from __future__ import annotations

import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.sources.base import SourceResult, SourceSpec


def probe(spec: SourceSpec, timeout_seconds: float = 2.5) -> SourceResult:
    env_name = str(spec.config.get("requires_env") or "API_FOOTBALL_KEY")
    key = os.getenv(env_name)
    if not key:
        return SourceResult(
            spec.source_id,
            "CONFIG_REQUIRED",
            False,
            None,
            0,
            {c: "CONFIG_REQUIRED" for c in spec.capabilities},
            {
                "missing_env": env_name,
                "credential_exposed": False,
                "decision_blocking": False,
                "note": "Optional quota-limited enrichment remains disabled until a key is configured.",
            },
        )

    base_url = str(spec.config.get("base_url") or "https://v3.football.api-sports.io").rstrip("/")
    url = f"{base_url}/status?{urlencode({})}"
    request = Request(url, headers={"x-apisports-key": key, "Accept": "application/json", "User-Agent": "FPL-iphoenk-engine/3.16"}, method="GET")
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status_code = int(getattr(response, "status", 200))
            raw = response.read(32768)
        elapsed = round((time.perf_counter() - started) * 1000.0, 3)
        payload = json.loads(raw.decode("utf-8", errors="ignore") or "{}")
        reachable = 200 <= status_code < 300 and not payload.get("errors")
        capabilities = {c: ("SOURCE_REACHABLE_NOT_INGESTED" if reachable else "UNAVAILABLE") for c in spec.capabilities}
        return SourceResult(
            spec.source_id,
            "LIVE" if reachable else "DEGRADED",
            reachable,
            elapsed,
            0,
            capabilities,
            {
                "http_status": status_code,
                "credential_exposed": False,
                "probe_only": True,
                "data_values_ingested": False,
                "quota_strategy": (spec.config.get("quota") or {}).get("strategy"),
                "competition_id_policy": "resolve via /leagues search at runtime; never hardcode from memory",
            },
        )
    except HTTPError as exc:
        elapsed = round((time.perf_counter() - started) * 1000.0, 3)
        return SourceResult(spec.source_id, "UNAVAILABLE", False, elapsed, 0, {c: "UNAVAILABLE" for c in spec.capabilities}, {"http_status": int(exc.code), "credential_exposed": False, "error": "HTTPError"})
    except (URLError, TimeoutError, OSError, ValueError):
        elapsed = round((time.perf_counter() - started) * 1000.0, 3)
        return SourceResult(spec.source_id, "UNAVAILABLE", False, elapsed, 0, {c: "UNAVAILABLE" for c in spec.capabilities}, {"credential_exposed": False, "error": "network_or_parse_error"})
