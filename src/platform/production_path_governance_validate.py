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
ALLOWED_V6_MONITORING_SCHEDULES = {"v6-scheduler-watchdog.yml"}


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
        "python -m src.runtime_v6.scheduler_watchdog",
    ):
        if marker not in text:
            errors.append(f"V6 monitoring watchdog missing required marker: {marker}")
    for forbidden in (
        "contents: write",
        "v6-runtime-publisher",
        "RECOVER_V6",
        "/v6-master-acquire",
        "actions/workflows/v6-natural-data-ingestion.yml/dispatches",
    ):
        if forbidden in text:
            errors.append(f"V6 monitoring watchdog contains forbidden authority: {forbidden}")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    authority = dict(config.get("authority") or {})
    if config.get("role") != "MONITORING_ONLY":
        errors.append("V6 watchdog role must be MONITORING_ONLY")
    expected_false = (
        "watchdog_is_scheduler_authority",
        "watchdog_may_trigger_acquisition",
        "watchdog_may_dispatch_ingestion",
        "watchdog_may_publish_runtime",
        "watchdog_may_advance_scheduler_proof",
        "watchdog_may_use_v6_publisher_credentials",
    )
    for key in expected_false:
        if authority.get(key) is not False:
            errors.append(f"V6 watchdog authority must be false: {key}")
    if authority.get("core_scheduler") != "CHATGPT_FPL_MASTER_MONITOR":
        errors.append("V6 watchdog must preserve CHATGPT_FPL_MASTER_MONITOR as core scheduler")

    schedule_policy = json.loads(schedule_policy_path.read_text(encoding="utf-8"))
    if (schedule_policy.get("github_natural_schedule") or {}).get("enabled") is not False:
        errors.append("GitHub natural acquisition schedule must remain disabled")
    if (schedule_policy.get("governance") or {}).get("chatgpt_scheduler_is_only_hourly_authority") is not True:
        errors.append("ChatGPT must remain the only hourly acquisition authority")


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
    unexpected_scheduled = scheduled_v6 - ALLOWED_V6_MONITORING_SCHEDULES
    missing_monitoring = ALLOWED_V6_MONITORING_SCHEDULES - scheduled_v6
    if unexpected_scheduled:
        errors.append(
            "V6 GitHub acquisition/unknown cron is forbidden: " + ", ".join(sorted(unexpected_scheduled))
        )
    if missing_monitoring:
        errors.append(
            "declared monitoring-only V6 watchdog cron is missing: " + ", ".join(sorted(missing_monitoring))
        )
    _validate_v6_watchdog(errors)

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
        )
        for marker in required:
            if marker not in text:
                errors.append(f"V6 ingestion missing governed marker: {marker}")
        forbidden = (
            "FPL_REPORT_PREFETCH ",
            "startsWith(github.event.comment.body, '/v6-master-acquire')",
        )
        for marker in forbidden:
            if marker in text:
                errors.append(f"V6 ingestion contains forbidden control path: {marker}")
        if SCHEDULE_TRIGGER.search(text):
            errors.append("V6 production ingestion workflow must not have a GitHub cron")
        if re.search(r"HEAD:refs/heads/runtime-data-(?!v6\b)", text):
            errors.append("V6 publisher targets a branch other than runtime-data-v6")

    if errors:
        raise ProductionPathGovernanceError("\n".join(errors))


if __name__ == "__main__":
    validate()
    print("production path governance: PASS")
