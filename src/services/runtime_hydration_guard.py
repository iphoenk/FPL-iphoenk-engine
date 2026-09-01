from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from src.utils import DATA, ROOT

RUNTIME_BRANCH = "runtime-data-v4"
RUNTIME_REF = f"refs/remotes/origin/{RUNTIME_BRANCH}"
EXPECTED_BOT_EMAIL = "actions@users.noreply.github.com"
EXPECTED_SUBJECT = "data(v4): atomic production snapshot [skip ci]"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _git_text(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL, text=True).strip()


def _git_bytes(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL)


def _git_ok(root: Path, *args: str) -> bool:
    return subprocess.run(["git", *args], cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0


def _required_in_this_process() -> bool:
    if os.getenv("GITHUB_ACTIONS") != "true":
        return False
    return os.getenv("GITHUB_EVENT_NAME") not in {"pull_request", "pull_request_target"}


def verify_hydrated_runtime_if_required(root: Path = ROOT) -> dict:
    if not _required_in_this_process():
        return {"status": "SKIPPED", "reason": "not_production_actions_context"}
    if not _git_ok(root, "show-ref", "--verify", "--quiet", RUNTIME_REF):
        return {"status": "SKIPPED", "reason": "runtime_branch_absent_first_publish"}

    commit = _git_text(root, "rev-parse", RUNTIME_REF).lower()
    parent_line = _git_text(root, "rev-list", "--parents", "-n1", RUNTIME_REF).split()
    if len(parent_line) != 1:
        raise RuntimeError("runtime hydration rejected: snapshot commit must be parentless")
    author = _git_text(root, "show", "-s", "--format=%ae", RUNTIME_REF)
    committer = _git_text(root, "show", "-s", "--format=%ce", RUNTIME_REF)
    subject = _git_text(root, "show", "-s", "--format=%s", RUNTIME_REF)
    if author != EXPECTED_BOT_EMAIL or committer != EXPECTED_BOT_EMAIL:
        raise RuntimeError("runtime hydration rejected: commit identity is not governed automation")
    if subject != EXPECTED_SUBJECT:
        raise RuntimeError("runtime hydration rejected: atomic snapshot commit contract mismatch")

    paths = [row for row in _git_text(root, "ls-tree", "-r", "--name-only", RUNTIME_REF).splitlines() if row]
    unexpected = [path for path in paths if not path.startswith("data/")]
    if unexpected:
        raise RuntimeError(f"runtime hydration rejected: non-data paths present: {unexpected[:5]}")

    remote_provenance_bytes = _git_bytes(root, "show", f"{RUNTIME_REF}:data/runtime_provenance_v4.json")
    remote_latest_bytes = _git_bytes(root, "show", f"{RUNTIME_REF}:data/latest.json")
    remote_snapshot_bytes = _git_bytes(root, "show", f"{RUNTIME_REF}:data/runtime/snapshot.v1.json")
    provenance = json.loads(remote_provenance_bytes)
    latest = json.loads(remote_latest_bytes)
    if provenance.get("contract") != "V4_RUNTIME_PROVENANCE_V1":
        raise RuntimeError("runtime hydration rejected: provenance contract mismatch")
    if provenance.get("runtime_branch") != RUNTIME_BRANCH:
        raise RuntimeError("runtime hydration rejected: provenance branch mismatch")
    repository = os.getenv("GITHUB_REPOSITORY")
    if repository and provenance.get("repository") != repository:
        raise RuntimeError("runtime hydration rejected: provenance repository mismatch")
    if latest.get("runtime_provenance") != provenance:
        raise RuntimeError("runtime hydration rejected: latest/provenance mismatch")
    snapshot_hash = hashlib.sha256(remote_snapshot_bytes).hexdigest()
    if snapshot_hash != provenance.get("snapshot_sha256"):
        raise RuntimeError("runtime hydration rejected: remote snapshot hash mismatch")

    workspace_provenance = DATA if root == ROOT else root / "data"
    workspace_provenance = workspace_provenance / "runtime_provenance_v4.json"
    workspace_snapshot = (DATA if root == ROOT else root / "data") / "runtime" / "snapshot.v1.json"
    if not workspace_provenance.exists() or not workspace_snapshot.exists():
        raise RuntimeError("runtime hydration rejected: hydrated provenance/snapshot missing")
    if json.loads(workspace_provenance.read_bytes()) != provenance:
        raise RuntimeError("runtime hydration rejected: workspace provenance differs from runtime branch")
    if hashlib.sha256(workspace_snapshot.read_bytes()).hexdigest() != snapshot_hash:
        raise RuntimeError("runtime hydration rejected: workspace snapshot differs from runtime branch")

    source = str(provenance.get("canonical_source_sha") or "").lower()
    if not _SHA_RE.fullmatch(source):
        raise RuntimeError("runtime hydration rejected: canonical source SHA invalid")
    if not _git_ok(root, "merge-base", "--is-ancestor", source, "HEAD"):
        raise RuntimeError("runtime hydration rejected: source SHA is not canonical checkout ancestry")

    return {
        "status": "PASS",
        "runtime_branch": RUNTIME_BRANCH,
        "runtime_commit": commit,
        "canonical_source_sha": source,
        "snapshot_sha256": snapshot_hash,
        "parentless_snapshot": True,
        "automation_identity": True,
        "data_only_tree": True,
        "provenance_verified": True,
    }
