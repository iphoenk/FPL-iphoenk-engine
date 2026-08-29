from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass
from typing import Any

import requests

from src.utils import iso_now
from src.v5.config_cache import load_json_config

POLICY_CONFIG = "config/v5_auth_policy_registry.json"
ENGINE_CONFIG = "config/engine.json"


class AuthConfigurationError(RuntimeError):
    pass


class AuthPolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuthMaterial:
    mode: str
    headers: dict[str, str]


def _policy() -> dict[str, Any]:
    data = load_json_config(POLICY_CONFIG)
    if not isinstance(data.get("resource_policy"), dict) or not isinstance(data.get("routes"), dict):
        raise RuntimeError("invalid V5 authenticated Official policy registry")
    return data


def expected_team_id() -> int:
    identity = _policy()["identity"]
    engine = load_json_config(str(identity["team_id_config"]))
    configured = int(engine[str(identity["team_id_key"])])
    override_name = str(identity.get("team_id_env_override") or "").strip()
    override = os.getenv(override_name, "").strip() if override_name else ""
    return int(override) if override else configured


def allowed_routes() -> dict[str, str]:
    team_id = expected_team_id()
    return {
        str(name): str(template).format(team_id=team_id)
        for name, template in _policy()["routes"].items()
    }


def _transport() -> tuple[str, int, int, float, bool]:
    transport = _policy()["transport"]
    base_env = str(transport["api_base_env"])
    timeout_env = str(transport["timeout_env"])
    base = os.getenv(base_env, str(transport["api_base_default"])).rstrip("/")
    timeout = int(os.getenv(timeout_env, str(transport["timeout_seconds_default"])))
    retries = int(transport["retries_default"])
    backoff = float(transport["backoff_seconds_default"])
    allow_redirects = bool(_policy()["resource_policy"]["allow_redirects"])
    return base, timeout, retries, backoff, allow_redirects


def _decode_session_cookie(value: str) -> str:
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
    except Exception as exc:
        raise AuthConfigurationError("invalid encoded FPL session material") from exc
    if not decoded or "=" not in decoded:
        raise AuthConfigurationError("decoded FPL session material is empty/invalid")
    return decoded


def _refresh_access_token(refresh_token: str, mode_cfg: dict[str, Any]) -> str:
    token_url = os.getenv(str(mode_cfg["token_url_env"]), "").strip()
    client_id = os.getenv(str(mode_cfg["client_id_env"]), "").strip()
    if not token_url or not client_id:
        raise AuthConfigurationError("refresh-token mode is missing token URL or client ID")
    _, timeout, _, _, _ = _transport()
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id}
    client_secret = os.getenv(str(mode_cfg["client_secret_env"]), "").strip()
    if client_secret:
        data["client_secret"] = client_secret
    try:
        response = requests.post(token_url, data=data, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise AuthConfigurationError("OIDC refresh failed") from exc
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not token:
        raise AuthConfigurationError("OIDC refresh response missing access token")
    return str(token)


def _resolve_auth_mode(modes: dict[str, Any]) -> str:
    raw = os.getenv("FPL_AUTH_MODE")
    if raw is not None and raw.strip():
        return raw.strip().lower()

    resolution = _policy().get("mode_resolution") or {}
    if not bool(resolution.get("auto_detect_single_secret_when_mode_unset", False)):
        return "disabled"

    candidates: list[str] = []
    for name, cfg in modes.items():
        if name == "disabled" or not isinstance(cfg, dict):
            continue
        secret_env = str(cfg.get("secret_env") or "").strip()
        if secret_env and os.getenv(secret_env, "").strip():
            candidates.append(str(name))

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1 and bool(resolution.get("ambiguous_multiple_credentials_fail_closed", True)):
        raise AuthConfigurationError("multiple FPL auth credentials are present while FPL_AUTH_MODE is unset")
    return "disabled"


def auth_material_from_env() -> AuthMaterial | None:
    modes = _policy()["auth_modes"]
    mode = _resolve_auth_mode(modes)
    cfg = modes.get(mode)
    if not isinstance(cfg, dict):
        raise AuthConfigurationError(f"unsupported FPL auth mode: {mode}")
    if mode == "disabled":
        return None
    secret = os.getenv(str(cfg["secret_env"]), "").strip()
    if not secret:
        raise AuthConfigurationError(f"missing secret material for auth mode: {mode}")
    if mode == "session_cookie":
        value = _decode_session_cookie(secret)
    elif mode == "refresh_token":
        value = str(cfg.get("prefix", "")) + _refresh_access_token(secret, cfg)
    else:
        value = str(cfg.get("prefix", "")) + secret
    return AuthMaterial(mode=mode, headers={str(cfg["header"]): value})


def safe_get(route_name: str, material: AuthMaterial, *, retries: int | None = None, backoff: float | None = None) -> tuple[Any | None, dict]:
    routes = allowed_routes()
    if route_name not in routes:
        raise AuthPolicyError(f"authenticated route not allowlisted: {route_name}")
    base, timeout, default_retries, default_backoff, allow_redirects = _transport()
    attempts_allowed = int(default_retries if retries is None else retries)
    backoff_seconds = float(default_backoff if backoff is None else backoff)
    url = f"{base}/{routes[route_name].lstrip('/')}"
    start = time.perf_counter()
    status_code = None
    last_error = None
    for attempt in range(1, attempts_allowed + 1):
        try:
            response = requests.get(
                url,
                headers={**material.headers, "Accept": "application/json"},
                timeout=timeout,
                allow_redirects=allow_redirects,
            )
            status_code = response.status_code
            if status_code in (401, 403):
                return None, {
                    "status": "AUTH_REJECTED",
                    "http_status": status_code,
                    "latency_ms": round((time.perf_counter() - start) * 1000),
                    "attempts": attempt,
                    "fetched_at": iso_now(),
                    "error": "authentication rejected",
                    "route": route_name,
                }
            response.raise_for_status()
            return response.json(), {
                "status": "LIVE",
                "http_status": status_code,
                "latency_ms": round((time.perf_counter() - start) * 1000),
                "attempts": attempt,
                "fetched_at": iso_now(),
                "error": None,
                "route": route_name,
            }
        except Exception as exc:
            last_error = type(exc).__name__
            if attempt < attempts_allowed:
                time.sleep(backoff_seconds * attempt)
    return None, {
        "status": "FAILED",
        "http_status": status_code,
        "latency_ms": round((time.perf_counter() - start) * 1000),
        "attempts": attempts_allowed,
        "fetched_at": iso_now(),
        "error": last_error,
        "route": route_name,
    }
