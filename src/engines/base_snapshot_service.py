from __future__ import annotations

import json
import os

from src.engines.snapshot_meta import age_minutes, changes, snapshot_id, source_meta
from src.rules import ruleset_metadata
from src.settings import FAIL_CLOSED, PRICE_SUMMARY_LIST_SIZE, TEAM_ID
from src.utils import DATA, ROOT, append_jsonl, atomic_json, iso_now, read_json
from src.version import ENGINE_VERSION, SCHEMA_VERSION

ENTRY_FIELDS = [
    "summary_overall_points",
    "summary_overall_rank",
    "summary_event_points",
    "summary_event_rank",
    "current_event",
    "last_deadline_bank",
    "last_deadline_value",
    "last_deadline_total_transfers",
]


def _reusable_state_from_previous(previous: dict) -> tuple[dict, dict, dict]:
    """Carry only registry-declared state owned by services reusable in the active profile.

    FAST/LIVE hydrate a previously accepted latest.json before base fan-in. The base snapshot
    is rebuilt from fresh authoritative core data, but reusable downstream services may be
    skipped later. Their declared latest keys therefore need to survive until either the
    reused artifact is accepted or a fresh service promotion overwrites them.
    """
    profile_name = os.getenv("FPL_EXECUTION_PROFILE", "").strip()
    if not profile_name or not previous:
        return {}, {}, {}
    profiles = read_json(ROOT / "config" / "runtime" / "execution_profiles.json", {})
    services = read_json(ROOT / "config" / "v3_service_registry.json", {})
    profile = ((profiles.get("profiles") or {}).get(profile_name) or {})
    reusable = set((profile.get("reuse_services") or {}).keys())
    if not reusable:
        return {}, {}, {}

    service_map = services.get("services") or {}
    previous_files = previous.get("files") if isinstance(previous.get("files"), dict) else {}
    carried: dict = {}
    carried_files: dict = {}
    audit: dict = {}
    for service_name in sorted(reusable):
        spec = service_map.get(service_name) or {}
        owned_keys = []
        owned_file_keys = []
        for key in spec.get("latest_keys") or []:
            key = str(key)
            if key in previous:
                carried[key] = previous[key]
                owned_keys.append(key)
        for key in spec.get("latest_file_keys") or []:
            key = str(key)
            if key in previous_files:
                carried_files[key] = previous_files[key]
                owned_file_keys.append(key)
        if owned_keys or owned_file_keys:
            audit[service_name] = {
                "latest_keys": owned_keys,
                "latest_file_keys": owned_file_keys,
            }
    return carried, carried_files, audit


def run(mode: str = "daily") -> dict:
    previous = read_json(DATA / "latest.json", {})
    official = read_json(DATA / "official_snapshot.json", {})
    team = read_json(DATA / "team.json", {})
    live = read_json(DATA / "live.json", {})
    prices = read_json(DATA / "prices.json", {})
    universe = read_json(DATA / "universe.json", {})
    chips = read_json(DATA / "chips.json", {})
    advanced = read_json(DATA / "advanced_stats_sync.json", {})
    health = read_json(DATA / "health.json", {})

    required = {
        "official_snapshot": official,
        "team": team,
        "live": live,
        "prices": prices,
        "universe": universe,
        "chips": chips,
        "health": health,
    }
    missing = [name for name, payload in required.items() if not payload]
    if missing:
        raise RuntimeError(f"base snapshot missing required upstream artifacts: {missing}")

    phase = official.get("phase") or {}
    entry_summary = team.get("entry") or {}
    history = official.get("history") or {}
    transfers = list(official.get("transfers") or [])
    picks = official.get("picks")
    submitted = phase.get("submitted_gw")
    used_chips = list(chips.get("used") or [])
    ruleset = ruleset_metadata()
    native = {
        "entry": entry_summary,
        "history": {
            "current": list(history.get("current") or []),
            "chips": used_chips,
            "past": list(history.get("past") or []),
        },
        "transfers": transfers,
        "picks": {"gw": submitted, "payload": picks} if submitted else None,
    }
    provenance = {
        key: source_meta(health, key)
        for key in ["bootstrap", "fixtures", "event_status", "entry", "history", "transfers", "picks"]
        if key in health
    }
    freshness = {
        key: {
            "fetched_at": value.get("fetched_at"),
            "age_minutes": age_minutes(value.get("fetched_at")),
            "status": value.get("status"),
        }
        for key, value in provenance.items()
    }
    delta = changes(previous.get("entry") or {}, entry_summary, ENTRY_FIELDS)
    totals = team.get("totals") or {}
    generated_at = iso_now()
    carried_state, carried_files, carry_audit = _reusable_state_from_previous(previous)
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "generated_at": generated_at,
        "mode": mode,
        "team_id": TEAM_ID,
        "phase": phase,
        "endpoint_health": health,
        "entry": entry_summary,
        "squad_authority": team.get("squad_authority"),
        "advanced_stats_sync": advanced,
        "team_summary": {
            "itb": totals.get("itb"),
            "market_value": totals.get("market_value"),
            "sell_value": totals.get("sell_value"),
        },
        "live_summary": {
            "status": live.get("status"),
            "gross_points": live.get("gross_points"),
            "net_points": live.get("net_points"),
        },
        "price_summary": {
            "confirmed_changes": prices.get("confirmed_changes") or [],
            "top_buy_pressure": list(prices.get("top_buy_pressure") or [])[:PRICE_SUMMARY_LIST_SIZE],
        },
        "files": {
            "team": "data/team.json",
            "live": "data/live.json",
            "prices": "data/prices.json",
            "health": "data/health.json",
            "universe": "data/universe.json",
            "chips": "data/chips.json",
            "native": "data/native.json",
            "advanced_stats_sync": "data/advanced_stats_sync.json",
        },
        "meta": {
            "direct_fpl_api_authority": True,
            "fail_closed": FAIL_CLOSED,
            "advanced_stats_are_community_enrichment": True,
            "leakage_guard_required_for_predictive_training": True,
            "base_snapshot_is_fan_in_only": True,
            "reused_latest_state_profile": os.getenv("FPL_EXECUTION_PROFILE", "").strip() or None,
            "reused_latest_state_carried_forward": carry_audit,
        },
        "native": native,
        "provenance": provenance,
        "source_freshness": freshness,
        "change_log": delta,
        "snapshot_id": snapshot_id(native),
        "ruleset": ruleset,
        "chip_ledger": chips.get("ledger") or {},
    }
    snapshot.update(carried_state)
    snapshot["files"].update(carried_files)
    atomic_json(DATA / "latest.json", snapshot)
    atomic_json(DATA / "native.json", {"generated_at": generated_at, "snapshot_id": snapshot["snapshot_id"], **native})
    archive_gw = phase.get("submitted_gw") or phase.get("planning_gw")
    if archive_gw:
        atomic_json(DATA / "gw" / f"{int(archive_gw):02d}.json", snapshot)
    append_jsonl(DATA / "history.jsonl", snapshot)
    return snapshot


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["daily", "deadline", "live"], default="daily", nargs="?")
    args = parser.parse_args()
    out = run(args.mode)
    print(json.dumps({
        "engine_version": out.get("engine_version"),
        "schema_version": out.get("schema_version"),
        "planning_gw": (out.get("phase") or {}).get("planning_gw"),
        "snapshot_id": out.get("snapshot_id"),
        "reused_latest_state_carried_forward": (out.get("meta") or {}).get("reused_latest_state_carried_forward"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
