from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def _parallel_fetch(requests: list[tuple[str, str, int | None]], health: dict[str, Any]) -> dict[str, Any]:
    """Fetch independent Official FPL endpoints concurrently while preserving one owner."""
    if not requests:
        return {}
    results: dict[str, Any] = {}
    workers = min(6, len(requests))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="official-fpl") as pool:
        futures = {
            pool.submit(get_json, path, retries=retries): key
            for key, path, retries in requests
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                payload, row = future.result()
            except Exception as exc:
                payload = None
                row = {"status": "UNAVAILABLE", "error": f"{type(exc).__name__}: {exc}"}
            health[key] = row
            results[key] = payload
    return results


def run() -> dict[str, Any]:
    health: dict[str, Any] = {}

    # Bootstrap remains the phase authority and must succeed before phase-scoped calls are built.
    bootstrap = _fetch("bootstrap-static/", health, "bootstrap")
    if not bootstrap:
        atomic_json(HEALTH_OUT, health)
        raise RuntimeError("FAIL CLOSED: Official bootstrap unavailable")

    phase = detect_phase(bootstrap)

    # These endpoints are mutually independent once bootstrap/phase is known.
    base_requests: list[tuple[str, str, int | None]] = [
        ("fixtures", "fixtures/", None),
        ("event_status", "event-status/", None),
        ("entry", f"entry/{TEAM_ID}/", None),
        ("history", f"entry/{TEAM_ID}/history/", None),
        ("transfers", f"entry/{TEAM_ID}/transfers/", None),
    ]

    submitted_gw = phase.get("submitted_gw")
    if submitted_gw:
        base_requests.append(("picks", f"entry/{TEAM_ID}/event/{submitted_gw}/picks/", None))

    scoring_gw = phase.get("scoring_gw")
    if scoring_gw:
        base_requests.append(("event_live", f"event/{scoring_gw}/live/", None))

    baseline_gw = PURCHASE_RECONSTRUCTION_BASELINE_GW
    base_requests.append(("purchase_baseline_picks", f"entry/{TEAM_ID}/event/{baseline_gw}/picks/", 1))

    fetched = _parallel_fetch(base_requests, health)

    fixtures = fetched.get("fixtures")
    event_status = fetched.get("event_status")
    entry = fetched.get("entry")
    history = fetched.get("history")
    transfers = fetched.get("transfers") or []
    picks = fetched.get("picks") if submitted_gw else None
    event_live = fetched.get("event_live") if scoring_gw else None
    baseline_picks = fetched.get("purchase_baseline_picks")

    if submitted_gw and "picks" in health:
        health["picks"]["status"] = "LIVE" if picks else "NOT_YET_AVAILABLE"
    if scoring_gw and "event_live" in health:
        if health["event_live"].get("status") == "LIVE" and not phase.get("is_live_event"):
            health["event_live"]["status"] = "IDLE"

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
            "independent_endpoint_fanout_parallelized": True,
            "bootstrap_remains_phase_authority": True,
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
