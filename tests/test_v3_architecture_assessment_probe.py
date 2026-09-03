from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (ROOT / "src" / "engines", ROOT / "src" / "runtime_v3")


HARDCODE_RE = re.compile(r"\b(?:if|elif)\b.*[<>=]=?\s*[0-9]+\.[0-9]{2,}\b")
DIRECT_WRITE_RES = (
    re.compile(r"\.write_text\s*\("),
    re.compile(r"json\.dump\s*\("),
    re.compile(r"open\s*\([^\n]*,[^\n]*[\"']w[bt]?[\"']"),
)


def _source_lines() -> list[tuple[str, int, str]]:
    rows: list[tuple[str, int, str]] = []
    for root in SOURCE_ROOTS:
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                rows.append((rel, lineno, line))
    return rows


def _ephemeral_artifact_declarations() -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for path in sorted((ROOT / "config").rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        def walk(value: object, trail: tuple[str, ...] = ()) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    next_trail = trail + (str(key),)
                    if key == "ephemeral_artifacts":
                        findings.append(
                            {
                                "file": path.relative_to(ROOT).as_posix(),
                                "path": ".".join(next_trail),
                                "value": item,
                            }
                        )
                    walk(item, next_trail)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    walk(item, trail + (str(index),))

        walk(payload)
    return findings


def _workflow_boundary_excerpt() -> list[dict[str, object]]:
    path = ROOT / ".github" / "workflows" / "v3-package-precompute.yml"
    lines = path.read_text(encoding="utf-8").splitlines()
    hits: list[dict[str, object]] = []
    markers = (
        "upload-artifact",
        "download-artifact",
        "official_snapshot.json",
        "official_snapshot.retry.json",
        "runtime-publish",
        "package-shard-plan.json",
        "shard-results",
    )
    for index, line in enumerate(lines):
        if any(marker in line for marker in markers):
            start = max(0, index - 2)
            end = min(len(lines), index + 5)
            hits.append(
                {
                    "line": index + 1,
                    "excerpt": "\n".join(f"{i + 1}: {lines[i]}" for i in range(start, end)),
                }
            )
    return hits


def test_emit_v3_architecture_assessment_probe() -> None:
    rows = _source_lines()
    hardcodes = [
        {"file": rel, "line": lineno, "text": text.strip()}
        for rel, lineno, text in rows
        if HARDCODE_RE.search(text)
    ]
    direct_writes = [
        {"file": rel, "line": lineno, "text": text.strip()}
        for rel, lineno, text in rows
        if any(pattern.search(text) for pattern in DIRECT_WRITE_RES)
        and "GITHUB_OUTPUT" not in text
    ]
    report = {
        "commit_scope": "V3 engines + runtime_v3",
        "hardcode_candidates": hardcodes,
        "direct_write_candidates": direct_writes,
        "ephemeral_artifact_declarations": _ephemeral_artifact_declarations(),
        "v3_package_precompute_boundary_excerpt": _workflow_boundary_excerpt(),
    }
    raise AssertionError("V3_ARCHITECTURE_ASSESSMENT_PROBE\n" + json.dumps(report, indent=2, sort_keys=True))
