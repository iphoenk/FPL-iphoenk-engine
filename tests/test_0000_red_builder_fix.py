from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "codex/v4-claude-red-hardening"
SELF = "tests/test_0000_red_builder_fix.py"
OLD = ROOT / "tests/test_000_claude_red_hardening_builder.py"


def test_repair_and_run_red_builder():
    if os.getenv("GITHUB_ACTIONS") != "true" or os.getenv("GITHUB_HEAD_REF") != BRANCH:
        pytest.skip("one-shot builder repair runs only in its PR CI")

    source = OLD.read_text(encoding="utf-8")
    source = source.replace(
        '        "tests/test_000_claude_red_hardening_builder.py",\n',
        "",
        1,
    )
    namespace = {"__file__": str(OLD), "__name__": "red_builder_repaired"}
    exec(compile(source, str(OLD), "exec"), namespace)
    namespace["test_build_red_hardening_patch"]()

    # Prevent the already-collected original test from running its stale staging path.
    os.environ["GITHUB_HEAD_REF"] = "__red_builder_already_applied__"

    subprocess.run(["git", "rm", SELF], cwd=ROOT, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=github-actions[bot]",
            "-c",
            "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "commit",
            "-m",
            "chore(v4): remove red hardening repair harness",
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(["git", "push", "origin", f"HEAD:{BRANCH}"], cwd=ROOT, check=True)
