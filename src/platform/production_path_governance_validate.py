from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"

RETIRED_OPERATIONAL_WORKFLOWS = (
    "v3-runtime.yml",
    "v3-package-precompute.yml",
    "v4-prediction.yml",
    "v4-timing-probe.yml",
    "fpl-engine-recovery.yml",
    "v5-evidence-dispatcher.yml",
)
LEGACY_PREFIXES = ("v3-", "v4-", "v5-")
AUTOMATIC_TRIGGER = re.compile(r"(?m)^\s*(schedule|workflow_run)\s*:")
SCHEDULE_TRIGGER = re.compile(r"(?m)^\s*schedule\s*:")
LEGACY_RUNTIME_PUSH = re.compile(
    r"(?:HEAD:refs/heads/|refs/heads/|RUNTIME_BRANCH\s*[:=]\s*)runtime-data-v[345](?:\b|$)"
)
ALLOWED_V6_CONTROL_SCHEDULES = {"v6-natural-data-ingestion.yml", "v6-scheduler-watchdog.yml"}


class ProductionPathGovernanceError(RuntimeError):
    pass


def _workflow_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _validate_v6_watchdog(errors: list[str]) -> None:
    workflow = WORKFLOW_DIR / "v6-scheduler-watchdog.yml"
    config_path = ROOT / "config" / "v6" / "scheduler_watchdog.json"
    schedule_policy_path = ROOT / "config" / "v6" / "schedule_policy.json"
    if not workflow.exists():
        errors.append("allowed V6 monitoring schedule is missing: .github/workflows/v6-scheduler-watchdog.yml")
        return
    if not config_path.exists():
        errors.append("V6 watchdog governance config is missing")
        return

    text = _workflow_text(workflow)
    for marker in (
        "cron: '50 * * * *'",
        "contents: read",
        "actions: read",
        "issues: write",
        "python -m src.runtime_v6.domains.control_plane.scheduler_watchdog",
    ):
        if marker not in text:
            errors.append(f"V6 monitoring watchdog missing required marker: {marker}")
    for forbidden in (
        "contents: write",
        "v6-runtime-publisher",
        "RECOVER_V6",
        "/v6-master-acquire",
        "actions/workflows/v6-natural-data-ingestion.yml/dispatches",
        "python -m src.runtime_v6.scheduler_watchdog",
    ):
        if forbidden in text:
            errors.append(f"V6 monitoring watchdog contains forbidden authority: {forbidden}")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    authority = dict(config.get("authority") or {})
    if config.get("role") != "MONITORING_ONLY":
        errors.append("V6 watchdog role must be MONITORING_ONLY")
    for key in (
        "watchdog_is_scheduler_authority",
        "watchdog_may_trigger_acquisition",
        "watchdog_may_dispatch_ingestion",
        "watchdog_may_publish_runtime",
        "watchdog_may_advance_scheduler_proof",
        "watchdog_may_use_v6_publisher_credentials",
    ):
        if authority.get(key) is not False:
            errors.append(f"V6 watchdog authority must be false: {key}")
    if authority.get("core_scheduler") != "GITHUB_FPL_MASTER_SCHEDULER":
        errors.append("V6 watchdog must preserve GitHub FPL Master scheduler authority")

    schedule_policy = json.loads(schedule_policy_path.read_text(encoding="utf-8"))
    github_schedule = dict(schedule_policy.get("github_natural_schedule") or {})
    if github_schedule.get("enabled") is not True or github_schedule.get("authority") != "GITHUB_ACTIONS":
        errors.append("GitHub natural acquisition schedule must be the active authority")
    if (schedule_policy.get("governance") or {}).get("single_schedule_owner") != "GITHUB_ACTIONS:v6-natural-data-ingestion.yml":
        errors.append("V6 natural ingestion must be the single schedule owner")


def _validate_v6_recovery_guard(errors: list[str]) -> None:
    workflow = WORKFLOW_DIR / "v6-core-recovery-guard.yml"
    config_path = ROOT / "config" / "v6" / "scheduler_recovery.json"
    schedule_policy_path = ROOT / "config" / "v6" / "schedule_policy.json"
    if not workflow.exists():
        errors.append("explicit V6 manual recovery workflow is missing: .github/workflows/v6-core-recovery-guard.yml")
        return
    if not config_path.exists():
        errors.append("V6 safe-recovery governance config is missing")
        return

    text = _workflow_text(workflow)
    for marker in (
        "workflow_dispatch:",
        "contents: read",
        "actions: write",
        "python -m src.runtime_v6.domains.control_plane.scheduler_watchdog",
        "python -m src.runtime_v6.domains.control_plane.scheduler_recovery",
        "inputs[mode]=manual_recovery",
        "inputs[confirm]=RECOVER_V6",
        "WAVE2_SAFE_RECOVERY_CRITICAL",
        "actions/workflows/${RECOVERY_WORKFLOW}/dispatches",
    ):
        if marker not in text:
            errors.append(f"V6 recovery guard missing required marker: {marker}")
    if SCHEDULE_TRIGGER.search(text):
        errors.append("V6 recovery guard must be workflow_dispatch-only; recurring recovery cron is forbidden")
    if re.search(r"(?m)^\s*workflow_run\s*:", text):
        errors.append("V6 recovery guard must not have workflow_run auto-trigger")

    for forbidden in (
        "contents: write",
        "issues: write",
        "FPL_MASTER_SLOT",
        "/v6-master-acquire",
        "v6-runtime-publisher",
        "V6_RUNTIME_APP_PRIVATE_KEY",
        "python -m src.runtime_v6.scheduler_watchdog",
        "python -m src.runtime_v6.scheduler_recovery",
    ):
        if forbidden in text:
            errors.append(f"V6 recovery guard contains forbidden authority: {forbidden}")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("role") != "SAFE_RECOVERY_ONLY":
        errors.append("V6 recovery guard role must be SAFE_RECOVERY_ONLY")
    if config.get("automatic_schedule_enabled") is not False:
        errors.append("V6 recovery guard automatic schedule must be disabled")
    if config.get("invocation_mode") != "WORKFLOW_DISPATCH_ONLY":
        errors.append("V6 recovery guard invocation must be WORKFLOW_DISPATCH_ONLY")
    if config.get("recurring_automated_initiator") is not False:
        errors.append("V6 recovery guard must not be a recurring automated initiator")
    if config.get("normal_scheduler_authority") != "GITHUB_FPL_MASTER_SCHEDULER":
        errors.append("V6 recovery guard must preserve GitHub FPL Master as normal scheduler authority")
    for key in (
        "recovery_counts_as_scheduler_proof",
        "recovery_counts_as_natural_wave3_slot",
        "recovery_counts_as_completed_scheduled_slot",
        "may_edit_fpl_master_slot_title",
        "may_publish_runtime_directly",
        "may_use_v6_publisher_credentials_directly",
    ):
        if config.get(key) is not False:
            errors.append(f"V6 recovery guard policy must be false: {key}")
    if config.get("github_natural_acquisition_schedule_enabled") is not True:
        errors.append("V6 recovery guard must acknowledge the active natural GitHub schedule")

    schedule_policy = json.loads(schedule_policy_path.read_text(encoding="utf-8"))
    manual = dict(schedule_policy.get("manual_recovery") or {})
    if manual.get("enabled") is not True:
        errors.append("governed V6 manual_recovery must remain enabled for recovery guard")
    if manual.get("counts_as_completed_operational_slot") is not False:
        errors.append("manual_recovery must not complete an operational core slot")
    if manual.get("counts_as_completed_scheduled_slot") is not False:
        errors.append("manual_recovery must not count as scheduled proof")
    if (schedule_policy.get("github_natural_schedule") or {}).get("enabled") is not True:
        errors.append("recovery guard must preserve the active GitHub natural acquisition schedule")



def _validate_v12_precompute_control(errors: list[str]) -> None:
    workflow = WORKFLOW_DIR / "v12-precompute-control.yml"
    config_path = ROOT / "config" / "delivery" / "v12_precompute_control.json"
    schedule_policy_path = ROOT / "config" / "v6" / "schedule_policy.json"
    if not workflow.exists():
        errors.append("V12 D-P2 precompute workflow is missing")
        return
    if not config_path.exists():
        errors.append("V12 D-P2 precompute config is missing")
        return

    text = _workflow_text(workflow)
    for marker in (
        "issue_comment:",
        "github.actor == github.repository_owner",
        "startsWith(github.event.comment.body, '/v12-precompute ')",
        "cancel-in-progress: false",
        "actions: write",
        "python -m src.engines.v12_precompute_control",
        "inputs[mode]=report_prefetch",
        "inputs[reason]=${DISPATCH_REASON}",
    ):
        if marker not in text:
            errors.append(f"V12 D-P2 precompute missing required marker: {marker}")
    for forbidden in (
        "schedule:",
        "cron:",
        "workflow_run:",
        "issues: write",
        "contents: write",
        "FPL_MASTER_SLOT",
        "python -m src.runtime_v6.domains.acquisition.collector",
        "HEAD:refs/heads/runtime-data-v6",
    ):
        if forbidden in text:
            errors.append(f"V12 D-P2 precompute contains forbidden authority: {forbidden}")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("role") != "REPORT_PRECOMPUTE_ONLY":
        errors.append("V12 D-P2 role must remain REPORT_PRECOMPUTE_ONLY")
    if config.get("normal_scheduler_authority") != "GITHUB_FPL_MASTER_SCHEDULER":
        errors.append("V12 D-P2 must preserve GitHub FPL Master scheduler authority")
    if config.get("cancel_in_progress") is not False:
        errors.append("V12 D-P2 cancel-in-progress must remain false")
    if config.get("schedule_trigger_enabled") is not False:
        errors.append("V12 D-P2 must not have an independent schedule")
    for key in (
        "may_complete_core_operational_slot",
        "may_advance_scheduler_proof",
        "may_edit_core_issue_title",
        "may_acquire_facts_directly",
        "may_publish_runtime_directly",
    ):
        if config.get(key) is not False:
            errors.append(f"V12 D-P2 policy must be false: {key}")
    if config.get("preserve_report_occurrence_identity") is not True:
        errors.append("V12 D-P2 must preserve report occurrence identity")

    policy = json.loads(schedule_policy_path.read_text(encoding="utf-8"))
    prefetch = dict(policy.get("report_prefetch") or {})
    if prefetch.get("precompute_dispatch_actor") != config.get("dispatch_actor"):
        errors.append("V12 D-P2 dispatch actor must match V6 report-prefetch policy")
    if prefetch.get("precompute_dispatch_reason") != config.get("dispatch_reason"):
        errors.append("V12 D-P2 dispatch reason must match V6 report-prefetch policy")
    if prefetch.get("precompute_dispatch_role") != "REPORT_PRECOMPUTE_ONLY":
        errors.append("V12 D-P2 dispatch role must be report-precompute only")
    if prefetch.get("precompute_dispatch_counts_as_scheduler_proof") is not False:
        errors.append("V12 D-P2 dispatch must not count as scheduler proof")
    if prefetch.get("precompute_dispatch_counts_as_completed_operational_slot") is not False:
        errors.append("V12 D-P2 dispatch must not complete a core operational slot")

def validate() -> None:
    errors: list[str] = []

    for name in RETIRED_OPERATIONAL_WORKFLOWS:
        path = WORKFLOW_DIR / name
        if path.exists():
            errors.append(f"retired operational workflow still present: {path.relative_to(ROOT)}")

    forensic = WORKFLOW_DIR / "fpl-engine.yml"
    if forensic.exists():
        text = _workflow_text(forensic)
        required = (
            "LEGACY_FORENSIC_ONLY",
            "workflow_dispatch:",
            "forensic-only",
            "NO_PRODUCTION_PUBLICATION",
        )
        for marker in required:
            if marker not in text:
                errors.append(f"legacy forensic marker missing hard-disable control: {marker}")
        if AUTOMATIC_TRIGGER.search(text):
            errors.append("legacy forensic marker must not have schedule/workflow_run")
        for forbidden in (
            "git push",
            "runtime-data-v3",
            "runtime-data-v4",
            "runtime-data-v5",
            "python -m src.runtime_v3",
            "python -m src.runtime_v4",
            "python -m src.runtime_v5",
        ):
            if forbidden in text:
                errors.append(f"legacy forensic marker contains operational action: {forbidden}")

    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        text = _workflow_text(path)
        if path.name.startswith(LEGACY_PREFIXES) and AUTOMATIC_TRIGGER.search(text):
            errors.append(
                f"legacy workflow has automatic trigger schedule/workflow_run: {path.relative_to(ROOT)}"
            )
        if LEGACY_RUNTIME_PUSH.search(text):
            errors.append(f"workflow references legacy runtime publication branch: {path.relative_to(ROOT)}")

    scheduled_v6 = {
        path.name
        for path in sorted(WORKFLOW_DIR.glob("v6-*.yml"))
        if SCHEDULE_TRIGGER.search(_workflow_text(path))
    }
    unexpected_scheduled = scheduled_v6 - ALLOWED_V6_CONTROL_SCHEDULES
    missing_controls = ALLOWED_V6_CONTROL_SCHEDULES - scheduled_v6
    if unexpected_scheduled:
        errors.append(
            "V6 GitHub acquisition/unknown cron is forbidden: " + ", ".join(sorted(unexpected_scheduled))
        )
    if missing_controls:
        errors.append(
            "declared V6 control-plane cron is missing: " + ", ".join(sorted(missing_controls))
        )
    _validate_v6_watchdog(errors)
    _validate_v6_recovery_guard(errors)
    _validate_v12_precompute_control(errors)

    ingestion = WORKFLOW_DIR / "v6-natural-data-ingestion.yml"
    if not ingestion.exists():
        errors.append("missing V6 production ingestion workflow")
    else:
        text = _workflow_text(ingestion)
        required = (
            "RUNTIME_BRANCH: runtime-data-v6",
            "github.event.issue.number == 431",
            "FPL_MASTER_SLOT ",
            "/v6-report-prefetch",
            "HEAD:refs/heads/${RUNTIME_BRANCH}",
            "python -m src.runtime_v6.domains.control_plane.workflow_control slot-guard",
            "python -m src.runtime_v6.domains.acquisition.collector",
            "python -m src.runtime_v6.domains.publication.production_validate publishable",
        )
        for marker in required:
            if marker not in text:
                errors.append(f"V6 ingestion missing governed marker: {marker}")
        forbidden = (
            "FPL_REPORT_PREFETCH ",
            "startsWith(github.event.comment.body, '/v6-master-acquire')",
            "python -m src.runtime_v6.workflow_control",
            "python -m src.runtime_v6.collector",
            "python -m src.runtime_v6.runtime_control",
            "python -m src.runtime_v6.report_prefetch",
            "python -m src.runtime_v6.publish_integrity",
            "python -m src.runtime_v6.production_validate",
        )
        for marker in forbidden:
            if marker in text:
                errors.append(f"V6 ingestion contains forbidden control path: {marker}")
        if not SCHEDULE_TRIGGER.search(text):
            errors.append("V6 production ingestion workflow must have the governed GitHub cron")
        if 'cron: "30 * * * *"' not in text:
            errors.append("V6 production ingestion workflow must use the exact hourly :30 UTC cron")
        if re.search(r"(?m)^\s*workflow_run\s*:", text):
            errors.append("V6 production ingestion workflow must not have workflow_run auto-trigger")
        if re.search(r"HEAD:refs/heads/runtime-data-(?!v6\b)", text):
            errors.append("V6 publisher targets a branch other than runtime-data-v6")

    if errors:
        raise ProductionPathGovernanceError("\n".join(errors))


if __name__ == "__main__":
    validate()
    print("production path governance: PASS")
