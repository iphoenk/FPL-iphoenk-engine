"""Governed future-only recovery dispatch: PREPARED AND DISABLED.

Active only when the repository variable FPL_RECOVERY_DISPATCH is exactly
"ENABLED" (set by the owner after separate approval). While disabled the entry
point performs no network call at all. When enabled it:

  * dispatches at most ONE occurrence per run, taken from the advisory
    recovery plan (ops.recovery_plan): MISSING + platform-gap diagnosis,
    overdue within the bound, next slot not yet due, no FAILED run for the mode;
  * is idempotent: any orchestrator run already titled for the exact occurrence
    (active, successful OR failed) blocks it, so a failed run is never retried;
  * announces the dispatch on issue #431 as RECOVERY (natural_proof=false)
    BEFORE dispatching, and only then runs the existing orchestrator with the
    existing EXTERNAL_CLOCK_FALLBACK authority;
  * never backfills (older slots are HISTORICAL in the plan) and creates no
    scheduler. Verification stays with the orchestrator, `latest/verified.json`
    and the missed-slot audit.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any, Callable, Mapping, Sequence

from ops.recovery_plan import ELIGIBLE

ENABLE_VARIABLE = "FPL_RECOVERY_DISPATCH"
ENABLED_VALUE = "ENABLED"
ORCHESTRATOR = "fpl-master-occurrence-orchestrator.yml"
AUTHORITY = "EXTERNAL_CLOCK_FALLBACK"  # existing choice; recovery is labelled in #431, not by a new authority


def enabled(environ: Mapping[str, str]) -> bool:
    return environ.get(ENABLE_VARIABLE, "") == ENABLED_VALUE


def run_title(candidate: Mapping[str, Any]) -> str:
    return f"FPL {AUTHORITY} occurrence {candidate['report_mode']} {candidate['report_slot']}"


def select(plan: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The single newest ELIGIBLE candidate, re-validated; never more than one."""
    rows = [
        d for d in plan.get("eligible", [])
        if d.get("decision") == ELIGIBLE
        and d.get("label") == "RECOVERY"
        and str(d.get("idempotency_key")) == f"RECOVERY|{d.get('occurrence_id')}"
        and d.get("natural_acceptance_eligible") is False
    ]
    if plan.get("dispatch_enabled") is not False and rows:
        # The plan itself must be the advisory artifact produced by the audit.
        return None
    return sorted(rows, key=lambda d: str(d["report_slot"]))[-1] if rows else None


def already_attempted(runs: Sequence[Mapping[str, Any]], candidate: Mapping[str, Any]) -> bool:
    title = run_title(candidate)
    return any(str(r.get("displayTitle") or r.get("display_title") or "") == title for r in runs)


def evidence_comment(candidate: Mapping[str, Any], overdue_minutes: Any) -> str:
    return (
        "FPL_RECOVERY_DISPATCH | label=RECOVERY | "
        f"occurrence_id={candidate['occurrence_id']} | "
        f"idempotency_key={candidate['idempotency_key']} | "
        f"overdue_minutes={overdue_minutes} | natural_proof=false | natural_acceptance_eligible=false"
    )


def dispatch_argv(candidate: Mapping[str, Any], repo: str) -> list[str]:
    return [
        "gh", "workflow", "run", ORCHESTRATOR, "--repo", repo, "--ref", "main",
        "-f", f"report_mode={candidate['report_mode']}",
        "-f", f"report_slot={candidate['report_slot']}",
        "-f", f"checkpoint_time={str(candidate['report_slot'])[11:16]}",
        "-f", f"scheduler_authority={AUTHORITY}",
    ]


def execute(
    plan: Mapping[str, Any],
    runs: Sequence[Mapping[str, Any]],
    repo: str,
    run: Callable[..., Any] = subprocess.run,
    recheck: Callable[[], Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    candidate = select(plan)
    if candidate is None:
        return {"action": "NO_ELIGIBLE_CANDIDATE"}
    if already_attempted(runs, candidate):
        return {"action": "SKIPPED_ALREADY_ATTEMPTED", "occurrence_id": candidate["occurrence_id"]}
    try:
        comment = run(
            ["gh", "issue", "comment", "431", "--repo", repo, "--body", evidence_comment(candidate, candidate.get("overdue_minutes"))],
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.SubprocessError:
        return {"action": "NOT_DISPATCHED_EVIDENCE_COMMENT_FAILED", "occurrence_id": candidate["occurrence_id"]}
    if comment.returncode:
        return {"action": "NOT_DISPATCHED_EVIDENCE_COMMENT_FAILED", "occurrence_id": candidate["occurrence_id"]}
    # Re-check immediately before the write: narrows the check-then-act window
    # against the scheduled path (which also cannot select an overdue slot).
    if recheck is not None and already_attempted(recheck(), candidate):
        return {"action": "SKIPPED_ALREADY_ATTEMPTED_ON_RECHECK", "occurrence_id": candidate["occurrence_id"]}
    try:
        dispatched = run(dispatch_argv(candidate, repo), capture_output=True, text=True, timeout=60)
    except subprocess.SubprocessError:
        # Outcome unknown: never retry blindly; the next run sees any created run by title.
        return {"action": "DISPATCH_STATE_UNKNOWN", "occurrence_id": candidate["occurrence_id"]}
    if dispatched.returncode:
        return {"action": "DISPATCH_FAILED", "occurrence_id": candidate["occurrence_id"]}
    return {"action": "DISPATCHED_RECOVERY", "occurrence_id": candidate["occurrence_id"]}


def _recent_runs(repo: str, run: Callable[..., Any] = subprocess.run) -> list[dict[str, Any]]:
    try:
        proc = run(
        ["gh", "run", "list", "--repo", repo, "--workflow", ORCHESTRATOR, "--event", "workflow_dispatch",
         "--branch", "main", "--limit", "100", "--json", "displayTitle,status,conclusion"],
        capture_output=True, text=True, timeout=60,
        )
    except subprocess.SubprocessError as exc:
        raise RuntimeError("RUNS_LIST_TIMEOUT") from exc
    if proc.returncode:
        raise RuntimeError("RUNS_LIST_FAILED")
    return json.loads(proc.stdout or "[]")


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    env = os.environ if environ is None else environ
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", required=True)
    args = parser.parse_args(argv)
    if not enabled(env):
        print(json.dumps({"event": "FPL_RECOVERY_DISPATCH", "action": "DISABLED"}, sort_keys=True))
        return 0
    repo = env.get("GITHUB_REPOSITORY", "iphoenk/FPL-iphoenk-engine")
    try:
        plan = json.loads(open(args.audit, encoding="utf-8").read()).get("recovery_plan") or {}
        result = execute(plan, _recent_runs(repo), repo, recheck=lambda: _recent_runs(repo))
    except (OSError, ValueError, RuntimeError) as exc:
        result = {"action": "NOT_DISPATCHED_ERROR", "reason": type(exc).__name__}
    print(json.dumps({"event": "FPL_RECOVERY_DISPATCH", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
