from __future__ import annotations

from datetime import datetime, timezone

from src.engines.leakage_guard import availability_before_deadline

REQUIRED_FILES = ("team", "live", "prices", "health", "universe", "chips")


def validate_snapshot(snapshot: dict) -> dict:
    errors = []
    if not isinstance(snapshot, dict):
        errors.append("snapshot_not_object")
    for key in ("schema_version", "engine_version", "generated_at", "phase", "team_summary", "files", "meta"):
        if key not in snapshot:
            errors.append(f"missing:{key}")
    files = snapshot.get("files") or {}
    for key in REQUIRED_FILES:
        if not files.get(key):
            errors.append(f"missing_file_pointer:{key}")
    summary = snapshot.get("team_summary") or {}
    required_value_fields = ("squad_market_value", "itb", "total_market_funds", "squad_sell_value", "transferable_funds")
    for key in required_value_fields:
        if summary.get(key) is None:
            errors.append(f"missing_team_summary:{key}")
    if summary.get("squad_market_value", 0) < 0 or summary.get("squad_sell_value", 0) < 0:
        errors.append("negative_team_value")
    return {"ok": not errors, "errors": errors}


def source_freshness(health: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    out = {}
    for name, row in (health or {}).items():
        fetched = (row or {}).get("fetched_at")
        age = None
        if fetched:
            try:
                parsed = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
                age = max(0, (now - parsed).total_seconds())
            except Exception:
                pass
        out[name] = {
            "status": (row or {}).get("status"),
            "http_status": (row or {}).get("http_status"),
            "fetched_at": fetched,
            "age_seconds": age,
        }
    return out


def leakage_allowed(feature_available_at: str | None, target_deadline: str | None) -> bool:
    """Compatibility wrapper around the canonical predictive timing gate."""
    return availability_before_deadline(feature_available_at, target_deadline)
