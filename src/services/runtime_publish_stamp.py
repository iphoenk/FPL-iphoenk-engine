from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
from pathlib import Path

from src.engines.v4_freshness import evaluate_freshness
from src.utils import DATA, atomic_json, iso_now, read_json

LATEST = DATA / "latest.json"
CHECKPOINT = DATA / "checkpoint_decision_v4.json"
SERVING = DATA / "serving_payload_v4.json"
BENCHMARK = DATA / "serving_benchmark_v4.json"
SNAPSHOT = DATA / "runtime" / "snapshot.v1.json"
PROVENANCE = DATA / "runtime_provenance_v4.json"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _checked_out_sha() -> str | None:
    try:
        value = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip().lower()
    except (OSError, subprocess.CalledProcessError):
        return None
    return value if _SHA_RE.fullmatch(value) else None


def provenance_from_env(*, required: bool = False) -> dict:
    # In a reusable workflow GITHUB_SHA belongs to the caller (for example
    # `main`), not necessarily the canonical V4 checkout. HEAD is therefore the
    # authoritative source identity after actions/checkout resolves inputs.ref.
    source_sha = (os.getenv("V4_CANONICAL_SOURCE_SHA") or "").strip().lower() or _checked_out_sha()
    run_id = (os.getenv("V4_PUBLISH_RUN_ID") or os.getenv("GITHUB_RUN_ID") or "").strip()
    run_attempt = (os.getenv("V4_PUBLISH_RUN_ATTEMPT") or os.getenv("GITHUB_RUN_ATTEMPT") or "").strip()
    workflow = (os.getenv("V4_PUBLISH_WORKFLOW") or os.getenv("GITHUB_WORKFLOW") or "").strip()
    event = (os.getenv("V4_PUBLISH_EVENT") or os.getenv("GITHUB_EVENT_NAME") or "").strip()
    actor = (os.getenv("V4_PUBLISH_ACTOR") or os.getenv("GITHUB_ACTOR") or "").strip()
    repository = (os.getenv("V4_PUBLISH_REPOSITORY") or os.getenv("GITHUB_REPOSITORY") or "").strip()

    if required:
        missing = [
            key
            for key, value in {
                "canonical checked-out source SHA": source_sha,
                "GITHUB_RUN_ID": run_id,
                "GITHUB_RUN_ATTEMPT": run_attempt,
                "GITHUB_WORKFLOW": workflow,
                "GITHUB_EVENT_NAME": event,
                "GITHUB_ACTOR": actor,
                "GITHUB_REPOSITORY": repository,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(f"runtime publication provenance missing: {', '.join(missing)}")
    if source_sha and not _SHA_RE.fullmatch(source_sha):
        raise RuntimeError("runtime canonical source must be an exact 40-char lowercase git SHA")
    if run_id and not run_id.isdigit():
        raise RuntimeError("runtime publication workflow run id must be numeric")
    if run_attempt and not run_attempt.isdigit():
        raise RuntimeError("runtime publication workflow run attempt must be numeric")

    return {
        "canonical_source_sha": source_sha or None,
        "workflow_run_id": int(run_id) if run_id else None,
        "workflow_run_attempt": int(run_attempt) if run_attempt else None,
        "workflow": workflow or None,
        "event": event or None,
        "actor": actor or None,
        "repository": repository or None,
        "runtime_branch": os.getenv("RUNTIME_BRANCH", "runtime-data-v4"),
    }


def _validate_provenance(provenance: dict, *, require_complete: bool) -> None:
    source_sha = provenance.get("canonical_source_sha")
    if require_complete and not source_sha:
        raise RuntimeError("runtime provenance requires canonical_source_sha")
    if source_sha and not _SHA_RE.fullmatch(str(source_sha)):
        raise RuntimeError("runtime provenance canonical_source_sha is invalid")
    if require_complete:
        for key in (
            "workflow_run_id",
            "workflow_run_attempt",
            "workflow",
            "event",
            "actor",
            "repository",
            "runtime_branch",
        ):
            if provenance.get(key) in (None, ""):
                raise RuntimeError(f"runtime provenance requires {key}")


def stamp_runtime_publish(
    published_at: str | None = None,
    *,
    provenance: dict | None = None,
    require_provenance: bool = False,
) -> dict:
    stamp = published_at or iso_now()
    latest = read_json(LATEST, {})
    if not latest:
        raise RuntimeError("runtime publish stamp requires latest.json")

    provenance = dict(provenance or provenance_from_env(required=require_provenance))
    _validate_provenance(provenance, require_complete=require_provenance)
    provenance.update(
        {
            "schema_version": 1,
            "contract": "V4_RUNTIME_PROVENANCE_V1",
            "runtime_publish_at": stamp,
            "snapshot_sha256": _sha256(SNAPSHOT),
        }
    )

    latest["runtime_publish_at"] = stamp
    freshness = evaluate_freshness(latest, now=stamp, runtime_publish_at=stamp)
    latest["freshness"] = freshness
    latest["source_age_minutes"] = freshness.get("source_age_minutes")
    latest["freshness_state"] = freshness.get("freshness_state")
    latest["runtime_provenance"] = provenance
    atomic_json(LATEST, latest)

    checkpoint = read_json(CHECKPOINT, {})
    if checkpoint:
        checkpoint["runtime_publish_at"] = stamp
        checkpoint["freshness_at_publish"] = freshness
        checkpoint["runtime_provenance"] = provenance
        atomic_json(CHECKPOINT, checkpoint)

    serving = read_json(SERVING, {})
    if serving:
        serving["runtime_publish_at"] = stamp
        engine_line = serving.setdefault("engine_source_line", {})
        engine_line["freshness_at_publish"] = freshness
        engine_line["runtime_provenance"] = provenance
        atomic_json(SERVING, serving)

    benchmark = read_json(BENCHMARK, {})
    if benchmark:
        benchmark["runtime_publish_at"] = stamp
        benchmark["publication_source_age_minutes"] = freshness.get("source_age_minutes")
        benchmark["runtime_provenance"] = provenance
        atomic_json(BENCHMARK, benchmark)

    atomic_json(PROVENANCE, provenance)
    return {
        "runtime_publish_at": stamp,
        "freshness_state": freshness.get("freshness_state"),
        "source_age_minutes": freshness.get("source_age_minutes"),
        "canonical_source_sha": provenance.get("canonical_source_sha"),
        "workflow_run_id": provenance.get("workflow_run_id"),
        "snapshot_sha256": provenance.get("snapshot_sha256"),
    }


def verify_runtime_provenance(
    *, expected_source_sha: str | None = None, expected_run_id: int | None = None
) -> dict:
    latest = read_json(LATEST, {})
    provenance = read_json(PROVENANCE, {})
    if not latest or not provenance:
        raise RuntimeError(
            "runtime provenance verification requires latest.json and runtime_provenance_v4.json"
        )
    _validate_provenance(provenance, require_complete=True)
    embedded = latest.get("runtime_provenance") or {}
    if embedded != provenance:
        raise RuntimeError(
            "latest.json runtime_provenance does not match runtime_provenance_v4.json"
        )
    if latest.get("runtime_publish_at") != provenance.get("runtime_publish_at"):
        raise RuntimeError("runtime publication timestamp provenance mismatch")
    if expected_source_sha and provenance.get("canonical_source_sha") != expected_source_sha.lower():
        raise RuntimeError("runtime provenance canonical source SHA mismatch")
    if expected_run_id is not None and provenance.get("workflow_run_id") != int(expected_run_id):
        raise RuntimeError("runtime provenance workflow run id mismatch")
    expected_snapshot_hash = provenance.get("snapshot_sha256")
    actual_snapshot_hash = _sha256(SNAPSHOT)
    if expected_snapshot_hash != actual_snapshot_hash:
        raise RuntimeError("runtime provenance snapshot hash mismatch")
    return provenance


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--expected-source-sha")
    parser.add_argument("--expected-run-id", type=int)
    args = parser.parse_args()
    if args.verify:
        print(
            verify_runtime_provenance(
                expected_source_sha=args.expected_source_sha,
                expected_run_id=args.expected_run_id,
            )
        )
        return

    require = os.getenv("V4_PROVENANCE_REQUIRED") == "1" or os.getenv("GITHUB_ACTIONS") == "true"
    result = stamp_runtime_publish(require_provenance=require)
    if require:
        verify_runtime_provenance(
            expected_source_sha=result["canonical_source_sha"],
            expected_run_id=result["workflow_run_id"],
        )
    print(result)


if __name__ == "__main__":
    main()
