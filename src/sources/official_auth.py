from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass
from typing import Any

import requests

from src.utils import iso_now

API_BASE = os.getenv("FPL_API_BASE", "https://fantasy.premierleague.com/api").rstrip("/")
TIMEOUT = int(os.getenv("FPL_TIMEOUT", "20"))
EXPECTED_TEAM_ID = int(os.getenv("FPL_TEAM_ID", "3462711"))

ALLOWED_API_PATHS = {
    "me/",
    f"my-team/{EXPECTED_TEAM_ID}/",
    f"entry/{EXPECTED_TEAM_ID}/transfers-latest/",
}


class AuthConfigurationError(RuntimeError):
    pass


class AuthPolicyError(RuntimeError):
    pass


@dataclass
class AuthMaterial:
    mode: str
    headers: dict[str, str]


def _decode_session_cookie(value: str) -> str:
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
    except Exception as exc:
        raise AuthConfigurationError("invalid FPL_SESSION_B64") from exc
    if not decoded or "=" not in decoded:
        raise AuthConfigurationError("decoded FPL session cookie is empty/invalid")
    return decoded


def _refresh_access_token(refresh_token: str) -> str:
    token_url = os.getenv("FPL_OIDC_TOKEN_URL", "").strip()
    client_id = os.getenv("FPL_OIDC_CLIENT_ID", "").strip()
    if not token_url or not client_id:
        raise AuthConfigurationError("refresh_token mode requires FPL_OIDC_TOKEN_URL and FPL_OIDC_CLIENT_ID")

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    client_secret = os.getenv("FPL_OIDC_CLIENT_SECRET", "").strip()
    if client_secret:
        data["client_secret"] = client_secret

    try:
        response = requests.post(token_url, data=data, timeout=TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise AuthConfigurationError("OIDC refresh failed") from exc

    access_token = payload.get("access_token")
    if not access_token:
        raise AuthConfigurationError("OIDC refresh response missing access_token")
    return str(access_token)


def auth_material_from_env() -> AuthMaterial | None:
    mode = os.getenv("FPL_AUTH_MODE", "disabled").strip().lower() or "disabled"
    if mode == "disabled":
        return None

    if mode == "session_cookie":
        encoded = os.getenv("FPL_SESSION_B64", "").strip()
        if not encoded:
            raise AuthConfigurationError("FPL_SESSION_B64 missing")
        cookie = _decode_session_cookie(encoded)
        return AuthMaterial(mode=mode, headers={"Cookie": cookie})

    if mode == "bearer_token":
        token = os.getenv("FPL_ACCESS_TOKEN", "").strip()
        if not token:
            raise AuthConfigurationError("FPL_ACCESS_TOKEN missing")
        return AuthMaterial(mode=mode, headers={"X-API-Authorization": f"Bearer {token}"})

    if mode == "refresh_token":
        refresh_token = os.getenv("FPL_REFRESH_TOKEN", "").strip()
        if not refresh_token:
            raise AuthConfigurationError("FPL_REFRESH_TOKEN missing")
        token = _refresh_access_token(refresh_token)
        return AuthMaterial(mode=mode, headers={"X-API-Authorization": f"Bearer {token}"})

    raise AuthConfigurationError(f"unsupported FPL_AUTH_MODE={mode}")


def _normalise_path(path: str) -> str:
    return path.strip().lstrip("/")


def _health(status: str, http_status: int | None, start: float, attempts: int, url: str, error: str | None) -> dict:
    return {
        "status": status,
        "http_status": http_status,
        "latency_ms": round((time.perf_counter() - start) * 1000),
        "attempts": attempts,
        "fetched_at": iso_now(),
        "error": error,
        "url": url,
    }


def safe_get(path: str, material: AuthMaterial, retries: int = 1, backoff: float = 0.5) -> tuple[Any | None, dict]:
    """GET-only authenticated Official FPL client with an exact route allowlist.

    Redirects are never followed. Any 3xx response is an explicit transport-policy
    rejection rather than a generic HTTP failure, because an authenticated request
    must never forward credentials to an unexpected redirect target.

    Credentials are never returned in health metadata and response bodies/Location
    headers are never included in errors. There is deliberately no generic
    request(method=...) API.
    """
    path = _normalise_path(path)
    if path not in ALLOWED_API_PATHS:
        raise AuthPolicyError(f"authenticated route not allowlisted: {path}")

    url = f"{API_BASE}/{path}"
    start = time.perf_counter()
    status_code = None
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(
                url,
                headers={**material.headers, "Accept": "application/json"},
                timeout=TIMEOUT,
                allow_redirects=False,
            )
            status_code = response.status_code
            if 300 <= status_code < 400:
                return None, _health(
                    "REDIRECT_REJECTED",
                    status_code,
                    start,
                    attempt,
                    url,
                    "authenticated redirect rejected by policy",
                )
            if status_code in (401, 403):
                return None, _health(
                    "AUTH_REJECTED", status_code, start, attempt, url, "authentication rejected"
                )
            response.raise_for_status()
            return response.json(), _health("LIVE", status_code, start, attempt, url, None)
        except Exception as exc:
            last_error = f"{type(exc).__name__}"
            if attempt < retries:
                time.sleep(backoff * attempt)

    return None, _health("FAILED", status_code, start, retries, url, last_error)
