from __future__ import annotations
from pathlib import Path
import json
from src.utils import DATA, atomic_json, read_json, iso_now
from src.engines.v4_validation import reconcile_predictions

SNAPDIR = DATA / "validation" / "deadline"
RECDIR = DATA / "validation" / "reconciled"


def deadline_snapshot_path(gw:int)->Path:
    return SNAPDIR / f"gw{int(gw):02d}.json"


def reconciled_path(gw:int)->Path:
    return RECDIR / f"gw{int(gw):02d}.json"


def persist_deadline_snapshot(gw:int, deadline_time:str|None, predictions:dict, generated_at:str|None=None)->dict:
    payload={
        "schema_version":44,
        "kind":"deadline_prediction_snapshot",
        "gw":int(gw),
        "deadline_time":deadline_time,
        "generated_at":generated_at or predictions.get("generated_at") or iso_now(),
        "model_version":predictions.get("model_version"),
        "point_in_time":True,
        "players":predictions.get("players",[]),
    }
    atomic_json(deadline_snapshot_path(gw),payload)
    return payload


def actual_rows_from_live(live:dict, elements:dict[int,dict])->list[dict]:
    rows=[]
    for item in (live or {}).get("elements",[]):
        eid=int(item.get("id")); stats=item.get("stats",{}); p=elements.get(eid,{})
        rows.append({
            "element":eid,
            "name":p.get("web_name"),
            "position":p.get("element_type"),
            "actual":float(stats.get("total_points",0) or 0),
            "actual_minutes":float(stats.get("minutes",0) or 0),
            "started":bool((stats.get("minutes",0) or 0)>=45),
            "p60_actual":bool((stats.get("minutes",0) or 0)>=60),
        })
    return rows


def reconcile_finished_gw(gw:int, live:dict, bootstrap:dict)->dict|None:
    snap=read_json(deadline_snapshot_path(gw),None)
    if not snap:return None
    elements={int(p["id"]):p for p in bootstrap.get("elements",[])}
    actual=actual_rows_from_live(live,elements)
    report=reconcile_predictions(snap.get("players",[]),actual,deadline=snap.get("deadline_time"))
    out={
        "schema_version":44,
        "kind":"post_gw_reconciliation",
        "gw":int(gw),
        "generated_at":iso_now(),
        "model_version":snap.get("model_version"),
        "deadline_time":snap.get("deadline_time"),
        "report":report,
    }
    atomic_json(reconciled_path(gw),out)
    return out
