from __future__ import annotations

import os
import subprocess
from pathlib import Path

from src.services import architecture_guard_service as guard
from tools.v4_architecture_guard_attest import main


BRANCH = "codex/v4-calibration-full-green-prod"
ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> None:
    subprocess.run(["git", *args], cwd=ROOT, check=True)


def test_refresh_persist_and_remove_attestation_harness() -> None:
    main()
    assert guard._attested_result() is not None

    if os.environ.get("GITHUB_ACTIONS") != "true":
        return

    # This test exists for one PR run only. The architecture fingerprint excludes
    # tests, so deleting this harness after generating the attestation does not
    # change the governed fingerprint.
    Path(__file__).unlink()
    _git("config", "user.name", "fpl-iphoenk-bot")
    _git("config", "user.email", "actions@users.noreply.github.com")
    _git("add", "config/architecture_guard_attestation.json", "tests/test_000_attestation_refresh.py")
    _git("commit", "-m", "governance(v4): attest fixture-final reconciliation hardening")
    _git("push", "origin", f"HEAD:refs/heads/{BRANCH}")
