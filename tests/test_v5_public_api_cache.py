from __future__ import annotations

import os
import time

from src.v5 import public_api


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return dict(self._payload)


def test_cross_run_cache_reuses_fresh_official_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("V5_PUBLIC_API_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("FPL_API_BASE", "https://cache-test.example/api")
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse({"elements": [{"id": 1}]})

    monkeypatch.setattr(public_api.requests, "get", fake_get)
    first, first_health = public_api.get("bootstrap")
    second, second_health = public_api.get("bootstrap")

    assert first == second
    assert len(calls) == 1
    assert first_health["cache_hit"] is False
    assert second_health["cache_hit"] is True
    assert second_health["cache_age_ms"] >= 0


def test_cache_key_includes_api_base(monkeypatch, tmp_path):
    monkeypatch.setenv("V5_PUBLIC_API_CACHE_DIR", str(tmp_path))
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse({"source": url})

    monkeypatch.setattr(public_api.requests, "get", fake_get)
    monkeypatch.setenv("FPL_API_BASE", "https://source-a.example/api")
    first, _ = public_api.get("bootstrap")
    monkeypatch.setenv("FPL_API_BASE", "https://source-b.example/api")
    second, _ = public_api.get("bootstrap")

    assert len(calls) == 2
    assert first["source"] != second["source"]


def test_stale_singleflight_lock_is_recovered(monkeypatch, tmp_path):
    monkeypatch.setenv("V5_PUBLIC_API_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("FPL_API_BASE", "https://stale-lock.example/api")
    base, *_ = public_api._transport()
    path = public_api.route_path("bootstrap")
    _, lock_path = public_api._cache_paths(base, path)
    assert lock_path is not None
    lock_path.write_text("stale", encoding="utf-8")
    stale_age = float(public_api._singleflight_cfg()["stale_lock_seconds"]) + 5.0
    old = time.time() - stale_age
    os.utime(lock_path, (old, old))
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse({"ok": True})

    monkeypatch.setattr(public_api.requests, "get", fake_get)
    payload, health = public_api.get("bootstrap")

    assert payload == {"ok": True}
    assert len(calls) == 1
    assert health["cache_hit"] is False
    assert not lock_path.exists()
