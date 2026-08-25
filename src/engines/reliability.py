from __future__ import annotations
from datetime import datetime, timezone

REQUIRED_FILES = ("team", "live", "prices", "health", "universe", "chips")


def validate_snapshot(snapshot: dict) -> dict:
    errors=[]
    if not isinstance(snapshot, dict): errors.append("snapshot_not_object")
    for key in ("schema_version","engine_version","generated_at","phase","entry","team_summary","files","meta"):
        if key not in snapshot: errors.append(f"missing:{key}")
    entry=snapshot.get("entry") or {}
    if not entry.get("fetched_at"): errors.append("missing_entry:fetched_at")
    for key in ("id","current_event","summary_overall_points","summary_overall_rank","summary_event_points","summary_event_rank"):
        if entry.get(key) is None: errors.append(f"missing_entry:{key}")
    files=snapshot.get("files") or {}
    for key in REQUIRED_FILES:
        if not files.get(key): errors.append(f"missing_file_pointer:{key}")
    ts=snapshot.get("team_summary") or {}
    for key in ("itb","market_value","sell_value"):
        if ts.get(key) is None: errors.append(f"missing_team_summary:{key}")
    if ts.get("market_value",0) < 0 or ts.get("sell_value",0) < 0: errors.append("negative_team_value")
    return {"ok":not errors,"errors":errors}


def source_freshness(health: dict, now: datetime|None=None) -> dict:
    now=now or datetime.now(timezone.utc)
    out={}
    for name,row in (health or {}).items():
        fetched=(row or {}).get("fetched_at")
        age=None
        if fetched:
            try:
                dt=datetime.fromisoformat(fetched.replace("Z","+00:00"))
                age=max(0,(now-dt).total_seconds())
            except Exception:
                pass
        out[name]={"status":(row or {}).get("status"),"http_status":(row or {}).get("http_status"),"fetched_at":fetched,"age_seconds":age}
    return out


def leakage_allowed(feature_available_at: str|None, target_deadline: str|None) -> bool:
    """Hard predictive leakage gate. Unknown availability fails closed."""
    if not feature_available_at or not target_deadline:
        return False
    try:
        a=datetime.fromisoformat(feature_available_at.replace("Z","+00:00"))
        d=datetime.fromisoformat(target_deadline.replace("Z","+00:00"))
        return a <= d
    except Exception:
        return False
