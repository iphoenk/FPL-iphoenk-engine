from __future__ import annotations

import ast
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (ROOT / "src" / "engines", ROOT / "src" / "runtime_v3")

DIRECT_WRITE_RES = (
    re.compile(r"\.write_text\s*\("),
    re.compile(r"json\.dump\s*\("),
    re.compile(r"open\s*\([^\n]*,[^\n]*[\"']w[bt]?[\"']"),
)


def _source_files() -> list[Path]:
    return [path for root in SOURCE_ROOTS for path in sorted(root.rglob("*.py"))]


def _float_compare_candidates() -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for path in _source_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            constants = [
                item.value
                for item in (node.left, *node.comparators)
                if isinstance(item, ast.Constant) and isinstance(item.value, float)
            ]
            if not constants:
                continue
            findings.append({
                "file": path.relative_to(ROOT).as_posix(),
                "line": node.lineno,
                "float_literals": constants,
                "text": lines[node.lineno - 1].strip(),
            })
    return findings


def _direct_write_candidates() -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for path in _source_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(pattern.search(line) for pattern in DIRECT_WRITE_RES) and "GITHUB_OUTPUT" not in line:
                findings.append({"file": path.relative_to(ROOT).as_posix(), "line": lineno, "text": line.strip()})
    return findings


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
                        findings.append({
                            "file": path.relative_to(ROOT).as_posix(),
                            "path": ".".join(next_trail),
                            "value": item,
                        })
                    walk(item, next_trail)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    walk(item, trail + (str(index),))

        walk(payload)
    return findings


def test_emit_v3_architecture_assessment_probe() -> None:
    report = {
        "commit_scope": "V3 engines + runtime_v3",
        "float_compare_candidates_ast": _float_compare_candidates(),
        "direct_write_candidates": _direct_write_candidates(),
        "ephemeral_artifact_declarations": _ephemeral_artifact_declarations(),
    }
    raise AssertionError("V3_ARCHITECTURE_ASSESSMENT_PROBE\n" + json.dumps(report, indent=2, sort_keys=True))
