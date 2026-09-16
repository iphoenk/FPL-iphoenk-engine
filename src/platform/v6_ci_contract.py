from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable


_EXACT_PATHS = frozenset(
    {
        "requirements-v6.lock",
        "requirements-v6-ci.lock",
        "tests/test_data_ingestion_engine.py",
        "tests/test_adaptive_polling.py",
        "tests/test_data_platform_production_acceptance.py",
        "src/platform/v6_ci_contract.py",
        "src/platform/production_path_governance_validate.py",
        ".github/workflows/v6-ci.yml",
        ".github/workflows/v6-natural-data-ingestion.yml",
        ".github/workflows/v6-scheduler-watchdog.yml",
        ".github/workflows/v6-core-recovery-guard.yml",
        ".github/workflows/v6-wave3-proof.yml",
        ".github/workflows/repository-governance.yml",
    }
)

_PREFIXES = (
    "config/v6/",
    "src/runtime_v6/",
)


def _normalize_path(path: str) -> str:
    value = str(path or "").strip()
    return value[2:] if value.startswith("./") else value


def is_v6_owned_path(path: str) -> bool:
    value = _normalize_path(path)
    if not value:
        return False
    if value in _EXACT_PATHS:
        return True
    if value.startswith(_PREFIXES):
        return True
    if value.startswith("docs/V6_") and value.endswith(".md"):
        return True
    if value.startswith("tests/test_data_platform_") and value.endswith(".py"):
        return True
    return False


def requires_v6_verification(paths: Iterable[str]) -> bool:
    return any(is_v6_owned_path(path) for path in paths)


def _changed_paths_from_stdin() -> list[str]:
    return [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Canonical V6 CI change-surface classifier")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("changed-paths", help="read newline-delimited repository paths from stdin")
    args = parser.parse_args(argv)

    if args.command == "changed-paths":
        print("true" if requires_v6_verification(_changed_paths_from_stdin()) else "false")
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
