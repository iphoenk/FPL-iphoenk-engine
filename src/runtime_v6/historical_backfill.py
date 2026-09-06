from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .historical_availability import (
    BEFORE_FIRST_OFFICIAL_ENTRY_HISTORY_GW,
    OFFICIAL_GW_RECORD_NOT_AVAILABLE,
    captain_multiplier_consistent,
    classify_completed_gw_official_absence,
    history_rows,
)
from .league_prefetch import fetch_all_standings
from .official_fpl_client import OfficialFPLClient
from .personal_prefetch import discover_memberships, normalise_submitted_picks, resolve_priority_leagues
from .prefetch_contract import NORMALIZATION_VERSION, digest, iso, load_consumer_context, read_json, utc_now, write_json
from .security import safe_error

COHORT_SEMANTICS = "CURRENT_COHORT_HISTORY"
MEMBERSHIP_STATUS = "UNKNOWN"
MEMBERSHIP_EVIDENCE = "CURRENT_STANDINGS_COHORT_ONLY"
LIVE_HISTORICAL = "LIVE_FETCHED_HISTORICAL_GW"
REUSED_HISTORICAL = "IMMUTABLE_HISTORICAL_CACHE_REUSED"
LIVE_CURRENT = "LIVE_FETCHED_CURRENT_GW_POST_DEADLINE"
REUSED_CURRENT = "POST_DEADLINE_CURRENT_GW_SUBMITTED_PICKS_CACHE_REUSED"
HISTORICAL_SCHEMA_VERSION = 4


class HistoricalBackfillError(RuntimeError):
    pass


def _parse_deadline(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _event_catalog(bootstrap: dict[str, Any], *, now: datetime | None = None) -> dict[int, dict[str, Any]]:
    current_time = now or utc_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)
    catalog: dict[int, dict[str, Any]] = {}
    for event in bootstrap.get("events") or []:
        if not isinstance(event, dict) or event.get("id") is None:
            continue
        gw = int(event["id"])
        deadline = _parse_deadline(event.get("deadline_time"))
        finished = event.get("finished") is True
        is_current = event.get("is_current") is True
        post_deadline = deadline is not None and deadline <= current_time
        if finished:
            semantics, eligible = "COMPLETED_GW", True
        elif is_current and post_deadline:
            semantics, eligible = "CURRENT_GW_POST_DEADLINE", True
        else:
            semantics = "CURRENT_GW_PRE_DEADLINE" if is_current else "FUTURE_OR_UNFINISHED_GW"
            eligible = False
        catalog[gw] = {
            "gw": gw,
            "finished": finished,
            "is_current": is_current,
            "deadline_time": event.get("deadline_time"),
            "post_deadline": post_deadline,
            "historical_backfill_eligible": eligible,
            "gw_semantics": semantics,
        }
    return catalog


def validate_gw_range(
    gw_from: int,
    gw_to: int,
    bootstrap: dict[str, Any],
    *,
    now: datetime | None = None,
) -> tuple[int, int]:
    gw_from, gw_to = int(gw_from), int(gw_to)
    if gw_from < 1 or gw_to < 1:
        raise HistoricalBackfillError("GW range must start at 1 or later")
    if gw_from > gw_to:
        raise HistoricalBackfillError("gw_from cannot be greater than gw_to")
    catalog = _event_catalog(bootstrap, now=now)
    if not catalog:
        raise HistoricalBackfillError("Official FPL exposes no event catalog")
    requested = list(range(gw_from, gw_to + 1))
    missing = [gw for gw in requested if gw not in catalog]
    if missing:
        raise HistoricalBackfillError(f"requested GW is outside Official event catalog: {missing}")
    ineligible = [gw for gw in requested if not catalog[gw]["historical_backfill_eligible"]]
    if ineligible:
        states = {gw: catalog[gw]["gw_semantics"] for gw in ineligible}
        raise HistoricalBackfillError(
            f"historical backfill accepts completed GWs and current post-deadline GW only: {states}"
        )
    return gw_from, gw_to


def _retry_count(result: dict[str, Any] | None) -> int:
    if not isinstance(result, dict):
        return 0
    attempts = result.get("attempts")
    return max(0, int(attempts) - 1) if isinstance(attempts, int) else 0


def _historical_record(entry_id: int, gw: int, result: dict[str, Any], *, completed: bool) -> dict[str, Any]:
    origin = LIVE_HISTORICAL if completed else LIVE_CURRENT
    normal = normalise_submitted_picks(entry_id, gw, result, origin=origin)
    record = {
        "entry_id": entry_id,
        "gw": gw,
        "status": normal.get("status"),
        "origin": origin,
        "current_cohort_member": True,
        "cohort_semantics": COHORT_SEMANTICS,
        "membership_at_gw_status": MEMBERSHIP_STATUS,
        "membership_evidence": MEMBERSHIP_EVIDENCE,
        "historical_membership_confirmed": None,
        "completed_gw": completed,
        "submitted_picks_post_deadline_fact": True,
        "checked_at": (normal.get("lineage") or {}).get("checked_at"),
        "http_status": (normal.get("lineage") or {}).get("http_status"),
        "payload_digest": (normal.get("lineage") or {}).get("payload_digest"),
        "attempts": result.get("attempts"),
        "active_chip": normal.get("active_chip"),
        "picks": normal.get("picks") or [],
        "lineage": normal.get("lineage"),
    }
    if record["status"] == "AVAILABLE" and len(record["picks"]) != 15:
        record["status"] = "INVALID_PICK_COUNT"
    record["record_digest"] = digest(record)
    return record


def _cache_valid(record: Any, *, season: str, league_id: int, gw: int, entry_id: int) -> bool:
    if not isinstance(record, dict):
        return False
    if record.get("entry_id") != entry_id or record.get("gw") != gw:
        return False
    factual_available = record.get("status") == "AVAILABLE"
    factual_absence = (
        record.get("completed_gw") is True
        and record.get("official_exclusion") is True
        and record.get("official_availability_status") == OFFICIAL_GW_RECORD_NOT_AVAILABLE
        and record.get("official_exclusion_reason") == BEFORE_FIRST_OFFICIAL_ENTRY_HISTORY_GW
    )
    if not (factual_available or factual_absence):
        return False
    if record.get("cache_identity") != {"season": season, "gw": gw, "league_id": league_id, "entry_id": entry_id}:
        return False
    expected = record.get("record_digest")
    return isinstance(expected, str) and bool(expected) and expected == digest(
        {key: value for key, value in record.items() if key != "record_digest"}
    )


def acquire_historical_picks(
    client: Any,
    *,
    previous_path: Path,
    season: str,
    league_id: int,
    gw: int,
    manager_ids: list[int],
    workers: int,
    force: bool,
    cache_enabled: bool,
    completed: bool = True,
) -> tuple[dict[str, Any], dict[str, int]]:
    previous = (read_json(previous_path) or {}) if cache_enabled else {}
    previous_entries = previous.get("entries") if isinstance(previous.get("entries"), dict) else {}
    manager_ids = sorted({int(entry_id) for entry_id in manager_ids})
    entries: dict[str, dict[str, Any]] = {}
    misses: list[int] = []
    cache_hits = 0

    for entry_id in manager_ids:
        cached = previous_entries.get(str(entry_id))
        if not force and _cache_valid(cached, season=season, league_id=league_id, gw=gw, entry_id=entry_id):
            body = {key: value for key, value in cached.items() if key != "record_digest"}
            body["origin"] = REUSED_HISTORICAL if completed else REUSED_CURRENT
            body["completed_gw"] = completed
            body["lineage"] = {**dict(body.get("lineage") or {}), "origin": body["origin"]}
            body["record_digest"] = digest(body)
            entries[str(entry_id)] = body
            cache_hits += 1
        else:
            misses.append(entry_id)

    def fetch(entry_id: int) -> tuple[int, dict[str, Any]]:
        record = _historical_record(entry_id, gw, client.submitted_picks(entry_id, gw), completed=completed)
        record["cache_identity"] = {"season": season, "gw": gw, "league_id": league_id, "entry_id": entry_id}
        record["record_digest"] = digest({key: value for key, value in record.items() if key != "record_digest"})
        return entry_id, record

    used_workers = 0
    if misses:
        used_workers = max(1, min(int(workers), len(misses)))
        with ThreadPoolExecutor(max_workers=used_workers, thread_name_prefix="v6-historical-picks") as pool:
            futures = {pool.submit(fetch, entry_id): entry_id for entry_id in misses}
            for future in as_completed(futures):
                entry_id = futures[future]
                try:
                    _, record = future.result()
                except Exception as exc:
                    record = {
                        "entry_id": entry_id,
                        "gw": gw,
                        "status": "UNAVAILABLE",
                        "origin": LIVE_HISTORICAL if completed else LIVE_CURRENT,
                        "cache_identity": {"season": season, "gw": gw, "league_id": league_id, "entry_id": entry_id},
                        "current_cohort_member": True,
                        "cohort_semantics": COHORT_SEMANTICS,
                        "membership_at_gw_status": MEMBERSHIP_STATUS,
                        "membership_evidence": MEMBERSHIP_EVIDENCE,
                        "historical_membership_confirmed": None,
                        "completed_gw": completed,
                        "submitted_picks_post_deadline_fact": True,
                        "attempts": None,
                        "active_chip": None,
                        "picks": [],
                        "lineage": {
                            "authority": "OFFICIAL_FPL",
                            "endpoint_class": "submitted_picks",
                            "gw": gw,
                            "entry_id": entry_id,
                            "origin": LIVE_HISTORICAL if completed else LIVE_CURRENT,
                            "error": safe_error(exc),
                        },
                    }
                    record["record_digest"] = digest(record)
                entries[str(entry_id)] = record

    available = [entry_id for entry_id in manager_ids if entries[str(entry_id)].get("status") == "AVAILABLE"]
    missing = [entry_id for entry_id in manager_ids if entries[str(entry_id)].get("status") != "AVAILABLE"]
    manager_set_digest = digest(manager_ids)
    artifact = {
        "schema_version": HISTORICAL_SCHEMA_VERSION,
        "normalization_version": NORMALIZATION_VERSION,
        "season": season,
        "league_id": league_id,
        "gw": gw,
        "gw_semantics": "COMPLETED_GW" if completed else "CURRENT_GW_POST_DEADLINE",
        "cohort_semantics": COHORT_SEMANTICS,
        "membership_at_gw_status": MEMBERSHIP_STATUS,
        "generated_at": iso(utc_now()),
        "immutable_completed_gw_facts": completed,
        "submitted_picks_cache_reusable": True,
        "manager_set_digest": manager_set_digest,
        "expected_manager_count": len(manager_ids),
        "collected_manager_count": len(available),
        "submitted_picks_available_count": len(available),
        "submitted_picks_missing_count": len(missing),
        "coverage_percent": round(len(available) * 100 / len(manager_ids), 4) if manager_ids else 0.0,
        "missing_entry_ids": missing,
        "complete": not missing,
        "entries": {key: entries[key] for key in sorted(entries, key=int)},
        "cache": {
            "enabled": bool(cache_enabled),
            "force": bool(force),
            "cache_hits": cache_hits,
            "cache_misses": len(misses),
            "previous_manager_set_digest": previous.get("manager_set_digest"),
            "manager_set_changed": bool(previous) and previous.get("manager_set_digest") != manager_set_digest,
        },
        "authority": "OFFICIAL_FPL",
        "lineage": {
            "authority": "OFFICIAL_FPL",
            "endpoint_class": "submitted_picks",
            "origin_counts": {
                LIVE_HISTORICAL: sum(1 for row in entries.values() if row.get("origin") == LIVE_HISTORICAL),
                REUSED_HISTORICAL: sum(1 for row in entries.values() if row.get("origin") == REUSED_HISTORICAL),
                LIVE_CURRENT: sum(1 for row in entries.values() if row.get("origin") == LIVE_CURRENT),
                REUSED_CURRENT: sum(1 for row in entries.values() if row.get("origin") == REUSED_CURRENT),
            },
        },
        "governance": {"data_only": True, "analytics_published": False},
    }
    return artifact, {
        "cache_hits": cache_hits,
        "cache_misses": len(misses),
        "maximum_concurrency_used": used_workers,
        "retry_count": sum(
            max(0, int(row.get("attempts") or 1) - 1)
            for row in entries.values()
            if row.get("origin") in {LIVE_HISTORICAL, LIVE_CURRENT}
        ),
    }


def _entry_history(client: Any, entry_id: int) -> dict[str, Any]:
    public = getattr(client, "entry_history", None)
    if callable(public):
        return public(int(entry_id))
    request = getattr(client, "_request", None)
    if not callable(request):
        raise HistoricalBackfillError("Official FPL client does not expose shared request transport")
    return request("entry_history", f"entry/{int(entry_id)}/history/")


def _history_cache_record(entry_id: int, result: dict[str, Any]) -> dict[str, Any]:
    record = {
        "entry_id": entry_id,
        "status": result.get("status"),
        "endpoint_class": result.get("endpoint_class") or "entry_history",
        "checked_at": result.get("checked_at"),
        "http_status": result.get("http_status"),
        "payload_digest": result.get("payload_digest"),
        "payload": result.get("payload") if result.get("status") == "LIVE" else None,
        "attempts": result.get("attempts"),
        "error": result.get("error"),
        "origin": result.get("origin") or LIVE_HISTORICAL,
        "authority": "OFFICIAL_FPL",
    }
    record["record_digest"] = digest(record)
    return record


def _cached_history_result(record: Any) -> dict[str, Any] | None:
    if not isinstance(record, dict) or record.get("status") != "LIVE":
        return None
    expected = record.get("record_digest")
    if not isinstance(expected, str) or expected != digest({key: value for key, value in record.items() if key != "record_digest"}):
        return None
    return {
        "status": "LIVE",
        "endpoint_class": "entry_history",
        "checked_at": record.get("checked_at"),
        "http_status": record.get("http_status") or 200,
        "payload_digest": record.get("payload_digest"),
        "payload": record.get("payload") or {},
        "attempts": 0,
        "duration_ms": 0,
        "error": None,
        "origin": REUSED_HISTORICAL,
    }


def acquire_entry_histories(
    client: Any,
    manager_ids: list[int],
    workers: int,
    *,
    previous_entry_histories: dict[str, Any] | None,
    force: bool,
    allow_cache_reuse: bool = True,
) -> tuple[dict[int, dict[str, Any]], dict[str, int]]:
    previous_entries = dict((previous_entry_histories or {}).get("entries") or {})
    manager_ids = sorted({int(value) for value in manager_ids})
    results: dict[int, dict[str, Any]] = {}
    misses: list[int] = []
    hits = 0
    for entry_id in manager_ids:
        cached = None
        if allow_cache_reuse and not force:
            cached = _cached_history_result(previous_entries.get(str(entry_id)))
        if cached is not None:
            results[entry_id] = cached
            hits += 1
        else:
            misses.append(entry_id)

    used_workers = max(1, min(int(workers), len(misses))) if misses else 0
    if misses:
        with ThreadPoolExecutor(max_workers=used_workers, thread_name_prefix="v6-entry-history") as pool:
            futures = {pool.submit(_entry_history, client, entry_id): entry_id for entry_id in misses}
            for future in as_completed(futures):
                entry_id = futures[future]
                try:
                    results[entry_id] = future.result()
                except Exception as exc:
                    results[entry_id] = {
                        "status": "FAILED",
                        "endpoint_class": "entry_history",
                        "payload": None,
                        "attempts": 0,
                        "error": safe_error(exc),
                    }
    failed = sum(1 for result in results.values() if result.get("status") != "LIVE")
    miss_set = set(misses)
    return results, {
        "history_cache_hits": hits,
        "history_cache_misses": len(misses),
        "history_requests": len(misses),
        "history_failed": failed,
        "retry_count": sum(_retry_count(result) for entry_id, result in results.items() if entry_id in miss_set),
        "maximum_concurrency_used": used_workers,
    }


def _entry_histories_artifact(
    *,
    season: str,
    league_id: int,
    results: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    entries = {
        str(entry_id): _history_cache_record(entry_id, result)
        for entry_id, result in sorted(results.items())
    }
    return {
        "schema_version": HISTORICAL_SCHEMA_VERSION,
        "season": season,
        "league_id": league_id,
        "generated_at": iso(utc_now()),
        "entries": entries,
        "authority": "OFFICIAL_FPL",
        "governance": {"data_only": True, "raw_entry_history_cache": True},
    }


def _apply_official_absence_classification(
    picks: dict[str, Any],
    histories: dict[int, dict[str, Any]],
    manager_ids: list[int],
    *,
    gw: int,
    completed: bool,
) -> dict[int, dict[str, Any]]:
    exclusions: dict[int, dict[str, Any]] = {}
    entries = picks.get("entries") or {}
    for entry_id in manager_ids:
        record = entries.get(str(entry_id))
        exclusion = classify_completed_gw_official_absence(
            pick_record=record,
            history_result=histories.get(entry_id),
            gw=gw,
            completed=completed,
        )
        if exclusion is None:
            if isinstance(record, dict) and record.get("official_exclusion") is True:
                record.pop("official_availability_status", None)
                record.pop("official_exclusion", None)
                record.pop("official_exclusion_reason", None)
                record.pop("official_exclusion_evidence", None)
                record["record_digest"] = digest({key: value for key, value in record.items() if key != "record_digest"})
            continue
        exclusions[entry_id] = exclusion
        if isinstance(record, dict):
            record["official_availability_status"] = exclusion["official_availability_status"]
            record["official_exclusion"] = True
            record["official_exclusion_reason"] = exclusion["official_exclusion_reason"]
            record["official_exclusion_evidence"] = exclusion
            record["record_digest"] = digest({key: value for key, value in record.items() if key != "record_digest"})

    raw_missing = {int(entry_id) for entry_id, record in entries.items() if record.get("status") != "AVAILABLE"}
    unresolved = sorted(raw_missing - set(exclusions))
    picks["officially_excluded_entry_ids"] = sorted(exclusions)
    picks["officially_excluded_manager_count"] = len(exclusions)
    picks["official_exclusion_reason_counts"] = {
        BEFORE_FIRST_OFFICIAL_ENTRY_HISTORY_GW: sum(
            1 for item in exclusions.values() if item.get("official_exclusion_reason") == BEFORE_FIRST_OFFICIAL_ENTRY_HISTORY_GW
        )
    }
    picks["eligible_manager_count"] = len(manager_ids) - len(exclusions)
    picks["unresolved_missing_entry_ids"] = unresolved
    picks["unresolved_submitted_picks_missing_count"] = len(unresolved)
    picks["complete"] = not unresolved
    return exclusions


def _history_row(result: dict[str, Any], gw: int) -> dict[str, Any] | None:
    return history_rows(result).get(gw)


def _chip_events(result: dict[str, Any]) -> dict[int, str]:
    if result.get("status") != "LIVE":
        return {}
    values: dict[int, str] = {}
    for chip in ((result.get("payload") or {}).get("chips") or []):
        if isinstance(chip, dict) and chip.get("event") is not None and chip.get("name"):
            values[int(chip["event"])] = str(chip["name"])
    return values


def _event_live_artifact(result: dict[str, Any], gw: int, *, completed: bool) -> dict[str, Any]:
    elements = []
    if result.get("status") == "LIVE":
        for item in ((result.get("payload") or {}).get("elements") or []):
            if not isinstance(item, dict) or item.get("id") is None:
                continue
            stats = item.get("stats") or {}
            elements.append(
                {
                    "element_id": int(item["id"]),
                    "total_points": stats.get("total_points"),
                    "minutes": stats.get("minutes"),
                    "bonus": stats.get("bonus"),
                    "bps": stats.get("bps"),
                }
            )
    return {
        "schema_version": HISTORICAL_SCHEMA_VERSION,
        "gw": gw,
        "gw_semantics": "COMPLETED_GW" if completed else "CURRENT_GW_POST_DEADLINE",
        "status": "AVAILABLE" if result.get("status") == "LIVE" else "UNAVAILABLE",
        "checked_at": result.get("checked_at"),
        "elements": elements,
        "authority": "OFFICIAL_FPL",
        "lineage": {
            "endpoint_class": "event_live",
            "http_status": result.get("http_status"),
            "payload_digest": result.get("payload_digest"),
            "attempts": result.get("attempts"),
        },
        "governance": {"data_only": True, "manager_scoring_analytics": "DOWNSTREAM"},
    }


def _reconciliation(
    entry_id: int,
    gw: int,
    pick_record: dict[str, Any],
    history_result: dict[str, Any],
    *,
    completed: bool,
) -> dict[str, Any]:
    history = _history_row(history_result, gw)
    chip_history = _chip_events(history_result).get(gw)
    picks = pick_record.get("picks") or []
    captains = [pick for pick in picks if pick.get("captain")]
    vice = [pick for pick in picks if pick.get("vice_captain")]
    excluded = pick_record.get("official_exclusion") is True
    checks = {
        "exact_15_picks": len(picks) == 15 if pick_record.get("status") == "AVAILABLE" else None,
        "one_captain": len(captains) == 1 if pick_record.get("status") == "AVAILABLE" else None,
        "one_vice": len(vice) == 1 if pick_record.get("status") == "AVAILABLE" else None,
        "captain_multiplier_consistent": captain_multiplier_consistent(picks) if pick_record.get("status") == "AVAILABLE" else None,
        "chip_consistent": pick_record.get("active_chip") == chip_history if history is not None else None,
    }
    return {
        "entry_id": entry_id,
        "gw": gw,
        "gw_semantics": "COMPLETED_GW" if completed else "CURRENT_GW_POST_DEADLINE",
        "submitted_picks_status": pick_record.get("status"),
        "history_available": history is not None,
        "history_required_for_complete": completed and not excluded,
        "active_chip_submitted_picks": pick_record.get("active_chip"),
        "active_chip_entry_history": chip_history,
        "official_exclusion": excluded,
        "official_exclusion_reason": pick_record.get("official_exclusion_reason"),
        "official_exclusion_evidence": pick_record.get("official_exclusion_evidence"),
        "checks": checks,
        "consistent": True if excluded else all(value is not False for value in checks.values()),
        "authority": "OFFICIAL_FPL_RECONCILIATION_INTEGRITY",
    }


class HistoricalBackfillService:
    def __init__(self, *, config: dict[str, Any], output_root: Path, client: Any | None = None) -> None:
        self.config = config
        self.output_root = Path(output_root)
        self.client = client or OfficialFPLClient(
            timeout_seconds=float(config.get("http_timeout_seconds") or 15),
            retries=int(config.get("http_retries") or 2),
            backoff_seconds=float(config.get("http_backoff_seconds") or 0.4),
        )

    def run(
        self,
        *,
        gw_from: int,
        gw_to: int,
        force: bool = False,
        requested_by: str = "FPL_MASTER_MONITOR",
    ) -> dict[str, Any]:
        started = time.perf_counter()
        generated_at = iso(utc_now())
        bootstrap_result = self.client.bootstrap()
        if bootstrap_result.get("status") != "LIVE":
            raise HistoricalBackfillError("Official bootstrap unavailable")
        bootstrap = bootstrap_result.get("payload") or {}
        gw_from, gw_to = validate_gw_range(gw_from, gw_to, bootstrap)
        gws = list(range(gw_from, gw_to + 1))
        gw_states = _event_catalog(bootstrap)
        has_provisional_current = any(not gw_states[gw]["finished"] for gw in gws)

        entry_id = int(self.config.get("entry_id") or 0)
        if entry_id <= 0:
            raise HistoricalBackfillError("V6 consumer context entry_id missing")
        configured_priorities = list(self.config.get("priority_leagues") or [])
        if not configured_priorities:
            raise HistoricalBackfillError("V6 priority league configuration is empty")

        entry_result = self.client.entry(entry_id)
        if entry_result.get("status") != "LIVE":
            raise HistoricalBackfillError("Official entry endpoint unavailable for priority league resolution")
        memberships = discover_memberships(entry_result.get("payload") or {}, generated_at)
        priorities = resolve_priority_leagues(memberships, configured_priorities)
        target = priorities[0] if priorities else None
        if not target or target.get("resolution_status") != "RESOLVED" or target.get("league_id") is None:
            raise HistoricalBackfillError("configured priority league did not resolve uniquely")
        if str(target.get("league_kind") or "").lower() != "classic":
            raise HistoricalBackfillError("historical mini-league backfill currently requires a classic priority league")
        if not bool(target.get("full_submitted_picks")):
            raise HistoricalBackfillError("priority league is not configured for full submitted picks")

        league_id = int(target["league_id"])
        standings = fetch_all_standings(self.client, target)
        if not standings.get("complete"):
            raise HistoricalBackfillError("current priority league standings incomplete; refusing ambiguous cohort")
        manager_rows = standings.get("rows") or []
        manager_ids = sorted({int(row["entry_id"]) for row in manager_rows})
        if not manager_ids:
            raise HistoricalBackfillError("resolved priority league has no current managers")

        history_root = self.output_root / "mini_leagues" / str(league_id) / "history"
        season = str(self.config.get("season") or "")
        workers = max(1, int(self.config.get("rival_picks_max_workers") or 8))
        cache_enabled = bool(self.config.get("submitted_picks_cache_enabled", True))
        previous_entry_histories = read_json(history_root / "entry_histories.json") if cache_enabled else None
        histories, history_metrics = acquire_entry_histories(
            self.client,
            manager_ids,
            workers,
            previous_entry_histories=previous_entry_histories,
            force=force,
            allow_cache_reuse=not has_provisional_current,
        )
        write_json(
            history_root / "entry_histories.json",
            _entry_histories_artifact(season=season, league_id=league_id, results=histories),
        )

        telemetry = {
            "cache_hits": 0,
            "cache_misses": 0,
            "history_cache_hits": history_metrics["history_cache_hits"],
            "history_cache_misses": history_metrics["history_cache_misses"],
            "fetched_count": 0,
            "reused_count": 0,
            "missing_count": 0,
            "failed_count": history_metrics["history_failed"],
            "official_absence_count": 0,
            "manager_requests": 0,
            "history_requests": history_metrics["history_requests"],
            "retry_count": _retry_count(bootstrap_result) + _retry_count(entry_result) + history_metrics["retry_count"],
            "maximum_concurrency_used": history_metrics["maximum_concurrency_used"],
        }
        gw_health: list[dict[str, Any]] = []

        for gw in gws:
            completed = bool(gw_states[gw]["finished"])
            gw_root = history_root / f"gw_{gw}"
            picks, cache_metrics = acquire_historical_picks(
                self.client,
                previous_path=gw_root / "manager_picks.json",
                season=season,
                league_id=league_id,
                gw=gw,
                manager_ids=manager_ids,
                workers=workers,
                force=force,
                cache_enabled=cache_enabled,
                completed=completed,
            )
            exclusions = _apply_official_absence_classification(
                picks,
                histories,
                manager_ids,
                gw=gw,
                completed=completed,
            )
            telemetry["official_absence_count"] += len(exclusions)
            telemetry["cache_hits"] += cache_metrics["cache_hits"]
            telemetry["cache_misses"] += cache_metrics["cache_misses"]
            telemetry["reused_count"] += cache_metrics["cache_hits"]
            telemetry["fetched_count"] += cache_metrics["cache_misses"]
            telemetry["manager_requests"] += cache_metrics["cache_misses"]
            telemetry["retry_count"] += cache_metrics["retry_count"]
            telemetry["maximum_concurrency_used"] = max(telemetry["maximum_concurrency_used"], cache_metrics["maximum_concurrency_used"])

            live_result = self.client.event_live(gw)
            telemetry["retry_count"] += _retry_count(live_result)
            live_artifact = _event_live_artifact(live_result, gw, completed=completed)
            event_points_available = live_artifact["status"] == "AVAILABLE"
            reconciliations = [
                _reconciliation(
                    candidate,
                    gw,
                    (picks.get("entries") or {}).get(str(candidate), {}),
                    histories.get(candidate, {}),
                    completed=completed,
                )
                for candidate in manager_ids
            ]

            write_json(gw_root / "manager_picks.json", picks)
            write_json(gw_root / "event_live.json", live_artifact)
            write_json(
                gw_root / "reconciliation.json",
                {
                    "schema_version": HISTORICAL_SCHEMA_VERSION,
                    "gw": gw,
                    "gw_semantics": gw_states[gw]["gw_semantics"],
                    "cohort_semantics": COHORT_SEMANTICS,
                    "officially_excluded_current_cohort_entries": [
                        exclusions[key] | {"entry_id": key} for key in sorted(exclusions)
                    ],
                    "reconciliations": reconciliations,
                    "authority": "OFFICIAL_FPL_RECONCILIATION_INTEGRITY",
                    "governance": {
                        "data_only": True,
                        "historical_rank_reconstruction": "DOWNSTREAM",
                        "transition_analytics": "DOWNSTREAM",
                    },
                },
            )

            excluded_ids = set(exclusions)
            eligible_ids = set(manager_ids) - excluded_ids
            available_ids = {
                int(candidate)
                for candidate, record in (picks.get("entries") or {}).items()
                if record.get("status") == "AVAILABLE"
            }
            history_available_ids = {row["entry_id"] for row in reconciliations if row["history_available"]}
            pick_failures = eligible_ids - available_ids
            reconciliation_failures = {
                row["entry_id"]
                for row in reconciliations
                if row["entry_id"] in eligible_ids and row["history_available"] and not row["consistent"]
            }
            history_missing = eligible_ids - history_available_ids
            failed_ids = sorted(pick_failures | reconciliation_failures | (history_missing if completed else set()))
            history_ok = not history_missing if completed else True
            complete = not pick_failures and not reconciliation_failures and event_points_available and history_ok
            raw_history_available_count = len(history_available_ids)
            raw_coverage_count = min(len(available_ids), raw_history_available_count) if completed else len(available_ids)
            eligible_count = len(eligible_ids)
            eligible_coverage_count = (
                min(len(available_ids & eligible_ids), len(history_available_ids & eligible_ids))
                if completed
                else len(available_ids & eligible_ids)
            )
            health = {
                "gw": gw,
                "gw_semantics": gw_states[gw]["gw_semantics"],
                "expected_manager_count": len(manager_ids),
                "current_cohort_manager_count": len(manager_ids),
                "eligible_manager_count": eligible_count,
                "officially_excluded_manager_count": len(excluded_ids),
                "officially_excluded_entry_ids": sorted(excluded_ids),
                "official_exclusion_reason_counts": dict(picks.get("official_exclusion_reason_counts") or {}),
                "collected_manager_count": len(available_ids),
                "submitted_picks_available_count": len(available_ids),
                "submitted_picks_missing_count": len(manager_ids) - len(available_ids),
                "unresolved_submitted_picks_missing_count": len(pick_failures),
                "entry_history_available_count": raw_history_available_count,
                "entry_history_missing_count": len(manager_ids) - raw_history_available_count,
                "eligible_entry_history_available_count": len(history_available_ids & eligible_ids),
                "eligible_entry_history_missing_count": len(history_missing),
                "entry_history_required_for_complete": completed,
                "entry_history_current_gw_policy": None if completed else "OPTIONAL_UNTIL_OFFICIAL_CURRENT_GW_HISTORY_IS_AVAILABLE",
                "final_points_available": event_points_available if completed else False,
                "live_points_available": event_points_available if not completed else False,
                "coverage_percent": round(raw_coverage_count * 100 / len(manager_ids), 4),
                "eligible_coverage_percent": round(eligible_coverage_count * 100 / eligible_count, 4) if eligible_count else 100.0,
                "complete": complete,
                "complete_with_explicit_official_exclusions": complete and bool(excluded_ids),
                "failed_entry_ids": failed_ids,
                "officially_unavailable_or_optional_entry_ids": sorted(history_missing) if not completed else [],
            }
            gw_health.append(health)
            telemetry["missing_count"] += len(failed_ids)
            telemetry["failed_count"] += len(pick_failures)

        managers_artifact = {
            "schema_version": HISTORICAL_SCHEMA_VERSION,
            "season": season,
            "league_id": league_id,
            "league_name": target.get("league_name"),
            "league_kind": target.get("league_kind"),
            "cohort_semantics": COHORT_SEMANTICS,
            "membership_semantics": "Current standings membership is authoritative only for the current cohort; historical membership per GW is unknown unless Official FPL supplies separate evidence.",
            "manager_count": len(manager_ids),
            "managers": [
                {
                    **row,
                    "current_cohort_member": True,
                    "historical_membership_confirmed": None,
                    "membership_at_gw_status": MEMBERSHIP_STATUS,
                    "membership_evidence": MEMBERSHIP_EVIDENCE,
                }
                for row in manager_rows
            ],
            "authority": "OFFICIAL_FPL_CURRENT_STANDINGS",
            "governance": {"data_only": True},
        }
        write_json(history_root / "managers.json", managers_artifact)

        complete_gws = sum(1 for row in gw_health if row["complete"])
        partial_gws = sum(1 for row in gw_health if not row["complete"] and row["eligible_coverage_percent"] > 0)
        failed_gws = len(gw_health) - complete_gws - partial_gws
        overall_status = "GREEN" if complete_gws == len(gws) else ("AMBER" if complete_gws or partial_gws else "RED")
        client_telemetry = self.client.telemetry() if callable(getattr(self.client, "telemetry", None)) else {}
        telemetry["total_requests"] = client_telemetry.get("request_count")
        telemetry["failed_requests"] = client_telemetry.get("failed_requests")
        telemetry["maximum_concurrency_used"] = max(telemetry["maximum_concurrency_used"], int(client_telemetry.get("maximum_concurrency_used") or 0))
        telemetry["duration_ms"] = round((time.perf_counter() - started) * 1000)

        manifest = {
            "schema_version": HISTORICAL_SCHEMA_VERSION,
            "season": season,
            "generated_at": generated_at,
            "requested_by": requested_by,
            "report_kind": "historical_backfill",
            "scope": "mini_league",
            "gw_from": gw_from,
            "gw_to": gw_to,
            "requested_gw_count": len(gws),
            "completed_requested_gw_count": sum(1 for gw in gws if gw_states[gw]["finished"]),
            "provisional_current_gw_count": sum(1 for gw in gws if not gw_states[gw]["finished"]),
            "league_id": league_id,
            "league_name": target.get("league_name"),
            "current_cohort_manager_count": len(manager_ids),
            "cohort_semantics": COHORT_SEMANTICS,
            "historical_membership_confirmed": False,
            "gw_health": gw_health,
            "complete_gw_count": complete_gws,
            "partial_gw_count": partial_gws,
            "failed_gw_count": failed_gws,
            "overall_status": overall_status,
            "cache": {
                "cache_hits": telemetry["cache_hits"],
                "cache_misses": telemetry["cache_misses"],
                "history_cache_hits": telemetry["history_cache_hits"],
                "history_cache_misses": telemetry["history_cache_misses"],
                "current_gw_entry_history_cache_reused": has_provisional_current and telemetry["history_cache_hits"] > 0,
            },
            "telemetry": telemetry,
            "artifacts": {
                "managers": f"data/v6/mini_leagues/{league_id}/history/managers.json",
                "entry_histories": f"data/v6/mini_leagues/{league_id}/history/entry_histories.json",
                "per_gw": [
                    {
                        "gw": gw,
                        "manager_picks": f"data/v6/mini_leagues/{league_id}/history/gw_{gw}/manager_picks.json",
                        "event_live": f"data/v6/mini_leagues/{league_id}/history/gw_{gw}/event_live.json",
                        "reconciliation": f"data/v6/mini_leagues/{league_id}/history/gw_{gw}/reconciliation.json",
                    }
                    for gw in gws
                ],
            },
            "retired_analytics": [
                "exposure.json",
                "transitions.json",
                "player_ownership_history.json",
                "captain_history.json",
                "manager_history.json",
                "squad_overlap_history.json",
                "reconstructed_current_cohort_ranks",
            ],
            "governance": {
                "data_only": True,
                "decision_authority": "NONE",
                "prediction_authority": "NONE",
                "optimizer_authority": "NONE",
                "tactical_authority": "NONE",
                "bayesian_authority": "NONE",
                "monte_carlo_authority": "NONE",
                "ownership_analytics_authority": "NONE",
                "effective_ownership_authority": "NONE",
                "rival_analytics_authority": "NONE",
                "atomic_facts_only": True,
                "analytics_belong_downstream": True,
            },
        }
        write_json(history_root / "manifest.json", manifest)
        write_json(self.output_root / "health/historical_backfill.json", {
            "schema_version": HISTORICAL_SCHEMA_VERSION,
            "generated_at": generated_at,
            "overall_status": overall_status,
            "league_id": league_id,
            "gw_from": gw_from,
            "gw_to": gw_to,
            "complete_gw_count": complete_gws,
            "partial_gw_count": partial_gws,
            "failed_gw_count": failed_gws,
            "cohort_semantics": COHORT_SEMANTICS,
            "data_contract": "ATOMIC_FACTS_ONLY",
        })
        return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="V6 data-only historical mini-league backfill")
    parser.add_argument("--gw-from", type=int, required=True)
    parser.add_argument("--gw-to", type=int, required=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--requested-by", default="FPL_MASTER_MONITOR")
    parser.add_argument("--config", type=Path, default=Path("config/v6/consumer_context.json"))
    parser.add_argument("--output-root", type=Path, default=Path("data/v6"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        manifest = HistoricalBackfillService(
            config=load_consumer_context(args.config),
            output_root=args.output_root,
        ).run(
            gw_from=args.gw_from,
            gw_to=args.gw_to,
            force=args.force,
            requested_by=args.requested_by,
        )
    except HistoricalBackfillError as exc:
        print(json.dumps({"status": "REJECTED", "error": safe_error(exc)}))
        return 2
    print(json.dumps({
        "status": manifest.get("overall_status"),
        "league_id": manifest.get("league_id"),
        "gw_from": manifest.get("gw_from"),
        "gw_to": manifest.get("gw_to"),
        "cache": manifest.get("cache"),
        "telemetry": manifest.get("telemetry"),
    }, indent=2))
    return 0 if manifest.get("overall_status") == "GREEN" else 3


if __name__ == "__main__":
    raise SystemExit(main())
