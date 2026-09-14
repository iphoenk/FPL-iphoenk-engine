from __future__ import annotations

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
    "fpl-engine.yml",
)
LEGACY_PREFIXES = ("v3-", "v4-", "v5-")
AUTOMATIC_TRIGGER = re.compile(r"(?m)^\s*(schedule|workflow_run)\s*:")
SCHEDULE_TRIGGER = re.compile(r"(?m)^\s*schedule\s*:")
LEGACY_RUNTIME_PUSH = re.compile(
    r"(?:HEAD:refs/heads/|refs/heads/|RUNTIME_BRANCH\s*[:=]\s*)runtime-data-v[345](?:\b|$)"
)


class ProductionPathGovernanceError(RuntimeError):
    pass


def _workflow_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def validate() -> None:
    errors: list[str] = []

    for name in RETIRED_OPERATIONAL_WORKFLOWS:
        path = WORKFLOW_DIR / name
        if path.exists():
            errors.append(f"retired operational workflow still present: {path.relative_to(ROOT)}")

    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        text = _workflow_text(path)
        if path.name.startswith(LEGACY_PREFIXES) and AUTOMATIC_TRIGGER.search(text):
            errors.append(
                f"legacy workflow has automatic trigger schedule/workflow_run: {path.relative_to(ROOT)}"
            )
        if LEGACY_RUNTIME_PUSH.search(text):
            errors.append(f"workflow references legacy runtime publication branch: {path.relative_to(ROOT)}")

    for path in sorted(WORKFLOW_DIR.glob("v6-*.yml")):
        if SCHEDULE_TRIGGER.search(_workflow_text(path)):
            errors.append(f"V6 GitHub cron is forbidden: {path.relative_to(ROOT)}")

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
        if re.search(r"HEAD:refs/heads/runtime-data-(?!v6\b)", text):
            errors.append("V6 publisher targets a branch other than runtime-data-v6")

    if errors:
        raise ProductionPathGovernanceError("\n".join(errors))


if __name__ == "__main__":
    validate()
    print("production path governance: PASS")
