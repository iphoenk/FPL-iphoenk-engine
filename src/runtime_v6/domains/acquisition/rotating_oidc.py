"""Fail-closed rotating OIDC grant state machine for the isolated FPL private plane.

Not enabled by legacy FPL_AUTH_MODE. Callers MUST supply a durable CAS-backed
secret store AND an inter-worker lease; unit-test locks are not production locks.
No refresh request is sent unless those dependencies and a verified client
contract have been provided. Neither tokens nor provider bodies are logged.
"""
from __future__ import annotations

import hmac
import secrets
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit

import requests


class RotationBlocked(RuntimeError):
    """Non-secret, terminal state requiring owner or operator action."""


class RotationUncertain(RotationBlocked):
    """A grant might have been consumed. NEVER automatically replay it."""


@dataclass(frozen=True)
class Credential:
    version: int
    phase: str
    refresh_token: str
    access_token: str = ""
    expires_at: float = 0
    transaction_id: str = ""

    def __repr__(self) -> str:
        return (
            "Credential(version="
            + str(self.version)
            + ", phase="
            + repr(self.phase)
            + ", secrets=<redacted>)"
        )


class DurableStore(Protocol):
    """Atomic compare-and-swap. All secrets must be encrypted at rest."""

    def load(self) -> Credential: ...

    def compare_and_swap(self, expected_version: int, proposed: Credential) -> Credential: ...


class LeaseProvider(Protocol):
    """Must serialize the grant across processes AND workflow runs."""

    def acquire(self) -> AbstractContextManager[None]: ...


class RefreshHTTP(Protocol):
    def post(self, url: str, **kwargs: Any) -> Any: ...


def _check_contract(token_url: str, approved_host: str, client_id: str) -> None:
    parts = urlsplit(token_url)
    if (
        parts.scheme != "https"
        or parts.hostname != approved_host
        or parts.username
        or parts.password
        or parts.fragment
        or parts.query
        or not parts.path
        or not client_id
    ):
        raise RotationBlocked("OIDC_CONTRACT_NOT_VERIFIED")


def _bounded_grant(
    *,
    refresh_token: str,
    token_url: str,
    approved_host: str,
    client_id: str,
    http: RefreshHTTP,
    timeout_seconds: float,
    permit_nonrotating: bool,
) -> tuple[str, str, int]:
    _check_contract(token_url, approved_host, client_id)
    try:
        response = http.post(
            token_url,
            data={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id},
            timeout=timeout_seconds,
            allow_redirects=False,
        )
    except Exception:
        # Even a timeout may mean the provider consumed a one-use token.
        raise RotationUncertain("OIDC_GRANT_RESULT_UNCERTAIN") from None

    code = getattr(response, "status_code", None)
    if code != 200:
        if code in (400, 401, 403):
            raise RotationBlocked("OIDC_GRANT_REJECTED")
        raise RotationUncertain("OIDC_GRANT_HTTP_UNCERTAIN")
    try:
        payload = response.json()
        access = payload["access_token"]
        renewed = payload.get("refresh_token")
        expires = payload["expires_in"]
        if (
            not isinstance(access, str) or not access
            or type(expires) is not int or not 60 <= expires <= 86400
        ):
            raise ValueError("invalid_grant_payload")
        if not renewed:
            if not permit_nonrotating:
                raise RotationBlocked("OIDC_REPLACEMENT_REFRESH_TOKEN_ABSENT")
            renewed = refresh_token
        if not isinstance(renewed, str) or not renewed:
            raise ValueError("invalid_refresh_token")
    except RotationBlocked:
        raise
    except Exception:
        raise RotationUncertain("OIDC_GRANT_PAYLOAD_UNCERTAIN") from None
    return access, renewed, expires


class RotatingCredentialManager:
    """One refresh transaction. No automatic retry after a sent grant.

    The durable IN_FLIGHT marker is written BEFORE the external POST. A crash
    leaves IN_FLIGHT, preventing a second worker from replaying that token.
    Re-enrollment is necessary if persistence/read-back fails after rotation.
    """

    def __init__(
        self,
        *,
        store: DurableStore,
        lease: LeaseProvider,
        token_url: str,
        approved_host: str,
        client_id: str,
        contract_verified: bool = False,
        permit_nonrotating: bool = False,
        http: RefreshHTTP = requests,
        clock: Callable[[], float] = time.time,
        timeout_seconds: float = 12.0,
    ) -> None:
        self.store = store
        self.lease = lease
        self.token_url = token_url
        self.approved_host = approved_host
        self.client_id = client_id
        self.contract_verified = contract_verified
        self.permit_nonrotating = permit_nonrotating
        self.http = http
        self.clock = clock
        self.timeout_seconds = timeout_seconds

    def get_access_token(self, *, refresh_before_seconds: int = 90) -> str:
        # Preserve the default 90-second behavior for report-prefetch callers.
        # Only the private natural-hourly maintenance worker requests 15 minutes.
        if (type(refresh_before_seconds) is not int
                or not 90 <= refresh_before_seconds <= 1800):
            raise RotationBlocked("OIDC_RENEWAL_WINDOW_INVALID")
        if not self.contract_verified:
            raise RotationBlocked("OIDC_CONTRACT_NOT_VERIFIED")
        _check_contract(self.token_url, self.approved_host, self.client_id)
        initial = self.store.load()
        if initial.phase != "READY":
            raise RotationUncertain("OIDC_ROTATION_REQUIRES_REENROLLMENT")
        if initial.access_token and initial.expires_at > self.clock() + refresh_before_seconds:
            return initial.access_token

        with self.lease.acquire():
            current = self.store.load()
            if current.phase != "READY":
                raise RotationUncertain("OIDC_ROTATION_REQUIRES_REENROLLMENT")
            if current.access_token and current.expires_at > self.clock() + refresh_before_seconds:
                return current.access_token
            if not current.refresh_token:
                raise RotationBlocked("OIDC_CREDENTIAL_NOT_ENROLLED")

            started = replace(current, phase="IN_FLIGHT", transaction_id=secrets.token_hex(16))
            try:
                marked = self.store.compare_and_swap(current.version, started)
                confirmed = self.store.load()
                if (
                    confirmed.version != marked.version
                    or confirmed.phase != "IN_FLIGHT"
                    or not marked.transaction_id
                    or not hmac.compare_digest(confirmed.transaction_id, marked.transaction_id)
                    or not hmac.compare_digest(confirmed.refresh_token, marked.refresh_token)
                ):
                    # Never issue a grant unless the exact claimed transaction,
                    # not merely an IN_FLIGHT phase, is durably read back.
                    raise RotationUncertain("OIDC_GRANT_MARKER_PERSISTENCE_UNVERIFIED")
            except RotationUncertain:
                # Previously swallowed into the generic PERSISTENCE_FAILED code:
                # retain the distinct fail-closed readback classification.
                raise RotationUncertain("OIDC_GRANT_MARKER_PERSISTENCE_UNVERIFIED") from None
            except RotationBlocked as exc:
                # Preserve sanitized Git CAS diagnostics, never reveal secrets
                # or issue a refresh POST without a verified IN_FLIGHT marker.
                if str(exc).startswith("CREDENTIAL_STORE_"):
                    raise
                raise RotationBlocked("OIDC_GRANT_MARKER_PERSISTENCE_FAILED") from None
            except Exception:
                raise RotationBlocked("OIDC_GRANT_MARKER_PERSISTENCE_FAILED") from None

            try:
                access, renewed, lifetime = _bounded_grant(
                    refresh_token=marked.refresh_token,
                    token_url=self.token_url,
                    approved_host=self.approved_host,
                    client_id=self.client_id,
                    http=self.http,
                    timeout_seconds=self.timeout_seconds,
                    permit_nonrotating=self.permit_nonrotating,
                )
            except RotationBlocked:
                # IN_FLIGHT remains durable on any provider error. Do not replay.
                raise

            updated = replace(
                marked, phase="READY", refresh_token=renewed,
                access_token=access, expires_at=self.clock() + lifetime,
                transaction_id="",
            )
            try:
                saved = self.store.compare_and_swap(marked.version, updated)
                confirmed = self.store.load()
                if (
                    saved.version != confirmed.version
                    or confirmed.phase != "READY"
                    or not hmac.compare_digest(confirmed.refresh_token, renewed)
                    or not hmac.compare_digest(confirmed.access_token, access)
                ):
                    raise RotationUncertain("OIDC_ROTATION_READBACK_FAILED")
            except Exception:
                raise RotationUncertain("OIDC_ROTATION_PERSISTENCE_UNVERIFIED") from None
            return access
