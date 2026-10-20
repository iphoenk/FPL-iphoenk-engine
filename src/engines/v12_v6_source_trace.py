"""Read-only occurrence-bound V6 source lineage for V12 presentation.

This is provider ACQUISITION telemetry, not proof of source-category news
review, independent counterpart assessments, or a completed deadline check.
Never supply it as news_source_coverage or use it to promote READY_FULL.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Mapping

INDEX = "data/v6/evidence/latest_index.json"
REGISTRY = "data/v6/evidence/resolved_registry.json"
TEAMS = "data/v6/normalized/canonical_teams.json"
INTEGRITY = "data/v6/health/publish_integrity.json"


def _read(root: Path, name: str) -> dict[str, Any]:
    try:
        value = json.loads((root / name).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _aware(raw: Any) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(raw or "").replace("Z", "+00:00"))
        return value if value.tzinfo and value.utcoffset() is not None else None
    except (TypeError, ValueError):
        return None


def build_v6_source_trace(*, runtime_data_root: Path, report_slot: str) -> dict[str, Any]:
    """Bind verified V6 acquisition metadata without creating synthetic scans."""
    integrity = _read(runtime_data_root, INTEGRITY)
    index = _read(runtime_data_root, INDEX)
    registry = _read(runtime_data_root, REGISTRY)
    teams = _read(runtime_data_root, TEAMS)
    failures: list[str] = []
    slot_time, acquired_at = _aware(report_slot), _aware(index.get("generated_at"))
    if slot_time is None or acquired_at is None:
        failures.append("V6_ACQUISITION_TIME_INVALID")
    elif not slot_time - timedelta(minutes=90) <= acquired_at <= slot_time + timedelta(minutes=15):
        failures.append("V6_ACQUISITION_OUTSIDE_OCCURRENCE_WINDOW")
    if integrity.get("status") != "PASS":
        failures.append("V6_PUBLISH_INTEGRITY_NOT_PASS")
    if str(integrity.get("logical_slot") or "") != report_slot:
        failures.append("V6_PUBLICATION_SLOT_MISMATCH")
    publication_run_id = str(integrity.get("run_id") or "").strip()
    if not publication_run_id:
        failures.append("V6_PUBLICATION_RUN_MISSING")

    source_rows = [x for x in index.get("sources") or [] if isinstance(x, Mapping)]
    registry_rows = [x for x in registry.get("sources") or [] if isinstance(x, Mapping)]
    config = {str(x.get("id") or ""): x for x in registry_rows}
    source_ids = [str(x.get("source_id") or "") for x in source_rows]
    if not source_rows or len(set(source_ids)) != len(source_ids) or any(not i for i in source_ids):
        failures.append("V6_SOURCE_INDEX_INVALID")
    if not config or any(i not in config for i in source_ids):
        failures.append("V6_SOURCE_REGISTRY_MISMATCH")

    observed: list[dict[str, Any]] = []
    for row in source_rows:
        sid = str(row.get("source_id") or "")
        checked_at = _aware(row.get("checked_at"))
        if checked_at is None or slot_time is None or not (
            slot_time - timedelta(minutes=90) <= checked_at <= slot_time + timedelta(minutes=15)
        ):
            failures.append("V6_SOURCE_ATTEMPT_TIME_INVALID:" + sid)
        snapshots = [str(x) for x in row.get("source_snapshot_ids") or [] if isinstance(x, str)]
        # A provider can be healthy without a news claim, or without snapshot IDs
        # (for example an official derived price predictor).
        observed.append({
            "source_id": sid,
            "independence_group": row.get("independence_group"),
            "health": row.get("health"),
            "availability": row.get("availability"),
            "checked_at": row.get("checked_at"),
            "snapshot_count": len(snapshots),
            "snapshot_ids": snapshots,
            "evidence_path": row.get("path"),
            "configured_source_category": config.get(sid, {}).get("category"),
            "category_news_review_proven": False,
            "independent_assessment_proven": False,
        })

    team_rows = [x for x in teams.get("teams") or [] if isinstance(x, Mapping)]
    official_ids = [x.get("official_fpl_team_id") for x in team_rows]
    identity_valid = (
        teams.get("authority") == "official_fpl"
        and teams.get("team_count") == 20
        and len(official_ids) == 20
        and all(type(i) is int and i > 0 for i in official_ids)
        and len(set(official_ids)) == 20
        and "official_fpl" in source_ids
    )
    if not identity_valid:
        failures.append("V6_OFFICIAL_TEAM_IDENTITY_NOT_PROVEN")
    # Preserve distinct semantics: an identity-proof is NOT 20 club news checks.
    return {
        "contract": "V12_V6_SOURCE_TRACE_V1",
        "status": "PASS" if not failures else "FAIL",
        "failures": list(dict.fromkeys(failures)),
        "report_slot": report_slot,
        "v6_publication_run_id": publication_run_id or None,
        "v6_acquired_at": index.get("generated_at"),
        "v6_publish_integrity": integrity.get("status"),
        "provider_count": len(observed),
        "providers": observed if not failures else [],
        "official_club_identity_count": len(set(official_ids)) if identity_valid else 0,
        "official_club_ids": official_ids if identity_valid and not failures else [],
        "club_news_verification": "NOT_PROVEN",
        "seven_category_news_scan": "NOT_PROVEN",
        "five_domain_independent_counterpart": "NOT_PROVEN",
        "official_deadline_check": "NOT_PROVEN",
        "sufficient_for_full_source_gate": False,
        "decision_authority": False,
        "factual_inputs_mutated": False,
        "producer": "EXISTING_V6_ACQUISITION_METADATA_READ_ONLY",
    }


def bind_official_deadline(
    trace: Mapping[str, Any],
    *,
    bootstrap: Mapping[str, Any],
    planning_gw: int,
    report_slot: str,
    runtime_data_root: Path,
) -> dict[str, Any]:
    """Read an exact official FPL event deadline, without declaring news scanned.

    This is one FPL bootstrap field bound to a verified V6 provider request.
    It cannot satisfy seven-category or independent counterpart coverage alone.
    """
    result = dict(trace)
    result["official_deadline_check"] = "NOT_PROVEN"
    result.pop("official_deadline_evidence", None)
    if result.get("status") != "PASS":
        return result

    provider = next(
        (r for r in result.get("providers") or []
         if isinstance(r, Mapping) and r.get("source_id") == "official_fpl"),
        None,
    )
    registry = _read(runtime_data_root, REGISTRY)
    official_config = next(
        (r for r in registry.get("sources") or []
         if isinstance(r, Mapping) and r.get("id") == "official_fpl"),
        {},
    )
    bootstrap_request = next(
        (r for r in official_config.get("requests") or []
         if isinstance(r, Mapping) and r.get("id") == "bootstrap"),
        {},
    )
    url = str(bootstrap_request.get("url") or "")
    snapshots = list((provider or {}).get("snapshot_ids") or [])
    bootstrap_snapshot = next(
        (s for s in snapshots if isinstance(s, str)
         and s.startswith("official_fpl:bootstrap:")),
        None,
    )
    if not (
        provider
        and provider.get("health") == "GREEN"
        and provider.get("availability") == "AVAILABLE"
        and bootstrap_snapshot
        and url == "https://fantasy.premierleague.com/api/bootstrap-static/"
    ):
        return result

    if type(planning_gw) is not int or planning_gw <= 0:
        return result
    events = bootstrap.get("events")
    if not isinstance(events, list):
        return result
    rows = [
        r for r in events
        if isinstance(r, Mapping)
        and type(r.get("id")) is int and r.get("id") == planning_gw
    ]
    if len(rows) != 1:
        return result
    deadline = _aware(rows[0].get("deadline_time"))
    report_time = _aware(report_slot)
    checked = _aware(provider.get("checked_at"))
    if deadline is None or report_time is None or checked is None:
        return result

    result["official_deadline_check"] = "VERIFIED_FPL_BOOTSTRAP_FIELD"
    result["official_deadline_evidence"] = {
        "gw": planning_gw,
        "deadline_utc": deadline.astimezone(ZoneInfo("UTC")).isoformat(),
        "deadline_wib": deadline.astimezone(ZoneInfo("Asia/Jakarta")).isoformat(),
        "deadline_source_url": url,
        "checked_at": provider["checked_at"],
        "source_snapshot_id": bootstrap_snapshot,
        "applicability": "UPCOMING" if report_time <= deadline else "PAST",
        "scope": "OFFICIAL_EVENT_DEADLINE_ONLY_NOT_NEWS_SCAN",
        "decision_authority": False,
    }
    return result
