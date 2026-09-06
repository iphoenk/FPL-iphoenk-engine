from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .http_client import utc_now

_HEALTH_ORDER = {"NOT_APPLICABLE": -1, "GREEN": 0, "AMBER": 1, "RED": 2}


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


def _effective_data_checked_at(row: dict[str, Any]) -> str | None:
    if row.get("data_origin") == "REVALIDATED_CACHE":
        return row.get("revalidated_at") or row.get("latest_attempt_checked_at") or row.get("checked_at")
    return row.get("checked_at")


def _max_data_age_minutes(payload: dict[str, Any]) -> float | None:
    ages = [
        _minutes_since(_effective_data_checked_at(row))
        for row in (payload.get("data") or {}).values()
        if isinstance(row, dict)
    ]
    concrete = [age for age in ages if age is not None]
    return max(concrete) if concrete else _minutes_since(payload.get("checked_at"))


def _last_success_at(payload: dict[str, Any]) -> str | None:
    values = [
        row.get("checked_at")
        for row in (payload.get("attempts") or [])
        if row.get("status") in {"AVAILABLE", "NOT_MODIFIED"} and row.get("checked_at")
    ]
    return max(values) if values else payload.get("checked_at")


def _worst(states: list[str]) -> str:
    relevant = [state for state in states if state != "NOT_APPLICABLE"]
    if not relevant:
        return "NOT_APPLICABLE"
    return max(relevant, key=lambda state: _HEALTH_ORDER.get(state, 2))


def _transport_health(source: dict[str, Any], payload: dict[str, Any]) -> str:
    attempts = list(payload.get("attempts") or [])
    coverage = dict(payload.get("coverage") or {})
    polling = dict(payload.get("polling") or {})
    expected = int(coverage.get("expected_requests") or len(source.get("requests") or []) or 0)
    succeeded = int(coverage.get("successful_checks_this_cycle") or 0)
    usable = int(coverage.get("usable_requests") or 0)

    if polling.get("skipped") is True and (usable > 0 or payload.get("availability") in {"AVAILABLE", "PARTIAL"}):
        return "GREEN"
    if expected > 0 and succeeded == expected:
        return "GREEN"
    if any(row.get("status") in {"AVAILABLE", "NOT_MODIFIED"} for row in attempts):
        return "AMBER"
    if usable > 0:
        return "AMBER"
    return "RED" if source.get("critical") else "AMBER"


def _freshness_health(source: dict[str, Any], payload: dict[str, Any], max_data_age: float | None) -> str:
    target = source.get("check_freshness_minutes")
    if max_data_age is None:
        return "RED" if source.get("critical") and payload.get("availability") == "UNAVAILABLE" else "AMBER"
    if target is None:
        return "GREEN"
    target_minutes = max(1.0, float(target))
    if max_data_age <= target_minutes:
        return "GREEN"
    if max_data_age <= target_minutes * 2:
        return "AMBER"
    return "RED"


def _schema_health(source: dict[str, Any], payload: dict[str, Any]) -> str:
    coverage = dict(payload.get("coverage") or {})
    degraded = int(coverage.get("degraded_successes") or 0)
    truncated = int(coverage.get("truncated_attempts") or 0)
    if degraded or truncated:
        return "AMBER"
    if payload.get("availability") == "AVAILABLE":
        return "GREEN"
    if payload.get("availability") == "PARTIAL":
        return "AMBER"
    return "RED" if source.get("critical") else "AMBER"


def _coverage_health(source: dict[str, Any], payload: dict[str, Any]) -> str:
    coverage = dict(payload.get("coverage") or {})
    ratio = coverage.get("coverage_ratio")
    if isinstance(ratio, (int, float)):
        if float(ratio) >= 1.0:
            return "GREEN"
        if float(ratio) > 0:
            return "AMBER"
        return "RED" if source.get("critical") else "AMBER"

    expected = int(coverage.get("expected_requests") or len(source.get("requests") or []) or 0)
    usable = int(coverage.get("usable_requests") or 0)
    if expected == 0:
        return "GREEN" if payload.get("availability") == "AVAILABLE" else "AMBER"
    if usable == expected:
        return "GREEN"
    if usable > 0:
        return "AMBER"
    return "RED" if source.get("critical") else "AMBER"


def _provenance_health(payload: dict[str, Any]) -> str:
    if not payload.get("checked_at"):
        return "RED"
    if payload.get("derived_from"):
        return "GREEN"
    data = dict(payload.get("data") or {})
    if not data:
        return "AMBER"
    rows = [row for row in data.values() if isinstance(row, dict)]
    if rows and all(
        _effective_data_checked_at(row)
        and (row.get("url") or row.get("data_origin") or row.get("request_id"))
        for row in rows
    ):
        return "GREEN"
    return "AMBER"


def _payload_integrity(source: dict[str, Any], payload: dict[str, Any]) -> str:
    coverage = dict(payload.get("coverage") or {})
    if int(coverage.get("truncated_attempts") or 0) > 0:
        return "AMBER"
    if payload.get("error"):
        return "RED" if source.get("critical") else "AMBER"
    if payload.get("availability") == "AVAILABLE":
        return "GREEN"
    if payload.get("availability") == "PARTIAL" or payload.get("data"):
        return "AMBER"
    return "RED" if source.get("critical") else "AMBER"


def _identity_dimension(
    source: dict[str, Any],
    identity_map: dict[str, Any] | None,
) -> tuple[str, dict[str, str]]:
    if source.get("id") == "official_fpl":
        return "GREEN", {"PLAYER": "GREEN", "TEAM": "GREEN", "FIXTURE": "GREEN"}
    if not identity_map:
        return "NOT_APPLICABLE", {}

    scopes = [str(value).upper() for value in source.get("entity_scopes") or []]
    join_scopes = [scope for scope in scopes if scope in {"PLAYER", "TEAM", "FIXTURE"}]
    if not join_scopes:
        return "NOT_APPLICABLE", {}

    bridges = dict(identity_map.get("entity_bridges") or {})
    per_scope: dict[str, str] = {}
    for scope in join_scopes:
        bridge = dict(bridges.get(scope.lower()) or {})
        row = dict((bridge.get("coverage") or {}).get(str(source["id"])) or {})
        per_scope[scope] = str(row.get("identity_health") or "RED")
    return _worst(list(per_scope.values())), per_scope


def build_source_health(
    config: dict[str, Any],
    results: dict[str, dict[str, Any]],
    *,
    identity_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sources = []
    counts = {"GREEN": 0, "AMBER": 0, "RED": 0}
    dimension_counts: dict[str, dict[str, int]] = {
        name: {"GREEN": 0, "AMBER": 0, "RED": 0, "NOT_APPLICABLE": 0}
        for name in (
            "transport",
            "freshness",
            "schema",
            "coverage",
            "identity",
            "provenance",
            "payload_integrity",
        )
    }

    for source in config.get("sources") or []:
        payload = results[source["id"]]
        health = str(payload.get("health") or "AMBER")
        counts[health] = counts.get(health, 0) + 1

        checked_at = payload.get("checked_at")
        check_age = _minutes_since(checked_at)
        max_data_age = _max_data_age_minutes(payload)
        coverage = payload.get("coverage") or {}
        polling = payload.get("polling") or {}
        identity_health, identity_scope_health = _identity_dimension(source, identity_map)

        dimensions = {
            "transport": _transport_health(source, payload),
            "freshness": _freshness_health(source, payload, max_data_age),
            "schema": _schema_health(source, payload),
            "coverage": _coverage_health(source, payload),
            "identity": identity_health,
            "provenance": _provenance_health(payload),
            "payload_integrity": _payload_integrity(source, payload),
        }
        for name, state in dimensions.items():
            dimension_counts[name][state] = dimension_counts[name].get(state, 0) + 1

        sources.append(
            {
                "source_id": source["id"],
                "source_name": source["name"],
                "category": source["category"],
                "critical": bool(source.get("critical")),
                "health": health,
                "dimension_overall": _worst(list(dimensions.values())),
                "health_dimensions": dimensions,
                "entity_scopes": list(source.get("entity_scopes") or []),
                "identity_scope_health": identity_scope_health,
                "availability": payload.get("availability"),
                "effective_state": payload.get("effective_state"),
                "changed": payload.get("changed"),
                "checked_at": checked_at,
                "last_success_at": _last_success_at(payload),
                "check_age_minutes": round(check_age, 3) if check_age is not None else None,
                "max_effective_data_age_minutes": round(max_data_age, 3) if max_data_age is not None else None,
                "check_freshness_target_minutes": source.get("check_freshness_minutes"),
                "duration_ms": payload.get("duration_ms"),
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
        "dimension_counts": dimension_counts,
        "source_count": len(sources),
        "sources": sources,
        "semantics": {
            "legacy_health": "Acquisition compatibility state. It does not imply identity safety or schema completeness.",
            "transport": "Whether the source could be reached/revalidated or has a governed reusable last-good payload.",
            "freshness": "Age of effective data against the source freshness contract.",
            "schema": "Whether acquisition validation completed without degraded/truncated schema evidence.",
            "coverage": "Completeness of expected requests or typed record coverage.",
            "identity": "Deterministic canonical join safety for explicitly declared PLAYER/TEAM/FIXTURE scopes only.",
            "provenance": "Presence of traceable acquisition/derived-source timing and origin metadata.",
            "payload_integrity": "Whether the published payload is usable without truncation or isolated acquisition failure.",
            "NOT_APPLICABLE": "The dimension is not semantically required for this source scope.",
        },
    }
