"""Active V6 integration tests for opt-in rotating auth, without real tokens."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.runtime_v6.domains.acquisition.official_fpl_client import (
    OfficialFPLAuthConfigurationError,
    OfficialFPLClient,
    auth_material_from_env,
)


def _clear(monkeypatch):
    for key in (
        "FPL_AUTH_MODE", "FPL_OIDC_CLIENT_ID", "FPL_OIDC_STORE_KEY",
        "FPL_OIDC_CONTRACT_VERIFIED", "FPL_ACCESS_TOKEN", "FPL_SESSION_B64",
    ):
        monkeypatch.delenv(key, raising=False)


def test_rotating_mode_is_never_autodetected_from_secret_presence(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("FPL_AUTH_MODE", "disabled")
    monkeypatch.setenv("FPL_OIDC_STORE_KEY", "example-invalid-only")
    assert auth_material_from_env() is None


def test_owner_client_contract_gate_blocks_before_any_request(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("FPL_AUTH_MODE", "rotating_oidc")
    monkeypatch.setenv("FPL_OIDC_CLIENT_ID", "example-client-id")
    with pytest.raises(OfficialFPLAuthConfigurationError, match="CONTRACT_NOT_VERIFIED"):
        auth_material_from_env()


def test_private_mode_uses_persisted_manager_not_legacy_token(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("FPL_AUTH_MODE", "rotating_oidc")
    monkeypatch.setenv("FPL_OIDC_CLIENT_ID", "example-client-id")
    monkeypatch.setenv("FPL_OIDC_CONTRACT_VERIFIED", "true")
    monkeypatch.setenv("FPL_ACCESS_TOKEN", "stale-legacy-token")
    from src.runtime_v6.domains.acquisition import git_oidc_store, rotating_oidc

    calls = []
    stub = object()
    monkeypatch.setattr(git_oidc_store, "store_from_env", lambda: stub)

    class Manager:
        def __init__(self, **kwargs):
            calls.append(kwargs)
        def get_access_token(self):
            return "new-verified-persistence-token"

    monkeypatch.setattr(rotating_oidc, "RotatingCredentialManager", Manager)
    material = auth_material_from_env()
    assert material is not None
    assert material.headers["X-API-Authorization"] == "Bearer new-verified-persistence-token"
    assert material.headers["X-API-Authorization"] != "Bearer stale-legacy-token"
    assert calls[0]["store"] is stub
    assert calls[0]["client_id"] == "example-client-id"
    assert calls[0]["contract_verified"] is True
    assert calls[0]["permit_nonrotating"] is False


def test_missing_secret_store_reports_only_safe_configuration(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("FPL_AUTH_MODE", "rotating_oidc")
    monkeypatch.setenv("FPL_OIDC_CLIENT_ID", "example-client")
    monkeypatch.setenv("FPL_OIDC_CONTRACT_VERIFIED", "true")
    client = OfficialFPLClient()
    assert client.auth_available is False
    assert client.auth_configuration_state == "INVALID"
    assert "token" not in client.auth_configuration_error.lower()


def test_public_bootstrap_remains_independent_of_private_auth_failure(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("FPL_AUTH_MODE", "rotating_oidc")
    monkeypatch.setenv("FPL_OIDC_CLIENT_ID", "example-client")
    monkeypatch.setenv("FPL_OIDC_CONTRACT_VERIFIED", "true")
    class Session:
        def get(self, url, **kwargs):
            assert "X-API-Authorization" not in kwargs["headers"]
            return SimpleNamespace(
                status_code=200, json=lambda: {"events": [], "elements": [], "teams": []},
                raise_for_status=lambda: None,
            )
    client = OfficialFPLClient(session_factory=Session, retries=1)
    assert client.auth_available is False
    assert client.bootstrap()["status"] == "LIVE"
