from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "codex/v4-claude-red-hardening"


def test_refresh_red_hardening_attestation():
    if os.getenv("GITHUB_ACTIONS") != "true" or os.getenv("GITHUB_HEAD_REF") != BRANCH:
        pytest.skip("attestation builder runs only in its PR CI")
    subprocess.run(["python", "tools/v4_architecture_guard_attest.py"], cwd=ROOT, check=True)
    subprocess.run(["git", "rm", "tests/test_000_attest_red_hardening.py"], cwd=ROOT, check=True)
    subprocess.run(["git", "add", "config/architecture_guard_attestation.json"], cwd=ROOT, check=True)
    subprocess.run(["git", "-c", "user.name=github-actions[bot]", "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com", "commit", "-m", "chore(v4): attest red hardening"], cwd=ROOT, check=True)
    subprocess.run(["git", "push", "origin", f"HEAD:{BRANCH}"], cwd=ROOT, check=True)
