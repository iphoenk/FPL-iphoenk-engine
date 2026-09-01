from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from src.utils import ROOT

RUNTIME_BRANCH = "runtime-data"
RUNTIME_REF = f"refs/remotes/origin/{RUNTIME_BRANCH}"
EXPECTED_BOT_EMAIL = "actions@users.noreply.github.com"
EXPECTED_SUBJECT = "data: rolling FPL runtime snapshot [skip ci]"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


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
    """Make canonical main ancestry available in shallow Actions checkouts.

    Runtime jobs intentionally checkout one source SHA with depth=1. An older,
    valid runtime manifest therefore cannot be ancestry-checked until canonical
    main history is materialized. Keep the ancestry requirement and expand only
    Git history; never weaken it to string equality or commit existence.
    """
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
    }


def main() -> int:
    result = verify_runtime_snapshot()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
