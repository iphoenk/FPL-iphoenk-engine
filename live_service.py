from __future__ import annotations

import asyncio
import json
import os
import secrets
import threading
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse

from src.engine import run
from src.utils import DATA, read_json
from src.version import ENGINE_VERSION

POLL = max(30, int(os.getenv("FPL_LIVE_POLL_SECONDS", "60")))
REFRESH_TOKEN = os.getenv("FPL_REFRESH_TOKEN")
_poller_task: asyncio.Task | None = None
_run_lock = threading.Lock()


def _run_live_locked():
    """Serialize FPL refreshes inside this service process."""
    with _run_lock:
        return run("live", sync_stats=False)


async def _shared_poller() -> None:
    """One poller per service process, shared by all SSE clients."""
    while True:
        try:
            await asyncio.to_thread(_run_live_locked)
        except Exception:
            # Endpoint health/latest snapshots retain failure evidence.
            pass
        await asyncio.sleep(POLL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _poller_task
    _poller_task = asyncio.create_task(_shared_poller())
    try:
        yield
    finally:
        if _poller_task:
            _poller_task.cancel()
            with suppress(asyncio.CancelledError):
                await _poller_task
            _poller_task = None


app = FastAPI(
    title=f"FPL iphoenk Engine v{ENGINE_VERSION}",
    version=ENGINE_VERSION,
    lifespan=lifespan,
)


def _require_refresh_token(authorization: str | None) -> None:
    if not REFRESH_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="Manual refresh disabled: FPL_REFRESH_TOKEN is not configured",
        )
    expected = f"Bearer {REFRESH_TOKEN}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
def health():
    return read_json(DATA / "health.json", {})


@app.get("/latest")
def latest():
    return read_json(DATA / "latest.json", {})


@app.get("/live")
def live():
    return read_json(DATA / "live.json", {})


@app.get("/team")
def team():
    return read_json(DATA / "team.json", {})


@app.get("/prices")
def prices():
    return read_json(DATA / "prices.json", {})


@app.post("/refresh")
def refresh(authorization: str | None = Header(default=None)):
    _require_refresh_token(authorization)
    return _run_live_locked()


@app.get("/stream")
async def stream():
    async def events():
        last = None
        while True:
            payload = read_json(DATA / "live.json", {})
            encoded = json.dumps(payload, ensure_ascii=False)
            if encoded != last:
                yield f"data: {encoded}\n\n"
                last = encoded
            else:
                yield ": keep-alive\n\n"
            await asyncio.sleep(POLL)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
