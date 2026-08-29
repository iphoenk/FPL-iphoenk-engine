from __future__ import annotations

import argparse
import json
import os
from datetime import datetime

from src.engines.checkpoint_policy import resolve_checkpoint
from src.services.raw_snapshot_service import _parallel_official_get, detect_phase
from src.utils import parse_dt, utcnow


def _as_aware_datetime(value: str | datetime | None) -> datetime:
    if isinstance(value, str):
        parsed = parse_dt(value)
    elif isinstance(value, datetime):
        parsed = value
    else:
        parsed = utcnow()
    if parsed is None or parsed.tzinfo is None:
        raise RuntimeError("timing probe as_of must be timezone-aware")
    return parsed


def evaluate_timing_probe(bootstrap: dict, as_of: str | datetime | None = None) -> dict:
    """Resolve whether a :00 wake-up needs the full V4 engine.

    The probe deliberately uses only Official FPL bootstrap data. Acquisition remains
    owned by raw_snapshot_service; this module delegates both Official fetch and phase
    detection instead of becoming a second source owner. Ordinary :00 runs stay silent.
    A full run is authorized only for an exact Final Review, or for a post-deadline
    reconciliation transition less than 30 minutes old.
    """
    now = _as_aware_datetime(as_of)
    phase = detect_phase(bootstrap, fixtures=[], as_of=now)
    checkpoint = resolve_checkpoint(
        "daily",
        phase.get("deadline_time"),
        is_live=False,
        as_of=now,
        simulated=as_of is not None,
        post_deadline_reconciliation=bool(phase.get("post_deadline_reconciliation")),
    )

    current_deadline = parse_dt(phase.get("current_deadline_time"))
    reconciliation_age_minutes = None
    recent_reconciliation_transition = False
    if current_deadline is not None:
        reconciliation_age_minutes = (now - current_deadline).total_seconds() / 60.0
        recent_reconciliation_transition = bool(
            checkpoint.get("policy_id") == "POST_DEADLINE_RECONCILIATION"
            and 0 <= reconciliation_age_minutes < 30
        )

    final_review = checkpoint.get("policy_id") == "FINAL_DEADLINE_REVIEW"
    run_full_engine = bool(final_review or recent_reconciliation_transition)
    reason = (
        "FINAL_DEADLINE_REVIEW"
        if final_review
        else "POST_DEADLINE_RECONCILIATION_TRANSITION"
        if recent_reconciliation_transition
        else "SILENT_TIMING_PROBE"
    )
    return {
        "run_full_engine": run_full_engine,
        "reason": reason,
        "policy_id": checkpoint.get("policy_id"),
        "visible_output_authorized": bool(checkpoint.get("visible_output_authorized")),
        "final_review": final_review,
        "recent_reconciliation_transition": recent_reconciliation_transition,
        "reconciliation_age_minutes": (
            round(reconciliation_age_minutes, 1)
            if reconciliation_age_minutes is not None
            else None
        ),
        "planning_deadline_time": phase.get("deadline_time"),
        "current_deadline_time": phase.get("current_deadline_time"),
        "current_gw": phase.get("current_gw"),
        "planning_gw": phase.get("planning_gw"),
        "checkpoint_context": checkpoint,
    }


def run(as_of: str | None = None) -> dict:
    fetched = _parallel_official_get([("bootstrap", "bootstrap-static/", 1)])
    bootstrap, health = fetched.get("bootstrap") or (None, {})
    if not bootstrap:
        raise RuntimeError(f"Official FPL bootstrap unavailable for timing probe: {health}")
    result = evaluate_timing_probe(bootstrap, as_of=as_of)
    result["official_bootstrap_health"] = health
    print(json.dumps(result, ensure_ascii=False))

    github_output = os.getenv("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"run_full={'true' if result['run_full_engine'] else 'false'}\n")
            handle.write(f"policy_id={result['policy_id']}\n")
            handle.write(f"reason={result['reason']}\n")
    return result


def cli() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of")
    args = parser.parse_args()
    return run(args.as_of)


if __name__ == "__main__":
    cli()
