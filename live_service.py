
from __future__ import annotations
import asyncio, json, os
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from src.engine import run
from src.utils import DATA, read_json

app=FastAPI(title="FPL iphoenk Engine v3.1",version="3.1.0")
POLL=int(os.getenv("FPL_LIVE_POLL_SECONDS","60"))

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
def refresh(): return run("live",sync_stats=False)

@app.get("/stream")
async def stream():
    async def events():
        last=None
        while True:
            try:
                run("live",sync_stats=False)
                payload=read_json(DATA/"live.json",{})
                encoded=json.dumps(payload,ensure_ascii=False)
                if encoded!=last:
                    yield f"data: {encoded}\n\n";last=encoded
            except Exception as exc:
                yield f"event: error\ndata: {json.dumps({'error':str(exc)})}\n\n"
            await asyncio.sleep(POLL)
    return StreamingResponse(events(),media_type="text/event-stream")
