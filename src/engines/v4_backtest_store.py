from __future__ import annotations
from pathlib import Path
from src.utils import DATA, atomic_json, read_json, iso_now
from src.engines.v4_validation import reconcile_prediction_snapshot

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


def actual_by_element(live:dict)->dict[int,dict]:
    out={}
    for item in (live or {}).get("elements",[]):
        stats=item.get("stats",{})
        out[int(item.get("id"))]={
            "total_points":float(stats.get("total_points",0) or 0),
            "minutes":float(stats.get("minutes",0) or 0),
            "started":bool((stats.get("minutes",0) or 0)>=45),
        }
    return out


def reconcile_finished_gw(gw:int, live:dict)->dict|None:
    snap=read_json(deadline_snapshot_path(gw),None)
    if not snap:return None
    report=reconcile_prediction_snapshot(snap,actual_by_element(live),event=int(gw),deadline=snap.get("deadline_time"))
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
