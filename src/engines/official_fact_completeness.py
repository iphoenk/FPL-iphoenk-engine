from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable

from src.engines.base_state import bootstrap_maps

PUBLIC_OFFICIAL_FACT = "PUBLIC_OFFICIAL_FACT"
PERSONAL_AUTH_FACT = "PERSONAL_AUTH_FACT"
RESOLVER_METHOD = "OFFICIAL_BOOTSTRAP_ELEMENT_ID"
EXPECTED_OWNED = 15
EXPECTED_WATCHLIST = 20
EXPECTED_RESOLVED_TOTAL = EXPECTED_OWNED + EXPECTED_WATCHLIST
WATCHLIST_POSITIONS = ("GK", "DEF", "MID", "FWD")
WATCHLIST_PER_POSITION = 5
REQUIRED_PUBLIC_FIELDS = (
    "element_id",
    "team",
    "position",
    "current_price",
    "current_ownership_pct",
    "status",
)
FALLBACK_BANNER = "OFFICIAL FRESH PULL FAILED — FALLBACK TO LAST VERIFIED SNAPSHOT"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snapshot_metadata(snapshot: dict[str, Any]) -> dict[str, Any]:
    bootstrap = snapshot.get("bootstrap") or {}
    health = (snapshot.get("endpoint_health") or {}).get("bootstrap") or {}
    freshness = snapshot.get("official_freshness") or {}
    health_status = str(health.get("status") or "UNKNOWN").upper()
    fallback = bool(freshness.get("fallback")) or str(freshness.get("state") or "").upper() == "FALLBACK"
    fresh_pull_succeeded = bool(bootstrap) and health_status in {"LIVE", "FRESH"} and not fallback
    verified_fallback = bool(
        fallback
        and bootstrap
        and freshness.get("last_verified_at")
        and str(freshness.get("confidence") or "").upper() == "DOWNGRADED"
    )
    if verified_fallback:
        fetched_at = freshness.get("last_verified_at")
    else:
        fetched_at = health.get("fetched_at") or freshness.get("last_verified_at") or snapshot.get("generated_at")
    snapshot_id = str(freshness.get("snapshot_id") or f"bootstrap-static@{fetched_at or 'unknown'}")
    return {
        "authority": PUBLIC_OFFICIAL_FACT,
        "source": "Official FPL bootstrap-static",
        "snapshot_id": snapshot_id,
        "snapshot_generated_at": snapshot.get("generated_at"),
        "fetched_at": fetched_at,
        "fresh_pull_succeeded": fresh_pull_succeeded,
        "verified_fallback": verified_fallback,
        "trusted_snapshot": fresh_pull_succeeded or verified_fallback,
        "freshness_state": "FALLBACK" if verified_fallback else "FRESH" if fresh_pull_succeeded else "UNAVAILABLE",
        "fallback": verified_fallback,
        "fallback_banner": FALLBACK_BANNER if verified_fallback else None,
        "last_verified_at": freshness.get("last_verified_at"),
        "fresh_pull_failed_at": freshness.get("fresh_pull_failed_at"),
        "age_seconds": freshness.get("age_seconds"),
        "confidence": freshness.get("confidence") or ("DOWNGRADED" if verified_fallback else "HIGH" if fresh_pull_succeeded else "UNKNOWN"),
        "bootstrap_health": health_status,
    }


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _defect_code(meta: dict[str, Any]) -> str:
    return "DATA_JOIN_DEFECT" if meta.get("fresh_pull_succeeded") else "OFFICIAL_SOURCE_UNAVAILABLE"


def _resolver_provenance(element_id: int, meta: dict[str, Any], *, resolved_element_id: int | None) -> dict[str, Any]:
    return {
        "resolver": RESOLVER_METHOD,
        "lookup_key": "element_id",
        "requested_element_id": element_id,
        "resolved_element_id": resolved_element_id,
        "resolved": resolved_element_id is not None,
        "snapshot_id": meta["snapshot_id"],
    }


def _hydrate(
    element_ids: Iterable[int],
    snapshot: dict[str, Any],
    *,
    scope: str,
) -> dict[str, Any]:
    meta = _snapshot_metadata(snapshot)
    bootstrap = snapshot.get("bootstrap") or {}
    teams, positions, by_id = bootstrap_maps(bootstrap) if bootstrap else ({}, {}, {})
    requested = [int(value) for value in element_ids]
    rows: list[dict[str, Any]] = []
    defects: list[dict[str, Any]] = []
    resolved = 0
    complete = 0
    resolver_provenance_complete = 0

    for element_id in requested:
        player = by_id.get(element_id)
        if not player:
            defects.append({
                "scope": scope,
                "element_id": element_id,
                "code": "ELEMENT_ID_UNRESOLVED",
                "message": "canonical Official FPL element_id did not resolve in the governed bootstrap snapshot",
                "resolver_provenance": _resolver_provenance(element_id, meta, resolved_element_id=None),
            })
            continue
        resolved += 1
        resolved_element_id = int(player.get("id") if player.get("id") is not None else element_id)
        resolver_provenance = _resolver_provenance(element_id, meta, resolved_element_id=resolved_element_id)
        if resolved_element_id != element_id:
            defects.append({
                "scope": scope,
                "element_id": element_id,
                "code": "ELEMENT_ID_RESOLUTION_MISMATCH",
                "message": "canonical element-id resolver returned a different Official FPL element id",
                "resolver_provenance": resolver_provenance,
            })
        else:
            resolver_provenance_complete += 1

        team = teams.get(int(player.get("team") or -1))
        position = positions.get(int(player.get("element_type") or -1))
        now_cost = player.get("now_cost")
        ownership = player.get("selected_by_percent")
        status = player.get("status")
        row = {
            "element_id": element_id,
            "element": element_id,
            "name": player.get("web_name") or player.get("first_name") or str(element_id),
            "web_name": player.get("web_name"),
            "team": team,
            "team_id": player.get("team"),
            "position": position,
            "element_type": player.get("element_type"),
            "now_cost": now_cost,
            "current_price": round(float(now_cost) / 10.0, 1) if now_cost is not None else None,
            "selected_by_percent": ownership,
            "current_ownership_pct": ownership,
            "status": status,
            "availability_news": player.get("news"),
            "chance_of_playing_next_round": player.get("chance_of_playing_next_round"),
            "fact_authority": PUBLIC_OFFICIAL_FACT,
            "resolver_provenance": resolver_provenance,
            "official_fact_provenance": {
                "source": meta["source"],
                "snapshot_id": meta["snapshot_id"],
                "snapshot_generated_at": meta["snapshot_generated_at"],
                "fetched_at": meta["fetched_at"],
                "freshness_state": meta["freshness_state"],
                "fallback": meta["fallback"],
            },
        }
        missing_fields = [field for field in REQUIRED_PUBLIC_FIELDS if _missing(row.get(field))]
        if missing_fields:
            defects.append({
                "scope": scope,
                "element_id": element_id,
                "code": _defect_code(meta),
                "missing_fields": missing_fields,
                "message": "required Official FACT field missing after canonical element-id join",
            })
        else:
            complete += 1
        rows.append(row)

    snapshot_ids = {
        str((row.get("official_fact_provenance") or {}).get("snapshot_id"))
        for row in rows
        if (row.get("official_fact_provenance") or {}).get("snapshot_id")
    }
    if len(snapshot_ids) > 1:
        defects.append({
            "scope": scope,
            "code": "MIXED_OFFICIAL_SNAPSHOT",
            "snapshot_ids": sorted(snapshot_ids),
            "message": "public Official facts were hydrated from more than one bootstrap snapshot",
        })

    return {
        "requested": len(requested),
        "resolved": resolved,
        "resolver_provenance_complete": resolver_provenance_complete,
        "official_fact_complete": complete,
        "rows": rows,
        "defects": defects,
        "snapshot_id": meta["snapshot_id"],
        "freshness_state": meta["freshness_state"],
    }


def _watchlist_ids(positions: dict[str, Any]) -> tuple[list[int], dict[str, int], list[dict[str, Any]]]:
    ids: list[int] = []
    counts: dict[str, int] = {}
    defects: list[dict[str, Any]] = []
    for position in WATCHLIST_POSITIONS:
        rows = list(positions.get(position) or [])
        counts[position] = len(rows)
        if len(rows) != WATCHLIST_PER_POSITION:
            defects.append({
                "scope": "watchlist",
                "code": "WATCHLIST_POSITION_COUNT_INVALID",
                "position": position,
                "actual": len(rows),
                "expected": WATCHLIST_PER_POSITION,
            })
        for row in rows:
            try:
                ids.append(int(row.get("element")))
            except (TypeError, ValueError, AttributeError):
                defects.append({
                    "scope": "watchlist",
                    "code": "ELEMENT_ID_UNRESOLVED",
                    "position": position,
                    "message": "watchlist row does not expose a canonical element_id",
                })
    return ids, counts, defects


def build_public_official_fact_integrity(
    snapshot: dict[str, Any],
    owned_ids: Iterable[int],
    watchlist_positions: dict[str, Any],
    *,
    personal_auth: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = _snapshot_metadata(snapshot)
    owned = [int(value) for value in owned_ids]
    watch_ids, position_counts, structural_defects = _watchlist_ids(watchlist_positions)

    owned_hydration = _hydrate(owned, snapshot, scope="owned")
    watch_hydration = _hydrate(watch_ids, snapshot, scope="watchlist")
    defects = [*structural_defects, *owned_hydration["defects"], *watch_hydration["defects"]]

    if not meta["trusted_snapshot"]:
        defects.append({
            "scope": "publication",
            "code": "OFFICIAL_SOURCE_UNAVAILABLE",
            "message": "publication requires a fresh Official snapshot or a previously verified fallback snapshot",
        })
    if len(owned) != EXPECTED_OWNED or len(set(owned)) != EXPECTED_OWNED:
        defects.append({
            "scope": "owned",
            "code": "OWNED_COUNT_INVALID",
            "actual": len(owned),
            "unique": len(set(owned)),
            "expected": EXPECTED_OWNED,
        })
    if len(watch_ids) != EXPECTED_WATCHLIST or len(set(watch_ids)) != EXPECTED_WATCHLIST:
        defects.append({
            "scope": "watchlist",
            "code": "WATCHLIST_COUNT_INVALID",
            "actual": len(watch_ids),
            "unique": len(set(watch_ids)),
            "expected": EXPECTED_WATCHLIST,
        })
    overlap = sorted(set(owned) & set(watch_ids))
    if overlap:
        defects.append({
            "scope": "watchlist",
            "code": "OWNED_PLAYER_IN_WATCHLIST",
            "element_ids": overlap,
        })

    all_snapshot_ids = {
        owned_hydration.get("snapshot_id"),
        watch_hydration.get("snapshot_id"),
    } - {None}
    if len(all_snapshot_ids) != 1:
        defects.append({
            "scope": "publication",
            "code": "MIXED_OFFICIAL_SNAPSHOT",
            "snapshot_ids": sorted(str(value) for value in all_snapshot_ids),
        })

    resolver_complete = (
        int(owned_hydration["resolver_provenance_complete"])
        + int(watch_hydration["resolver_provenance_complete"])
    )
    resolver_ok = (
        owned_hydration["resolver_provenance_complete"] == EXPECTED_OWNED
        and watch_hydration["resolver_provenance_complete"] == EXPECTED_WATCHLIST
        and resolver_complete == EXPECTED_RESOLVED_TOTAL
    )
    if not resolver_ok:
        defects.append({
            "scope": "publication",
            "code": "RESOLVER_PROVENANCE_INCOMPLETE",
            "actual": resolver_complete,
            "expected": EXPECTED_RESOLVED_TOTAL,
            "message": "all 35 published Official FACT rows require auditable canonical element-id resolver provenance",
        })

    owned_ok = (
        len(owned) == EXPECTED_OWNED
        and len(set(owned)) == EXPECTED_OWNED
        and owned_hydration["resolved"] == EXPECTED_OWNED
        and owned_hydration["official_fact_complete"] == EXPECTED_OWNED
    )
    watch_ok = (
        len(watch_ids) == EXPECTED_WATCHLIST
        and len(set(watch_ids)) == EXPECTED_WATCHLIST
        and all(position_counts.get(position) == WATCHLIST_PER_POSITION for position in WATCHLIST_POSITIONS)
        and not overlap
        and watch_hydration["resolved"] == EXPECTED_WATCHLIST
        and watch_hydration["official_fact_complete"] == EXPECTED_WATCHLIST
    )
    complete_and_trusted = owned_ok and watch_ok and resolver_ok and meta["trusted_snapshot"] and not defects
    publication_status = "PASS" if complete_and_trusted and meta["fresh_pull_succeeded"] else "DEGRADED" if complete_and_trusted and meta["verified_fallback"] else "BLOCKED"

    auth = personal_auth or {}
    auth_status = str(auth.get("status") or auth.get("state") or "UNAVAILABLE").upper()
    health = {
        "Official public pull": "PASS" if meta["fresh_pull_succeeded"] else "DEGRADED" if meta["verified_fallback"] else "BLOCKED",
        "Personal authenticated pull": auth_status,
        "Element-ID Resolver": "PASS" if resolver_ok else "BLOCKED",
        "Official Fact Join": "PASS" if not any(row.get("code") in {"DATA_JOIN_DEFECT", "MIXED_OFFICIAL_SNAPSHOT", "OFFICIAL_SOURCE_UNAVAILABLE", "ELEMENT_ID_RESOLUTION_MISMATCH", "RESOLVER_PROVENANCE_INCOMPLETE"} for row in defects) else "BLOCKED",
        "Owned Fact Completeness": "PASS" if owned_ok else "BLOCKED",
        "Watchlist Fact Completeness": "PASS" if watch_ok else "BLOCKED",
        "Publication Integrity Gate": publication_status,
        "Reporting": "READY" if publication_status == "PASS" else "DEGRADED" if publication_status == "DEGRADED" else "BLOCKED",
        "Serving": "READY" if publication_status == "PASS" else "DEGRADED" if publication_status == "DEGRADED" else "BLOCKED",
    }

    return {
        "schema": "official_fact_integrity.v1",
        "generated_at": _now(),
        "authority_model": {
            "public_official_fact": PUBLIC_OFFICIAL_FACT,
            "personal_auth_fact": PERSONAL_AUTH_FACT,
            "personal_auth_failure_cannot_erase_public_facts": True,
        },
        "official_snapshot": meta,
        "resolver": {
            "method": RESOLVER_METHOD,
            "expected": EXPECTED_RESOLVED_TOTAL,
            "provenance_complete": resolver_complete,
            "status": "PASS" if resolver_ok else "BLOCKED",
        },
        "owned": {
            "expected": EXPECTED_OWNED,
            "resolved": owned_hydration["resolved"],
            "resolver_provenance_complete": owned_hydration["resolver_provenance_complete"],
            "official_fact_complete": owned_hydration["official_fact_complete"],
            "visible_gate": f"Owned Official FACT completeness = {owned_hydration['official_fact_complete']}/{EXPECTED_OWNED}",
            "rows": owned_hydration["rows"],
        },
        "watchlist": {
            "expected": EXPECTED_WATCHLIST,
            "resolved": watch_hydration["resolved"],
            "resolver_provenance_complete": watch_hydration["resolver_provenance_complete"],
            "official_fact_complete": watch_hydration["official_fact_complete"],
            "position_counts": position_counts,
            "visible_gate": f"Watchlist Official FACT completeness = {watch_hydration['official_fact_complete']}/{EXPECTED_WATCHLIST}",
            "rows": watch_hydration["rows"],
        },
        "publication_integrity": {
            "status": publication_status,
            "complete_user_report_allowed": publication_status in {"PASS", "DEGRADED"},
            "reasons": defects,
            "reason_counts": dict(Counter(str(row.get("code")) for row in defects)),
        },
        "health": health,
    }


def require_complete_user_report(integrity: dict[str, Any]) -> None:
    gate = integrity.get("publication_integrity") or {}
    if gate.get("complete_user_report_allowed") is True and gate.get("status") in {"PASS", "DEGRADED"}:
        return
    reasons = [str(row.get("code")) for row in gate.get("reasons") or []]
    raise RuntimeError(f"USER_REPORT BLOCKED: Official FACT completeness failed: {reasons}")
