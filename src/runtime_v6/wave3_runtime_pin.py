"""Fail-closed immutable runtime commit pin for genuine Wave 3 source runs.

Do not resolve a prior source's publication through the moving runtime-data-v6
branch tip. The original successful source publisher's own job log records its
candidate Git commit SHA; verify that commit's Git object and original V6
artifact contents before permitting Wave 3 proof.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path
from typing import Any, Mapping

_SHA = r"[0-9a-f]{40}"
_CANDIDATE = re.compile(r"Runtime publish CAS attempt [1-3]; expected=(" + _SHA + r"); candidate=(" + _SHA + r")")
_PUBLISHED = re.compile(r"PUBLISHED_RUNTIME_SHA:\s*(" + _SHA + r")")


class ImmutableRuntimePinError(ValueError):
    """Source publisher/immutable commit provenance mismatch."""


def pin_from_publisher_log(log: str) -> str:
    candidates = set(_CANDIDATE.findall(log))
    published = set(_PUBLISHED.findall(log))
    if not candidates:
        raise ImmutableRuntimePinError("SOURCE_PUBLISHER_COMMIT_NOT_IN_ORIGINAL_JOB_LOG")
    unique = {candidate for _lease, candidate in candidates}
    if len(unique) != 1:
        raise ImmutableRuntimePinError("AMBIGUOUS_SOURCE_PUBLISHER_CANDIDATE_SHA")
    if len(published) != 1 or published != unique:
        raise ImmutableRuntimePinError("SOURCE_PUBLISHER_SHA_NOT_CONFIRMED_BY_VERIFY_JOB")
    return next(iter(unique))


def _bytes(envelope: Mapping[str, Any]) -> bytes:
    if str(envelope.get("encoding") or "") != "base64":
        raise ImmutableRuntimePinError("ORIGINAL_GIT_CONTENT_ENCODING_UNVERIFIED")
    try:
        return base64.b64decode(str(envelope.get("content") or "").replace("\n", ""), validate=True)
    except (ValueError, Exception) as exc:
        raise ImmutableRuntimePinError("ORIGINAL_GIT_CONTENT_DECODE_FAILED") from exc


def verify_original_runtime(
    *,
    runtime_sha: str,
    source_run_id: str,
    source_attempt: str,
    git_commit: Mapping[str, Any],
    freeze_envelope: Mapping[str, Any],
    integrity_envelope: Mapping[str, Any],
    archive_root: Path,
) -> dict[str, Any]:
    if not re.fullmatch(_SHA, runtime_sha):
        raise ImmutableRuntimePinError("SOURCE_RUNTIME_SHA_INVALID")
    if git_commit.get("sha") != runtime_sha:
        raise ImmutableRuntimePinError("SOURCE_RUNTIME_GIT_COMMIT_SHA_MISMATCH")
    expected_message = (
        f"data(v6): atomic hourly snapshot {source_run_id} "
        "[chatgpt_scheduler] [dedicated_v6_github_app]"
    )
    if str(git_commit.get("message") or "") != expected_message:
        raise ImmutableRuntimePinError("SOURCE_RUNTIME_GIT_COMMIT_IDENTITY_MISMATCH")
    if git_commit.get("parents") != []:
        raise ImmutableRuntimePinError("SOURCE_RUNTIME_GIT_ROOT_COMMIT_NOT_VERIFIED")

    objects = [
        ("health/candidate_freeze.lock", freeze_envelope),
        ("health/publish_integrity.json", integrity_envelope),
    ]
    decoded = {}
    for relative, envelope in objects:
        source = archive_root / relative
        if not source.is_file():
            raise ImmutableRuntimePinError("SOURCE_IMMUTABLE_ARTIFACT_FILE_MISSING:" + relative)
        original = _bytes(envelope)
        if original != source.read_bytes():
            raise ImmutableRuntimePinError("SOURCE_GIT_OBJECT_ARTIFACT_BYTES_MISMATCH:" + relative)
        decoded[relative] = json.loads(original.decode("utf-8"))

    freeze = decoded["health/candidate_freeze.lock"]
    integrity = decoded["health/publish_integrity.json"]
    if (
        str(freeze.get("run_id")) != str(source_run_id)
        or str(freeze.get("run_attempt")) != str(source_attempt)
        or freeze.get("candidate_state") != "FROZEN"
        or str(integrity.get("run_id")) != str(source_run_id)
        or str(integrity.get("run_attempt")) != str(source_attempt)
        or integrity.get("status") != "PASS"
    ):
        raise ImmutableRuntimePinError("SOURCE_IMMUTABLE_RUNTIME_IDENTITY_OR_INTEGRITY_FAILED")
    return {
        "published_runtime_sha": runtime_sha,
        "source_run_id": str(source_run_id),
        "source_run_attempt": str(source_attempt),
        "commit_identity_verified": True,
        "git_object_artifact_exact_bytes": True,
        "source_publish_integrity": "PASS",
        "moving_branch_tip_consulted": False,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=("extract", "verify"))
    p.add_argument("--log", type=Path, required=True)
    p.add_argument("--source-run-id", required=True)
    p.add_argument("--source-attempt", required=True)
    p.add_argument("--git-commit", type=Path)
    p.add_argument("--freeze-envelope", type=Path)
    p.add_argument("--integrity-envelope", type=Path)
    p.add_argument("--archive-root", type=Path)
    args = p.parse_args()
    runtime_sha = pin_from_publisher_log(args.log.read_text(encoding="utf-8"))
    if args.mode == "extract":
        print(runtime_sha)
        return
    if not all((args.git_commit, args.freeze_envelope, args.integrity_envelope, args.archive_root)):
        raise ImmutableRuntimePinError("ORIGINAL_GIT_OBJECT_ARGUMENT_MISSING")
    result = verify_original_runtime(
        runtime_sha=runtime_sha,
        source_run_id=args.source_run_id,
        source_attempt=args.source_attempt,
        git_commit=json.loads(args.git_commit.read_text(encoding="utf-8")),
        freeze_envelope=json.loads(args.freeze_envelope.read_text(encoding="utf-8")),
        integrity_envelope=json.loads(args.integrity_envelope.read_text(encoding="utf-8")),
        archive_root=args.archive_root,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
