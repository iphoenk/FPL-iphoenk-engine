from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V6_SOURCE = ROOT / "src" / "runtime_v6"
V6_CONFIG = ROOT / "config" / "v6"
V6_WORKFLOWS = tuple(sorted((ROOT / ".github" / "workflows").glob("v6-*.yml")))
ALLOWED_THIRD_PARTY = {"requests"}


def _python_import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def validate_repository(root: Path = ROOT) -> list[str]:
    failures: list[str] = []
    source_root = root / "src" / "runtime_v6"
    workflow_root = root / ".github" / "workflows"
    config_root = root / "config" / "v6"

    forbidden_modules = {
        "src.runtime_" + "v3",
        "src.runtime_" + "v4",
        "runtime_" + "v3",
        "runtime_" + "v4",
    }

    third_party: set[str] = set()
    for path in sorted(source_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                module = node.module
                if any(module == item or module.startswith(item + ".") for item in forbidden_modules):
                    failures.append(f"forbidden cross-version import: {path.relative_to(root)} -> {module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name
                    if any(module == item or module.startswith(item + ".") for item in forbidden_modules):
                        failures.append(f"forbidden cross-version import: {path.relative_to(root)} -> {module}")

        for imported in _python_import_roots(path):
            if imported in {"src"} or imported in sys.stdlib_module_names:
                continue
            third_party.add(imported)

    unexpected = third_party - ALLOWED_THIRD_PARTY
    if unexpected:
        failures.append(f"unexpected V6 third-party imports outside dedicated lock policy: {sorted(unexpected)}")

    forbidden_workflow_tokens = (
        "runtime_" + "v3",
        "runtime_" + "v4",
        "V3_RUNTIME_",
        "V4_RUNTIME_",
        "runtime-data-v4",
        "V3" + " CI",
    )
    for path in sorted(workflow_root.glob("v6-*.yml")):
        text = path.read_text(encoding="utf-8")
        for token in forbidden_workflow_tokens:
            if token in text:
                failures.append(f"forbidden cross-version V6 workflow reference: {path.relative_to(root)} -> {token}")
        if "workflow_run:" in text:
            failures.append(f"V6 workflow must not be chained from another engine: {path.relative_to(root)}")
        if re.search(r"(?m)^\s*RUNTIME_BRANCH:\s*runtime-data\s*$", text):
            failures.append(f"V6 workflow points at non-V6 runtime branch: {path.relative_to(root)}")

    ci = (workflow_root / "v6-ci.yml").read_text(encoding="utf-8")
    if "requirements-v6-ci.lock" not in ci:
        failures.append("V6 CI must install requirements-v6-ci.lock")
    if re.search(r"(?m)^\s*run:.*-r\s+requirements-ci\.lock\s*$", ci):
        failures.append("V6 CI still installs repository/V3 CI lock")
    if not re.search(r"(?m)^  v6-verify:\s*$", ci):
        failures.append("V6 CI check identity must be v6-verify")

    hourly = (workflow_root / "v6-hourly-data-ingestion.yml").read_text(encoding="utf-8")
    if "-r requirements-v6.lock" not in hourly:
        failures.append("V6 runtime must install requirements-v6.lock")
    if re.search(r"(?m)-r\s+requirements\.lock\s*$", hourly):
        failures.append("V6 runtime still installs shared/V3 runtime lock")

    for path in sorted(config_root.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for token in ("runtime-data-v4", "V3_RUNTIME_", "V4_RUNTIME_"):
            if token in text:
                failures.append(f"forbidden V6 config dependency: {path.relative_to(root)} -> {token}")

    runtime_lock = (root / "requirements-v6.lock").read_text(encoding="utf-8")
    for package in sorted(ALLOWED_THIRD_PARTY):
        if not re.search(rf"(?mi)^{re.escape(package)}==", runtime_lock):
            failures.append(f"V6 runtime lock missing declared third-party dependency: {package}")

    return failures


def main() -> int:
    failures = validate_repository()
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("PASS: V6 is implementation-independent from V3/V4 and uses V6-owned dependencies/runtime paths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
