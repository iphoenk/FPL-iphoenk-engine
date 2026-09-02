#!/usr/bin/env python3
"""Decide whether an exact V4 checkpoint precompute is still safe to reuse."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "config" / "runtime" / "v4_operational_policy.json"


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _load_fresh_max_minutes(path: Path = POLICY_PATH) -> float:
    raw = json.loads(path.read_text(encoding="utf-8"))
    value = float(raw["fresh_max_minutes"])
    if value <= 0:
        raise RuntimeError("fresh_max_minutes must be positive")
    return value


def evaluate(
    provenance: dict,
    *,
    target_checkpoint: str,
    canonical_sha: str,
    observed: datetime,
    fresh_max_minutes: float | None = None,
) -> dict:
    if observed.tzinfo is None:
        raise ValueError("observed must be timezone-aware")
    observed = observed.astimezone(timezone.utc)
    target = _parse_timestamp(target_checkpoint)
    published = _parse_timestamp(provenance.get("runtime_publish_at"))
    cp = provenance.get("checkpoint") or {}
    fresh_max = _load_fresh_max_minutes() if fresh_max_minutes is None else float(fresh_max_minutes)

    reason = "REUSABLE"
    age_minutes: float | None = None
    reusable = True

    if target is None:
        reusable = False
        reason = "TARGET_CHECKPOINT_INVALID"
    elif published is None:
        reusable = False
        reason = "RUNTIME_PUBLISH_TIMESTAMP_MISSING_OR_INVALID"
    else:
        raw_age = (observed - published).total_seconds() / 60.0
        age_minutes = round(max(0.0, raw_age), 2)
        checks = (
            (provenance.get("canonical_source_sha") == canonical_sha, "CANONICAL_SHA_MISMATCH"),
            (cp.get("snapshot_role") == "PRECOMPUTE_NEXT_CHECKPOINT", "SNAPSHOT_ROLE_NOT_PRECOMPUTE"),
            (cp.get("target_checkpoint") == target_checkpoint, "TARGET_CHECKPOINT_MISMATCH"),
            (cp.get("precomputed") is True, "PRECOMPUTED_FLAG_MISSING"),
            (cp.get("generated_before_or_at_target") is True, "PRECOMPUTE_NOT_GENERATED_BY_TARGET"),
            (cp.get("materialization_complete") is True, "MATERIALIZATION_INCOMPLETE"),
            (cp.get("publication_proof") == "PRESENCE_ON_RUNTIME_BRANCH", "PUBLICATION_PROOF_MISSING"),
            (published <= target, "PUBLISHED_AFTER_TARGET"),
            (raw_age >= -5.0, "RUNTIME_PUBLISH_TIMESTAMP_IN_FUTURE"),
            (raw_age <= fresh_max, "PUBLISH_AGE_EXCEEDS_FRESH_MAX"),
        )
        for passed, failure_reason in checks:
            if not passed:
                reusable = False
                reason = failure_reason
                break

    return {
        "reusable": reusable,
        "reason": reason,
        "canonical_sha": canonical_sha,
        "target_checkpoint": target_checkpoint,
        "runtime_publish_at": published.isoformat() if published else None,
        "execution_observed": observed.isoformat(),
        "age_minutes": age_minutes,
        "fresh_max_minutes": fresh_max,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--target-checkpoint", required=True)
    parser.add_argument("--canonical-sha", required=True)
    parser.add_argument("--observed", required=True)
    args = parser.parse_args()

    try:
        provenance = json.loads(args.provenance.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        provenance = {}
    observed = _parse_timestamp(args.observed)
    if observed is None:
        raise SystemExit("--observed must be a timezone-aware ISO timestamp")
    report = evaluate(
        provenance,
        target_checkpoint=args.target_checkpoint,
        canonical_sha=args.canonical_sha,
        observed=observed,
    )
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report["reusable"] else 1)


if __name__ == "__main__":
    main()
