from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"

V6_OWNED_PATH_MARKERS = (
    "src/runtime_v6/**",
    "config/v6/**",
    "docs/V6_*.md",
    "tests/test_data_ingestion_engine.py",
    "tests/test_adaptive_polling.py",
    "tests/test_weather_context.py",
    "tests/test_data_platform_*.py",
    "requirements-v6.lock",
    "requirements-v6-ci.lock",
    ".github/workflows/v6-ci.yml",
    ".github/workflows/v6-hourly-data-ingestion.yml",
)


def validate_repository(root: Path = ROOT) -> list[str]:
    failures: list[str] = []
    workflows = root / ".github" / "workflows"
    v3_ci = (workflows / "v3-ci.yml").read_text(encoding="utf-8")
    v6_ci = (workflows / "v6-ci.yml").read_text(encoding="utf-8")

    if not re.search(r"(?m)^  v3-verify:\s*$", v3_ci):
        failures.append("V3 CI must expose version-unique job id v3-verify")
    if not re.search(r"(?m)^  v6-verify:\s*$", v6_ci):
        failures.append("V6 CI must expose version-unique job id v6-verify")

    for marker in V6_OWNED_PATH_MARKERS:
        if v3_ci.count(marker) < 2:
            failures.append(
                f"V3 CI must ignore V6-owned path on both pull_request and push: {marker}"
            )

    v6_workflows = sorted(workflows.glob("v6-*.yml"))
    for path in v6_workflows:
        text = path.read_text(encoding="utf-8")
        if "workflow_run:" in text:
            failures.append(f"V6 workflow must not use cross-engine workflow_run chaining: {path.name}")

    generic_verify_owners: list[str] = []
    for path in sorted(workflows.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        if re.search(r"(?m)^  verify:\s*$", text):
            generic_verify_owners.append(path.name)
    if generic_verify_owners != ["repository-governance.yml"]:
        failures.append(
            "generic required check 'verify' must be owned only by neutral repository governance; "
            f"found={generic_verify_owners}"
        )

    repository_governance = (workflows / "repository-governance.yml").read_text(encoding="utf-8")
    if "repository_version_isolation_validate.py" not in repository_governance:
        failures.append("neutral repository governance must execute version-isolation validator")

    return failures


def main() -> int:
    failures = validate_repository()
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("PASS: repository CI/workflow ownership is version-isolated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
