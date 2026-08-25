import pytest
from fastapi import HTTPException

import live_service


def test_manual_refresh_fails_closed_without_token(monkeypatch):
    monkeypatch.setattr(live_service, "REFRESH_TOKEN", None)
    with pytest.raises(HTTPException) as exc:
        live_service._require_refresh_token(None)
    assert exc.value.status_code == 503


def test_manual_refresh_rejects_wrong_token(monkeypatch):
    monkeypatch.setattr(live_service, "REFRESH_TOKEN", "secret-value")
    with pytest.raises(HTTPException) as exc:
        live_service._require_refresh_token("Bearer wrong-value")
    assert exc.value.status_code == 401


def test_manual_refresh_accepts_matching_bearer_token(monkeypatch):
    monkeypatch.setattr(live_service, "REFRESH_TOKEN", "secret-value")
    live_service._require_refresh_token("Bearer secret-value")


def test_live_poll_interval_has_safe_floor():
    assert live_service.POLL >= 30
