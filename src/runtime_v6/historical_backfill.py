from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .league_prefetch import fetch_all_standings
from .official_fpl_client import OfficialFPLClient
from .personal_prefetch import discover_memberships, normalise_submitted_picks, resolve_priority_leagues
from .prefetch_contract import NORMALIZATION_VERSION, digest, iso, lineage, load_consumer_context, read_json, utc_now, write_json
from .security import assert_publish_safe, safe_error

COHORT_SEMANTICS = "CURRENT_COHORT_HISTORY"
MEMBERSHIP_STATUS = "UNKNOWN"
MEMBERSHIP_EVIDENCE = "CURRENT_STANDINGS_COHORT_ONLY"
LIVE_HISTORICAL = "LIVE_FETCHED_HISTORICAL_GW"
REUSED_HISTORICAL = "IMMUTABLE_HISTORICAL_CACHE_REUSED"
HISTORICAL_SCHEMA_VERSION = 1


class HistoricalBackfillError(RuntimeError):
    pass


def _latest_finished_gw(bootstrap: dict[str, Any]) -> int:
    return max(
        (
            int(event["id"])
            for event in (bootstrap.get("events") or [])
            if isinstance(event, dict) and event.get("id") is not None and event.get("finished") is True
        ),
        default=0,
    )


def validate_gw_range(gw_from: int, gw_to: int, bootstrap: dict[str, Any]) -> tuple[int, int]:
    gw_from, gw_to = int(gw_from), int(gw_to)
    if gw_from < 1 or gw_to < 1:
        raise HistoricalBackfillError("GW range must start at 1 or later")
    if gw_from > gw_to:
        raise HistoricalBackfillError("gw_from cannot be greater than gw_to")
    latest_finished = _latest_finished_gw(bootstrap)
    if latest_finished < 1:
        raise HistoricalBackfillError("Official FPL exposes no finished GW for historical backfill")
    if gw_to > latest_finished:
        raise HistoricalBackfillError(
            f"historical backfill accepts finished GWs only; latest_finished_gw={latest_finished}, requested_gw_to={gw_to}"
        )
    return gw_from, gw_to


def _element_index(bootstrap: dict[str, Any]) -> dict[int, dict[str, Any]]:
    teams = {
        int(team["id"]): {"name": team.get("name"), "short_name": team.get("short_name")}
        for team in (bootstrap.get("teams") or [])
        if isinstance(team, dict) and team.get("id") is not None
    }
    positions = {
        int(item["id"]): item.get("singular_name_short") or item.get("singular_name")
        for item in (bootstrap.get("element_types") or [])
        if isinstance(item, dict) and item.get("id") is not None
    }
    result: dict[int, dict[str, Any]] = {}
    for element in bootstrap.get("elements") or []:
        if not isinstance(element, dict) or element.get("id") is None:
            continue
        team_id = element.get("team")
        team = teams.get(int(team_id)) if team_id is not None else {}
        element_type = element.get("element_type")
        result[int(element["id"])] = {
            "official_element_id": int(element["id"]),
            "web_name": element.get("web_name"),
            "club": (team or {}).get("short_name") or (team or {}).get("name"),
            "club_id_current": int(team_id) if team_id is not None else None,
            "position": positions.get(int(element_type)) if element_type is not None else None,
            "identity_snapshot_semantics": "CURRENT_BOOTSTRAP_CANONICAL_IDENTITY",
            "historical_club_snapshot_available": False,
        }
    return result


def _entry_history(client: Any, entry_id: int) -> dict[str, Any]:
    public = getattr(client, "entry_history", None)
    if callable(public):
        return public(int(entry_id))
    request = getattr(client, "_request", None)
    if not callable(request):
        raise HistoricalBackfillError("Official FPL client does not expose shared request transport")
    return request("entry_history", f"entry/{int(entry_id)}/history/")


def _retry_count(result: dict[str, Any] | None) -> int:
    if not isinstance(result, dict):
        return 0
    attempts = result.get("attempts")
    return max(0, int(attempts) - 1) if isinstance(attempts, int) else 0


def _historical_record(entry_id: int, gw: int, result: dict[str, Any]) -> dict[str, Any]:
    normal = normalise_submitted_picks(entry_id, gw, result, origin=LIVE_HISTORICAL)
    record = {
        "entry_id": entry_id,
        "gw": gw,
        "status": normal.get("status"),
        "origin": LIVE_HISTORICAL,
        "current_cohort_member": True,
        "cohort_semantics": COHORT_SEMANTICS,
        "membership_at_gw_status": MEMBERSHIP_STATUS,
        "membership_evidence": MEMBERSHIP_EVIDENCE,
        "historical_membership_confirmed": None,
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
    record["record_digest"] = digest({key: value for key, value in record.items() if key != "record_digest"})
    return record


def _cache_valid(record: Any, *, season: str, league_id: int, gw: int, entry_id: int) -> bool:
    if not isinstance(record, dict):
        return False
    if record.get("entry_id") != entry_id or record.get("gw") != gw or record.get("status") != "AVAILABLE":
        return False
    if record.get("cache_identity") != {"season": season, "gw": gw, "league_id": league_id, "entry_id": entry_id}:
        return False
    expected = record.get("record_digest")
    if not isinstance(expected, str) or not expected:
        return False
    return expected == digest({key: value for key, value in record.items() if key != "record_digest"})


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
            body["origin"] = REUSED_HISTORICAL
            body["lineage"] = {**dict(body.get("lineage") or {}), "origin": REUSED_HISTORICAL}
            body["record_digest"] = digest(body)
            entries[str(entry_id)] = body
            cache_hits += 1
        else:
            misses.append(entry_id)

    def fetch(entry_id: int) -> tuple[int, dict[str, Any]]:
        record = _historical_record(entry_id, gw, client.submitted_picks(entry_id, gw))
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
                        "origin": LIVE_HISTORICAL,
                        "cache_identity": {"season": season, "gw": gw, "league_id": league_id, "entry_id": entry_id},
                        "current_cohort_member": True,
                        "cohort_semantics": COHORT_SEMANTICS,
                        "membership_at_gw_status": MEMBERSHIP_STATUS,
                        "membership_evidence": MEMBERSHIP_EVIDENCE,
                        "historical_membership_confirmed": None,
                        "attempts": None,
                        "active_chip": None,
                        "picks": [],
                        "lineage": {"authority": "OFFICIAL_FPL", "endpoint_class": "submitted_picks", "gw": gw, "entry_id": entry_id, "origin": LIVE_HISTORICAL, "error": safe_error(exc)},
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
        "cohort_semantics": COHORT_SEMANTICS,
        "membership_at_gw_status": MEMBERSHIP_STATUS,
        "generated_at": iso(utc_now()),
        "immutable_completed_gw_facts": True,
        "manager_set_digest": manager_set_digest,
        "expected_manager_count": len(manager_ids),
        "collected_manager_count": len(available),
        "submitted_picks_available_count": len(available),
        "submitted_picks_missing_count": len(missing),
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
            },
        },
    }
    return artifact, {
        "cache_hits": cache_hits,
        "cache_misses": len(misses),
        "maximum_concurrency_used": used_workers,
        "retry_count": sum(max(0, int(row.get("attempts") or 1) - 1) for row in entries.values() if row.get("origin") == LIVE_HISTORICAL),
    }


def _history_rows(result: dict[str, Any]) -> dict[int, dict[str, Any]]:
    if result.get("status") != "LIVE":
        return {}
    return {
        int(row["event"]): dict(row)
        for row in ((result.get("payload") or {}).get("current") or [])
        if isinstance(row, dict) and row.get("event") is not None
    }


def _chip_events(result: dict[str, Any]) -> dict[int, str]:
    if result.get("status") != "LIVE":
        return {}
    values = {}
    for chip in ((result.get("payload") or {}).get("chips") or []):
        if isinstance(chip, dict) and chip.get("event") is not None and chip.get("name"):
            values[int(chip["event"])] = str(chip["name"])
    return values


def _cached_history_result(manager: dict[str, Any], requested_gws: list[int]) -> dict[str, Any] | None:
    if not isinstance(manager, dict):
        return None
    expected = manager.get("record_digest")
    if not isinstance(expected, str) or expected != digest({key: value for key, value in manager.items() if key != "record_digest"}):
        return None
    rows = manager.get("gws") or []
    by_gw = {int(row["gw"]): row for row in rows if isinstance(row, dict) and row.get("gw") is not None}
    if any(gw not in by_gw for gw in requested_gws):
        return None
    current = []
    chips = []
    for gw in requested_gws:
        row = by_gw[gw]
        if row.get("gw_points") is None or row.get("cumulative_points") is None:
            return None
        current.append({"event": gw, "points": row.get("gw_points"), "total_points": row.get("cumulative_points"), "overall_rank": row.get("overall_rank")})
        if row.get("active_chip"):
            chips.append({"event": gw, "name": row["active_chip"]})
    return {
        "status": "LIVE",
        "endpoint_class": "entry_history",
        "checked_at": manager.get("history_checked_at"),
        "http_status": 200,
        "payload_digest": manager.get("history_payload_digest"),
        "payload": {"current": current, "chips": chips},
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
    previous_manager_history: dict[str, Any] | None,
    requested_gws: list[int],
    force: bool,
) -> tuple[dict[int, dict[str, Any]], dict[str, int]]:
    previous_managers = {
        int(row["entry_id"]): row
        for row in ((previous_manager_history or {}).get("managers") or [])
        if isinstance(row, dict) and row.get("entry_id") is not None
    }
    manager_ids = sorted({int(value) for value in manager_ids})
    results: dict[int, dict[str, Any]] = {}
    misses = []
    hits = 0
    for entry_id in manager_ids:
        cached = None if force else _cached_history_result(previous_managers.get(entry_id, {}), requested_gws)
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
                    results[entry_id] = {"status": "FAILED", "endpoint_class": "entry_history", "payload": None, "attempts": 0, "error": safe_error(exc)}
    failed = sum(1 for result in results.values() if result.get("status") != "LIVE")
    return results, {
        "history_cache_hits": hits,
        "history_cache_misses": len(misses),
        "history_requests": len(misses),
        "history_failed": failed,
        "retry_count": sum(_retry_count(result) for entry_id, result in results.items() if entry_id in set(misses)),
        "maximum_concurrency_used": used_workers,
    }


def _live_points(result: dict[str, Any]) -> dict[int, int] | None:
    if result.get("status") != "LIVE":
        return None
    values: dict[int, int] = {}
    for item in ((result.get("payload") or {}).get("elements") or []):
        stats = item.get("stats") if isinstance(item, dict) else None
        if isinstance(item, dict) and item.get("id") is not None and isinstance(stats, dict) and isinstance(stats.get("total_points"), int):
            values[int(item["id"])] = int(stats["total_points"])
    return values


def _exposure(manager_picks: dict[str, Any], element_index: dict[int, dict[str, Any]], final_points: dict[int, int] | None) -> dict[str, Any]:
    available = [row for row in (manager_picks.get("entries") or {}).values() if row.get("status") == "AVAILABLE"]
    denominator = len(available)
    aggregate: dict[int, dict[str, Any]] = {}
    for manager in available:
        for pick in manager.get("picks") or []:
            element_id = int(pick["element_id"])
            row = aggregate.setdefault(element_id, {"official_element_id": element_id, "managers_owned_count": 0, "starts_count": 0, "captain_count": 0, "vice_count": 0, "bench_count": 0, "multiplier_sum": 0})
            row["managers_owned_count"] += 1
            row["starts_count" if int(pick.get("squad_position") or 99) <= 11 else "bench_count"] += 1
            row["captain_count"] += int(bool(pick.get("captain")))
            row["vice_count"] += int(bool(pick.get("vice_captain")))
            if isinstance(pick.get("multiplier"), (int, float)):
                row["multiplier_sum"] += pick["multiplier"]
    players = []
    for element_id in sorted(aggregate):
        row = aggregate[element_id]
        points = final_points.get(element_id) if final_points is not None else None
        meta = element_index.get(element_id, {})
        players.append({
            **row,
            "web_name": meta.get("web_name"),
            "club": meta.get("club"),
            "position": meta.get("position"),
            "identity_snapshot_semantics": meta.get("identity_snapshot_semantics"),
            "historical_club_snapshot_available": meta.get("historical_club_snapshot_available"),
            "manager_count": denominator,
            "ownership_percent": round(row["managers_owned_count"] * 100 / denominator, 4) if denominator else None,
            "effective_ownership_percent": round(row["multiplier_sum"] * 100 / denominator, 4) if denominator else None,
            "final_points": points,
            "total_cohort_points_contribution": row["multiplier_sum"] * points if isinstance(points, int) else None,
        })
    expected = int(manager_picks.get("expected_manager_count") or 0)
    return {
        "schema_version": HISTORICAL_SCHEMA_VERSION,
        "season": manager_picks.get("season"),
        "league_id": manager_picks.get("league_id"),
        "gw": manager_picks.get("gw"),
        "cohort_semantics": COHORT_SEMANTICS,
        "manager_count_denominator": denominator,
        "expected_manager_count": expected,
        "submitted_picks_available_count": denominator,
        "submitted_picks_missing_count": max(0, expected - denominator),
        "coverage_percent": round(denominator * 100 / expected, 4) if expected else 0.0,
        "players": players,
        "authority": "OFFICIAL_FPL_MECHANICAL_AGGREGATE",
        "identity_limitation": "Player club/position labels use current Official bootstrap identity; historical club snapshot is not asserted.",
    }


def _reconciliation(entry_id: int, gw: int, pick_record: dict[str, Any], history_result: dict[str, Any]) -> dict[str, Any]:
    history = _history_rows(history_result).get(gw)
    chip_history = _chip_events(history_result).get(gw)
    captains = [pick for pick in pick_record.get("picks") or [] if pick.get("captain")]
    vice = [pick for pick in pick_record.get("picks") or [] if pick.get("vice_captain")]
    checks = {
        "exact_15_picks": len(pick_record.get("picks") or []) == 15 if pick_record.get("status") == "AVAILABLE" else None,
        "one_captain": len(captains) == 1 if pick_record.get("status") == "AVAILABLE" else None,
        "one_vice": len(vice) == 1 if pick_record.get("status") == "AVAILABLE" else None,
        "captain_multiplier_consistent": (bool(captains) and isinstance(captains[0].get("multiplier"), (int, float)) and captains[0]["multiplier"] >= 2) if pick_record.get("status") == "AVAILABLE" else None,
        "chip_consistent": pick_record.get("active_chip") == chip_history if history is not None else None,
    }
    return {
        "entry_id": entry_id,
        "gw": gw,
        "submitted_picks_status": pick_record.get("status"),
        "gw_points": history.get("points") if history else None,
        "cumulative_points": history.get("total_points") if history else None,
        "official_overall_rank": history.get("overall_rank") if history else None,
        "active_chip_submitted_picks": pick_record.get("active_chip"),
        "active_chip_entry_history": chip_history,
        "history_available": history is not None,
        "checks": checks,
        "consistent": all(value is not False for value in checks.values()),
        "authority": "OFFICIAL_FPL_RECONCILED_FACT",
    }


def _manager_gw_state(pick_record: dict[str, Any], history_result: dict[str, Any], gw: int) -> dict[str, Any]:
    history = _history_rows(history_result).get(gw)
    picks = pick_record.get("picks") or []
    return {
        "gw": gw,
        "submitted_picks_available": pick_record.get("status") == "AVAILABLE",
        "squad": [int(p["element_id"]) for p in picks],
        "starting_xi": [int(p["element_id"]) for p in picks if int(p.get("squad_position") or 99) <= 11],
        "bench": [int(p["element_id"]) for p in sorted(picks, key=lambda p: int(p.get("squad_position") or 99)) if int(p.get("squad_position") or 99) > 11],
        "captain": next((int(p["element_id"]) for p in picks if p.get("captain")), None),
        "vice_captain": next((int(p["element_id"]) for p in picks if p.get("vice_captain")), None),
        "active_chip": pick_record.get("active_chip"),
        "gw_points": history.get("points") if history else None,
        "cumulative_points": history.get("total_points") if history else None,
        "overall_rank": history.get("overall_rank") if history else None,
    }


def _pct_overlap(left: list[int], right: list[int], denominator: int) -> float | None:
    if len(left) != denominator or len(right) != denominator:
        return None
    return round(len(set(left) & set(right)) * 100 / denominator, 4)


def _manager_longitudinal(manager_ids: list[int], picks_by_gw: dict[int, dict[str, Any]], histories: dict[int, dict[str, Any]], gws: list[int]) -> dict[str, Any]:
    managers = []
    for entry_id in manager_ids:
        rows = []
        previous = None
        for gw in gws:
            pick = (picks_by_gw[gw].get("entries") or {}).get(str(entry_id), {})
            state = _manager_gw_state(pick, histories.get(entry_id, {}), gw)
            if previous is None:
                state.update({"squad_overlap_percent_vs_previous_gw": None, "xi_overlap_percent_vs_previous_gw": None, "number_of_player_changes": None, "number_of_captain_changes": None, "number_of_starting_xi_changes": None, "number_of_bench_order_changes": None})
            else:
                state.update({
                    "squad_overlap_percent_vs_previous_gw": _pct_overlap(previous["squad"], state["squad"], 15),
                    "xi_overlap_percent_vs_previous_gw": _pct_overlap(previous["starting_xi"], state["starting_xi"], 11),
                    "number_of_player_changes": 15 - len(set(previous["squad"]) & set(state["squad"])) if len(previous["squad"]) == len(state["squad"]) == 15 else None,
                    "number_of_captain_changes": int(previous["captain"] != state["captain"]) if previous["captain"] is not None and state["captain"] is not None else None,
                    "number_of_starting_xi_changes": 11 - len(set(previous["starting_xi"]) & set(state["starting_xi"])) if len(previous["starting_xi"]) == len(state["starting_xi"]) == 11 else None,
                    "number_of_bench_order_changes": sum(a != b for a, b in zip(previous["bench"], state["bench"])) if len(previous["bench"]) == len(state["bench"]) == 4 else None,
                })
            rows.append(state)
            previous = state
        history_result = histories.get(entry_id, {})
        manager = {
            "entry_id": entry_id,
            "current_cohort_member": True,
            "cohort_semantics": COHORT_SEMANTICS,
            "historical_membership_confirmed": None,
            "history_origin": history_result.get("origin", LIVE_HISTORICAL),
            "history_checked_at": history_result.get("checked_at"),
            "history_payload_digest": history_result.get("payload_digest"),
            "gws": rows,
        }
        manager["record_digest"] = digest(manager)
        managers.append(manager)
    return {"schema_version": HISTORICAL_SCHEMA_VERSION, "cohort_semantics": COHORT_SEMANTICS, "managers": managers, "authority": "OFFICIAL_FPL_MECHANICAL_LONGITUDINAL_FACTS"}


def _player_longitudinal(exposure_by_gw: dict[int, dict[str, Any]], picks_by_gw: dict[int, dict[str, Any]], gws: list[int]) -> dict[str, Any]:
    element_ids = sorted({int(row["official_element_id"]) for artifact in exposure_by_gw.values() for row in artifact.get("players") or []})
    players = []
    for element_id in element_ids:
        series = []
        previous_owned: set[int] = set()
        previous_captain: set[int] = set()
        previous_started: set[int] = set()
        for index, gw in enumerate(gws):
            exposure = next((row for row in exposure_by_gw[gw].get("players") or [] if int(row["official_element_id"]) == element_id), None)
            entries = picks_by_gw[gw].get("entries") or {}
            owned = {int(entry_id) for entry_id, record in entries.items() if record.get("status") == "AVAILABLE" and any(int(p["element_id"]) == element_id for p in record.get("picks") or [])}
            captain = {int(entry_id) for entry_id, record in entries.items() if record.get("status") == "AVAILABLE" and any(int(p["element_id"]) == element_id and p.get("captain") for p in record.get("picks") or [])}
            started = {int(entry_id) for entry_id, record in entries.items() if record.get("status") == "AVAILABLE" and any(int(p["element_id"]) == element_id and int(p.get("squad_position") or 99) <= 11 for p in record.get("picks") or [])}
            series.append({
                "gw": gw,
                "owned_count": len(owned),
                "started_count": len(started),
                "captain_count": len(captain),
                "vice_count": exposure.get("vice_count") if exposure else 0,
                "effective_ownership_percent": exposure.get("effective_ownership_percent") if exposure else 0.0,
                "new_owners_from_previous_gw": None if index == 0 else len(owned - previous_owned),
                "dropped_by_previous_owners": None if index == 0 else len(previous_owned - owned),
                "retained_by_previous_owners": None if index == 0 else len(owned & previous_owned),
                "captain_gain_count": None if index == 0 else len(captain - previous_captain),
                "captain_drop_count": None if index == 0 else len(previous_captain - captain),
                "bench_to_start_count": None if index == 0 else len((started & previous_owned) - previous_started),
                "start_to_bench_count": None if index == 0 else len((previous_started & owned) - started),
            })
            previous_owned, previous_captain, previous_started = owned, captain, started
        meta = next((row for artifact in exposure_by_gw.values() for row in artifact.get("players") or [] if int(row["official_element_id"]) == element_id), {})
        players.append({"official_element_id": element_id, "web_name": meta.get("web_name"), "position": meta.get("position"), "gws": series})
    return {"schema_version": HISTORICAL_SCHEMA_VERSION, "cohort_semantics": COHORT_SEMANTICS, "players": players, "authority": "OFFICIAL_FPL_MECHANICAL_LONGITUDINAL_FACTS"}


def _overlap_artifact(picks_by_gw: dict[int, dict[str, Any]], gws: list[int]) -> dict[str, Any]:
    gw_rows = []
    for gw in gws:
        entries = {int(k): v for k, v in (picks_by_gw[gw].get("entries") or {}).items() if v.get("status") == "AVAILABLE"}
        pairs, squad_values, xi_values = [], [], []
        manager_ids = sorted(entries)
        for index, left in enumerate(manager_ids):
            left_squad = {int(p["element_id"]) for p in entries[left].get("picks") or []}
            left_xi = {int(p["element_id"]) for p in entries[left].get("picks") or [] if int(p.get("squad_position") or 99) <= 11}
            for right in manager_ids[index + 1:]:
                right_squad = {int(p["element_id"]) for p in entries[right].get("picks") or []}
                right_xi = {int(p["element_id"]) for p in entries[right].get("picks") or [] if int(p.get("squad_position") or 99) <= 11}
                squad_overlap = round(len(left_squad & right_squad) * 100 / 15, 4)
                xi_overlap = round(len(left_xi & right_xi) * 100 / 11, 4)
                squad_values.append(squad_overlap)
                xi_values.append(xi_overlap)
                pairs.append({"entry_id_a": left, "entry_id_b": right, "squad_overlap_percent": squad_overlap, "xi_overlap_percent": xi_overlap})
        captain_counts: dict[int, int] = {}
        player_counts: dict[int, int] = {}
        for record in entries.values():
            for pick in record.get("picks") or []:
                element_id = int(pick["element_id"])
                player_counts[element_id] = player_counts.get(element_id, 0) + 1
                if pick.get("captain"):
                    captain_counts[element_id] = captain_counts.get(element_id, 0) + 1
        denominator = len(entries)
        captain_shares = [count / denominator for count in captain_counts.values()] if denominator else []
        slot_denominator = denominator * 15
        slot_shares = [count / slot_denominator for count in player_counts.values()] if slot_denominator else []
        gw_rows.append({
            "gw": gw,
            "manager_count": denominator,
            "pair_count": len(pairs),
            "pairs": pairs,
            "average_pairwise_squad_overlap_percent": round(statistics.mean(squad_values), 4) if squad_values else None,
            "median_pairwise_squad_overlap_percent": round(statistics.median(squad_values), 4) if squad_values else None,
            "average_pairwise_xi_overlap_percent": round(statistics.mean(xi_values), 4) if xi_values else None,
            "median_pairwise_xi_overlap_percent": round(statistics.median(xi_values), 4) if xi_values else None,
            "player_concentration": {
                "maximum_ownership_percent": round(max(player_counts.values()) * 100 / denominator, 4) if denominator and player_counts else None,
                "squad_slot_hhi": round(sum(value * value for value in slot_shares), 6) if slot_shares else None,
            },
            "captain_concentration": {
                "maximum_captain_percent": round(max(captain_shares) * 100, 4) if captain_shares else None,
                "captain_hhi": round(sum(value * value for value in captain_shares), 6) if captain_shares else None,
            },
        })
    return {"schema_version": HISTORICAL_SCHEMA_VERSION, "cohort_semantics": COHORT_SEMANTICS, "gws": gw_rows, "authority": "OFFICIAL_FPL_MECHANICAL_AGGREGATE"}


def _ranks(manager_states: list[dict[str, Any]], gw: int) -> list[dict[str, Any]]:
    values = []
    for manager in manager_states:
        row = next((item for item in manager.get("gws") or [] if item.get("gw") == gw), None)
        if row and isinstance(row.get("cumulative_points"), int):
            values.append((int(manager["entry_id"]), int(row["cumulative_points"]), row.get("gw_points")))
    values.sort(key=lambda item: (-item[1], item[0]))
    ranks, last_points, last_rank = [], None, 0
    for index, (entry_id, points, gw_points) in enumerate(values, start=1):
        if points != last_points:
            last_rank, last_points = index, points
        ranks.append({"entry_id": entry_id, "gw": gw, "gw_points": gw_points, "cumulative_points": points, "reconstructed_current_cohort_rank": last_rank, "rank_semantics": "RECONSTRUCTED_CURRENT_COHORT_ONLY", "official_historical_league_rank": None})
    return ranks


def _authority() -> dict[str, Any]:
    return {
        "data_only": True,
        "decision_authority": "NONE",
        "prediction_authority": "NONE",
        "optimizer_authority": "NONE",
        "tactical_authority": "NONE",
        "bayesian_authority": "NONE",
        "monte_carlo_authority": "NONE",
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

    def run(self, *, gw_from: int, gw_to: int, force: bool = False, requested_by: str = "FPL_MASTER_MONITOR") -> dict[str, Any]:
        started = time.perf_counter()
        generated_at = iso(utc_now())
        bootstrap_result = self.client.bootstrap()
        if bootstrap_result.get("status") != "LIVE":
            raise HistoricalBackfillError("Official bootstrap unavailable")
        bootstrap = bootstrap_result.get("payload") or {}
        gw_from, gw_to = validate_gw_range(gw_from, gw_to, bootstrap)
        gws = list(range(gw_from, gw_to + 1))
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
        element_index = _element_index(bootstrap)
        previous_manager_history = read_json(history_root / "longitudinal" / "manager_history.json") if cache_enabled else None
        histories, history_metrics = acquire_entry_histories(
            self.client,
            manager_ids,
            workers,
            previous_manager_history=previous_manager_history,
            requested_gws=gws,
            force=force,
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
            "manager_requests": 0,
            "history_requests": history_metrics["history_requests"],
            "retry_count": _retry_count(bootstrap_result) + _retry_count(entry_result) + history_metrics["retry_count"],
            "maximum_concurrency_used": history_metrics["maximum_concurrency_used"],
        }
        picks_by_gw: dict[int, dict[str, Any]] = {}
        exposure_by_gw: dict[int, dict[str, Any]] = {}
        reconciliations_by_gw: dict[int, list[dict[str, Any]]] = {}
        event_live_available: dict[int, bool] = {}

        for gw in gws:
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
            )
            picks_by_gw[gw] = picks
            telemetry["cache_hits"] += cache_metrics["cache_hits"]
            telemetry["cache_misses"] += cache_metrics["cache_misses"]
            telemetry["reused_count"] += cache_metrics["cache_hits"]
            telemetry["fetched_count"] += cache_metrics["cache_misses"]
            telemetry["manager_requests"] += cache_metrics["cache_misses"]
            telemetry["retry_count"] += cache_metrics["retry_count"]
            telemetry["maximum_concurrency_used"] = max(telemetry["maximum_concurrency_used"], cache_metrics["maximum_concurrency_used"])

            live_result = self.client.event_live(gw)
            telemetry["retry_count"] += _retry_count(live_result)
            points = _live_points(live_result)
            event_live_available[gw] = points is not None
            exposure_by_gw[gw] = _exposure(picks, element_index, points)
            reconciliations_by_gw[gw] = [
                _reconciliation(candidate, gw, (picks.get("entries") or {}).get(str(candidate), {}), histories.get(candidate, {}))
                for candidate in manager_ids
            ]
            write_json(gw_root / "manager_picks.json", picks)
            write_json(gw_root / "exposure.json", exposure_by_gw[gw])

        manager_longitudinal = _manager_longitudinal(manager_ids, picks_by_gw, histories, gws)
        player_longitudinal = _player_longitudinal(exposure_by_gw, picks_by_gw, gws)
        overlap = _overlap_artifact(picks_by_gw, gws)
        gw_health = []
        for gw in gws:
            picks = picks_by_gw[gw]
            reconciliations = reconciliations_by_gw[gw]
            ranks = _ranks(manager_longitudinal["managers"], gw)
            available = int(picks.get("submitted_picks_available_count") or 0)
            history_available_count = sum(1 for row in reconciliations if row["history_available"])
            failed_ids = sorted({*picks.get("missing_entry_ids", []), *[row["entry_id"] for row in reconciliations if not row["history_available"] or not row["consistent"]]})
            complete = available == len(manager_ids) and history_available_count == len(manager_ids) and not failed_ids and event_live_available[gw]
            coverage_count = min(available, history_available_count)
            health = {
                "gw": gw,
                "expected_manager_count": len(manager_ids),
                "collected_manager_count": available,
                "submitted_picks_available_count": available,
                "submitted_picks_missing_count": len(manager_ids) - available,
                "entry_history_available_count": history_available_count,
                "final_points_available": event_live_available[gw],
                "coverage_percent": round(coverage_count * 100 / len(manager_ids), 4),
                "complete": complete,
                "failed_entry_ids": failed_ids,
            }
            gw_health.append(health)
            telemetry["missing_count"] += len(failed_ids)
            telemetry["failed_count"] += len(picks.get("missing_entry_ids") or [])
            gw_root = history_root / f"gw_{gw}"
            write_json(gw_root / "standings_or_points.json", {
                "schema_version": HISTORICAL_SCHEMA_VERSION,
                "gw": gw,
                "cohort_semantics": COHORT_SEMANTICS,
                "rank_semantics": "RECONSTRUCTED_CURRENT_COHORT_ONLY",
                "official_historical_league_rank_available": False,
                "reconciliations": reconciliations,
                "reconstructed_current_cohort_ranks": ranks,
            })
            write_json(gw_root / "transitions.json", {
                "schema_version": HISTORICAL_SCHEMA_VERSION,
                "gw": gw,
                "cohort_semantics": COHORT_SEMANTICS,
                "manager_rows": [{"entry_id": manager["entry_id"], **next(item for item in manager["gws"] if item["gw"] == gw)} for manager in manager_longitudinal["managers"]],
            })

        longitudinal_root = history_root / "longitudinal"
        write_json(longitudinal_root / "player_ownership_history.json", player_longitudinal)
        write_json(longitudinal_root / "captain_history.json", {
            "schema_version": HISTORICAL_SCHEMA_VERSION,
            "cohort_semantics": COHORT_SEMANTICS,
            "players": [
                {
                    "official_element_id": row["official_element_id"],
                    "web_name": row.get("web_name"),
                    "gws": [{"gw": item["gw"], "captain_count": item["captain_count"], "captain_gain_count": item["captain_gain_count"], "captain_drop_count": item["captain_drop_count"]} for item in row["gws"]],
                }
                for row in player_longitudinal["players"]
            ],
            "authority": "OFFICIAL_FPL_MECHANICAL_LONGITUDINAL_FACTS",
        })
        write_json(longitudinal_root / "manager_history.json", manager_longitudinal)
        write_json(longitudinal_root / "squad_overlap_history.json", overlap)
        write_json(longitudinal_root / "transitions.json", {"schema_version": HISTORICAL_SCHEMA_VERSION, "cohort_semantics": COHORT_SEMANTICS, "player_transitions": player_longitudinal["players"], "manager_transitions": manager_longitudinal["managers"]})

        managers_artifact = {
            "schema_version": HISTORICAL_SCHEMA_VERSION,
            "season": season,
            "league_id": league_id,
            "league_name": target.get("league_name"),
            "league_kind": target.get("league_kind"),
            "cohort_semantics": COHORT_SEMANTICS,
            "membership_semantics": "Current standings membership is authoritative only for the current cohort; historical membership per GW is unknown unless Official FPL supplies separate evidence.",
            "manager_count": len(manager_ids),
            "managers": [{**row, "current_cohort_member": True, "historical_membership_confirmed": None, "membership_at_gw_status": MEMBERSHIP_STATUS, "membership_evidence": MEMBERSHIP_EVIDENCE} for row in manager_rows],
            "authority": "OFFICIAL_FPL_CURRENT_STANDINGS",
        }
        write_json(history_root / "managers.json", managers_artifact)

        complete_gws = sum(1 for row in gw_health if row["complete"])
        partial_gws = sum(1 for row in gw_health if not row["complete"] and row["coverage_percent"] > 0)
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
            "league_id": league_id,
            "league_name": target.get("league_name"),
            "league_kind": target.get("league_kind"),
            "league_resolution": "DYNAMIC_PRIORITY_LEAGUE_NAME_AND_KIND",
            "cohort_semantics": COHORT_SEMANTICS,
            "historical_membership_confirmed": False,
            "gw_from": gw_from,
            "gw_to": gw_to,
            "requested_gw_count": len(gws),
            "complete_gw_count": complete_gws,
            "partial_gw_count": partial_gws,
            "failed_gw_count": failed_gws,
            "overall_status": overall_status,
            "current_cohort_manager_count": len(manager_ids),
            "gw_health": gw_health,
            "cache": {
                "immutable_completed_gw_cache": True,
                "force": bool(force),
                "cache_hits": telemetry["cache_hits"],
                "cache_misses": telemetry["cache_misses"],
                "history_cache_hits": telemetry["history_cache_hits"],
                "history_cache_misses": telemetry["history_cache_misses"],
                "fetched_count": telemetry["fetched_count"],
                "reused_count": telemetry["reused_count"],
            },
            "telemetry": telemetry,
            "governance": _authority(),
            "lineage": {"bootstrap": lineage(bootstrap_result), "entry": lineage(entry_result, entry_id=entry_id), "standings_pages": standings.get("lineage") or [], "authority": "OFFICIAL_FPL"},
            "limitations": [
                "Historical league membership is not inferred from current membership; records are CURRENT_COHORT_HISTORY.",
                "Historical league rank is not asserted; reconstructed_current_cohort_rank uses only today's resolved cohort.",
                "Historical club identity is not asserted when Official historical endpoints do not expose it; element_id remains authoritative.",
            ],
        }
        assert_publish_safe(manifest, secret_values=getattr(self.client, "secret_values", ()))
        write_json(history_root / "manifest.json", manifest)
        write_json(self.output_root / "health" / "historical_backfill.json", manifest)
        return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Governed V6 historical mini-league backfill")
    parser.add_argument("--gw-from", type=int, required=True)
    parser.add_argument("--gw-to", type=int, required=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--requested-by", default="FPL_MASTER_MONITOR")
    parser.add_argument("--config", default="config/v6/consumer_context.json")
    parser.add_argument("--output-root", default="data/v6")
    args = parser.parse_args()
    config = load_consumer_context(Path(args.config))
    service = HistoricalBackfillService(config=config, output_root=Path(args.output_root))
    try:
        manifest = service.run(gw_from=args.gw_from, gw_to=args.gw_to, force=args.force, requested_by=args.requested_by)
    except HistoricalBackfillError as exc:
        print(json.dumps({"status": "RED", "error": safe_error(exc)}, indent=2))
        return 2
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if manifest["overall_status"] == "GREEN" else 3


if __name__ == "__main__":
    raise SystemExit(main())
