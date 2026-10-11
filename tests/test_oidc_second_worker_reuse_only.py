"""Second worker must reuse existing encrypted access token without rotating."""
from dataclasses import replace
import pytest

from src.runtime_v6.domains.acquisition.rotating_oidc import Credential, RotationBlocked
from src.runtime_v6.domains.report_plane.oidc_reuse_probe import reuse_only_probe


class FakeStore:
    def __init__(self, *, token="dummy-saved-access", expires_at=1800, phase="READY"):
        self.state = Credential(
            version=3, phase=phase,
            refresh_token="dummy-saved-refresh", access_token=token,
            expires_at=expires_at,
        )
        self.load_calls = 0
        self.write_calls = 0

    def load(self):
        self.load_calls += 1
        return self.state

    def compare_and_swap(self, *args):
        self.write_calls += 1
        raise AssertionError("read-only probe must NEVER write credentials")


class FakeClient:
    calls = []
    mutation_store = None
    def __init__(self, *, auth_material):
        assert auth_material.mode == "bearer_token"
        assert auth_material.headers["X-API-Authorization"] == "Bearer dummy-saved-access"
        self.auth_configuration_state = "CONFIGURED"
        self.auth_material = auth_material
        self.auth_available = True
        type(self).calls = []
    def me(self):
        type(self).calls.append("/me")
        return {
            "status": "LIVE", "http_status": 200,
            "payload": {"player": {"entry": 3462711}},
        }
    def my_team(self, entry_id):
        type(self).calls.append(f"/my-team/{entry_id}")
        if type(self).mutation_store:
            type(self).mutation_store.state = replace(type(self).mutation_store.state, version=4)
        return {
            "status": "LIVE", "http_status": 200,
            "payload": {
                "picks": [{"element": i, "selling_price": 50, "purchase_price": 45} for i in range(1, 16)],
                "transfers": {"bank": 5, "free_transfers": 1},
            },
        }


def test_fresh_worker_success_with_no_refresh_no_write():
    store = FakeStore()
    FakeClient.mutation_store = None
    response = reuse_only_probe(store=store, client_factory=FakeClient, clock=lambda: 1000, entry_id=3462711)
    assert response["probe_state"] == "AUTH_AVAILABLE"
    assert response["credential_version"] == 3
    assert response["credential_unchanged"] is True
    assert response["entry_match"] is True
    assert response["private_squad_15_valid"] is True
    assert FakeClient.calls == ["/me", "/my-team/3462711"]
    assert store.write_calls == 0
    assert store.load_calls == 2
    assert "dummy-saved-access" not in str(response)
    assert "dummy-saved-refresh" not in str(response)


@pytest.mark.parametrize("phase,token,expiry,marker", [
    ("IN_FLIGHT", "dummy-saved-access", 1800, "NOT_READY"),
    ("READY", "", 1800, "NO_SAVED_ACCESS"),
    ("READY", "dummy-saved-access", 1090, "NEAR_EXPIRY"),
    ("READY", "dummy-saved-access", 1000, "NEAR_EXPIRY"),
])
def test_no_refresh_when_credential_not_reusable(phase, token, expiry, marker):
    store = FakeStore(phase=phase, token=token, expires_at=expiry)
    FakeClient.calls = []
    with pytest.raises(RotationBlocked, match=marker):
        reuse_only_probe(store=store, client_factory=FakeClient, clock=lambda: 1000, entry_id=3462711)
    assert store.write_calls == 0
    assert store.load_calls == 1
    assert FakeClient.calls == []


def test_state_mutation_is_detected_instead_of_green():
    store = FakeStore()
    FakeClient.mutation_store = store
    try:
        result = reuse_only_probe(store=store, client_factory=FakeClient, clock=lambda: 1000, entry_id=3462711)
        assert result["credential_unchanged"] is False
    finally:
        FakeClient.mutation_store = None
    assert store.write_calls == 0


def test_wrong_entry_fails_before_reading_secret():
    store = FakeStore()
    with pytest.raises(RotationBlocked, match="WRONG_EXPECTED_ENTRY"):
        reuse_only_probe(store=store, client_factory=FakeClient, clock=lambda: 1000, entry_id=1)
    assert store.load_calls == 0


def test_no_refresh_grant_capability_in_module():
    from pathlib import Path
    code = Path("src/runtime_v6/domains/report_plane/oidc_reuse_probe.py").read_text()
    assert "_bounded_grant" not in code
    assert "RotatingCredentialManager" not in code
    assert "http.post(" not in code
    assert "store.compare_and_swap(" not in code
