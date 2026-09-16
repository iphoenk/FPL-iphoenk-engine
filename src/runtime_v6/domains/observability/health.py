from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .entity_scope import entity_scopes_for_source
from .http_client import utc_now

_DIMENSION_STATES = {"GREEN", "AMBER", "RED", "NOT_APPLICABLE"}
_READINESS_ORDER = {"GREEN": 0, "NOT_APPLICABLE": 0, "AMBER": 1, "RED": 2}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
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
    return max(concrete) if concrete else None


def _last_success_at(payload: dict[str, Any]) -> str | None:
    values = [
        row.get("checked_at")
        for row in (payload.get("attempts") or [])
        if row.get("status") in {"AVAILABLE", "NOT_MODIFIED"} and row.get("checked_at")
    ]
    return max(values) if values else None


def _transport_health(source: dict[str, Any], payload: dict[str, Any]) -> str:
    polling = dict(payload.get("polling") or {})
    if polling.get("skipped") is True:
        return "GREEN" if payload.get("availability") != "UNAVAILABLE" else "AMBER"
    attempts = [row for row in payload.get("attempts") or [] if isinstance(row, dict)]
    if not attempts:
        return "GREEN" if payload.get("availability") in {"AVAILABLE", "PARTIAL"} else "AMBER"
    success = sum(row.get("status") in {"AVAILABLE", "NOT_MODIFIED"} for row in attempts)
    if success == len(attempts):
        return "GREEN"
    if success > 0:
        return "AMBER"
    return "RED"


def _freshness_health(source: dict[str, Any], payload: dict[str, Any]) -> str:
    target = float(source.get("check_freshness_minutes") or 90)
    age = _max_data_age_minutes(payload)
    if age is None:
        age = _minutes_since(payload.get("checked_at"))
    if age is None:
        return "RED" if source.get("critical") else "AMBER"
    if age <= target:
        return "GREEN"
    if age <= target * 2:
        return "AMBER"
    return "RED"


def _schema_health(payload: dict[str, Any]) -> str:
    coverage = dict(payload.get("coverage") or {})
    if int(coverage.get("truncated_attempts") or 0) > 0:
        return "RED"
    attempts = [row for row in payload.get("attempts") or [] if isinstance(row, dict)]
    successful = [row for row in attempts if row.get("status") in {"AVAILABLE", "NOT_MODIFIED"}]
    if any(row.get("health") not in {None, "GREEN"} for row in successful):
        return "AMBER"
    if payload.get("availability") == "UNAVAILABLE" and not successful and attempts:
        return "AMBER"
    return "GREEN"


def _coverage_health(source: dict[str, Any], payload: dict[str, Any]) -> str:
    coverage = dict(payload.get("coverage") or {})
    if "coverage_ratio" in coverage:
        try:
            ratio = float(coverage.get("coverage_ratio") or 0.0)
        except (TypeError, ValueError):
            ratio = 0.0
        if ratio >= 0.999999:
            return "GREEN"
        if ratio > 0:
            return "AMBER"
        return "RED" if source.get("critical") else "AMBER"
    expected = int(coverage.get("expected_requests") or 0)
    usable = int(coverage.get("usable_requests") or 0)
    if expected <= 0:
        return "GREEN" if payload.get("availability") in {"AVAILABLE", "PARTIAL"} else "AMBER"
    if usable >= expected:
        return "GREEN"
    if usable > 0:
        return "AMBER"
    return "RED" if source.get("critical") else "AMBER"


def _identity_scope_health(
    source_id: str,
    scopes: list[str],
    identity_map: dict[str, Any],
) -> tuple[str, dict[str, str]]:
    applicable: dict[str, str] = {}
    if "PLAYER" in scopes:
        row = dict((identity_map.get("coverage") or {}).get(source_id) or {})
        applicable["PLAYER"] = str(row.get("identity_health") or "RED")
    bridges = dict(identity_map.get("entity_bridges") or {})
    if "TEAM" in scopes:
        row = dict(((bridges.get("team") or {}).get("coverage") or {}).get(source_id) or {})
        applicable["TEAM"] = str(row.get("identity_health") or "RED")
    if "FIXTURE" in scopes:
        row = dict(((bridges.get("fixture") or {}).get("coverage") or {}).get(source_id) or {})
        applicable["FIXTURE"] = str(row.get("identity_health") or "RED")

    if not applicable:
        return "NOT_APPLICABLE", {}
    states = set(applicable.values())
    if "RED" in states:
        return "RED", applicable
    if "AMBER" in states:
        return "AMBER", applicable
    return "GREEN", applicable


def _provenance_health(payload: dict[str, Any]) -> str:
    if not payload.get("source_id") or not payload.get("checked_at"):
        return "RED"
    if payload.get("semantic_class") == "UPSTREAM_MODEL_SIGNAL":
        if not payload.get("model_author") or payload.get("v6_computation") != "NONE":
            return "RED"
    attempts = [row for row in payload.get("attempts") or [] if isinstance(row, dict)]
    for row in attempts:
        if row.get("status") in {"AVAILABLE", "NOT_MODIFIED"} and not row.get("checked_at"):
            return "AMBER"
    return "GREEN"


def _payload_integrity(payload: dict[str, Any]) -> str:
    coverage = dict(payload.get("coverage") or {})
    if int(coverage.get("truncated_attempts") or 0) > 0:
        return "RED"
    data_rows = [row for row in (payload.get("data") or {}).values() if isinstance(row, dict)]
    raw_rows = [row for row in data_rows if row.get("data_origin") in {"CURRENT_CYCLE", "REVALIDATED_CACHE", "LAST_GOOD_CACHE"}]
    if raw_rows and any(not row.get("sha256") for row in raw_rows):
        return "AMBER"
    if payload.get("semantic_class") == "UPSTREAM_MODEL_SIGNAL" and payload.get("v6_computation") != "NONE":
        return "RED"
    return "GREEN"


def _current_run_action(payload: dict[str, Any]) -> str:
    polling = dict(payload.get("polling") or {})
    if polling.get("skipped") is True:
        reason = str(polling.get("reason") or "")
        return "SKIPPED_ALREADY_POLLED" if "ALREADY" in reason else "SKIPPED_NOT_DUE"
    value = str(payload.get("current_run_action") or "")
    if value:
        return value
    origins = {
        str(row.get("data_origin") or "")
        for row in (payload.get("data") or {}).values()
        if isinstance(row, dict)
    }
    if "LAST_GOOD_CACHE" in origins:
        return "LAST_GOOD_CACHE"
    if "REVALIDATED_CACHE" in origins:
        return "REVALIDATED"
    return "FETCHED"


def _worst_state(states: list[str]) -> str:
    concrete = [state for state in states if state != "NOT_APPLICABLE"]
    if not concrete:
        return "NOT_APPLICABLE"
    return max(concrete, key=lambda state: _READINESS_ORDER.get(state, 1))


def _readiness(dimensions: dict[str, str]) -> dict[str, str]:
    operational = _worst_state(
        [
            dimensions["transport_health"],
            dimensions["freshness_health"],
            dimensions["provenance_health"],
            dimensions["payload_integrity"],
        ]
    )
    data = _worst_state(
        [
            dimensions["freshness_health"],
            dimensions["schema_health"],
            dimensions["coverage_health"],
            dimensions["payload_integrity"],
        ]
    )
    return {
        "operational": operational,
        "data": data,
        "join": dimensions["identity_health"],
    }


def _fallback_reason(dimensions: dict[str, str], payload: dict[str, Any]) -> str | None:
    if dimensions["transport_health"] != "GREEN" or payload.get("availability") == "UNAVAILABLE":
        return "TRANSPORT_UNAVAILABLE"
    if dimensions["freshness_health"] != "GREEN":
        return "STALE"
    if dimensions["schema_health"] != "GREEN":
        return "SCHEMA_UNAVAILABLE"
    if dimensions["coverage_health"] != "GREEN":
        return "COVERAGE_INCOMPLETE"
    if dimensions["payload_integrity"] != "GREEN":
        return "PAYLOAD_INTEGRITY"
    if dimensions["provenance_health"] != "GREEN":
        return "PROVENANCE_INCOMPLETE"
    return None


def build_source_health(
    config: dict[str, Any],
    results: dict[str, dict[str, Any]],
    identity_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    identity_map = identity_map or {}
    sources = []
    counts = {"GREEN": 0, "AMBER": 0, "RED": 0}
    dimension_counts: dict[str, dict[str, int]] = {}
    readiness_counts = {
        "operational": {"GREEN": 0, "AMBER": 0, "RED": 0, "NOT_APPLICABLE": 0},
        "data": {"GREEN": 0, "AMBER": 0, "RED": 0, "NOT_APPLICABLE": 0},
        "join": {"GREEN": 0, "AMBER": 0, "RED": 0, "NOT_APPLICABLE": 0},
    }
    fallback_sources: list[dict[str, str]] = []
    critical_readiness: list[str] = []

    for source in config.get("sources") or []:
        payload = results[source["id"]]
        health = str(payload.get("health") or "AMBER")
        counts[health] = counts.get(health, 0) + 1

        checked_at = payload.get("checked_at")
        check_age = _minutes_since(checked_at)
        max_data_age = _max_data_age_minutes(payload)
        coverage = payload.get("coverage") or {}
        polling = payload.get("polling") or {}
        scopes = entity_scopes_for_source(source)
        identity_health, identity_by_scope = _identity_scope_health(
            str(source["id"]), scopes, identity_map
        )
        dimensions = {
            "transport_health": _transport_health(source, payload),
            "freshness_health": _freshness_health(source, payload),
            "schema_health": _schema_health(payload),
            "coverage_health": _coverage_health(source, payload),
            "identity_health": identity_health,
            "provenance_health": _provenance_health(payload),
            "payload_integrity": _payload_integrity(payload),
        }
        for dimension, state in dimensions.items():
            if state not in _DIMENSION_STATES:
                state = "AMBER"
                dimensions[dimension] = state
            bucket = dimension_counts.setdefault(
                dimension,
                {"GREEN": 0, "AMBER": 0, "RED": 0, "NOT_APPLICABLE": 0},
            )
            bucket[state] = bucket.get(state, 0) + 1

        readiness = _readiness(dimensions)
        for name, state in readiness.items():
            readiness_counts[name][state] = readiness_counts[name].get(state, 0) + 1
        consumer_state = _worst_state([readiness["operational"], readiness["data"]])
        if bool(source.get("critical")):
            critical_readiness.append(consumer_state)
        fallback_reason = _fallback_reason(dimensions, payload)
        fallback_recommended = fallback_reason is not None
        if fallback_recommended:
            fallback_sources.append(
                {"source_id": str(source["id"]), "reason": str(fallback_reason)}
            )

        sources.append(
            {
                "source_id": source["id"],
                "source_name": source["name"],
                "category": source["category"],
                "critical": bool(source.get("critical")),
                "entity_scopes": scopes,
                "health": health,
                "dimensions": dimensions,
                "readiness": readiness,
                "consumer_readiness": consumer_state,
                "fallback_recommended": fallback_recommended,
                "fallback_reason": fallback_reason,
                "identity_by_scope": identity_by_scope,
                "join_ready": identity_health in {"GREEN", "NOT_APPLICABLE"},
                "availability": payload.get("availability"),
                "effective_state": payload.get("effective_state"),
                "changed": payload.get("changed"),
                "checked_at": checked_at,
                "last_success_at": _last_success_at(payload),
                "check_age_minutes": round(check_age, 3) if check_age is not None else None,
                "max_effective_data_age_minutes": round(max_data_age, 3) if max_data_age is not None else None,
                "check_freshness_target_minutes": source.get("check_freshness_minutes"),
                "duration_ms": payload.get("duration_ms"),
                "current_run_action": _current_run_action(payload),
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
    public_core_status = _worst_state(critical_readiness) if critical_readiness else "GREEN"
    consumer_readiness_overall = _worst_state(
        [str(row["consumer_readiness"]) for row in sources]
    ) if sources else "GREEN"
    return {
        "schema_version": 5,
        "generated_at": utc_now(),
        "overall": overall,
        "public_core_status": public_core_status,
        "consumer_readiness_overall": consumer_readiness_overall,
        "fallback_recommended": bool(fallback_sources),
        "fallback_sources": fallback_sources,
        "counts": counts,
        "dimension_counts": dimension_counts,
        "readiness_counts": readiness_counts,
        "source_count": len(sources),
        "sources": sources,
        "semantics": {
            "health": "Backward-compatible operational acquisition health; inspect readiness and dimensions for consumer usability.",
            "public_core_status": "Critical public V6 data-plane readiness only; authenticated personal state is a separate report-prefetch concern.",
            "consumer_readiness_overall": "Worst operational/data readiness across all active public sources; identity is intentionally reported separately.",
            "fallback_recommended": "Machine-readable hint for FPL Master/report layer to refresh only degraded, stale, or unusable public resources directly. V6 itself never performs downstream fallback.",
            "transport_health": "Whether the current network/source acquisition attempt succeeded independently of cache freshness.",
            "freshness_health": "Age of the effective payload against the source-specific freshness target.",
            "schema_health": "Whether the payload passed structural/validation checks without truncation or degraded successful reads.",
            "coverage_health": "Whether the expected source-native requests/records are materially covered.",
            "identity_health": "Deterministic cross-source identity readiness only for entity scopes relevant to this source; unmapped identity does not make source-native public facts unavailable.",
            "provenance_health": "Whether source identity, timestamps, and upstream-model authorship lineage are explicit.",
            "payload_integrity": "Whether payload hashes/truncation/model-signal boundaries are internally consistent.",
        },
    }
