from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .personal_prefetch import normalise_submitted_picks
from .prefetch_contract import (
    NORMALIZATION_VERSION,
    SCHEMA_VERSION,
    digest,
    iso,
    lineage,
    read_json,
    utc_now,
)
from .security import safe_error


def fetch_all_standings(client: Any, league: dict[str, Any]) -> dict[str, Any]:
    league_id = int(league["league_id"])
    kind = str(league["league_kind"])
    rows: list[dict[str, Any]] = []
    lineages: list[dict[str, Any]] = []
    failures = []
    complete = False
    for page in range(1, 1001):
        result = (
            client.classic_standings(league_id, page)
            if kind == "classic"
            else client.h2h_standings(league_id, page)
        )
        if result.get("status") != "LIVE":
            failures.append(
                {
                    "page": page,
                    "status": result.get("status"),
                    "http_status": result.get("http_status"),
                    "error": result.get("error"),
                }
            )
            break
        payload = result.get("payload") or {}
        standings = payload.get("standings") or {}
        page_rows = standings.get("results") or []
        for row in page_rows:
            if not isinstance(row, dict) or row.get("entry") is None:
                continue
            rows.append(
                {
                    "entry_id": int(row["entry"]),
                    "manager_name": row.get("player_name"),
                    "team_name": row.get("entry_name"),
                    "league_rank": row.get("rank"),
                    "league_total": row.get("total"),
                    "gw_score": row.get("event_total"),
                    "last_rank": row.get("last_rank"),
                }
            )
        lineages.append(
            lineage(
                result,
                league_id=league_id,
                pagination_coverage={"page": page, "rows_on_page": len(page_rows)},
            )
        )
        if not bool(standings.get("has_next")):
            complete = True
            break
    return {
        "rows": rows,
        "complete": complete,
        "pages_collected": len(lineages),
        "failed_pages": failures,
        "lineage": lineages,
    }


def standings_artifact(
    *,
    league: dict[str, Any],
    state: dict[str, Any],
    entry_id: int,
    generated_at: str,
) -> dict[str, Any]:
    rows = state["rows"]
    leader_total = rows[0].get("league_total") if rows else None
    user = next((row for row in rows if row["entry_id"] == entry_id), None)
    return {
        "schema_version": SCHEMA_VERSION,
        "league_id": int(league["league_id"]),
        "league_name": league["league_name"],
        "league_kind": league["league_kind"],
        "generated_at": generated_at,
        "complete": state["complete"],
        "pages_collected": state["pages_collected"],
        "failed_pages": state["failed_pages"],
        "expected_manager_count": len(rows) if state["complete"] else None,
        "collected_manager_count": len(rows),
        "managers": rows,
        "user_summary": {
            "entry_id": entry_id,
            "rank": user.get("league_rank") if user else None,
            "total": user.get("league_total") if user else None,
            "gap_to_first": (
                leader_total - user.get("league_total")
                if user
                and isinstance(leader_total, int)
                and isinstance(user.get("league_total"), int)
                else None
            ),
        },
        "lineage": state["lineage"],
        "authority": "OFFICIAL_FPL",
        "normalization_version": NORMALIZATION_VERSION,
    }


def _record_from_result(entry_id: int, gw: int, result: dict[str, Any]) -> dict[str, Any]:
    normal = normalise_submitted_picks(entry_id, gw, result)
    record = {
        "entry_id": entry_id,
        "gw": gw,
        "status": normal["status"],
        "origin": "LIVE_FETCHED_CURRENT_GW",
        "checked_at": (normal.get("lineage") or {}).get("checked_at"),
        "http_status": (normal.get("lineage") or {}).get("http_status"),
        "payload_digest": (normal.get("lineage") or {}).get("payload_digest"),
        "active_chip": normal.get("active_chip"),
        "picks": normal.get("picks", []),
        "lineage": normal.get("lineage"),
    }
    if record["status"] == "AVAILABLE":
        record["record_digest"] = digest(record)
    return record


def _valid_cached(record: Any, entry_id: int, gw: int) -> bool:
    if not isinstance(record, dict):
        return False
    if record.get("entry_id") != entry_id or record.get("gw") != gw or record.get("status") != "AVAILABLE":
        return False
    expected = record.get("record_digest")
    if not expected:
        return False
    body = {key: value for key, value in record.items() if key != "record_digest"}
    return expected == digest(body)


def acquire_manager_picks(
    client: Any,
    *,
    previous_path: Any,
    season: str,
    league_id: int,
    gw: int,
    manager_ids: list[int],
    deadline_passed: bool,
    workers: int,
    force: bool,
    cache_enabled: bool,
) -> tuple[dict[str, Any], dict[str, int]]:
    previous = (read_json(previous_path) or {}) if cache_enabled else {}
    previous_entries = previous.get("entries") if isinstance(previous.get("entries"), dict) else {}
    manager_ids = sorted(set(int(value) for value in manager_ids))
    manager_set_digest = digest(manager_ids)
    entries: dict[str, dict[str, Any]] = {}
    misses = []
    hits = 0

    for entry_id in manager_ids:
        cached = previous_entries.get(str(entry_id))
        if deadline_passed and not force and _valid_cached(cached, entry_id, gw):
            body = {key: value for key, value in cached.items() if key != "record_digest"}
            body["origin"] = "IMMUTABLE_GW_CACHE_REUSED"
            body["lineage"] = {
                **dict(body.get("lineage") or {}),
                "origin": "IMMUTABLE_GW_CACHE_REUSED",
            }
            body["record_digest"] = digest(body)
            entries[str(entry_id)] = body
            hits += 1
        else:
            misses.append(entry_id)

    def fetch(entry_id: int) -> tuple[int, dict[str, Any]]:
        return entry_id, _record_from_result(entry_id, gw, client.submitted_picks(entry_id, gw))

    used_workers = 0
    if misses:
        used_workers = max(1, min(int(workers), len(misses)))
        with ThreadPoolExecutor(max_workers=used_workers, thread_name_prefix="v6-rival-picks") as pool:
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
                        "origin": "LIVE_FETCHED_CURRENT_GW",
                        "checked_at": iso(utc_now()),
                        "http_status": None,
                        "payload_digest": None,
                        "active_chip": None,
                        "picks": [],
                        "lineage": {
                            "authority": "OFFICIAL_FPL",
                            "endpoint_class": "submitted_picks",
                            "checked_at": iso(utc_now()),
                            "http_status": None,
                            "payload_digest": None,
                            "origin": "LIVE_FETCHED_CURRENT_GW",
                            "gw": gw,
                            "entry_id": entry_id,
                            "league_id": league_id,
                            "pagination_coverage": None,
                            "normalization_version": NORMALIZATION_VERSION,
                            "error": safe_error(exc),
                        },
                    }
                entries[str(entry_id)] = record

    available = [entry_id for entry_id in manager_ids if entries[str(entry_id)]["status"] == "AVAILABLE"]
    missing = [entry_id for entry_id in manager_ids if entries[str(entry_id)]["status"] != "AVAILABLE"]
    origins = {
        "LIVE_FETCHED_CURRENT_GW": sum(
            1 for record in entries.values() if record.get("origin") == "LIVE_FETCHED_CURRENT_GW"
        ),
        "IMMUTABLE_GW_CACHE_REUSED": sum(
            1 for record in entries.values() if record.get("origin") == "IMMUTABLE_GW_CACHE_REUSED"
        ),
    }
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "season": season,
        "gw": gw,
        "league_id": league_id,
        "generated_at": iso(utc_now()),
        "deadline_passed": deadline_passed,
        "immutable_after_deadline": deadline_passed,
        "manager_set_digest": manager_set_digest,
        "expected_manager_count": len(manager_ids),
        "submitted_picks_available_count": len(available),
        "submitted_picks_missing_count": len(missing),
        "missing_entry_ids": missing,
        "complete": not missing,
        "entries": {key: entries[key] for key in sorted(entries, key=int)},
        "cache": {
            "enabled": cache_enabled,
            "cache_hits": hits,
            "cache_misses": len(misses),
            "previous_manager_set_digest": previous.get("manager_set_digest"),
            "manager_set_changed": bool(previous) and previous.get("manager_set_digest") != manager_set_digest,
        },
        "lineage": {
            "authority": "OFFICIAL_FPL",
            "endpoint_class": "submitted_picks",
            "checked_at": max(
                (str(record.get("checked_at")) for record in entries.values() if record.get("checked_at")),
                default=None,
            ),
            "payload_digest": digest(
                sorted(
                    str(record.get("payload_digest"))
                    for record in entries.values()
                    if record.get("payload_digest")
                )
            ),
            "origin_counts": origins,
            "gw": gw,
            "league_id": league_id,
            "pagination_coverage": {
                "expected_managers": len(manager_ids),
                "available_managers": len(available),
                "missing_managers": len(missing),
            },
            "normalization_version": NORMALIZATION_VERSION,
        },
        "authority": "OFFICIAL_FPL",
        "normalization_version": NORMALIZATION_VERSION,
    }
    return artifact, {
        "cache_hits": hits,
        "cache_misses": len(misses),
        "maximum_concurrency_used": used_workers,
    }


def live_state(result: dict[str, Any], gw: int) -> tuple[dict[int, int] | None, dict[str, Any]]:
    if result.get("status") != "LIVE":
        return None, {
            "schema_version": SCHEMA_VERSION,
            "gw": gw,
            "generated_at": iso(utc_now()),
            "status": "UNAVAILABLE",
            "checked_at": result.get("checked_at"),
            "elements": [],
            "lineage": lineage(result, gw=gw),
            "authority": "OFFICIAL_FPL",
        }
    points: dict[int, int] = {}
    elements = []
    for item in (result.get("payload") or {}).get("elements") or []:
        if not isinstance(item, dict) or item.get("id") is None:
            continue
        element_id = int(item["id"])
        stats = item.get("stats") or {}
        if isinstance(stats.get("total_points"), int):
            points[element_id] = stats["total_points"]
        elements.append(
            {
                "element_id": element_id,
                "total_points": stats.get("total_points"),
                "minutes": stats.get("minutes"),
                "bonus": stats.get("bonus"),
                "bps": stats.get("bps"),
            }
        )
    return points, {
        "schema_version": SCHEMA_VERSION,
        "gw": gw,
        "generated_at": iso(utc_now()),
        "status": "AVAILABLE",
        "checked_at": result.get("checked_at"),
        "elements": elements,
        "lineage": lineage(result, gw=gw),
        "authority": "OFFICIAL_FPL",
        "normalization_version": NORMALIZATION_VERSION,
    }


def exposure_artifact(
    manager_picks: dict[str, Any],
    element_index: dict[int, dict[str, Any]],
    *,
    bootstrap_lineage: dict[str, Any] | None,
    live_points: dict[int, int] | None = None,
    live_lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    available = [
        record
        for record in (manager_picks.get("entries") or {}).values()
        if record.get("status") == "AVAILABLE"
    ]
    denominator = len(available)
    aggregate: dict[int, dict[str, Any]] = {}
    for record in available:
        for pick in record.get("picks") or []:
            element_id = int(pick["element_id"])
            row = aggregate.setdefault(
                element_id,
                {
                    "official_element_id": element_id,
                    "managers_owned_count": 0,
                    "starts_count": 0,
                    "captain_count": 0,
                    "vice_count": 0,
                    "bench_count": 0,
                    "multiplier_sum": 0,
                },
            )
            row["managers_owned_count"] += 1
            position = pick.get("squad_position")
            if isinstance(position, int) and position <= 11:
                row["starts_count"] += 1
            else:
                row["bench_count"] += 1
            row["captain_count"] += int(bool(pick.get("captain")))
            row["vice_count"] += int(bool(pick.get("vice_captain")))
            if isinstance(pick.get("multiplier"), (int, float)):
                row["multiplier_sum"] += pick["multiplier"]

    players = []
    for element_id in sorted(aggregate):
        row = aggregate[element_id]
        meta = element_index.get(element_id, {})
        row.update(
            {
                "web_name": meta.get("web_name"),
                "club": meta.get("club"),
                "position": meta.get("position"),
                "manager_count": denominator,
                "ownership_percent": round(row["managers_owned_count"] * 100 / denominator, 4)
                if denominator
                else None,
                "mini_league_effective_ownership_percent": round(
                    row["multiplier_sum"] * 100 / denominator, 4
                )
                if denominator
                else None,
                "live_points": live_points.get(element_id) if live_points is not None else None,
            }
        )
        players.append(row)

    expected = int(manager_picks.get("expected_manager_count") or 0)
    return {
        "schema_version": SCHEMA_VERSION,
        "season": manager_picks.get("season"),
        "gw": manager_picks.get("gw"),
        "league_id": manager_picks.get("league_id"),
        "generated_at": iso(utc_now()),
        "expected_manager_count": expected,
        "collected_manager_count": expected,
        "submitted_picks_available_count": denominator,
        "submitted_picks_missing_count": max(0, expected - denominator),
        "coverage_percent": round(denominator * 100 / expected, 4) if expected else 0.0,
        "ownership_denominator": denominator,
        "ownership_denominator_semantics": "SUBMITTED_PICKS_AVAILABLE_MANAGERS_ONLY",
        "complete": expected > 0 and denominator == expected,
        "players": players,
        "lineage": {
            "submitted_picks": manager_picks.get("lineage"),
            "bootstrap_static": bootstrap_lineage,
            "event_live": live_lineage,
            "normalization_version": NORMALIZATION_VERSION,
        },
        "authority": "OFFICIAL_FPL_DERIVED_FACT",
        "normalization_version": NORMALIZATION_VERSION,
    }


def add_manager_live_totals(
    live: dict[str, Any],
    manager_picks: dict[str, Any],
    points: dict[int, int],
) -> dict[str, Any]:
    value = dict(live)
    totals = []
    for record in (manager_picks.get("entries") or {}).values():
        if record.get("status") != "AVAILABLE":
            continue
        total = 0
        missing = []
        for pick in record.get("picks") or []:
            element_id = int(pick["element_id"])
            multiplier = pick.get("multiplier")
            if element_id not in points or not isinstance(multiplier, (int, float)):
                missing.append(element_id)
                continue
            total += multiplier * points[element_id]
        totals.append(
            {
                "entry_id": record["entry_id"],
                "raw_multiplier_points": total if not missing else None,
                "missing_live_element_ids": sorted(set(missing)),
            }
        )
    value["manager_multiplier_points"] = totals
    value["manager_multiplier_points_semantics"] = (
        "MECHANICAL_SUBMITTED_MULTIPLIER_X_CURRENT_ELEMENT_POINTS"
    )
    return value
