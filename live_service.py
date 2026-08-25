from __future__ import annotations
import asyncio, json, os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from src.engine import run
from src.utils import DATA, read_json
from src.version import ENGINE_VERSION, SERVICE_TITLE

POLL=max(30,int(os.getenv("FPL_LIVE_POLL_SECONDS","60")))
REFRESH_API_KEY=os.getenv("FPL_REFRESH_API_KEY")
_poll_lock=asyncio.Lock()
_stop_event=asyncio.Event()

async def _refresh_once():
    async with _poll_lock:
        return await asyncio.to_thread(run,"live",False)

async def _shared_poller():
    while not _stop_event.is_set():
        try:
            await _refresh_once()
        except Exception:
            pass
        try:
            await asyncio.wait_for(_stop_event.wait(),timeout=POLL)
        except asyncio.TimeoutError:
            continue

@asynccontextmanager
async def lifespan(app:FastAPI):
    _stop_event.clear()
    task=asyncio.create_task(_shared_poller())
    try:
        yield
    finally:
        _stop_event.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

app=FastAPI(title=SERVICE_TITLE,version=ENGINE_VERSION,lifespan=lifespan)

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
async def refresh(x_fpl_refresh_key:str|None=Header(default=None)):
    if not REFRESH_API_KEY:
        raise HTTPException(status_code=503,detail="manual refresh disabled: FPL_REFRESH_API_KEY is not configured")
    if x_fpl_refresh_key!=REFRESH_API_KEY:
        raise HTTPException(status_code=401,detail="invalid refresh key")
    return await _refresh_once()

@app.get("/stream")
async def stream():
    async def events():
        last=None
        while True:
            payload=read_json(DATA/"live.json",{})
            encoded=json.dumps(payload,ensure_ascii=False)
            if encoded!=last:
                yield f"data: {encoded}\n\n"
                last=encoded
            await asyncio.sleep(min(POLL,15))
    return StreamingResponse(events(),media_type="text/event-stream")
