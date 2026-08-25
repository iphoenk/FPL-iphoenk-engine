
from __future__ import annotations
import csv, io, json
from pathlib import Path
from typing import Any
import requests
from src.utils import ROOT, DATA, CONFIG, iso_now, atomic_json, read_json

CACHE = DATA / "stats"
SCHEMA_REQUIRED = {"id"}

def _cfg():
    return read_json(CONFIG/"sources.json", {})

def season():
    cfg = _cfg()
    return cfg.get("fpl_core_insights",{}).get("season") or cfg.get("season")

def base_url():
    return _cfg().get("fpl_core_insights",{}).get(
        "raw_base","https://raw.githubusercontent.com/olbauday/FPL-Core-Insights/main/data"
    )

def _fetch_csv(url: str, timeout=25):
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    text = r.text
    rows = list(csv.DictReader(io.StringIO(text)))
    return rows

def _candidate_urls(gw: int):
    s = season()
    b = base_url().rstrip("/")
    # Multiple path candidates because community repo layouts can evolve.
    return [
        f"{b}/{s}/gws/gw{gw}.csv",
        f"{b}/{s}/gw{gw}.csv",
        f"{b}/{s}/gameweeks/gw{gw}.csv",
        f"{b}/{s}/players/gw{gw}.csv"
    ]

def sync_gw(gw: int):
    last_error = None
    for url in _candidate_urls(gw):
        try:
            rows = _fetch_csv(url)
            if not rows:
                raise RuntimeError("empty CSV")
            keys = set(rows[0].keys())
            if not SCHEMA_REQUIRED.issubset(keys):
                raise RuntimeError(f"schema missing required columns: {sorted(SCHEMA_REQUIRED-keys)}")
            payload = {
                "source":"FPL-Core-Insights",
                "source_tier":"community_enrichment",
                "season":season(),
                "gw":gw,
                "fetched_at":iso_now(),
                "available_at":iso_now(),
                "data_class":"post_match_or_post_gw",
                "leakage_guard":"NOT_ELIGIBLE_FOR_SAME_GW_PREDEADLINE_TRAINING",
                "source_url":url,
                "row_count":len(rows),
                "schema_columns":sorted(keys),
                "schema_valid":True,
                "rows":rows
            }
            atomic_json(CACHE/f"core_insights_gw{gw}.json", payload)
            return payload
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
    failure = {
        "source":"FPL-Core-Insights","season":season(),"gw":gw,
        "fetched_at":iso_now(),"schema_valid":False,"error":last_error
    }
    atomic_json(CACHE/f"core_insights_gw{gw}_error.json", failure)
    return failure

def load_gw(gw: int):
    return read_json(CACHE/f"core_insights_gw{gw}.json", {})

def query_player(gw: int, query: str):
    data = load_gw(gw)
    q = query.casefold()
    hits = []
    for r in data.get("rows",[]):
        hay = " ".join(str(r.get(k,"")) for k in ["name","web_name","first_name","second_name","id"]).casefold()
        if q in hay:
            hits.append(r)
    return {
        "source":data.get("source"),
        "gw":gw,
        "fetched_at":data.get("fetched_at"),
        "schema_valid":data.get("schema_valid"),
        "matches":hits
    }

def sync_optional_deep_files(gw: int):
    s=season(); b=base_url().rstrip("/")
    out={}
    candidates={
        "shots":[f"{b}/{s}/shots.csv",f"{b}/{s}/gws/shots.csv"],
        "playermatchstats":[f"{b}/{s}/playermatchstats.csv",f"{b}/{s}/matchstats/playermatchstats.csv"]
    }
    for name, urls in candidates.items():
        last=None
        for url in urls:
            try:
                rows=_fetch_csv(url)
                payload={"source":"FPL-Core-Insights","dataset":name,"season":s,
                         "fetched_at":iso_now(),"source_url":url,"row_count":len(rows),
                         "schema_columns":sorted(rows[0].keys()) if rows else [],
                         "rows":rows}
                atomic_json(CACHE/f"{name}.json", payload)
                out[name]={"ok":True,"rows":len(rows),"url":url}
                break
            except Exception as exc:
                last=str(exc)
        else:
            out[name]={"ok":False,"error":last}
    return out
