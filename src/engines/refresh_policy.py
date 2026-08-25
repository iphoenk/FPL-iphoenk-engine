from __future__ import annotations
from datetime import datetime,timezone

def refresh_interval_minutes(deadline:str|None,is_live:bool=False)->int:
    if is_live: return 1
    if not deadline: return 60
    try: d=datetime.fromisoformat(deadline.replace("Z","+00:00")); hours=(d-datetime.now(timezone.utc)).total_seconds()/3600
    except Exception: return 60
    if hours<=1: return 10
    if hours<=4: return 15
    if hours<=24: return 30
    return 60

def mode(deadline:str|None,is_live:bool=False)->dict:
    mins=refresh_interval_minutes(deadline,is_live)
    return {"mode":"MATCHDAY_LIVE" if is_live else "DEADLINE_AWARE","recommended_interval_minutes":mins,"requires_always_on_host":mins<15 or is_live}
