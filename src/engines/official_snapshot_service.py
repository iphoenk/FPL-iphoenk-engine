from __future__ import annotations

import json
from typing import Any

from src.engines.base_state import detect_phase
from src.settings import PURCHASE_RECONSTRUCTION_BASELINE_GW, TEAM_ID
from src.sources.official_fpl import get_json
from src.utils import DATA, atomic_json, iso_now

OUT = DATA / "official_snapshot.json"
HEALTH_OUT = DATA / "health.json"


def _fetch(path: str, health: dict[str, Any], key: str, *, retries: int | None = None):
    payload, row = get_json(path, retries=retries)
    health[key] = row
    return payload


def run() -> dict[str, Any]:
    health: dict[str, Any] = {}
    bootstrap = _fetch("bootstrap-static/", health, "bootstrap")
    if not bootstrap:
        atomic_json(HEALTH_OUT, health)
        raise RuntimeError("FAIL CLOSED: Official bootstrap unavailable")

    fixtures = _fetch("fixtures/", health, "fixtures")
    event_status = _fetch("event-status/", health, "event_status")
    entry = _fetch(f"entry/{TEAM_ID}/", health, "entry")
    history = _fetch(f"entry/{TEAM_ID}/history/", health, "history")
    transfers = _fetch(f"entry/{TEAM_ID}/transfers/", health, "transfers") or []
    phase = detect_phase(bootstrap)

    picks = None
    submitted_gw = phase.get("submitted_gw")
    if submitted_gw:
        picks = _fetch(f"entry/{TEAM_ID}/event/{submitted_gw}/picks/", health, "picks")
        health["picks"]["status"] = "LIVE" if picks else "NOT_YET_AVAILABLE"

    event_live = None
    scoring_gw = phase.get("scoring_gw")
    if scoring_gw:
        event_live = _fetch(f"event/{scoring_gw}/live/", health, "event_live")
        if health["event_live"].get("status") == "LIVE" and not phase.get("is_live_event"):
            health["event_live"]["status"] = "IDLE"

    baseline_gw = PURCHASE_RECONSTRUCTION_BASELINE_GW
    baseline_picks, baseline_health = get_json(f"entry/{TEAM_ID}/event/{baseline_gw}/picks/", retries=1)
    health["purchase_baseline_picks"] = baseline_health

    payload = {
        "schema_version": 1,
        "generated_at": iso_now(),
        "team_id": TEAM_ID,
        "phase": phase,
        "bootstrap": bootstrap,
        "fixtures": fixtures or [],
        "event_status": event_status,
        "entry": entry,
        "history": history,
        "transfers": transfers,
        "picks": picks,
        "event_live": event_live,
        "purchase_baseline": {
            "gw": baseline_gw,
            "picks": baseline_picks,
        },
        "endpoint_health": health,
        "governance": {
            "single_owner_for_standard_official_fetches": True,
            "downstream_services_consume_snapshot_not_network": True,
            "official_fpl_is_native_authority": True,
        },
    }
    atomic_json(OUT, payload)
    atomic_json(HEALTH_OUT, health)
    return payload


if __name__ == "__main__":
    out = run()
    print(json.dumps({
        "team_id": out.get("team_id"),
        "planning_gw": (out.get("phase") or {}).get("planning_gw"),
        "submitted_gw": (out.get("phase") or {}).get("submitted_gw"),
    }, ensure_ascii=False))
