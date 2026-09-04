from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .http_client import utc_now

def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

def _minutes_since(value: str | None) -> float | None:
    dt = _parse_dt(value)
    if dt is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 60.0)

def build_source_health(config: dict[str, Any], results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    sources = []
    counts = {"GREEN": 0, "AMBER": 0, "RED": 0}
    for source in config.get("sources") or []:
        payload = results[source["id"]]
        health = str(payload.get("health") or "AMBER")
        counts[health] = counts.get(health, 0) + 1
        checked_at = payload.get("checked_at")
        check_age = _minutes_since(checked_at)
        sources.append({"source_id": source["id"], "source_name": source["name"], "category": source["category"], "critical": bool(source.get("critical")), "health": health, "availability": payload.get("availability"), "effective_state": payload.get("effective_state"), "changed": payload.get("changed"), "checked_at": checked_at, "check_age_minutes": round(check_age, 3) if check_age is not None else None, "check_freshness_target_minutes": source.get("check_freshness_minutes"), "coverage": payload.get("coverage")})
    overall = "RED" if counts.get("RED", 0) else ("AMBER" if counts.get("AMBER", 0) else "GREEN")
    return {"schema_version": 1, "generated_at": utc_now(), "overall": overall, "counts": counts, "source_count": len(sources), "sources": sources, "semantics": {"GREEN": "Current cycle acquisition succeeded. Unchanged upstream data is still GREEN.", "AMBER": "Usable but partial, cached, credential-required, or otherwise degraded.", "RED": "Critical source has no usable current or cached data."}}
