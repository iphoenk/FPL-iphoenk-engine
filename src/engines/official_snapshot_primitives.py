from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.utils import DATA


def load_snapshot(data_dir: Path | None = None, *, required: bool = True) -> dict[str, Any]:
    path = Path(data_dir or DATA) / "official_snapshot.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        if required:
            raise RuntimeError(f"Official snapshot required before downstream Official consumption: {path}") from exc
        return {}
    if not isinstance(payload, dict) or not payload.get("bootstrap"):
        if required:
            raise RuntimeError("Official snapshot is malformed or missing bootstrap authority")
        return {}
    return payload


def endpoint_health(snapshot: dict[str, Any], key: str) -> dict[str, Any]:
    row = (snapshot.get("endpoint_health") or {}).get(key) or {}
    return dict(row) if isinstance(row, dict) else {}


def snapshot_picks_for_gw(snapshot: dict[str, Any], gw: int) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    phase = snapshot.get("phase") or {}
    submitted = int(phase.get("submitted_gw") or 0)
    if submitted == int(gw) and isinstance(snapshot.get("picks"), dict):
        return snapshot.get("picks"), endpoint_health(snapshot, "picks")
    baseline = snapshot.get("purchase_baseline") or {}
    if int(baseline.get("gw") or 0) == int(gw) and isinstance(baseline.get("picks"), dict):
        return baseline.get("picks"), endpoint_health(snapshot, "purchase_baseline_picks")
    return None, {}


def snapshot_event_live_for_gw(snapshot: dict[str, Any], gw: int) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    phase = snapshot.get("phase") or {}
    scoring = int(phase.get("scoring_gw") or 0)
    if scoring == int(gw) and isinstance(snapshot.get("event_live"), dict):
        return snapshot.get("event_live"), endpoint_health(snapshot, "event_live")
    return None, {}
