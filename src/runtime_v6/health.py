from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .http_client import utc_now
from .store import EVIDENCE, read_json

_SUCCESS_STATUSES = {"AVAILABLE", "NOT_MODIFIED"}
_SCHEMA_FAILURE_STATUSES = {"INVALID_PAYLOAD", "TRUNCATED"}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _minutes_since(value: str | None) -> float | None:
    dt = _parse_dt(value)
    if dt is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 60.0)


def _seconds_since(value: str | None) -> float | None:
    minutes = _minutes_since(value)
    return minutes * 60.0 if minutes is not None else None


def _effective_data_checked_at(row: dict[str, Any]) -> str | None:
    if row.get("data_origin") == "REVALIDATED_CACHE":
        return row.get("revalidated_at") or row.get("latest_attempt_checked_at") or row.get("checked_at")
    return row.get("checked_at")


def _data_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in (payload.get("data") or {}).values() if isinstance(row, dict)]


def _effective_timestamps(payload: dict[str, Any]) -> list[str]:
    values = [value for row in _data_rows(payload) if (value := _effective_data_checked_at(row))]
    if not values and payload.get("derived_from") and payload.get("checked_at"):
        values.append(str(payload["checked_at"]))
    return values


def _payload_effective_at(payload: dict[str, Any]) -> str | None:
    values = _effective_timestamps(payload)
    return max(values) if values else None


def _max_data_age_minutes(payload: dict[str, Any]) -> float | None:
    ages = [_minutes_since(value) for value in _effective_timestamps(payload)]
    concrete = [age for age in ages if age is not None]
    return max(concrete) if concrete else None


def _last_fetch_at(payload: dict[str, Any]) -> str | None:
    values = [
        str(row["checked_at"])
        for row in (payload.get("attempts") or [])
        if isinstance(row, dict) and row.get("checked_at")
    ]
    return max(values) if values else None


def _last_success_at(payload: dict[str, Any]) -> str | None:
    values = [
        str(row["checked_at"])
        for row in (payload.get("attempts") or [])
        if isinstance(row, dict)
        and row.get("status") in _SUCCESS_STATUSES
        and row.get("checked_at")
    ]
    if values:
        return max(values)
    cached = [
        str(row["checked_at"])
        for row in _data_rows(payload)
        if row.get("checked_at")
    ]
    if cached:
        return max(cached)
    if payload.get("derived_from") and payload.get("checked_at") and payload.get("health") == "GREEN":
        return str(payload["checked_at"])
    return None


def _transport_health(payload: dict[str, Any]) -> str:
    coverage = payload.get("coverage") or {}
    polling = payload.get("polling") or {}
    expected = int(coverage.get("expected_requests") or 0)
    successes = int(coverage.get("successful_checks_this_cycle") or 0)
    usable = int(coverage.get("usable_requests") or 0)
    if polling.get("skipped") is True and usable > 0:
        return "GREEN"
    if payload.get("derived_from"):
        return "GREEN" if payload.get("health") == "GREEN" else ("AMBER" if payload.get("data") else "RED")
    if expected > 0 and successes == expected:
        return "GREEN"
    if successes > 0 or usable > 0:
        return "AMBER"
    return "RED"


def _freshness_dimension(source: dict[str, Any], payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    target = source.get("check_freshness_minutes")
    age = _max_data_age_minutes(payload)
    effective_state = str(payload.get("effective_state") or "")
    usable = bool(payload.get("data"))

    if not usable and not payload.get("derived_from"):
        health, classification = "RED", "HARD_STALE"
    elif age is None:
        health, classification = "AMBER", "UNKNOWN_AGE"
    elif target is not None and age > float(target):
        health, classification = "RED", "HARD_STALE"
    elif effective_state in {"STALE_CACHE", "PARTIAL_CACHE"}:
        health, classification = "AMBER", "STALE_BUT_USABLE"
    else:
        health, classification = "GREEN", "FRESH"

    return health, {
        "classification": classification,
        "target_minutes": target,
        "effective_data_age_minutes": round(age, 3) if age is not None else None,
        "payload_effective_at": _payload_effective_at(payload),
        "source_specific_slo": True,
    }


def _schema_health(payload: dict[str, Any]) -> str:
    attempts = [row for row in (payload.get("attempts") or []) if isinstance(row, dict)]
    failures = [row for row in attempts if row.get("status") in _SCHEMA_FAILURE_STATUSES]
    if not failures:
        return "GREEN"
    return "AMBER" if payload.get("data") else "RED"


def _coverage_health(payload: dict[str, Any]) -> str:
    coverage = payload.get("coverage") or {}
    if isinstance(coverage.get("coverage_ratio"), (int, float)):
        ratio = float(coverage["coverage_ratio"])
        return "GREEN" if ratio >= 1.0 else ("AMBER" if ratio > 0 else "RED")
    expected = coverage.get("expected_requests")
    usable = coverage.get("usable_requests")
    if isinstance(expected, int) and expected > 0 and isinstance(usable, int):
        return "GREEN" if usable == expected else ("AMBER" if usable > 0 else "RED")
    if payload.get("data"):
        return "GREEN"
    return "RED"


def _identity_detail(source: dict[str, Any], identity_map: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    source_id = str(source["id"])
    if source_id == "official_fpl":
        return "GREEN", {
            "status": "CANONICAL_AUTHORITY",
            "join_allowed": True,
            "strategy": "OFFICIAL_FPL_CANONICAL_ID",
        }
    row = dict((identity_map.get("coverage") or {}).get(source_id) or {})
    if not row:
        return "NOT_EVALUATED", {
            "status": "NOT_EVALUATED",
            "join_allowed": False,
            "strategy": None,
        }
    return str(row.get("identity_health") or "NOT_EVALUATED"), {
        "status": row.get("mapped_status"),
        "join_allowed": bool(row.get("join_allowed")),
        "strategy": row.get("strategy"),
        "coverage_ratio": row.get("coverage_ratio"),
        "mapped_player_count": row.get("mapped_player_count"),
        "unmapped_player_count": row.get("unmapped_player_count"),
    }


def _provenance_health(source: dict[str, Any], payload: dict[str, Any]) -> str:
    identity_ok = str(payload.get("source_id") or "") == str(source["id"])
    checked = bool(payload.get("checked_at"))
    governance = payload.get("governance") or {}
    data_only = governance.get("data_only") is True
    rows = _data_rows(payload)
    origins_ok = all(bool(row.get("data_origin")) for row in rows) if rows else bool(payload.get("derived_from"))
    if identity_ok and checked and data_only and origins_ok:
        return "GREEN"
    if identity_ok and checked:
        return "AMBER"
    return "RED"


def _payload_integrity_health(payload: dict[str, Any]) -> str:
    if payload.get("derived_from"):
        return "GREEN" if bool(payload.get("data")) else "RED"
    rows = _data_rows(payload)
    if not rows:
        return "RED"
    verified = [row for row in rows if row.get("sha256")]
    if len(verified) == len(rows):
        return "GREEN"
    return "AMBER" if verified else "RED"


def _current_run_action(payload: dict[str, Any]) -> tuple[str, str]:
    polling = payload.get("polling") or {}
    attempts = [row for row in (payload.get("attempts") or []) if isinstance(row, dict)]
    if polling.get("skipped") is True:
        reason = str(polling.get("reason") or "")
        return (
            "SKIPPED_ALREADY_POLLED" if reason == "ALREADY_POLLED_THIS_SLOT" else "SKIPPED_NOT_DUE",
            reason or "SCHEDULED_SKIP",
        )
    if payload.get("derived_from"):
        return "DERIVED_CURRENT", str(payload.get("effective_state") or "DERIVED_FROM_UPSTREAM")
    if any(row.get("status") == "AVAILABLE" for row in attempts):
        return "FETCHED", "CURRENT_NETWORK_PAYLOAD"
    if any(row.get("status") == "NOT_MODIFIED" for row in attempts):
        return "REVALIDATED", "HTTP_NOT_MODIFIED"
    if attempts:
        return "FETCHED", "CURRENT_FETCH_FAILED_LAST_GOOD_RETAINED" if payload.get("data") else "CURRENT_FETCH_FAILED"
    if payload.get("data"):
        return "REUSED", str(payload.get("effective_state") or "LAST_GOOD_REUSED")
    return "REUSED", "NO_CURRENT_PAYLOAD"


def _cache_observability(payload: dict[str, Any]) -> dict[str, Any]:
    attempts = [row for row in (payload.get("attempts") or []) if isinstance(row, dict)]
    action, reason = _current_run_action(payload)
    effective_at = _payload_effective_at(payload)
    validators = {
        str(row.get("request_id")): {
            "etag": row.get("etag"),
            "last_modified": row.get("last_modified"),
        }
        for row in [*_data_rows(payload), *attempts]
        if row.get("request_id") and (row.get("etag") or row.get("last_modified"))
    }
    latencies = [float(row["latency_ms"]) for row in attempts if isinstance(row.get("latency_ms"), (int, float))]
    network_fetch = any(int(row.get("attempt_count") or 0) > 0 for row in attempts)
    cache_age = _seconds_since(effective_at)
    return {
        "current_run_action": action,
        "current_run_outcome": reason,
        "network_fetch_performed": network_fetch,
        "last_fetch_at": _last_fetch_at(payload),
        "last_success_at": _last_success_at(payload),
        "payload_effective_at": effective_at,
        "cache_age_seconds": round(cache_age, 3) if cache_age is not None else None,
        "last_fetch_duration_ms": max(latencies) if latencies else None,
        "current_run_duration_ms": payload.get("duration_ms"),
        "validators": validators,
        "reuse_reason": reason if action in {"REUSED", "REVALIDATED", "SKIPPED_NOT_DUE", "SKIPPED_ALREADY_POLLED"} else None,
        "zero_duration_is_never_network_fetch_claim": not (
            payload.get("duration_ms") == 0 and network_fetch
        ),
    }


def build_source_health(config: dict[str, Any], results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    sources = []
    counts = {"GREEN": 0, "AMBER": 0, "RED": 0}
    identity_map = read_json(EVIDENCE / "player_identity_map.json") or {}

    for source in config.get("sources") or []:
        payload = results[source["id"]]
        health = str(payload.get("health") or "AMBER")
        counts[health] = counts.get(health, 0) + 1

        checked_at = payload.get("checked_at")
        check_age = _minutes_since(checked_at)
        max_data_age = _max_data_age_minutes(payload)
        coverage = payload.get("coverage") or {}
        polling = payload.get("polling") or {}
        freshness_health, freshness_detail = _freshness_dimension(source, payload)
        identity_health, identity_detail = _identity_detail(source, identity_map)

        sources.append(
            {
                "source_id": source["id"],
                "source_name": source["name"],
                "category": source["category"],
                "critical": bool(source.get("critical")),
                "health": health,
                "availability": payload.get("availability"),
                "effective_state": payload.get("effective_state"),
                "changed": payload.get("changed"),
                "checked_at": checked_at,
                "last_success_at": _last_success_at(payload),
                "check_age_minutes": round(check_age, 3) if check_age is not None else None,
                "max_effective_data_age_minutes": round(max_data_age, 3) if max_data_age is not None else None,
                "check_freshness_target_minutes": source.get("check_freshness_minutes"),
                "duration_ms": payload.get("duration_ms"),
                "health_dimensions": {
                    "transport_health": _transport_health(payload),
                    "freshness_health": freshness_health,
                    "schema_health": _schema_health(payload),
                    "coverage_health": _coverage_health(payload),
                    "identity_health": identity_health,
                    "provenance_health": _provenance_health(source, payload),
                    "payload_integrity": _payload_integrity_health(payload),
                },
                "freshness": freshness_detail,
                "identity": identity_detail,
                "cache_reuse_observability": _cache_observability(payload),
                "coverage": coverage,
                "polling": {
                    "acquisition_kind": source.get("acquisition_kind"),
                    "poll_interval_minutes": polling.get("poll_interval_minutes"),
                    "deadline_window": polling.get("deadline_window"),
                    "skipped": polling.get("skipped", False),
                    "reason": polling.get("reason"),
                    "last_polled_at": polling.get("last_polled_at"),
                },
                "budget": payload.get("budget"),
            }
        )

    overall = "RED" if counts.get("RED", 0) else ("AMBER" if counts.get("AMBER", 0) else "GREEN")
    return {
        "schema_version": 4,
        "generated_at": utc_now(),
        "overall": overall,
        "counts": counts,
        "source_count": len(sources),
        "sources": sources,
        "semantics": {
            "GREEN": "Latest required acquisition/revalidation succeeded, or the source is intentionally not due yet under its registry polling contract. Unchanged upstream data is not degraded.",
            "AMBER": "Usable but partial/cached, credential or verification required, budget exhausted, truncated, or otherwise degraded.",
            "RED": "Critical source has no usable current or cached data.",
            "multidimensional_health": "Transport, freshness, schema, coverage, identity, provenance, and payload integrity are reported independently. Scalar source health remains the operational acquisition summary and never masks a RED identity join dimension.",
            "freshness_classes": {
                "FRESH": "Effective data is inside the source-specific freshness target.",
                "STALE_BUT_USABLE": "A last-good payload remains inside its source-specific target but current revalidation failed.",
                "HARD_STALE": "Effective data is missing or older than the source-specific freshness target.",
            },
        },
    }
