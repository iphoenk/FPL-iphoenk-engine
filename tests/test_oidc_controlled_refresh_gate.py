"""One-time owner-authorized refresh: guardrails, no real credential."""
from pathlib import Path

import pytest

from src.runtime_v6.domains.acquisition.official_fpl_client import (
    OfficialFPLAuthConfigurationError,
    auth_material_from_env,
)


def _set_environ(monkeypatch):
    for name in (
        "FPL_AUTH_MODE", "FPL_OIDC_CLIENT_ID", "FPL_OIDC_CONTRACT_VERIFIED",
        "FPL_OIDC_OWNER_CONTROLLED_GRANT", "FPL_ACCESS_TOKEN", "FPL_SESSION_B64",
    ):
        monkeypatch.delenv(name, raising=False)


def test_controlled_probe_requires_both_explicit_mode_and_owner_grant(monkeypatch):
    _set_environ(monkeypatch)
    monkeypatch.setenv("FPL_OIDC_OWNER_CONTROLLED_GRANT", "true")
    assert auth_material_from_env() is None
    monkeypatch.setenv("FPL_AUTH_MODE", "rotating_oidc")
    monkeypatch.setenv("FPL_OIDC_CLIENT_ID", "dummy-public-client-id")
    from src.runtime_v6.domains.acquisition import git_oidc_store, rotating_oidc
    monkeypatch.setattr(git_oidc_store, "store_from_env", lambda: object())

    class Manager:
        def __init__(self, **kwargs):
            assert kwargs["contract_verified"]
            assert not kwargs["permit_nonrotating"]
        def get_access_token(self):
            return "dummy-access-token"

    monkeypatch.setattr(rotating_oidc, "RotatingCredentialManager", Manager)
    material = auth_material_from_env()
    assert material.headers["X-API-Authorization"] == "Bearer dummy-access-token"


def test_no_implicit_first_grant_without_owner_approval(monkeypatch):
    _set_environ(monkeypatch)
    monkeypatch.setenv("FPL_AUTH_MODE", "rotating_oidc")
    monkeypatch.setenv("FPL_OIDC_CLIENT_ID", "dummy-public-client-id")
    with pytest.raises(OfficialFPLAuthConfigurationError, match="CONTRACT_NOT_VERIFIED"):
        auth_material_from_env()


def test_workflow_has_owner_only_nonrecurring_opt_in():
    flow = Path(".github/workflows/v6-auth-probe.yml").read_text()
    assert "auth_attempt:" in flow
    assert "CONTROLLED_ONCE" in flow
    assert "github.actor == github.repository_owner" in flow
    assert "FPL_OIDC_OWNER_CONTROLLED_GRANT:" in flow
    assert "github.event_name == 'workflow_dispatch'" in flow
    assert "environment: v12-private-reports-publisher" in flow
    assert "FPL_OIDC_STORE_KEY: ${{ secrets.FPL_OIDC_STORE_KEY }}" in flow
    assert "FPL_OIDC_CLIENT_ID: ${{ vars.FPL_OIDC_CLIENT_ID }}" in flow
    assert "cron:" not in flow
    assert "schedule:" not in flow
