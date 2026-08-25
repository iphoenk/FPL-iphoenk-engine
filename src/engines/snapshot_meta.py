from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone


def source_meta(health: dict, key: str, authority: str = "TIER_1_OFFICIAL", derived: bool = False) -> dict:
    h=(health or {}).get(key) or {}
    return {"source":"official_fpl","endpoint":key,"authority_level":authority,"derived":derived,
            "status":h.get("status"),"http_status":h.get("http_status"),"fetched_at":h.get("fetched_at")}


def age_minutes(fetched_at: str | None) -> float | None:
    if not fetched_at: return None
    try:
        dt=datetime.fromisoformat(fetched_at.replace("Z","+00:00"))
        return round((datetime.now(timezone.utc)-dt).total_seconds()/60,2)
    except Exception:
        return None


def snapshot_id(native: dict) -> str:
    raw=json.dumps(native,sort_keys=True,separators=(",",":"),default=str).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def changes(previous: dict, current: dict, fields: list[str]) -> list[dict]:
    out=[]
    for field in fields:
        old=(previous or {}).get(field); new=(current or {}).get(field)
        if old != new: out.append({"field":field,"old":old,"new":new})
    return out
