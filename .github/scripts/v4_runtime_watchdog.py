#!/usr/bin/env python3
"""Evaluate V4 runtime publication freshness without running the engine."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "config" / "runtime" / "v4_operational_policy.json"


def _load_policy(path: Path = POLICY_PATH) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "timezone",
        "master_checkpoint_minute",
        "fresh_max_minutes",
        "stale_after_minutes",
        "max_reported_misses",
        "runtime_branch",
        "canonical_ref",
        "production_concurrency_group",
    }
    missing = sorted(required - raw.keys())
    if missing:
        raise RuntimeError(f"V4 operational policy missing keys: {', '.join(missing)}")
    fresh = float(raw["fresh_max_minutes"])
    stale = float(raw["stale_after_minutes"])
    minute = int(raw["master_checkpoint_minute"])
    misses = int(raw["max_reported_misses"])
    if not 0 <= minute <= 59:
        raise RuntimeError("master_checkpoint_minute must be in 0..59")
    if fresh <= 0 or stale <= fresh:
        raise RuntimeError("stale_after_minutes must be greater than fresh_max_minutes > 0")
    if misses <= 0:
        raise RuntimeError("max_reported_misses must be positive")
    return raw


POLICY = _load_policy()
WIB = ZoneInfo(str(POLICY["timezone"]))
FRESH_MAX_MINUTES = float(POLICY["fresh_max_minutes"])
STALE_AFTER_MINUTES = float(POLICY["stale_after_minutes"])
MASTER_CHECKPOINT_MINUTE = int(POLICY["master_checkpoint_minute"])
MAX_REPORTED_MISSES = int(POLICY["max_reported_misses"])


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


def _latest_expected_checkpoint(now: datetime) -> datetime:
    local = now.astimezone(WIB)
    target = local.replace(minute=MASTER_CHECKPOINT_MINUTE, second=0, microsecond=0)
    if local < target:
        target -= timedelta(hours=1)
    return target


def _missed_checkpoints(published_at: datetime | None, now: datetime) -> list[datetime]:
    if published_at is None:
        return []
    local_publish = published_at.astimezone(WIB)
    candidate = local_publish.replace(minute=MASTER_CHECKPOINT_MINUTE, second=0, microsecond=0)
    if candidate <= local_publish:
        candidate += timedelta(hours=1)
    expected = _latest_expected_checkpoint(now)
    missed: list[datetime] = []
    while candidate <= expected and len(missed) < MAX_REPORTED_MISSES:
        missed.append(candidate)
        candidate += timedelta(hours=1)
    return missed


def evaluate(
    latest: dict,
    *,
    now: datetime,
    canonical_ref: str,
    canonical_sha: str,
    runtime_branch: str,
) -> dict:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    published_at = _parse_timestamp(latest.get("runtime_publish_at"))
    reason = "AGE_WITHIN_CONTRACT"
    age_minutes: float | None = None

    if published_at is None:
        state = "STALE"
        reason = "RUNTIME_PUBLISH_TIMESTAMP_MISSING_OR_INVALID"
    else:
        raw_age = (now - published_at).total_seconds() / 60.0
        if raw_age < -5.0:
            state = "STALE"
            reason = "RUNTIME_PUBLISH_TIMESTAMP_IN_FUTURE"
        else:
            age_minutes = round(max(0.0, raw_age), 2)
            if age_minutes <= FRESH_MAX_MINUTES:
                state = "FRESH"
            elif age_minutes <= STALE_AFTER_MINUTES:
                state = "DEGRADED"
            else:
                state = "STALE"
                reason = "MAX_SNAPSHOT_AGE_EXCEEDED"

    missed = _missed_checkpoints(published_at, now)
    expected = _latest_expected_checkpoint(now)
    return {
        "schema_version": 1,
        "policy_id": POLICY.get("policy_id"),
        "timezone_authority": str(POLICY["timezone"]),
        "schedule_target": expected.isoformat(),
        "execution_observed": now.astimezone(WIB).isoformat(),
        "runtime_branch": runtime_branch,
        "runtime_publish_at": published_at.isoformat() if published_at else None,
        "age_minutes": age_minutes,
        "freshness_state": state,
        "fresh_max_minutes": FRESH_MAX_MINUTES,
        "stale_after_minutes": STALE_AFTER_MINUTES,
        "recovery_required": state == "STALE",
        "reason": reason,
        "missed_checkpoint_count": len(missed),
        "missed_checkpoint_targets": [item.isoformat() for item in missed],
        "canonical_v4_ref": canonical_ref,
        "canonical_v4_sha": canonical_sha,
        "visibility_policy_unchanged": True,
        "recovery_is_evaluation_only": True,
    }


def _write_github_output(path: Path, report: dict) -> None:
    values = {
        "recovery_required": str(report["recovery_required"]).lower(),
        "freshness_state": report["freshness_state"],
        "age_minutes": "" if report["age_minutes"] is None else report["age_minutes"],
        "missed_checkpoint_count": report["missed_checkpoint_count"],
        "canonical_sha": report["canonical_v4_sha"],
    }
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def _write_github_summary(path: Path, report: dict) -> None:
    misses = ", ".join(report["missed_checkpoint_targets"]) or "none"
    lines = [
        "### V4 runtime freshness watchdog",
        f"- POLICY_ID={report['policy_id']}",
        f"- SCHEDULE_TARGET={report['schedule_target']}",
        f"- EXECUTION_OBSERVED={report['execution_observed']}",
        f"- RUNTIME_PUBLISH_AT={report['runtime_publish_at']}",
        f"- AGE_MINUTES={report['age_minutes']}",
        f"- FRESHNESS_STATE={report['freshness_state']}",
        f"- RECOVERY_REQUIRED={str(report['recovery_required']).lower()}",
        f"- MISSED_CHECKPOINTS={misses}",
        f"- CANONICAL_V4_SHA={report['canonical_v4_sha']}",
    ]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--latest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--github-summary", type=Path)
    parser.add_argument("--canonical-ref", default=str(POLICY["canonical_ref"]))
    parser.add_argument("--canonical-sha", required=True)
    parser.add_argument("--runtime-branch", default=str(POLICY["runtime_branch"]))
    parser.add_argument("--now", help="ISO timestamp override for deterministic verification")
    args = parser.parse_args()

    try:
        latest = json.loads(args.latest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        latest = {}
    now = _parse_timestamp(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        raise SystemExit("--now must be a timezone-aware ISO timestamp")
    report = evaluate(
        latest,
        now=now,
        canonical_ref=args.canonical_ref,
        canonical_sha=args.canonical_sha,
        runtime_branch=args.runtime_branch,
    )
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.github_output:
        _write_github_output(args.github_output, report)
    if args.github_summary:
        _write_github_summary(args.github_summary, report)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
