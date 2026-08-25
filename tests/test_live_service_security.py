import pytest
from fastapi import HTTPException

import live_service


def test_manual_refresh_fails_closed_without_key(monkeypatch):
    monkeypatch.setattr(live_service, "REFRESH_API_KEY", None)
    with pytest.raises(HTTPException) as exc:
        live_service._require_refresh_key(None)
    assert exc.value.status_code == 503


def test_manual_refresh_rejects_wrong_key(monkeypatch):
    monkeypatch.setattr(live_service, "REFRESH_API_KEY", "secret-value")
    with pytest.raises(HTTPException) as exc:
        live_service._require_refresh_key("wrong-value")
    assert exc.value.status_code == 401


def test_manual_refresh_accepts_matching_key(monkeypatch):
    monkeypatch.setattr(live_service, "REFRESH_API_KEY", "secret-value")
    live_service._require_refresh_key("secret-value")


def test_live_poll_interval_has_safe_floor():
    assert live_service.POLL >= 30
