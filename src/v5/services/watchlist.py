from __future__ import annotations
from typing import Any
from src.v5.decision.watchlist import build_watchlist

def handle(operation:str,payload:dict[str,Any])->Any:
    if operation=="status": return {"status":"ACTIVE","model":"full_dss_watchlist_v5_v2","operations":["build"]}
    if operation!="build": raise KeyError(f"unsupported watchlist operation: {operation}")
    prediction=payload.get("prediction") if isinstance(payload.get("prediction"),dict) else {}; truth=payload.get("truth") if isinstance(payload.get("truth"),dict) else {}; team=truth.get("team") if isinstance(truth.get("team"),dict) else {}; dss=payload.get("dss") if isinstance(payload.get("dss"),dict) else {}
    if not prediction or not team: raise ValueError("watchlist service requires prediction and truth team")
    return build_watchlist(prediction,team,dss)
