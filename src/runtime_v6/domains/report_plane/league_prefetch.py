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
    seen_entry_ids: set[int] = set()
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
        page_ids = frozenset(
            int(row["entry"]) for row in page_rows if isinstance(row, dict) and row.get("entry") is not None
        )
        if page_ids and page_ids <= seen_entry_ids:
            # A repeated page (pagination loop) must not inflate membership or run to the page cap.
            failures.append({"page": page, "status": "DUPLICATE_PAGE", "http_status": None, "error": None})
            break
        for row in page_rows:
            if not isinstance(row, dict) or row.get("entry") is None:
                continue
            if int(row["entry"]) in seen_entry_ids:
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
        seen_entry_ids |= page_ids
        lineages.append(
            lineage(
                result,
                league_id=league_id,
                pagination_coverage={"page": page, "rows_on_page": len(page_rows)},
            )
        )
        if not page_rows and bool(standings.get("has_next")):
            # An empty page that still claims a next page is not a valid end of the standings.
            failures.append({"page": page, "status": "EMPTY_PAGE_BEFORE_END", "http_status": None, "error": None})
            break
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


LEAGUE_CONTEXT_VERSION = "FPL_LEAGUE_CONTEXT_V1"


def build_league_membership_context(
    pages: list[dict[str, Any]],
    *,
    season: str,
    league_id: int,
    gw: int,
    observed_at: str,
    baseline_member_ids: set[int] | None = None,
) -> dict[str, Any]:
    """Facts-only league membership from official standings pages.

    Membership is the set observed at ``observed_at``. It is never presented as historical
    membership: joins/leavers are computed only against an explicit baseline and are otherwise null.
    No Awards utility, forecast or recommendation belongs here.
    """
    members: dict[int, dict[str, Any]] = {}
    reasons: list[str] = []
    seen_pages: list[frozenset[int]] = []
    pages_collected = 0
    duplicate_entries = 0
    ended = False
    for index, page in enumerate(pages or [], start=1):
        league = page.get("league") if isinstance(page, dict) else None
        if isinstance(league, dict) and league.get("id") is not None and int(league["id"]) != int(league_id):
            reasons.append("LEAGUE_MISMATCH")
            break
        standings = (page.get("standings") if isinstance(page, dict) else None) or {}
        rows = [r for r in (standings.get("results") or []) if isinstance(r, dict) and r.get("entry") is not None]
        ids = frozenset(int(r["entry"]) for r in rows)
        if ids and any(ids <= earlier for earlier in seen_pages):
            reasons.append("DUPLICATE_PAGE")
            break
        seen_pages.append(ids)
        pages_collected += 1
        for row in rows:
            entry = int(row["entry"])
            if entry in members:
                duplicate_entries += 1
                continue
            members[entry] = {
                "entry_id": entry,
                "manager_name": row.get("player_name"),
                "team_name": row.get("entry_name"),
                "rank": row.get("rank"),
                "last_rank": row.get("last_rank"),
                "total": row.get("total"),
                "event_total": row.get("event_total"),
            }
        has_next = bool(standings.get("has_next"))
        if not rows and has_next:
            reasons.append("EMPTY_PAGE_BEFORE_END")
            break
        if not has_next:
            ended = True
            break
    if not ended and not reasons:
        reasons.append("NEXT_PAGE_MISSING" if pages_collected else "NO_PAGES")
    ordered = sorted(members.values(), key=lambda m: (m["rank"] is None, m["rank"] or 0, m["entry_id"]))
    by_rank: dict[Any, list[int]] = {}
    for m in ordered:
        if m["rank"] is not None:
            by_rank.setdefault(m["rank"], []).append(m["entry_id"])
    current_ids = set(members)
    return {
        "version": LEAGUE_CONTEXT_VERSION,
        "season": season,
        "league_id": int(league_id),
        "gameweek": int(gw),
        "observed_at": observed_at,
        "authority": "OFFICIAL_FPL",
        "membership_basis": "CURRENT_AT_OBSERVED_AT",
        "members": ordered,
        "coverage": {
            "status": "EMPTY" if not members else ("COMPLETE" if ended and not reasons else "PARTIAL"),
            "pages_collected": pages_collected,
            "members_collected": len(members),
            "duplicate_entries": duplicate_entries,
            "expected_members": None,
            "reasons": reasons,
        },
        "rank_ties": {str(rank): ids for rank, ids in by_rank.items() if len(ids) > 1},
        "joins": sorted(current_ids - baseline_member_ids) if baseline_member_ids is not None else None,
        "leavers": sorted(baseline_member_ids - current_ids) if baseline_member_ids is not None else None,
        "membership_change_basis": "EXPLICIT_BASELINE" if baseline_member_ids is not None else "NO_BASELINE_EVIDENCE",
    }


def standings_artifact(
    *,
    league: dict[str, Any],
    state: dict[str, Any],
    entry_id: int,
    generated_at: str,
) -> dict[str, Any]:
    rows = state["rows"]
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
        "entry_history": normal.get("entry_history"),
        "automatic_subs": normal.get("automatic_subs"),
        "previous_overall_points": None,
        "previous_overall_authority": None,
        "history_lineage": None,
        "official_raw": result.get("payload") if result.get("status") == "LIVE" else None,
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
    include_previous_history: bool = False,
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
        record = _record_from_result(entry_id, gw, client.submitted_picks(entry_id, gw))
        if not include_previous_history or record["status"] != "AVAILABLE":
            return entry_id, record
        # Only the previous GW's Official cumulative total establishes an
        # unambiguous pre-GW baseline. Never subtract current hit twice.
        if gw == 1:
            record["previous_overall_points"] = 0
            record["previous_overall_authority"] = "OFFICIAL_NEW_SEASON_START"
        else:
            fetch_history = getattr(client, "entry_history", None)
            history_result = fetch_history(entry_id) if callable(fetch_history) else {}
            record["history_lineage"] = lineage(history_result, gw=gw - 1, entry_id=entry_id)
            if history_result.get("status") == "LIVE":
                rows = (history_result.get("payload") or {}).get("current") or []
                prior = next(
                    (row for row in rows if isinstance(row, dict)
                     and row.get("event") == gw - 1
                     and isinstance(row.get("total_points"), int)),
                    None,
                )
                if prior is not None:
                    record["previous_overall_points"] = prior["total_points"]
                    record["previous_overall_authority"] = "OFFICIAL_PREVIOUS_GW_HISTORY"
        record["record_digest"] = digest({k: v for k, v in record.items() if k != "record_digest"})
        return entry_id, record

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
    expected_count = len(manager_ids)
    available_count = len(available)
    missing_count = len(missing)
    complete = expected_count > 0 and missing_count == 0
    coverage_percent = round(available_count * 100 / expected_count, 4) if expected_count else 0.0
    health = "GREEN" if complete else ("AMBER" if available_count else "RED")
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
        "expected_manager_count": expected_count,
        "collected_manager_count": available_count,
        "submitted_picks_available_count": available_count,
        "submitted_picks_missing_count": missing_count,
        "coverage_percent": coverage_percent,
        "health": health,
        "missing_entry_ids": missing,
        "complete": complete,
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
                "expected_managers": expected_count,
                "available_managers": available_count,
                "missing_managers": missing_count,
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
                "stats": stats,
                "explain": item.get("explain"),
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


def add_manager_live_totals(
    live: dict[str, Any],
    manager_picks: dict[str, Any],
    points: dict[int, int],
) -> dict[str, Any]:
    """Preserve raw live data without manager-level analytical aggregation."""
    del manager_picks, points
    value = dict(live)
    value.pop("manager_multiplier_points", None)
    value.pop("manager_multiplier_points_semantics", None)
    value["governance"] = {
        **dict(value.get("governance") or {}),
        "data_only": True,
        "manager_live_aggregation_authority": "NONE",
        "manager_live_aggregation": "DOWNSTREAM_ONLY",
    }
    return value
