from __future__ import annotations

import json
import subprocess


def _git(*args: str) -> None:
    subprocess.run(["git", *args], check=True)


def test_emit_refreshed_architecture_attestation_for_pr_repair():
    from src.services import architecture_guard_service as guard
    from src.utils import atomic_json

    # Re-anchor to the actual PR head so the attestation fingerprint is for the
    # branch that will be reviewed/merged, not GitHub's synthetic PR merge ref.
    _git("fetch", "origin", "user-state/gw3-ajayi-v4")
    _git("checkout", "-B", "attestation-repair", "FETCH_HEAD")

    result = guard.run(force_full_scan=True)
    fingerprint = guard.repository_fingerprint()
    payload = {
        "schema_version": guard.ATTESTATION_SCHEMA_VERSION,
        "fingerprint": fingerprint,
        "release": result.get("release"),
        "guard_schema_version": result.get("schema_version"),
        "result": result,
    }
    atomic_json(guard.ATTESTATION_PATH, payload)

    _git("config", "user.name", "fpl-iphoenk-bot")
    _git("config", "user.email", "actions@users.noreply.github.com")
    _git("add", "config/architecture_guard_attestation.json")
    _git("commit", "-m", "chore(v4): refresh architecture attestation for capture authority")
    _git("push", "origin", "HEAD:refs/heads/user-state/gw3-ajayi-v4")

    print("ATTJSON=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    assert False, "ATTTEST_PUSHED_ATTESTATION"
