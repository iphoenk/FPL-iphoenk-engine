from __future__ import annotations

"""Bounded GW6 owner-provided press-news supplement for V12 evidence adapter.

V6 official facts remain untouched. The merged secondary signals are validated by
the existing report_time_evidence_v1 validator and consumed by the existing
V12 target-aware injury resolver / P1.1 player-minutes owner. No probability
or projection override is assigned here. Do not reuse after GW6 deadline.
"""

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
GW6_NEWS_PATH = ROOT / "config/intelligence/v12_gw6_20261010_team_news.json"


def merge_gw6_deadline_team_news(
    payload: Mapping[str, Any] | None,
    *,
    report_slot: str,
    target_gw: int | None,
    source_path: Path = GW6_NEWS_PATH,
) -> dict[str, Any]:
    original = dict(payload or {})
    if target_gw != 6 or original.get("contract") not in (
        None, "report_time_evidence_v1"
    ):
        return original
    try:
        slot = datetime.fromisoformat(report_slot.replace("Z", "+00:00"))
        if slot.tzinfo is None:
            return original
        source = json.loads(source_path.read_text(encoding="utf-8"))
        observed = datetime.fromisoformat(str(source["observed_at"]))
        deadline = datetime.fromisoformat(str(source["expires_at"]))
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return original
    if (
        source.get("contract") != "v12_gw6_deadline_team_news_v1"
        or source.get("target_gw") != target_gw
        or slot < observed
        or slot >= deadline
    ):
        return original
    rows = source.get("signals") or []
    if not isinstance(rows, list):
        return original
    merged = dict(original)
    merged["contract"] = "report_time_evidence_v1"
    existing = [dict(row) for row in original.get("signals") or [] if isinstance(row, Mapping)]
    seen = {
        (str(r.get("source_id")), str(r.get("subject")), str(r.get("observed_at")))
        for r in existing
    }
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        key = (str(row.get("source_id")), str(row.get("subject")), str(row.get("observed_at")))
        if key not in seen:
            existing.append(dict(row))
            seen.add(key)
    merged["signals"] = existing
    return merged
