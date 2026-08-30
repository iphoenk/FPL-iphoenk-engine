from __future__ import annotations

from src.sources import official_fpl


class _Response:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True}
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._payload


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, timeout=None, headers=None):
        self.calls.append({"url": url, "timeout": timeout, "headers": dict(headers or {})})
        return self.responses.pop(0)


def test_live_event_requests_force_cache_bypass(monkeypatch):
    session = _Session([_Response(headers={"Age": "0"})])
    monkeypatch.setattr(official_fpl, "_session", lambda: session)

    payload, health = official_fpl.get_json("event/2/live/", retries=1)

    assert payload == {"ok": True}
    assert health["status"] == "LIVE"
    assert health["volatile_endpoint"] is True
    assert health["response_cache_age_seconds"] == 0
    assert "no-cache" in session.calls[0]["headers"]["Cache-Control"]
    assert session.calls[0]["headers"]["Pragma"] == "no-cache"


def test_static_unknown_endpoint_does_not_claim_cache_bypass(monkeypatch):
    session = _Session([_Response()])
    monkeypatch.setattr(official_fpl, "_session", lambda: session)

    payload, health = official_fpl.get_json("some-static-contract/", retries=1)

    assert payload == {"ok": True}
    assert health["volatile_endpoint"] is False
    assert health["cache_control"] is None
    assert "Cache-Control" not in session.calls[0]["headers"]


def test_transient_503_retries_but_permanent_404_fails_fast(monkeypatch):
    transient = _Session([_Response(status_code=503), _Response(status_code=200)])
    monkeypatch.setattr(official_fpl, "_session", lambda: transient)
    monkeypatch.setattr(official_fpl.time, "sleep", lambda *_: None)

    payload, health = official_fpl.get_json("event-status/", retries=3)
    assert payload == {"ok": True}
    assert health["attempts"] == 2
    assert len(transient.calls) == 2

    permanent = _Session([_Response(status_code=404), _Response(status_code=200)])
    monkeypatch.setattr(official_fpl, "_session", lambda: permanent)

    payload, health = official_fpl.get_json("entry/1/", retries=3)
    assert payload is None
    assert health["status"] == "FAILED"
    assert health["attempts"] == 1
    assert len(permanent.calls) == 1


def test_retry_after_is_bounded(monkeypatch):
    delays = []
    session = _Session([
        _Response(status_code=429, headers={"Retry-After": "30"}),
        _Response(status_code=200),
    ])
    monkeypatch.setattr(official_fpl, "_session", lambda: session)
    monkeypatch.setattr(official_fpl.time, "sleep", lambda seconds: delays.append(seconds))

    payload, health = official_fpl.get_json("bootstrap-static/", retries=2)

    assert payload == {"ok": True}
    assert health["attempts"] == 2
    assert delays == [15.0]
