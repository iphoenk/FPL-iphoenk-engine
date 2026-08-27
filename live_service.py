
from __future__ import annotations

import asyncio
import json
import os
import secrets

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from src.services.orchestrator import orchestrate
from src.utils import DATA, read_json

app = FastAPI(title="FPL iphoenk Engine V4.9.2", version="4.9.2")
POLL = int(os.getenv("FPL_LIVE_POLL_SECONDS", "60"))
_subscribers: set[asyncio.Queue] = set()
_broadcast_task: asyncio.Task | None = None
_subscriber_lock = asyncio.Lock()


def _authorize_refresh(authorization: str | None, refresh_token: str | None) -> None:
    expected = os.getenv("FPL_REFRESH_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="refresh endpoint is disabled until FPL_REFRESH_TOKEN is configured")
    bearer = authorization.removeprefix("Bearer ") if authorization and authorization.startswith("Bearer ") else None
    supplied = refresh_token or bearer
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid refresh credentials")


def _run_live() -> dict:
    return orchestrate("live", stats=False, deep_stats=False)


async def _broadcast_loop() -> None:
    last = None
    while True:
        try:
            await asyncio.to_thread(_run_live)
            event = {"event": "message", "data": read_json(DATA / "live.json", {})}
        except Exception as exc:  # fail visibly to every connected client
            event = {"event": "error", "data": {"error": str(exc)}}
        encoded = json.dumps(event["data"], ensure_ascii=False, sort_keys=True)
        if event["event"] == "error" or encoded != last:
            for queue in tuple(_subscribers):
                if queue.full():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                queue.put_nowait(event)
            if event["event"] == "message":
                last = encoded
        await asyncio.sleep(POLL)


async def _subscribe():
    global _broadcast_task
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    async with _subscriber_lock:
        _subscribers.add(queue)
        if _broadcast_task is None or _broadcast_task.done():
            _broadcast_task = asyncio.create_task(_broadcast_loop())
    try:
        while True:
            event = await queue.get()
            prefix = "" if event["event"] == "message" else f"event: {event['event']}\n"
            yield f"{prefix}data: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
    finally:
        async with _subscriber_lock:
            _subscribers.discard(queue)
            if not _subscribers and _broadcast_task and not _broadcast_task.done():
                _broadcast_task.cancel()
                _broadcast_task = None

@app.get("/health")
def health(): return read_json(DATA/"health.json",{})

@app.get("/latest")
def latest(): return read_json(DATA/"latest.json",{})

@app.get("/live")
def live(): return read_json(DATA/"live.json",{})

@app.get("/team")
def team(): return read_json(DATA/"team.json",{})

@app.get("/prices")
def prices(): return read_json(DATA/"prices.json",{})

@app.post("/refresh")
async def refresh(
    authorization: str | None = Header(default=None),
    refresh_token: str | None = Header(default=None, alias="X-FPL-Refresh-Token"),
):
    _authorize_refresh(authorization, refresh_token)
    return await asyncio.to_thread(_run_live)

@app.get("/stream")
async def stream():
    return StreamingResponse(_subscribe(), media_type="text/event-stream")
