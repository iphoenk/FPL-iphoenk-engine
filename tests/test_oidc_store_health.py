from types import SimpleNamespace

from src.runtime_v6.domains.report_plane.oidc_store_health import inspect_store


class FakeStore:
    def __init__(self, credential):
        self.credential = credential
        self.load_count = 0

    def load(self):
        self.load_count += 1
        return self.credential


def test_health_metadata_only_no_grant_or_write():
    store = FakeStore(SimpleNamespace(
        version=3, phase="READY",
        access_token="fake-secret-access",
        refresh_token="fake-secret-refresh",
        transaction_id="fake-secret-transaction",
        expires_at=3000.0,
    ))
    result = inspect_store(store, now=1000.0)
    assert store.load_count == 1
    assert result == {
        "credential_version": 3,
        "phase": "READY",
        "access_state": "VALID_OVER_90S",
        "refresh_present": True,
        "grant_sent": False,
        "credentials_mutated": False,
    }
    assert "fake-secret" not in repr(result)


def test_health_in_flight_does_not_retry_grant():
    store = FakeStore(SimpleNamespace(
        version=4, phase="IN_FLIGHT",
        access_token="", refresh_token="fake-secret",
        transaction_id="another-secret", expires_at=0,
    ))
    result = inspect_store(store, now=1000.0)
    assert result["phase"] == "IN_FLIGHT"
    assert result["access_state"] == "EXPIRED_OR_UNAVAILABLE"
    assert result["grant_sent"] is False
    assert store.load_count == 1
