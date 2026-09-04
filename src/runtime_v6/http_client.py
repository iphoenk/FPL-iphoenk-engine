from __future__ import annotations

import hashlib
import os
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import requests

USER_AGENT = "FPL-iphoenk-engine-v6-fresh-data-platform/3.0 (+read-only acquisition)"
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _redact_url(url: str, secret: str | None) -> str:
    if not secret:
        return url
    return url.replace(secret, "<redacted>")


def _retry_delay(response: requests.Response | None, base: float, attempt: int) -> float:
    if response is not None:
        raw = str(response.headers.get("retry-after") or "").strip()
        if raw:
            try:
                return min(5.0, max(0.0, float(raw)))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(raw)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    return min(5.0, max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds()))
                except (TypeError, ValueError, OverflowError):
                    pass
    return min(5.0, base * attempt)


class AcquisitionClient:
    def __init__(self, policy: dict[str, Any]):
        legacy_timeout = float(policy.get("timeout_seconds") or 20)
        self.connect_timeout = max(1.0, float(policy.get("connect_timeout_seconds") or min(5.0, legacy_timeout)))
        self.read_timeout = max(1.0, float(policy.get("read_timeout_seconds") or legacy_timeout))
        self.max_body = int(policy.get("max_body_bytes") or 750000)
        self.retry_attempts = max(1, int(policy.get("retry_attempts") or 1))
        self.retry_backoff = max(0.0, float(policy.get("retry_backoff_seconds") or 0.0))
        self.request_workers = max(1, int(policy.get("request_workers") or 4))
        self.conditional_revalidation = bool(policy.get("conditional_revalidation", True))
        self._local = threading.local()

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            self._local.session = session
        return session

    def fetch(
        self,
        source: dict[str, Any],
        request_cfg: dict[str, Any],
        *,
        previous: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        auth = source.get("auth") or {}
        secret = None
        if auth:
            secret = os.getenv(str(auth.get("env") or ""), "").strip()
            if not secret:
                return {
                    "request_id": request_cfg["id"],
                    "status": "CONFIG_REQUIRED",
                    "health": "AMBER",
                    "url": str(request_cfg["url"]),
                    "checked_at": utc_now(),
                    "auth_env": auth.get("env"),
                    "error": "missing_required_credential",
                    "content_changed": None,
                    "attempt_count": 0,
                }

        url = str(request_cfg["url"])
        params = dict(request_cfg.get("params") or {})
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/csv,text/html,application/xhtml+xml,*/*;q=0.8",
        }
        if auth:
            if auth["mode"] == "query":
                params[str(auth["name"])] = secret
            else:
                headers[str(auth["name"])] = secret
        for key, value in (request_cfg.get("headers") or {}).items():
            headers[str(key)] = str(value)

        if self.conditional_revalidation and previous:
            etag = previous.get("etag")
            last_modified = previous.get("last_modified")
            if etag:
                headers.setdefault("If-None-Match", str(etag))
            if last_modified:
                headers.setdefault("If-Modified-Since", str(last_modified))

        connect_timeout = max(
            1.0,
            float(request_cfg.get("connect_timeout_seconds") or source.get("connect_timeout_seconds") or self.connect_timeout),
        )
        read_timeout = max(
            1.0,
            float(request_cfg.get("read_timeout_seconds") or source.get("read_timeout_seconds") or self.read_timeout),
        )
        max_body = max(
            1,
            int(request_cfg.get("max_body_bytes") or source.get("max_body_bytes") or self.max_body),
        )

        started = time.perf_counter()
        last_error: Exception | None = None
        response: requests.Response | None = None
        attempt_count = 0

        for attempt in range(1, self.retry_attempts + 1):
            attempt_count = attempt
            try:
                response = self._session().get(
                    url,
                    params=params or None,
                    timeout=(connect_timeout, read_timeout),
                    headers=headers,
                    allow_redirects=True,
                )
                if response.status_code in _RETRYABLE_STATUS and attempt < self.retry_attempts:
                    time.sleep(_retry_delay(response, self.retry_backoff, attempt))
                    continue
                break
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.retry_attempts:
                    time.sleep(_retry_delay(None, self.retry_backoff, attempt))

        elapsed = round((time.perf_counter() - started) * 1000.0, 3)
        if response is None:
            return {
                "request_id": request_cfg["id"],
                "status": "UNAVAILABLE",
                "health": "RED" if source.get("critical") else "AMBER",
                "url": url,
                "checked_at": utc_now(),
                "latency_ms": elapsed,
                "attempt_count": attempt_count,
                "error": type(last_error).__name__ if last_error else "RequestException",
                "content_changed": None,
            }

        checked_at = utc_now()
        safe_url = _redact_url(str(response.url), secret)

        if response.status_code == 304 and previous:
            return {
                "request_id": request_cfg["id"],
                "status": "NOT_MODIFIED",
                "health": "GREEN",
                "http_status": 304,
                "url": safe_url,
                "checked_at": checked_at,
                "latency_ms": elapsed,
                "attempt_count": attempt_count,
                "etag": response.headers.get("etag") or previous.get("etag"),
                "last_modified": response.headers.get("last-modified") or previous.get("last_modified"),
                "server_date": response.headers.get("date"),
                "content_changed": False,
                "revalidated": True,
                "error": None,
            }

        raw = response.content
        kept = raw[:max_body]
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

        truncated = parsed_json is None and len(raw) > len(kept)
        if truncated and status == "AVAILABLE":
            health = "AMBER"

        return {
            "request_id": request_cfg["id"],
            "status": status,
            "health": health,
            "http_status": response.status_code,
            "url": safe_url,
            "checked_at": checked_at,
            "latency_ms": elapsed,
            "attempt_count": attempt_count,
            "content_type": content_type,
            "etag": response.headers.get("etag"),
            "last_modified": response.headers.get("last-modified"),
            "server_date": response.headers.get("date"),
            "content_length_bytes": len(raw),
            "stored_bytes": len(kept) if parsed_json is None else len(raw),
            "truncated": truncated,
            "sha256": digest,
            "content_changed": previous is None or previous.get("sha256") != digest,
            "payload_kind": "json" if parsed_json is not None else expected,
            "json": parsed_json,
            "body": body,
            "error": None if status == "AVAILABLE" else f"http_{response.status_code}",
        }
