from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .publish_integrity import validate_publish_tree
from .registry import ZERO_AUTHORITY_KEYS


DEFAULT_MAX_AGE_MINUTES = 90
MAX_CLOCK_SKEW_MINUTES = 5
_ALLOWED_RUNTIME_KINDS = {"primary", "recovery", "master_orchestrated", "report_prefetch"}
_FALLBACK_SCOPE = "EXTERNAL_SOURCES_ONLY"


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _governance_failures(governance: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if governance.get("data_only") is not True:
        failures.append("DATA_ONLY_CONTRACT_BROKEN")
    for authority in ZERO_AUTHORITY_KEYS:
        if governance.get(authority) != "NONE":
            failures.append(f"UNEXPECTED_{authority.upper()}")
    return failures


def _control_failures(control: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    kind = str(control.get("schedule_kind") or "")
    event_name = str(control.get("event_name") or "")
    scheduled = control.get("scheduled_cycle") is True
    natural = kind in {"primary", "recovery"} and event_name == "schedule" and scheduled
    governed_event = event_name in {"issue_comment", "workflow_dispatch"}
    master = kind == "master_orchestrated" and governed_event and control.get("master_orchestrated") is True
    report_prefetch = kind == "report_prefetch" and governed_event and control.get("report_prefetch") is True

    explicit_authority = control.get("authoritative_runtime_snapshot")
    authoritative = explicit_authority is True or (explicit_authority is None and natural)
    operational_raw = control.get("counts_as_completed_operational_slot")
    # Runtime snapshots published before the explicit operational-slot field was
    # introduced are still valid when they have unambiguous natural-scheduler
    # provenance. Governed non-natural snapshots must remain explicit.
    operational = operational_raw is True or (operational_raw is None and natural)

    if not authoritative:
        failures.append("NON_AUTHORITATIVE_RUNTIME_SNAPSHOT")
    if kind not in _ALLOWED_RUNTIME_KINDS:
        failures.append("INVALID_RUNTIME_SCHEDULE_KIND")
        if not scheduled:
            failures.append("NON_SCHEDULED_RUNTIME_SNAPSHOT")
        if not operational:
            failures.append("NON_OPERATIONAL_RUNTIME_SNAPSHOT")

    if kind in {"primary", "recovery"} and not natural:
        failures.append("INVALID_NATURAL_SCHEDULE_PROVENANCE")
    elif kind == "master_orchestrated" and not master:
        failures.append("INVALID_MASTER_ORCHESTRATED_PROVENANCE")
    elif kind == "report_prefetch" and not report_prefetch:
        failures.append("INVALID_REPORT_PREFETCH_PROVENANCE")

    if natural or master:
        if not operational:
            failures.append("NON_OPERATIONAL_RUNTIME_SNAPSHOT")
    elif report_prefetch:
        if operational:
            failures.append("REPORT_PREFETCH_MUST_NOT_COMPLETE_CORE_OPERATIONAL_SLOT")
        if control.get("counts_as_completed_report_slot") is not True:
            failures.append("REPORT_PREFETCH_SLOT_NOT_RECORDED")

    if scheduled:
        if control.get("duplicate_scheduled_cycle") is True:
            failures.append("DUPLICATE_SCHEDULED_CYCLE")
        if control.get("out_of_order_scheduled_cycle") is True:
            failures.append("OUT_OF_ORDER_SCHEDULED_CYCLE")
    if not control.get("run_id"):
        failures.append("MISSING_RUNTIME_RUN_ID")
    return failures


def _invalid_result(failure: str) -> dict[str, Any]:
    return {
        "state": "INVALID",
        "usable": False,
        "direct_fallback_eligible": True,
        "fallback_scope": _FALLBACK_SCOPE,
        "engine_artifact_fallback_allowed": False,
        "failures": [failure],
    }


def assess_snapshot(
    root: Path | str = Path("data/v6"),
    *,
    now: datetime | None = None,
    max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES,
) -> dict[str, Any]:
    root = Path(root)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    failures: list[str] = []

    manifest_path = root / "manifest.json"
    integrity_path = root / "health" / "publish_integrity.json"
    if not manifest_path.exists():
        return _invalid_result("MISSING_MANIFEST")
    if not integrity_path.exists():
        return _invalid_result("MISSING_PUBLISH_INTEGRITY")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return _invalid_result(f"UNREADABLE_RUNTIME:{type(exc).__name__}")

    governance = manifest.get("governance") or {}
    failures.extend(_governance_failures(governance))

    if integrity.get("status") != "PASS":
        failures.append("PUBLISH_INTEGRITY_NOT_PASS")
    if integrity.get("current_source_files_exact") is not True:
        failures.append("CURRENT_SOURCE_FILESET_NOT_EXACT")
    if integrity.get("resolved_registry_exact") is not True:
        failures.append("RESOLVED_REGISTRY_NOT_EXACT")
    if integrity.get("identity_map_consistent") is not True:
        failures.append("IDENTITY_MAP_NOT_CONSISTENT")

    recomputed = validate_publish_tree(root)
    if recomputed.get("status") != "PASS":
        failures.append("RECOMPUTED_PUBLISH_INTEGRITY_NOT_PASS")
    if recomputed.get("resolved_registry_exact") is not True:
        failures.append("RECOMPUTED_RESOLVED_REGISTRY_NOT_EXACT")
    stored_digest = integrity.get("tree_sha256")
    recomputed_digest = recomputed.get("tree_sha256")
    if not stored_digest:
        failures.append("MISSING_PUBLISH_TREE_DIGEST")
    elif stored_digest != recomputed_digest:
        failures.append("PUBLISH_TREE_DIGEST_MISMATCH")

    generated_at_raw = manifest.get("generated_at")
    if not generated_at_raw:
        failures.append("MISSING_GENERATED_AT")
        generated_at = None
        age_minutes = None
    else:
        try:
            generated_at = _utc(str(generated_at_raw))
            age_minutes = (now - generated_at).total_seconds() / 60.0
            if age_minutes < -MAX_CLOCK_SKEW_MINUTES:
                failures.append("GENERATED_AT_IN_FUTURE")
        except (TypeError, ValueError):
            generated_at = None
            age_minutes = None
            failures.append("INVALID_GENERATED_AT")

    control = manifest.get("runtime_control") or {}
    failures.extend(_control_failures(control))

    if manifest.get("overall") == "RED":
        failures.append("MANIFEST_OVERALL_RED")
    if control.get("health") == "RED":
        failures.append("RUNTIME_CONTROL_RED")
    for failure in manifest.get("critical_failures") or []:
        failures.append(f"CRITICAL:{failure}")
    for failure in manifest.get("control_failures") or []:
        failures.append(f"CONTROL:{failure}")

    failures = list(dict.fromkeys(failures))
    if failures:
        state = "INVALID"
        usable = False
        fallback = True
    elif age_minutes is None:
        state = "INVALID"
        usable = False
        fallback = True
    elif age_minutes > float(max_age_minutes):
        state = "STALE"
        usable = False
        fallback = True
    else:
        state = "FRESH"
        usable = True
        fallback = False

    return {
        "state": state,
        "usable": usable,
        "direct_fallback_eligible": fallback,
        "fallback_scope": _FALLBACK_SCOPE if fallback else None,
        "engine_artifact_fallback_allowed": False,
        "generated_at": generated_at.isoformat() if generated_at else None,
        "evaluated_at": now.isoformat(),
        "age_minutes": round(age_minutes, 3) if age_minutes is not None else None,
        "max_age_minutes": int(max_age_minutes),
        "manifest_overall": manifest.get("overall"),
        "runtime_control_health": control.get("health"),
        "runtime_schedule_kind": control.get("schedule_kind"),
        "authoritative_runtime_snapshot": control.get("authoritative_runtime_snapshot"),
        "counts_as_completed_operational_slot": control.get("counts_as_completed_operational_slot"),
        "stored_tree_sha256": stored_digest,
        "recomputed_tree_sha256": recomputed_digest,
        "failures": failures,
        "governance": {
            "consumer_does_not_trust_static_green_without_freshness": True,
            "consumer_recomputes_publish_integrity": True,
            "consumer_requires_exact_resolved_registry": True,
            "consumer_requires_authoritative_runtime_provenance": True,
            "consumer_requires_authoritative_operational_provenance": True,
            "consumer_accepts_natural_master_and_report_prefetch_authority": True,
            "consumer_accepts_natural_and_master_orchestrated_authority": True,
            "report_prefetch_does_not_complete_core_operational_slot": True,
            "natural_scheduler_evidence_is_checked_separately": True,
            "consumer_requires_full_zero_authority_contract": True,
            "stale_or_invalid_allows_minimum_scope_direct_fallback": True,
            "fallback_is_external_sources_only": True,
            "fallback_must_not_read_other_engine_artifacts": True,
            "fresh_v6_is_primary_data_authority": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Assess whether the latest V6 runtime snapshot is safe to consume")
    parser.add_argument("--root", default="data/v6")
    parser.add_argument("--max-age-minutes", type=int, default=DEFAULT_MAX_AGE_MINUTES)
    args = parser.parse_args()
    result = assess_snapshot(args.root, max_age_minutes=args.max_age_minutes)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["usable"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
