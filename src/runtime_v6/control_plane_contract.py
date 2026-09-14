from __future__ import annotations

from typing import Any, Mapping


def validate_control_plane_contract(
    schedule_policy: Mapping[str, Any],
    watchdog_policy: Mapping[str, Any],
    recovery_policy: Mapping[str, Any],
) -> list[str]:
    """Validate static cross-file V6 scheduler/control-plane invariants.

    This is a fail-closed configuration contract only. It does not perform network
    I/O, trigger acquisition, advance scheduler proof, or publish runtime state.
    """
    failures: list[str] = []
    scheduler = dict(schedule_policy.get("scheduler_authority") or {})
    master = dict(schedule_policy.get("master_orchestrated") or {})
    report = dict(schedule_policy.get("report_prefetch") or {})
    manual = dict(schedule_policy.get("manual_recovery") or {})
    watchdog_schedule = dict(watchdog_policy.get("schedule") or {})
    watchdog_authority = dict(watchdog_policy.get("authority") or {})
    watchdog_incident = dict(watchdog_policy.get("incident") or {})

    authority = str(scheduler.get("runtime_authority_id") or "")
    if not authority:
        failures.append("scheduler authority runtime_authority_id is missing")
    if str(watchdog_authority.get("core_scheduler") or "") != authority:
        failures.append("watchdog scheduler authority does not match schedule policy")
    if str(recovery_policy.get("normal_scheduler_authority") or "") != authority:
        failures.append("recovery scheduler authority does not match schedule policy")

    control_issue = scheduler.get("control_issue_number")
    if not isinstance(control_issue, int) or isinstance(control_issue, bool) or control_issue <= 0:
        failures.append("scheduler control issue must be a positive integer")
    for label, value in (
        ("master", master.get("control_issue_number")),
        ("report_prefetch", report.get("control_issue_number")),
        ("watchdog", watchdog_incident.get("control_issue_number")),
    ):
        if value != control_issue:
            failures.append(f"{label} control issue does not match scheduler control issue")

    marker = str(scheduler.get("issue_title_marker") or "").strip()
    if not marker:
        failures.append("scheduler issue title marker is missing")
    if str(master.get("issue_title_marker") or "").strip() != marker:
        failures.append("master issue title marker does not match scheduler issue title marker")
    if scheduler.get("issue_title_transport_enabled") is not True:
        failures.append("scheduler issue title transport must remain enabled")
    if str(scheduler.get("preferred_transport") or "") != "ISSUE_TITLE_EDIT":
        failures.append("scheduler preferred transport must remain ISSUE_TITLE_EDIT")
    if str(report.get("preferred_transport") or "") != "ISSUE_COMMENT":
        failures.append("report prefetch preferred transport must remain ISSUE_COMMENT")

    try:
        fresh = float(scheduler.get("proof_fresh_after_minutes"))
        stale = float(scheduler.get("proof_stale_after_minutes"))
        watchdog_fresh = float(watchdog_schedule.get("proof_fresh_after_minutes"))
        warning = float(watchdog_schedule.get("warning_after_minutes"))
        critical = float(watchdog_schedule.get("critical_after_minutes"))
    except (TypeError, ValueError):
        failures.append("scheduler/watchdog threshold values must be numeric")
    else:
        if watchdog_fresh != fresh:
            failures.append("watchdog proof-fresh threshold does not match schedule policy")
        if critical != stale:
            failures.append("watchdog critical threshold does not match scheduler stale threshold")
        if not fresh < warning < critical:
            failures.append("threshold ordering must be fresh < warning < critical")

    if str(recovery_policy.get("recovery_mode") or "") != str(manual.get("schedule_kind") or ""):
        failures.append("recovery mode does not match schedule manual_recovery kind")
    if str(recovery_policy.get("recovery_confirmation") or "") != str(manual.get("confirmation_phrase") or ""):
        failures.append("recovery confirmation does not match schedule policy")
    if recovery_policy.get("recovery_counts_as_scheduler_proof") is not False:
        failures.append("manual recovery must not count as scheduler proof")
    if recovery_policy.get("recovery_counts_as_natural_wave3_slot") is not False:
        failures.append("manual recovery must not count as natural Wave-3 slot")
    if recovery_policy.get("recovery_counts_as_completed_scheduled_slot") is not False:
        failures.append("manual recovery must not count as completed scheduled slot")

    return failures
