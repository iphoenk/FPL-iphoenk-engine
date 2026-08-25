
from __future__ import annotations
import csv, io, requests
from src.utils import DATA, CONFIG, iso_now, atomic_json, read_json

CACHE=DATA/"stats"

def _cfg(): return read_json(CONFIG/"sources.json",{})

def sync_gw(gw:int):
    season=_cfg().get("season","2026-2027")
    base=_cfg().get("vaastav",{}).get("raw_base",
        "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data")
    url=f"{base}/{season}/gws/gw{gw}.csv"
    try:
        r=requests.get(url,timeout=25); r.raise_for_status()
        rows=list(csv.DictReader(io.StringIO(r.text)))
        payload={
            "source":"vaastav/Fantasy-Premier-League","gw":gw,"season":season,
            "fetched_at":iso_now(),"source_url":url,"row_count":len(rows),
            "leakage_warning":"Historical xP/expected-points style columns may be post-match. Shift/exclude for predictive training.",
            "rows":rows
        }
        atomic_json(CACHE/f"vaastav_gw{gw}.json",payload)
        return payload
    except Exception as exc:
        return {"source":"vaastav/Fantasy-Premier-League","gw":gw,"error":str(exc),"fetched_at":iso_now()}
