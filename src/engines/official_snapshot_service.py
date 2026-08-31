from __future__ import annotations

import json
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from src.engines.base_state import detect_phase
from src.engines.official_fact_completeness import FALLBACK_BANNER
from src.settings import PURCHASE_RECONSTRUCTION_BASELINE_GW, TEAM_ID
from src.sources.official_fpl import get_json
from src.utils import DATA, atomic_json, iso_now, read_json

OUT = DATA / "official_snapshot.json"
RETRY_OUT = DATA / "official_snapshot.retry.json"
HEALTH_OUT = DATA / "health.json"


def _clear_retry_mirror() -> None:
    RETRY_OUT.unlink(missing_ok=True)


def _parallel_fetch(requests: list[tuple[str, str, int | None]], health: dict[str, Any]) -> dict[str, Any]:
    """Fetch independent Official FPL endpoints concurrently while preserving one owner."""
    if not requests:
        return {}
    results: dict[str, Any] = {}
    workers = min(8, len(requests))
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


def _resolve_future(future: Future, health: dict[str, Any], key: str):
    try:
        payload, row = future.result()
    except Exception as exc:
        payload = None
        row = {"status": "UNAVAILABLE", "error": f"{type(exc).__name__}: {exc}"}
    health[key] = row
    return payload


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _verified_previous_snapshot(previous: dict[str, Any]) -> bool:
    if not (previous.get("bootstrap") or {}).get("elements"):
        return False
    freshness = previous.get("official_freshness") or {}
    if str(freshness.get("state") or "").upper() == "FALLBACK":
        return bool(freshness.get("last_verified_at"))
    bootstrap_health = ((previous.get("endpoint_health") or {}).get("bootstrap") or {})
    return str(bootstrap_health.get("status") or "").upper() in {"LIVE", "FRESH"}


def _fallback_snapshot(previous: dict[str, Any], failed_health: dict[str, Any]) -> dict[str, Any] | None:
    if not _verified_previous_snapshot(previous):
        return None
    out = dict(previous)
    previous_freshness = previous.get("official_freshness") or {}
    previous_bootstrap_health = ((previous.get("endpoint_health") or {}).get("bootstrap") or {})
    last_verified_at = (
        previous_freshness.get("last_verified_at")
        or previous_bootstrap_health.get("fetched_at")
        or previous.get("generated_at")
    )
    verified_dt = _parse_dt(last_verified_at)
    age_seconds = None
    if verified_dt is not None:
        age_seconds = max(0, int((datetime.now(timezone.utc) - verified_dt).total_seconds()))
    snapshot_id = previous_freshness.get("snapshot_id") or f"bootstrap-static@{last_verified_at or 'unknown'}"
    endpoint_health = dict(previous.get("endpoint_health") or {})
    endpoint_health["bootstrap"] = dict(failed_health)
    out.update({
        "generated_at": iso_now(),
        "endpoint_health": endpoint_health,
        "official_freshness": {
            "state": "FALLBACK",
            "fallback": True,
            "banner": FALLBACK_BANNER,
            "snapshot_id": snapshot_id,
            "last_verified_at": last_verified_at,
            "age_seconds": age_seconds,
            "confidence": "DOWNGRADED",
            "fresh_pull_failed_at": failed_health.get("fetched_at"),
            "fresh_pull_error": failed_health.get("error"),
        },
    })
    governance = dict(out.get("governance") or {})
    governance.update({
        "fallback_never_represented_as_fresh": True,
        "fallback_requires_previously_verified_bootstrap": True,
        "fallback_banner_exact": FALLBACK_BANNER,
        "workspace_retry_mirror_created_only_from_fresh_pull": True,
    })
    out["governance"] = governance
    return out


def run() -> dict[str, Any]:
    health: dict[str, Any] = {}
    baseline_gw = PURCHASE_RECONSTRUCTION_BASELINE_GW
    previous = read_json(OUT, {})

    # Bootstrap is the phase authority, but most account/global endpoints do not
    # depend on phase. Start those requests at the same time as bootstrap so a
    # fresh production run does not pay two sequential network waves.
    phase_independent: list[tuple[str, str, int | None]] = [
        ("fixtures", "fixtures/", None),
        ("event_status", "event-status/", None),
        ("entry", f"entry/{TEAM_ID}/", None),
        ("history", f"entry/{TEAM_ID}/history/", None),
        ("transfers", f"entry/{TEAM_ID}/transfers/", None),
        ("purchase_baseline_picks", f"entry/{TEAM_ID}/event/{baseline_gw}/picks/", 1),
    ]

    independent_results: dict[str, Any] = {}
    workers = 1 + len(phase_independent)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="official-fpl-bootstrap") as pool:
        bootstrap_future = pool.submit(get_json, "bootstrap-static/")
        independent_futures = {
            pool.submit(get_json, path, retries=retries): key
            for key, path, retries in phase_independent
        }

        bootstrap = _resolve_future(bootstrap_future, health, "bootstrap")
        if not bootstrap:
            for future, key in independent_futures.items():
                _resolve_future(future, health, key)
            _clear_retry_mirror()
            fallback = _fallback_snapshot(previous, health.get("bootstrap") or {})
            atomic_json(HEALTH_OUT, health)
            if fallback is not None:
                atomic_json(OUT, fallback)
                return fallback
            raise RuntimeError("FAIL CLOSED: Official bootstrap unavailable and no verified fallback snapshot exists")

        phase = detect_phase(bootstrap)

        for future in as_completed(independent_futures):
            key = independent_futures[future]
            independent_results[key] = _resolve_future(future, health, key)

    # Only phase-scoped endpoints wait for bootstrap/phase detection.
    phase_requests: list[tuple[str, str, int | None]] = []
    submitted_gw = phase.get("submitted_gw")
    if submitted_gw:
        phase_requests.append(("picks", f"entry/{TEAM_ID}/event/{submitted_gw}/picks/", None))

    scoring_gw = phase.get("scoring_gw")
    if scoring_gw:
        phase_requests.append(("event_live", f"event/{scoring_gw}/live/", None))

    phase_results = _parallel_fetch(phase_requests, health)

    fixtures = independent_results.get("fixtures")
    event_status = independent_results.get("event_status")
    entry = independent_results.get("entry")
    history = independent_results.get("history")
    transfers = independent_results.get("transfers") or []
    baseline_picks = independent_results.get("purchase_baseline_picks")
    picks = phase_results.get("picks") if submitted_gw else None
    event_live = phase_results.get("event_live") if scoring_gw else None

    if submitted_gw and "picks" in health:
        health["picks"]["status"] = "LIVE" if picks else "NOT_YET_AVAILABLE"
    if scoring_gw and "event_live" in health:
        if health["event_live"].get("status") == "LIVE" and not phase.get("is_live_event"):
            health["event_live"]["status"] = "IDLE"

    bootstrap_fetched_at = (health.get("bootstrap") or {}).get("fetched_at") or iso_now()
    snapshot_id = f"bootstrap-static@{bootstrap_fetched_at}"
    payload = {
        "schema_version": 2,
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
        "official_freshness": {
            "state": "FRESH",
            "fallback": False,
            "banner": None,
            "snapshot_id": snapshot_id,
            "last_verified_at": bootstrap_fetched_at,
            "age_seconds": 0,
            "confidence": "HIGH",
        },
        "governance": {
            "single_owner_for_standard_official_fetches": True,
            "downstream_services_consume_snapshot_not_network": True,
            "official_fpl_is_native_authority": True,
            "independent_endpoint_fanout_parallelized": True,
            "phase_independent_fetches_overlap_bootstrap": True,
            "phase_scoped_fetches_wait_for_bootstrap_authority": True,
            "bootstrap_remains_phase_authority": True,
            "fallback_never_represented_as_fresh": True,
            "fallback_requires_previously_verified_bootstrap": True,
            "fallback_banner_exact": FALLBACK_BANNER,
            "workspace_retry_mirror_created_only_from_fresh_pull": True,
            "workspace_retry_mirror_has_zero_publication_authority": True,
        },
    }
    atomic_json(OUT, payload)
    atomic_json(RETRY_OUT, payload)
    atomic_json(HEALTH_OUT, health)
    return payload


if __name__ == "__main__":
    out = run()
    print(json.dumps({
        "team_id": out.get("team_id"),
        "planning_gw": (out.get("phase") or {}).get("planning_gw"),
        "submitted_gw": (out.get("phase") or {}).get("submitted_gw"),
        "official_freshness": out.get("official_freshness"),
    }, ensure_ascii=False))
