from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import requests

API_BASE = "https://fantasy.premierleague.com/api"
AUTHENTICATED_ROUTE_NAMES = frozenset({"me", "my_team"})


class OfficialFPLClientError(RuntimeError):
    pass


class OfficialFPLAuthConfigurationError(OfficialFPLClientError):
    pass


@dataclass(frozen=True)
class AuthMaterial:
    mode: str
    headers: dict[str, str]
    secret_values: tuple[str, ...]


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def auth_material_from_env() -> AuthMaterial | None:
    mode = (os.getenv("FPL_AUTH_MODE") or "disabled").strip().lower() or "disabled"
    if mode == "disabled":
        return None
    if mode == "session_cookie":
        encoded = (os.getenv("FPL_SESSION_B64") or "").strip()
        if not encoded:
            raise OfficialFPLAuthConfigurationError("FPL_SESSION_B64 missing")
        try:
            cookie = base64.b64decode(encoded, validate=True).decode("utf-8")
        except Exception as exc:
            raise OfficialFPLAuthConfigurationError("invalid FPL_SESSION_B64") from exc
        if not cookie or "=" not in cookie:
            raise OfficialFPLAuthConfigurationError("decoded FPL session cookie invalid")
        return AuthMaterial("session_cookie", {"Cookie": cookie}, (encoded, cookie))
    if mode == "bearer_token":
        token = (os.getenv("FPL_ACCESS_TOKEN") or "").strip()
        if not token:
            raise OfficialFPLAuthConfigurationError("FPL_ACCESS_TOKEN missing")
        return AuthMaterial(
            "bearer_token",
            {"X-API-Authorization": f"Bearer {token}"},
            (token, f"Bearer {token}"),
        )
    raise OfficialFPLAuthConfigurationError(f"unsupported FPL_AUTH_MODE={mode}")


class OfficialFPLClient:
    """V6-only Official FPL HTTP client shared by public and personal/league domains."""

    def __init__(
        self,
        *,
        base_url: str = API_BASE,
        timeout_seconds: float = 15.0,
        retries: int = 2,
        backoff_seconds: float = 0.4,
        session_factory: Callable[[], requests.Session] = requests.Session,
        auth_material: AuthMaterial | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.retries = max(1, retries)
        self.backoff_seconds = max(0.0, backoff_seconds)
        self.session_factory = session_factory
        self.auth_configuration_error: str | None = None
        if auth_material is not None:
            self.auth_material = auth_material
        else:
            try:
                self.auth_material = auth_material_from_env()
            except OfficialFPLAuthConfigurationError as exc:
                self.auth_material = None
                self.auth_configuration_error = type(exc).__name__
        self._local = threading.local()
        self._lock = threading.Lock()
        self._request_count = 0
        self._failed_requests = 0
        self._active_requests = 0
        self._max_concurrency = 0

    @property
    def auth_available(self) -> bool:
        return self.auth_material is not None

    @property
    def auth_configuration_state(self) -> str:
        if self.auth_material is not None:
            return "CONFIGURED"
        if self.auth_configuration_error:
            return "INVALID"
        return "UNAVAILABLE"

    @property
    def secret_values(self) -> tuple[str, ...]:
        if self.auth_material is None:
            return ()
        return self.auth_material.secret_values

    def telemetry(self) -> dict[str, int]:
        with self._lock:
            return {
                "request_count": self._request_count,
                "failed_requests": self._failed_requests,
                "maximum_concurrency_used": self._max_concurrency,
            }

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = self.session_factory()
            self._local.session = session
        return session

    def _request(
        self,
        endpoint_class: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        authenticated: bool = False,
    ) -> dict[str, Any]:
        if authenticated and endpoint_class not in AUTHENTICATED_ROUTE_NAMES:
            raise OfficialFPLClientError("authenticated endpoint class not allowlisted")
        if authenticated and self.auth_material is None:
            return {
                "status": "AUTH_UNAVAILABLE",
                "endpoint_class": endpoint_class,
                "checked_at": _iso_now(),
                "http_status": None,
                "payload_digest": None,
                "payload": None,
                "attempts": 0,
                "duration_ms": 0,
                "error": None,
            }

        path = path.strip().lstrip("/")
        url = f"{self.base_url}/{path}"
        headers = {"Accept": "application/json"}
        allow_redirects = True
        if authenticated:
            headers.update(self.auth_material.headers)
            allow_redirects = False

        started = time.perf_counter()
        status_code: int | None = None
        last_error: str | None = None
        payload: Any = None
        attempts = 0
        final_status = "FAILED"

        with self._lock:
            self._request_count += 1
            self._active_requests += 1
            self._max_concurrency = max(self._max_concurrency, self._active_requests)
        try:
            for attempt in range(1, self.retries + 1):
                attempts = attempt
                try:
                    response = self._session().get(
                        url,
                        params=params,
                        headers=headers,
                        timeout=self.timeout_seconds,
                        allow_redirects=allow_redirects,
                    )
                    status_code = int(response.status_code)
                    if authenticated and 300 <= status_code < 400:
                        final_status = "REDIRECT_REJECTED"
                        last_error = "authenticated_redirect_rejected"
                        break
                    if authenticated and status_code in (401, 403):
                        final_status = "AUTH_REJECTED"
                        last_error = "authentication_rejected"
                        break
                    if status_code == 404:
                        final_status = "NOT_FOUND"
                        last_error = None
                        break
                    response.raise_for_status()
                    payload = response.json()
                    final_status = "LIVE"
                    last_error = None
                    break
                except Exception as exc:
                    last_error = type(exc).__name__
                    if attempt < self.retries:
                        time.sleep(self.backoff_seconds * attempt)
            if final_status != "LIVE":
                with self._lock:
                    self._failed_requests += 1
        finally:
            with self._lock:
                self._active_requests -= 1

        duration_ms = round((time.perf_counter() - started) * 1000)
        return {
            "status": final_status,
            "endpoint_class": endpoint_class,
            "checked_at": _iso_now(),
            "http_status": status_code,
            "payload_digest": _digest(payload) if final_status == "LIVE" else None,
            "payload": payload if final_status == "LIVE" else None,
            "attempts": attempts,
            "duration_ms": duration_ms,
            "error": last_error,
        }

    def bootstrap(self) -> dict[str, Any]:
        return self._request("bootstrap_static", "bootstrap-static/")

    def entry(self, entry_id: int) -> dict[str, Any]:
        return self._request("entry", f"entry/{int(entry_id)}/")

    def submitted_picks(self, entry_id: int, gw: int) -> dict[str, Any]:
        return self._request("submitted_picks", f"entry/{int(entry_id)}/event/{int(gw)}/picks/")

    def classic_standings(self, league_id: int, page: int) -> dict[str, Any]:
        return self._request(
            "classic_standings",
            f"leagues-classic/{int(league_id)}/standings/",
            params={"page_standings": int(page)},
        )

    def h2h_standings(self, league_id: int, page: int) -> dict[str, Any]:
        return self._request(
            "h2h_standings",
            f"leagues-h2h/{int(league_id)}/standings/",
            params={"page_standings": int(page)},
        )

    def event_live(self, gw: int) -> dict[str, Any]:
        return self._request("event_live", f"event/{int(gw)}/live/")

    def me(self) -> dict[str, Any]:
        return self._request("me", "me/", authenticated=True)

    def my_team(self, entry_id: int) -> dict[str, Any]:
        return self._request("my_team", f"my-team/{int(entry_id)}/", authenticated=True)
