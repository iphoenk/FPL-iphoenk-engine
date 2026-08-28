from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def parse_iso_datetime(value: Any) -> datetime | None:
    """Parse an ISO-like datetime and normalize it to UTC.

    Invalid or empty values return None. Callers that require strict parsing can
    wrap this primitive and raise at their own contract boundary.
    """
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
