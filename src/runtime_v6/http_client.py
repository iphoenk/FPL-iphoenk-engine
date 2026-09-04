from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timezone
from typing import Any

import requests

USER_AGENT = "FPL-iphoenk-engine-v6-fresh-data-platform/2.0 (+read-only acquisition)"

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def _redact_url(url: str, secret: str | None) -> str:
    if not secret:
        return url
    return url.replace(secret, "<redacted>")

class AcquisitionClient:
    def __init__(self, policy: dict[str, Any]):
        self.timeout = float(policy.get("timeout_seconds") or 25)
        self.max_body = int(policy.get("max_body_bytes") or 750000)
        self.retry_attempts = max(1, int(policy.get("retry_attempts") or 1))
        self.retry_backoff = max(0.0, float(policy.get("retry_backoff_seconds") or 0.0))

    def fetch(self, source: dict[str, Any], request_cfg: dict[str, Any], *, previous_hash: str | None = None) -> dict[str, Any]:
        auth = source.get("auth") or {}
        secret = None
        if auth:
            secret = os.getenv(str(auth.get("env") or ""), "").strip()
            if not secret:
                return {"request_id": request_cfg["id"], "status": "CONFIG_REQUIRED", "health": "AMBER", "url": str(request_cfg["url"]), "checked_at": utc_now(), "auth_env": auth.get("env"), "error": "missing_required_credential", "content_changed": None}
        url = str(request_cfg["url"])
        params = dict(request_cfg.get("params") or {})
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json,text/csv,text/html,application/xhtml+xml,*/*;q=0.8"}
        if auth:
            if auth["mode"] == "query":
                params[str(auth["name"])] = secret
            else:
                headers[str(auth["name"])] = secret
        for key, value in (request_cfg.get("headers") or {}).items():
            headers[str(key)] = str(value)
        started = time.perf_counter()
        last_error: Exception | None = None
        response = None
        for attempt in range(1, self.retry_attempts + 1):
            try:
                response = requests.get(url, params=params or None, timeout=self.timeout, headers=headers, allow_redirects=True)
                if response.status_code >= 500 and attempt < self.retry_attempts:
                    time.sleep(self.retry_backoff * attempt)
                    continue
                break
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.retry_attempts:
                    time.sleep(self.retry_backoff * attempt)
        elapsed = round((time.perf_counter() - started) * 1000.0, 3)
        if response is None:
            return {"request_id": request_cfg["id"], "status": "UNAVAILABLE", "health": "RED" if source.get("critical") else "AMBER", "url": url, "checked_at": utc_now(), "latency_ms": elapsed, "error": type(last_error).__name__ if last_error else "RequestException", "content_changed": None}
        checked_at = utc_now()
        raw = response.content
        kept = raw[: self.max_body]
        digest = sha256_bytes(raw)
        content_type = str(response.headers.get("content-type") or "")
        encoding = response.encoding or "utf-8"
        text = kept.decode(encoding, errors="replace")
        expected = str(request_cfg.get("expect") or "auto").lower()
        parsed_json = None
        if expected == "json" or "json" in content_type.lower():
            try:
                parsed_json = response.json()
            except ValueError:
                parsed_json = None
        status = "AVAILABLE" if 200 <= response.status_code < 400 else "UNAVAILABLE"
        if response.status_code in {401, 403} and auth:
            status = "AUTH_REJECTED"
        health = "GREEN" if status == "AVAILABLE" else ("RED" if source.get("critical") else "AMBER")
        body = None if parsed_json is not None else text
        if expected == "json" and parsed_json is None and status == "AVAILABLE":
            health = "AMBER"
        safe_url = _redact_url(str(response.url), secret)
        return {"request_id": request_cfg["id"], "status": status, "health": health, "http_status": response.status_code, "url": safe_url, "checked_at": checked_at, "latency_ms": elapsed, "content_type": content_type, "etag": response.headers.get("etag"), "last_modified": response.headers.get("last-modified"), "server_date": response.headers.get("date"), "content_length_bytes": len(raw), "stored_bytes": len(kept), "truncated": len(raw) > len(kept), "sha256": digest, "content_changed": previous_hash is None or previous_hash != digest, "payload_kind": "json" if parsed_json is not None else expected, "json": parsed_json, "body": body, "error": None if status == "AVAILABLE" else f"http_{response.status_code}"}
