from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"
DOMAIN_SUITES = {
    "test_prediction_and_correctness.py",
    "test_lineup_watchlist_and_governance.py",
    "test_reporting_and_sources.py",
    "test_architecture_and_runtime_contracts.py",
}
FORBIDDEN_NAMES = {
    "x",
    "noop",
    "noop.txt",
    "probe",
    "probe.txt",
    "accidental-noop",
    "accidental_noop",
}
FORBIDDEN_EXACT_CONTENTS = {
    "x",
    "noop",
    "probe",
    "accidental noop",
    "accidental noop/probe file",
}


def validate_repository(root: Path = ROOT) -> list[str]:
    failures: list[str] = []
    tests = root / "tests"

    version_pattern = re.compile(r"^test_v\d")
    versioned = sorted(
        path.name for path in tests.glob("test_v*.py") if version_pattern.match(path.name)
    )
    if versioned:
        failures.append(
            "release-version test modules are forbidden; tests must be owned by stable "
            f"domain/capability suites: {versioned}"
        )

    missing_domains = sorted(name for name in DOMAIN_SUITES if not (tests / name).exists())
    if missing_domains:
        failures.append(f"required stable domain test suites are missing: {missing_domains}")
    if not (tests / "test_runtime_optimization.py").exists():
        failures.append("required runtime optimization test suite is missing")

    offenders: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.name.lower() in FORBIDDEN_NAMES:
            offenders.append(str(path.relative_to(root)))
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".zip", ".gz", ".pyc"}:
            continue
        try:
            if path.stat().st_size <= 128:
                value = path.read_text(encoding="utf-8").strip().lower()
                if value in FORBIDDEN_EXACT_CONTENTS:
                    offenders.append(str(path.relative_to(root)))
        except (UnicodeDecodeError, OSError):
            continue
    if offenders:
        failures.append(
            f"accidental placeholder/probe files must not be committed: {sorted(offenders)}"
        )
    return failures


def main() -> int:
    failures = validate_repository()
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("PASS: repository test naming and placeholder policy is satisfied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
