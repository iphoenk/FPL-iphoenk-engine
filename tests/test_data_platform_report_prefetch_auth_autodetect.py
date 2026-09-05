from __future__ import annotations

import base64

import pytest

from src.runtime_v6.official_fpl_client import (
    OfficialFPLAuthConfigurationError,
    auth_material_from_env,
)


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("FPL_AUTH_MODE", "FPL_SESSION_B64", "FPL_ACCESS_TOKEN"):
        monkeypatch.delenv(key, raising=False)


def test_disabled_without_credentials_stays_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("FPL_AUTH_MODE", "disabled")
    assert auth_material_from_env() is None


def test_disabled_fallback_auto_promotes_single_session_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    encoded = base64.b64encode(b"sessionid=abc123").decode("ascii")
    monkeypatch.setenv("FPL_AUTH_MODE", "disabled")
    monkeypatch.setenv("FPL_SESSION_B64", encoded)
    material = auth_material_from_env()
    assert material is not None
    assert material.mode == "session_cookie"
    assert material.headers == {"Cookie": "sessionid=abc123"}
    assert encoded in material.secret_values


def test_disabled_fallback_auto_promotes_single_bearer_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("FPL_AUTH_MODE", "disabled")
    monkeypatch.setenv("FPL_ACCESS_TOKEN", "token-abc")
    material = auth_material_from_env()
    assert material is not None
    assert material.mode == "bearer_token"
    assert material.headers == {"X-API-Authorization": "Bearer token-abc"}


def test_multiple_credentials_fail_closed_without_explicit_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("FPL_AUTH_MODE", "disabled")
    monkeypatch.setenv("FPL_SESSION_B64", base64.b64encode(b"sessionid=abc123").decode("ascii"))
    monkeypatch.setenv("FPL_ACCESS_TOKEN", "token-abc")
    with pytest.raises(OfficialFPLAuthConfigurationError):
        auth_material_from_env()


def test_explicit_mode_resolves_ambiguity(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    encoded = base64.b64encode(b"sessionid=abc123").decode("ascii")
    monkeypatch.setenv("FPL_AUTH_MODE", "session_cookie")
    monkeypatch.setenv("FPL_SESSION_B64", encoded)
    monkeypatch.setenv("FPL_ACCESS_TOKEN", "token-abc")
    material = auth_material_from_env()
    assert material is not None
    assert material.mode == "session_cookie"


def test_explicit_off_is_hard_disable_even_when_secret_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("FPL_AUTH_MODE", "off")
    monkeypatch.setenv("FPL_SESSION_B64", base64.b64encode(b"sessionid=abc123").decode("ascii"))
    assert auth_material_from_env() is None
