import asyncio

import pytest
from fastapi import HTTPException

import live_service


def test_refresh_auth_fails_closed_without_config(monkeypatch):
    monkeypatch.delenv("FPL_REFRESH_TOKEN", raising=False)
    with pytest.raises(HTTPException) as exc:
        live_service._authorize_refresh(None, None)
    assert exc.value.status_code == 503


def test_refresh_auth_accepts_header_or_bearer(monkeypatch):
    monkeypatch.setenv("FPL_REFRESH_TOKEN", "secret")
    live_service._authorize_refresh(None, "secret")
    live_service._authorize_refresh("Bearer secret", None)
    with pytest.raises(HTTPException) as exc:
        live_service._authorize_refresh("Bearer wrong", None)
    assert exc.value.status_code == 401


def test_stream_subscribers_share_one_broadcast_task(monkeypatch):
    async def scenario():
        started = 0

        async def fake_loop():
            nonlocal started
            started += 1
            await asyncio.Event().wait()

        monkeypatch.setattr(live_service, "_broadcast_loop", fake_loop)
        first = live_service._subscribe()
        second = live_service._subscribe()
        first_next = asyncio.create_task(anext(first))
        second_next = asyncio.create_task(anext(second))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert started == 1
        first_next.cancel()
        second_next.cancel()
        await asyncio.gather(first_next, second_next, return_exceptions=True)
        await first.aclose()
        await second.aclose()

    asyncio.run(scenario())
