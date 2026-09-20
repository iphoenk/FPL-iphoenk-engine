from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def validate_repository(root: Path = ROOT) -> list[str]:
    failures: list[str] = []
    workflows = root / ".github" / "workflows"
    names = sorted(
        path.name
        for path in list(workflows.glob("*.yml")) + list(workflows.glob("*.yaml"))
    )

    legacy_workflows = [
        name for name in names
        if re.match(r"^v[345]-", name)
    ]
    if legacy_workflows:
        failures.append(
            "active workflow tree must contain zero V3/V4/V5 workflows; "
            f"found={legacy_workflows}"
        )

    v6_ci_path = workflows / "v6-ci.yml"
    governance_path = workflows / "repository-governance.yml"
    if not v6_ci_path.is_file():
        failures.append("active V6 CI workflow missing")
        return failures
    if not governance_path.is_file():
        failures.append("neutral repository governance workflow missing")
        return failures

    v6_ci = v6_ci_path.read_text(encoding="utf-8")
    governance = governance_path.read_text(encoding="utf-8")

    if not re.search(r"(?m)^  v6-verify:\s*$", v6_ci):
        failures.append("V6 CI must expose version-unique job id v6-verify")
    if not re.search(r"(?m)^  v12-verify:\s*$", governance):
        failures.append("repository governance must expose active V12 job id v12-verify")
    if "legacy_execution_isolation_validate.py" not in governance:
        failures.append("repository governance must execute static legacy isolation validator")

    for path in sorted(workflows.glob("v6-*.yml")):
        text = path.read_text(encoding="utf-8")
        if "workflow_run:" in text:
            failures.append(
                f"V6 workflow must not use cross-engine workflow_run chaining: {path.name}"
            )

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

    if "repository_version_isolation_validate.py" not in governance:
        failures.append("neutral repository governance must execute version-isolation validator")

    for token in ("src.runtime_v3", "src.runtime_v4", "src.runtime_v5"):
        if token in governance:
            failures.append(f"active repository governance must not execute legacy runtime: {token}")

    return failures


def main() -> int:
    failures = validate_repository()
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("PASS: active CI ownership is isolated to V6 + V12 with static legacy freeze")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
