from __future__ import annotations

import hashlib
import os
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

USER_AGENT = "FPL-iphoenk-engine-v6-fresh-data-platform/3.1 (+read-only acquisition)"
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_AUTH_PATH_MARKERS = ("/signin", "/login", "/auth/login")
_ACCESS_BLOCK_MARKERS = (
    "verify that you're not a robot",
    "javascript is disabled",
    "attention required! | cloudflare",
    "just a moment...",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _redact_url(url: str, secret: str | None, query_key: str | None = None) -> str:
    """Redact credentials without depending on their encoded representation."""
    safe = url
    if query_key:
        parts = urlsplit(safe)
        query = [
            (key, "<redacted>" if key == query_key else value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
        ]
        safe = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    if secret:
        safe = safe.replace(secret, "<redacted>")
    return safe


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


def _json_path(payload: Any, path: str) -> Any:
    current = payload
    for part in str(path).split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        return None
    return current


def _validation_failure(
    *,
    status: str,
    error: str,
    classification: str,
) -> tuple[str, str, str, str]:
    return status, "AMBER", error, classification


def _validate_payload(
    request_cfg: dict[str, Any],
    *,
    requested_url: str,
    final_url: str,
    parsed_json: Any,
    text: str,
    raw_size: int,
) -> tuple[str, str, str | None, str]:
    validation = dict(request_cfg.get("validation") or {})
    lower_text = text.lower()
    lower_final_url = final_url.lower()
    lower_requested_url = requested_url.lower()

    redirect_markers = [
        str(value).lower()
        for value in validation.get("reject_redirect_contains") or _AUTH_PATH_MARKERS
    ]
    if any(marker in lower_final_url for marker in redirect_markers) and not any(
        marker in lower_requested_url for marker in redirect_markers
    ):
        return _validation_failure(
            status="AUTH_REQUIRED",
            error="authentication_required",
            classification="AUTH_REQUIRED",
        )

    if any(marker in lower_text for marker in _ACCESS_BLOCK_MARKERS):
        return _validation_failure(
            status="ACCESS_RESTRICTED",
            error="access_challenge_detected",
            classification="ACCESS_RESTRICTED",
        )

    forbidden = [str(value).lower() for value in validation.get("forbidden_text_any") or []]
    if any(value in lower_text for value in forbidden):
        classification = "AUTH_REQUIRED" if any(
            token in lower_text for token in ("member", "log in", "login", "signin", "sign in")
        ) else "INVALID_PAYLOAD"
        status = "AUTH_REQUIRED" if classification == "AUTH_REQUIRED" else "INVALID_PAYLOAD"
        return _validation_failure(
            status=status,
            error="forbidden_payload_marker",
            classification=classification,
        )

    minimum = int(validation.get("min_body_bytes") or 0)
    if minimum and raw_size < minimum:
        return _validation_failure(
            status="INVALID_PAYLOAD",
            error="payload_too_small",
            classification="INVALID_PAYLOAD",
        )

    required_any = [str(value).lower() for value in validation.get("required_text_any") or []]
    if required_any and not any(value in lower_text for value in required_any):
        return _validation_failure(
            status="INVALID_PAYLOAD",
            error="required_text_missing",
            classification="INVALID_PAYLOAD",
        )

    required_all = [str(value).lower() for value in validation.get("required_text_all") or []]
    if required_all and not all(value in lower_text for value in required_all):
        return _validation_failure(
            status="INVALID_PAYLOAD",
            error="required_text_missing",
            classification="INVALID_PAYLOAD",
        )

    if parsed_json is not None:
        for path in validation.get("required_json_paths") or []:
            value = _json_path(parsed_json, str(path))
            if value is None:
                return _validation_failure(
                    status="INVALID_PAYLOAD",
                    error=f"required_json_path_missing:{path}",
                    classification="INVALID_PAYLOAD",
                )
        for path in validation.get("reject_json_truthy_paths") or []:
            value = _json_path(parsed_json, str(path))
            if value:
                return _validation_failure(
                    status="PROVIDER_REJECTED",
                    error=f"provider_rejected:{path}",
                    classification="PROVIDER_REJECTED",
                )

    return "AVAILABLE", "GREEN", None, "USABLE_DATA"


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
                    "validation_classification": "CONFIG_REQUIRED",
                }

        url = str(request_cfg["url"]).format(
            utc_date=datetime.now(timezone.utc).date().isoformat(),
        )
        params = dict(request_cfg.get("params") or {})
        headers = {
            "Accept": "application/json,text/csv,text/html,application/xhtml+xml,*/*;q=0.8",
        }
        if not request_cfg.get("use_default_user_agent"):
            headers["User-Agent"] = USER_AGENT
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
                "validation_classification": "TRANSPORT_FAILURE",
            }

        checked_at = utc_now()
        query_auth_name = str(auth.get("name")) if auth.get("mode") == "query" and auth.get("name") else None
        safe_url = _redact_url(str(response.url), secret, query_auth_name)

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
                "validation_classification": previous.get("validation_classification") or "REVALIDATED_USABLE_DATA",
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
        validation_error = None
        validation_classification = "TRANSPORT_OK" if status == "AVAILABLE" else "TRANSPORT_FAILURE"

        if status == "AVAILABLE" and expected == "json" and parsed_json is None:
            status = "INVALID_PAYLOAD"
            health = "AMBER"
            validation_error = "expected_json_not_parseable"
            validation_classification = "INVALID_PAYLOAD"

        body = None if parsed_json is not None else text
        truncated = parsed_json is None and len(raw) > len(kept)
        if truncated and status == "AVAILABLE":
            health = "AMBER"
            validation_classification = "TRUNCATED"

        if status == "AVAILABLE":
            status, health, validation_error, validation_classification = _validate_payload(
                request_cfg,
                requested_url=url,
                final_url=str(response.url),
                parsed_json=parsed_json,
                text=text,
                raw_size=len(raw),
            )

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
            "error": validation_error if validation_error is not None else (None if status == "AVAILABLE" else f"http_{response.status_code}"),
            "validation_classification": validation_classification,
        }
