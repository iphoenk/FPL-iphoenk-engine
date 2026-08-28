from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def parse_utc_timestamp(value: Any) -> datetime | None:
    """Parse an ISO-like timestamp and normalize it to timezone-aware UTC."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def safe_int(value: Any) -> int | None:
    """Coerce numeric-like input to int without inventing a value for missing/invalid data."""
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None
