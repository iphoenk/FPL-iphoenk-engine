from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "config" / "governance" / "legacy_freeze_manifest_v12.json"
WORKFLOWS = ROOT / ".github" / "workflows"

CANONICAL_PATH = "control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt"
STATE_PATH = "control/fpl_master_v12/FPL_MASTER_STATE_V12.json"

FORBIDDEN_WORKFLOW_PATTERNS = (
    ("runtime_v3", re.compile(r"\\bsrc\\.runtime_v3\\b")),
    ("runtime_v4", re.compile(r"\\bsrc\\.runtime_v4\\b")),
    ("runtime_v5", re.compile(r"\\bsrc\\.runtime_v5\\b")),
    ("release_acceptance", re.compile(r"\\brelease_acceptance\\b")),
    ("domain_orchestrator", re.compile(r"\\bdomain_orchestrator\\b")),
    ("legacy_sharded_optimizer", re.compile(r"\\bpackage_optimizer_shards\\b")),
    ("legacy_performance_guard", re.compile(r"\\bperformance_guard\\b")),
    ("legacy_fast_lane", re.compile(r"\\bfast_consistency_acceptance\\b|\\bunified_fastpath\\b")),
    ("legacy_exhaustive_optimizer", re.compile(r"\\bpackage_optimizer_exhaustive_accelerated\\b")),
    ("v4_prediction", re.compile(r"v4[-_]prediction", re.IGNORECASE)),
    ("v4_timing_probe", re.compile(r"v4[-_]timing[-_]probe", re.IGNORECASE)),
    ("v5_evidence_dispatcher", re.compile(r"v5[-_]evidence[-_]dispatcher", re.IGNORECASE)),
    ("legacy_runtime_data_branch", re.compile(r"runtime-data-v[345]\\b")),
)

LEGACY_LIBRARY_BASENAMES = (
    "FPL_MASTER_RUNTIME_CONTRACT.txt",
    "FPL_MASTER_SPEC_V11.txt",
    "ACTIVE_DECISION_CONTEXT.json",
)


def _git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    header = b"blob " + str(len(data)).encode("ascii") + bytes((0,))
    return hashlib.sha1(header + data).hexdigest()


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def validate(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    manifest_path = root / MANIFEST.relative_to(ROOT)
    if not manifest_path.exists():
        return ["legacy freeze manifest missing"]

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frozen_files = dict(manifest.get("frozen_files") or {})
    if not frozen_files:
        errors.append("legacy freeze manifest has no frozen files")
        return errors

    for rel_path, expected_sha in sorted(frozen_files.items()):
        path = root / rel_path
        if not path.is_file():
            errors.append(f"frozen legacy file missing: {rel_path}")
            continue
        actual_sha = _git_blob_sha(path)
        if actual_sha != expected_sha:
            errors.append(
                f"frozen legacy file changed: {rel_path} actual={actual_sha} expected={expected_sha}"
            )

    expected_v3 = {
        path for path in frozen_files
        if path.startswith("src/runtime_v3/")
    }
    runtime_v3 = root / "src" / "runtime_v3"
    actual_v3 = {
        _rel(path, root)
        for path in runtime_v3.rglob("*")
        if path.is_file()
    } if runtime_v3.exists() else set()
    if actual_v3 != expected_v3:
        errors.append(
            "src/runtime_v3 frozen scope changed: "
            f"added={sorted(actual_v3 - expected_v3)} removed={sorted(expected_v3 - actual_v3)}"
        )

    expected_v4_scripts = {
        path for path in frozen_files
        if path.startswith(".github/scripts/v4_")
    }
    actual_v4_scripts = {
        _rel(path, root)
        for path in (root / ".github" / "scripts").glob("v4_*.py")
        if path.is_file()
    }
    if actual_v4_scripts != expected_v4_scripts:
        errors.append(
            "V4 frozen script scope changed: "
            f"added={sorted(actual_v4_scripts - expected_v4_scripts)} "
            f"removed={sorted(expected_v4_scripts - actual_v4_scripts)}"
        )

    for prefix in manifest.get("must_remain_absent_prefixes") or []:
        base = root / prefix
        if base.exists() and any(path.is_file() for path in base.rglob("*")):
            errors.append(f"frozen legacy runtime namespace must remain absent: {prefix}")

    workflow_files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    forbidden_prefixes = tuple(manifest.get("active_workflow_forbidden_prefixes") or ())
    for workflow in workflow_files:
        if workflow.name.startswith(forbidden_prefixes):
            errors.append(f"legacy workflow remains active: {workflow.relative_to(root)}")
        text = workflow.read_text(encoding="utf-8")
        for label, pattern in FORBIDDEN_WORKFLOW_PATTERNS:
            if pattern.search(text):
                errors.append(
                    f"active workflow contains prohibited legacy execution token {label}: "
                    f"{workflow.relative_to(root)}"
                )
        for basename in LEGACY_LIBRARY_BASENAMES:
            if basename in text:
                errors.append(
                    f"active workflow references obsolete V12 Library authority/state: "
                    f"{workflow.relative_to(root)} token={basename}"
                )

    canonical = root / CANONICAL_PATH
    state_path = root / STATE_PATH
    if not canonical.is_file():
        errors.append(f"Canonical V12 authority missing: {CANONICAL_PATH}")
    if not state_path.is_file():
        errors.append(f"V12 state missing: {STATE_PATH}")
    else:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("architecture_authority") != CANONICAL_PATH:
            errors.append("State does not bind the exact Canonical V12 authority path")
        if state.get("authority") is not False:
            errors.append("State JSON must remain non-authoritative: authority=false")
        if state.get("non_authoritative_state_file") is not True:
            errors.append("State JSON must declare non_authoritative_state_file=true")
        if state.get("latest_explicit_user_state_wins") is not True:
            errors.append("State JSON must preserve latest explicit user state precedence")
        core = dict(state.get("core_policy") or {})
        if core.get("v6_only") is not True:
            errors.append("State core policy must preserve V6-only factual routing")
        if core.get("v3_v4_v5_fallback_allowed") is not False:
            errors.append("State core policy must forbid V3/V4/V5 fallback")

    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS: static legacy freeze integrity and zero active V3/V4/V5 execution")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
