"""Credential tests intentionally contain dummy values only; never live secrets."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from src.runtime_v6.domains.acquisition.rotating_oidc import (
    Credential, RotatingCredentialManager, RotationBlocked, RotationUncertain,
)


class MemoryStore:
    def __init__(self, *, access="", expiry=0):
        self.state = Credential(1, "READY", "dummy-refresh-token", access, expiry)
        self.mutex = threading.Lock()
        self.reject_write = False

    def load(self):
        with self.mutex:
            return self.state

    def compare_and_swap(self, version, proposed):
        with self.mutex:
            if self.reject_write:
                raise ValueError("reject")
            if self.state.version != version:
                raise ValueError("conflict")
            self.state = replace(proposed, version=version + 1)
            return self.state


class Lock:
    def __init__(self):
        self.lock = threading.Lock()

    @contextmanager
    def acquire(self):
        with self.lock:
            yield


class FakeHTTP:
    def __init__(self, *, payload=None, code=200, error=None):
        self.payload = payload if payload is not None else {
            "access_token": "dummy-access-next",
            "refresh_token": "dummy-refresh-next",
            "expires_in": 3600,
        }
        self.code = code
        self.error = error
        self.calls = 0

    def post(self, url, **kwargs):
        self.calls += 1
        assert url == "https://account.premierleague.com/as/token"
        assert kwargs["allow_redirects"] is False
        assert kwargs["timeout"] <= 15
        assert kwargs["data"]["grant_type"] == "refresh_token"
        if self.error:
            raise self.error
        return SimpleNamespace(status_code=self.code, json=lambda: self.payload)


def manager(store=None, http=None, lock=None, **kwargs):
    return RotatingCredentialManager(
        store=store or MemoryStore(),
        lease=lock or Lock(),
        token_url="https://account.premierleague.com/as/token",
        approved_host="account.premierleague.com",
        client_id="dummy-client",
        contract_verified=True,
        http=http or FakeHTTP(),
        clock=lambda: 1000.0,
        **kwargs,
    )


def test_valid_access_never_refreshes():
    store, http = MemoryStore(access="valid-access", expiry=2000), FakeHTTP()
    assert manager(store, http).get_access_token() == "valid-access"
    assert http.calls == 0


def test_expired_access_refreshes_persists_and_next_worker_reuses():
    store, http, lock = MemoryStore(access="expired", expiry=10), FakeHTTP(), Lock()
    assert manager(store, http, lock).get_access_token() == "dummy-access-next"
    assert store.state.phase == "READY"
    assert store.state.refresh_token == "dummy-refresh-next"
    assert manager(store, http, lock).get_access_token() == "dummy-access-next"
    assert http.calls == 1


def test_concurrent_workers_only_one_grant():
    store, http, lock = MemoryStore(), FakeHTTP(), Lock()
    with ThreadPoolExecutor(max_workers=5) as pool:
        output = list(pool.map(lambda _: manager(store, http, lock).get_access_token(), range(5)))
    assert output == ["dummy-access-next"] * 5
    assert http.calls == 1


def test_unverified_contract_blocks_before_store_or_http():
    store, http = MemoryStore(), FakeHTTP()
    c = manager(store, http)
    c.contract_verified = False
    with pytest.raises(RotationBlocked, match="CONTRACT_NOT_VERIFIED"):
        c.get_access_token()
    assert http.calls == 0


def test_insecure_endpoint_blocks():
    c = manager()
    c.token_url = "http://account.premierleague.com/as/token"
    with pytest.raises(RotationBlocked, match="CONTRACT_NOT_VERIFIED"):
        c.get_access_token()


@pytest.mark.parametrize("code", [400, 401, 403])
def test_grant_rejection_never_retries(code):
    store, http = MemoryStore(), FakeHTTP(code=code)
    with pytest.raises(RotationBlocked, match="GRANT_REJECTED"):
        manager(store, http).get_access_token()
    assert store.state.phase == "IN_FLIGHT"
    assert http.calls == 1
    with pytest.raises(RotationUncertain, match="REENROLLMENT"):
        manager(store, http).get_access_token()
    assert http.calls == 1


def test_timeout_may_have_consumed_grant():
    store, http = MemoryStore(), FakeHTTP(error=TimeoutError())
    with pytest.raises(RotationUncertain, match="RESULT_UNCERTAIN"):
        manager(store, http).get_access_token()
    assert store.state.phase == "IN_FLIGHT"
    with pytest.raises(RotationUncertain):
        manager(store, http).get_access_token()
    assert http.calls == 1


def test_marker_write_failure_sends_no_grant():
    store, http = MemoryStore(), FakeHTTP()
    store.reject_write = True
    with pytest.raises(RotationBlocked, match="MARKER_PERSISTENCE_FAILED"):
        manager(store, http).get_access_token()
    assert http.calls == 0


@pytest.mark.parametrize("corruption", ["phase", "transaction", "refresh"])
def test_marker_readback_must_match_the_exact_durable_claim(corruption):
    class DisagreeingReadbackStore(MemoryStore):
        def load(self):
            state = super().load()
            if state.phase != "IN_FLIGHT":
                return state
            if corruption == "phase":
                return replace(state, phase="READY")
            if corruption == "transaction":
                return replace(state, transaction_id="different-transaction")
            return replace(state, refresh_token="different-refresh-placeholder")

    store, http = DisagreeingReadbackStore(), FakeHTTP()
    with pytest.raises(RotationUncertain, match="OIDC_GRANT_MARKER_PERSISTENCE_UNVERIFIED"):
        manager(store, http).get_access_token()
    assert store.state.phase == "IN_FLIGHT"
    assert http.calls == 0


def test_marker_git_transport_error_keeps_nonsecret_root_cause():
    class UnavailableGitStore(MemoryStore):
        def compare_and_swap(self, version, proposed):
            raise RotationBlocked("CREDENTIAL_STORE_GIT_TIMEOUT")

    store, http = UnavailableGitStore(), FakeHTTP()
    with pytest.raises(RotationBlocked, match="^CREDENTIAL_STORE_GIT_TIMEOUT$"):
        manager(store, http).get_access_token()
    assert http.calls == 0


def test_missing_refresh_replacement_is_fail_closed():
    store, http = MemoryStore(), FakeHTTP(payload={"access_token": "dummy", "expires_in": 3600})
    with pytest.raises(RotationBlocked, match="REPLACEMENT_REFRESH_TOKEN_ABSENT"):
        manager(store, http).get_access_token()
    assert store.state.phase == "IN_FLIGHT"


def test_nonrotating_only_with_explicit_verified_policy():
    store, http = MemoryStore(), FakeHTTP(payload={"access_token": "dummy", "expires_in": 3600})
    assert manager(store, http, permit_nonrotating=True).get_access_token() == "dummy"
    assert store.state.refresh_token == "dummy-refresh-token"


def test_crashed_grant_never_replays():
    store, http = MemoryStore(), FakeHTTP()
    store.state = replace(store.state, phase="IN_FLIGHT")
    with pytest.raises(RotationUncertain, match="REENROLLMENT"):
        manager(store, http).get_access_token()
    assert http.calls == 0


def test_errors_do_not_embed_credentials():
    store, http = MemoryStore(), FakeHTTP(error=TimeoutError("dummy-refresh-token"))
    try:
        manager(store, http).get_access_token()
    except RotationUncertain as exc:
        assert "dummy-refresh-token" not in repr(exc)
        assert "dummy-refresh-token" not in str(exc)
        assert exc.__cause__ is None


def test_repr_redacts_sensitive_values():
    assert "dummy-refresh-token" not in repr(MemoryStore().state)


def test_hourly_15_minute_threshold_renews_without_changing_default_behavior():
    # A token 10 minutes from expiry is still valid for ordinary report-prefetch,
    # but the natural hourly maintenance check may renew it proactively.
    store, http, lock = MemoryStore(access="dummy-still-valid", expiry=1600), FakeHTTP(), Lock()
    m = manager(store, http, lock)
    assert m.get_access_token() == "dummy-still-valid"
    assert http.calls == 0
    assert m.get_access_token(refresh_before_seconds=900) == "dummy-access-next"
    assert http.calls == 1
    assert m.get_access_token(refresh_before_seconds=900) == "dummy-access-next"
    assert http.calls == 1


@pytest.mark.parametrize("invalid", [0, 89, 1801, True, 900.0, None])
def test_hourly_threshold_cannot_exceed_bounded_contract(invalid):
    store, http = MemoryStore(), FakeHTTP()
    with pytest.raises(RotationBlocked, match="RENEWAL_WINDOW_INVALID"):
        manager(store, http).get_access_token(refresh_before_seconds=invalid)
    assert http.calls == 0
