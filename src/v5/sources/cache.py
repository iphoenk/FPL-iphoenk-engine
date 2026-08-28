from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils import atomic_json


def load_json_cache(path: Path, ttl_seconds: int, *, now: datetime | None = None) -> dict[str, Any] | None:
    if not path.exists():
        return None
    current = (now or datetime.now(timezone.utc)).timestamp()
    if current - path.stat().st_mtime > max(0, int(ttl_seconds)):
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def write_json_cache(path: Path, payload: dict[str, Any]) -> None:
    atomic_json(path, payload)
