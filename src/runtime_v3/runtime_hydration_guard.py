from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

from src.runtime_v3.publish_snapshot import (
    ATTESTATION_DIGEST_CONTRACT,
    ATTESTATION_REGISTRY,
    snapshot_digest,
)
from src.utils import ROOT

RUNTIME_BRANCH = "runtime-data"
RUNTIME_REF = f"refs/remotes/origin/{RUNTIME_BRANCH}"
EXPECTED_BOT_EMAIL = "actions@users.noreply.github.com"
EXPECTED_SUBJECT = "data: rolling FPL runtime snapshot [skip ci]"
EXPECTED_WORKFLOW = "V3 Runtime"
ATTESTATION_MARKER = "V3_RUNTIME_SNAPSHOT_ATTESTATION "
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _git_text(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=root, stderr=subprocess.DEVNULL, text=True
    ).strip()


def _git_bytes(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL)


def _git_ok(root: Path, *args: str) -> bool:
    return (
        subprocess.run(
            ["git", *args],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def _refresh_main_history(root: Path) -> None:
    """Make canonical main ancestry available in shallow Actions checkouts."""
    shallow = _git_text(root, "rev-parse", "--is-shallow-repository").lower() == "true"
    args = ["git", "fetch", "--no-tags"]
    if shallow:
        args.append("--unshallow")
    args.extend(
        [
            "origin",
            "+refs/heads/main:refs/remotes/origin/main",
        ]
    )
    subprocess.run(
        args,
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


def _source_is_canonical_ancestor(root: Path, source: str) -> bool:
    if _git_ok(root, "merge-base", "--is-ancestor", source, "HEAD"):
        return True
    try:
        _refresh_main_history(root)
    except (subprocess.CalledProcessError, OSError):
        return False
    return _git_ok(root, "merge-base", "--is-ancestor", source, "HEAD")


def _production_actions_context() -> bool:
    return os.getenv("GITHUB_ACTIONS") == "true" and os.getenv("GITHUB_WORKFLOW") == EXPECTED_WORKFLOW


def _request(url: str) -> Request:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = str(os.getenv("GH_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return Request(url, headers=headers)


def _fetch_json(url: str) -> dict:
    try:
        with urlopen(_request(url), timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("runtime hydration rejected: workflow attestation metadata unavailable") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("runtime hydration rejected: workflow attestation metadata invalid")
    return payload


def _fetch_bytes(url: str) -> bytes:
    try:
        with urlopen(_request(url), timeout=30) as response:
            return response.read()
    except Exception as exc:
        raise RuntimeError("runtime hydration rejected: workflow attestation logs unavailable") from exc


def _verify_embedded_attestation(root: Path, manifest: dict, actual_paths: list[str]) -> dict:
    schema_version = int(manifest.get("schema_version") or 0)
    attestation = manifest.get("attestation")
    if schema_version < 3:
        if _production_actions_context():
            raise RuntimeError("runtime hydration rejected: production snapshot attestation required")
        return {
            "embedded_attestation_verified": False,
            "workflow_run_id": None,
            "snapshot_sha256": None,
            "attestation": None,
        }
    if not isinstance(attestation, dict):
        raise RuntimeError("runtime hydration rejected: attestation missing")
    if attestation.get("registry") != ATTESTATION_REGISTRY:
        raise RuntimeError("runtime hydration rejected: attestation registry mismatch")
    if attestation.get("digest_contract") != ATTESTATION_DIGEST_CONTRACT:
        raise RuntimeError("runtime hydration rejected: attestation digest contract mismatch")
    if attestation.get("workflow_name") != EXPECTED_WORKFLOW:
        raise RuntimeError("runtime hydration rejected: attestation workflow mismatch")

    run_id = attestation.get("workflow_run_id")
    if not isinstance(run_id, int) or run_id <= 0:
        raise RuntimeError("runtime hydration rejected: attestation workflow run id invalid")
    source = str(manifest.get("source_commit") or "").lower()
    if attestation.get("source_commit") != source:
        raise RuntimeError("runtime hydration rejected: attestation source commit mismatch")
    claimed = str(attestation.get("snapshot_sha256") or "").lower()
    if not _DIGEST_RE.fullmatch(claimed):
        raise RuntimeError("runtime hydration rejected: attestation digest invalid")

    with tempfile.TemporaryDirectory(prefix="v3-runtime-attestation-") as tmp:
        data_dir = Path(tmp)
        for relative in actual_paths:
            target = data_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_git_bytes(root, "show", f"{RUNTIME_REF}:data/{relative}"))
        calculated = snapshot_digest(data_dir, manifest)
    if calculated != claimed:
        raise RuntimeError("runtime hydration rejected: attested runtime content digest mismatch")

    return {
        "embedded_attestation_verified": True,
        "workflow_run_id": run_id,
        "snapshot_sha256": claimed,
        "attestation": attestation,
    }


def _verify_compute_job_attestation(
    *,
    api: str,
    repository: str,
    run_id: int,
    expected_marker: str,
) -> None:
    """Verify the exact marker in a successful compute job, including rerun attempts.

    GitHub's workflow-run aggregate log archive is not a stable authority across
    reruns. The attestation is emitted by the compute job, so bind verification to
    that immutable job log while still requiring the parent workflow run itself to
    be canonical and successful.
    """
    jobs_payload = _fetch_json(
        f"{api}/repos/{repository}/actions/runs/{run_id}/jobs?filter=all&per_page=100"
    )
    jobs = jobs_payload.get("jobs")
    if not isinstance(jobs, list):
        raise RuntimeError("runtime hydration rejected: attesting workflow jobs unavailable")

    candidates = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        if job.get("name") != "compute" or job.get("conclusion") != "success":
            continue
        job_run_id = job.get("run_id")
        if job_run_id is not None and job_run_id != run_id:
            continue
        job_id = job.get("id")
        if not isinstance(job_id, int) or job_id <= 0:
            continue
        candidates.append(job)

    candidates.sort(
        key=lambda job: (int(job.get("run_attempt") or 0), int(job.get("id") or 0)),
        reverse=True,
    )
    for job in candidates:
        job_id = int(job["id"])
        text = _fetch_bytes(
            f"{api}/repos/{repository}/actions/jobs/{job_id}/logs"
        ).decode("utf-8", errors="replace")
        if expected_marker in text:
            return

    raise RuntimeError("runtime hydration rejected: immutable workflow attestation marker missing")


def _verify_immutable_workflow_evidence(attestation: dict) -> dict:
    if not _production_actions_context():
        return {
            "workflow_run_success_verified": False,
            "immutable_log_attestation_verified": False,
        }

    repository = str(os.getenv("GITHUB_REPOSITORY") or "").strip()
    api = str(os.getenv("GITHUB_API_URL") or "https://api.github.com").rstrip("/")
    if not repository:
        raise RuntimeError("runtime hydration rejected: GitHub repository identity unavailable")

    run_id = int(attestation["workflow_run_id"])
    metadata = _fetch_json(f"{api}/repos/{repository}/actions/runs/{run_id}")
    if metadata.get("id") != run_id:
        raise RuntimeError("runtime hydration rejected: workflow run id mismatch")
    if metadata.get("name") != EXPECTED_WORKFLOW:
        raise RuntimeError("runtime hydration rejected: workflow run name mismatch")
    if metadata.get("head_branch") != "main":
        raise RuntimeError("runtime hydration rejected: attesting workflow was not canonical main")
    if metadata.get("head_sha") != attestation.get("source_commit"):
        raise RuntimeError("runtime hydration rejected: attesting workflow source SHA mismatch")
    if metadata.get("conclusion") != "success":
        raise RuntimeError("runtime hydration rejected: attesting workflow did not complete successfully")

    expected_marker = ATTESTATION_MARKER + json.dumps(
        attestation, ensure_ascii=False, sort_keys=True
    )
    _verify_compute_job_attestation(
        api=api,
        repository=repository,
        run_id=run_id,
        expected_marker=expected_marker,
    )

    return {
        "workflow_run_success_verified": True,
        "immutable_log_attestation_verified": True,
    }


def verify_runtime_snapshot(root: Path = ROOT) -> dict:
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
        raise RuntimeError("runtime hydration rejected: rolling snapshot commit contract mismatch")

    tree_paths = [
        row
        for row in _git_text(root, "ls-tree", "-r", "--name-only", RUNTIME_REF).splitlines()
        if row
    ]
    unexpected = [path for path in tree_paths if not path.startswith("data/")]
    if unexpected:
        raise RuntimeError(
            f"runtime hydration rejected: non-data paths present: {unexpected[:5]}"
        )

    manifest_path = "data/runtime_manifest.json"
    if manifest_path not in tree_paths:
        raise RuntimeError("runtime hydration rejected: runtime manifest missing")
    try:
        manifest = json.loads(_git_bytes(root, "show", f"{RUNTIME_REF}:{manifest_path}"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("runtime hydration rejected: runtime manifest invalid") from exc

    if manifest.get("registry") != "RUNTIME_MANIFEST_V1":
        raise RuntimeError("runtime hydration rejected: manifest registry mismatch")
    publication = manifest.get("publication")
    if not isinstance(publication, dict):
        raise RuntimeError("runtime hydration rejected: publication metadata missing")
    if publication.get("registry") != "RUNTIME_PUBLISH_REGISTRY_V1":
        raise RuntimeError("runtime hydration rejected: publication registry mismatch")

    declared = publication.get("paths")
    if not isinstance(declared, list):
        raise RuntimeError("runtime hydration rejected: publication whitelist missing")
    declared_paths = sorted(str(path) for path in declared)
    actual_paths = sorted(
        path.removeprefix("data/") for path in tree_paths if path != manifest_path
    )
    if declared_paths != actual_paths:
        raise RuntimeError("runtime hydration rejected: manifest/tree whitelist mismatch")

    expected_without_manifest = publication.get("file_count_without_manifest")
    expected_total = publication.get("file_count")
    if expected_without_manifest != len(actual_paths):
        raise RuntimeError("runtime hydration rejected: payload file count mismatch")
    if expected_total != len(tree_paths):
        raise RuntimeError("runtime hydration rejected: total file count mismatch")

    source = str(manifest.get("source_commit") or "").lower()
    if not _SHA_RE.fullmatch(source):
        raise RuntimeError("runtime hydration rejected: source commit invalid")
    if not _source_is_canonical_ancestor(root, source):
        raise RuntimeError(
            "runtime hydration rejected: source commit is not canonical checkout ancestry"
        )

    embedded = _verify_embedded_attestation(root, manifest, actual_paths)
    external = _verify_immutable_workflow_evidence(embedded.get("attestation") or {})

    return {
        "status": "PASS",
        "runtime_branch": RUNTIME_BRANCH,
        "runtime_commit": commit,
        "canonical_source_sha": source,
        "parentless_snapshot": True,
        "automation_identity": True,
        "data_only_tree": True,
        "publication_whitelist_verified": True,
        "canonical_source_ancestry_verified": True,
        "embedded_attestation_verified": embedded["embedded_attestation_verified"],
        "workflow_run_id": embedded["workflow_run_id"],
        "snapshot_sha256": embedded["snapshot_sha256"],
        "workflow_run_success_verified": external["workflow_run_success_verified"],
        "immutable_log_attestation_verified": external["immutable_log_attestation_verified"],
    }


def main() -> int:
    result = verify_runtime_snapshot()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
