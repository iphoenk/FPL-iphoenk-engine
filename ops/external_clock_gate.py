"""Eligibility, kill switch and provenance for the independent external clock trigger.

The external scheduler is only a trigger: it dispatches the existing `fpl-github-clock.yml` with
`trigger_origin=EXTERNAL_INDEPENDENT_CLOCK`. Occurrence identity still comes from
`ops.render_external_clock.resolve_tick`; the pipeline (fallback, V6, orchestrator, verification) is
unchanged. This module decides, fail closed, whether such a trigger may proceed. It never dispatches.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Mapping, Sequence

ORIGIN_EXTERNAL = "EXTERNAL_INDEPENDENT_CLOCK"
ENABLE_VARIABLE = "FPL_EXTERNAL_CLOCK"
ORCHESTRATOR = "fpl-master-occurrence-orchestrator.yml"
ACTIVE = {"queued", "in_progress", "waiting", "pending", "requested"}


def enabled(environ: Mapping[str, str]) -> bool:
    return environ.get(ENABLE_VARIABLE, "") == "ENABLED"


def run_title(mode: str, slot: str) -> str:
    """Display title the orchestrator gives an EXTERNAL_CLOCK_FALLBACK occurrence run (its run-name)."""
    return f"FPL EXTERNAL_CLOCK_FALLBACK occurrence {mode} {slot}"


def decide(
    origin: str, tick: Mapping[str, str], runs: Sequence[Mapping[str, Any]] | None, environ: Mapping[str, str]
) -> dict[str, str]:
    """Non-external origins are untouched (PROCEED). External origin is bounded and idempotent."""
    if origin != ORIGIN_EXTERNAL:
        return {"action": "PROCEED", "reason": "NOT_EXTERNAL_ORIGIN_UNCHANGED"}
    if not enabled(environ):
        return {"action": "SKIP", "reason": "EXTERNAL_CLOCK_DISABLED"}
    mode, slot = str(tick.get("report_mode") or "NONE"), str(tick.get("report_slot") or "")
    if mode not in {"DEEP", "PRICE"} or not slot:
        return {"action": "SKIP", "reason": "NO_REPORT_DUE_IN_RESOLVER_WINDOW"}
    if runs is None:
        return {"action": "SKIP", "reason": "RUN_STATE_UNKNOWN_FAIL_CLOSED"}
    title = run_title(mode, slot)
    mine = [r for r in runs if r.get("displayTitle") == title]
    if any(str(r.get("status")) in ACTIVE for r in mine):
        return {"action": "SKIP", "reason": "OCCURRENCE_RUN_ACTIVE"}
    if any(r.get("status") == "completed" and r.get("conclusion") == "success" for r in mine):
        return {"action": "SKIP", "reason": "OCCURRENCE_ALREADY_SUCCEEDED"}
    if mine:
        return {"action": "SKIP", "reason": "PRIOR_ATTEMPT_FAILED_NO_AUTOMATIC_RETRY"}
    return {"action": "PROCEED", "reason": "ELIGIBLE"}


def announcement(tick: Mapping[str, str], *, external_trigger_id: str, actor: str) -> str:
    oid = f"{tick['report_mode']}|{tick['report_slot']}"
    return (
        f"FPL_EXTERNAL_CLOCK_TRIGGER | label={ORIGIN_EXTERNAL} | occurrence_id={oid} | "
        f"external_trigger_id={external_trigger_id or 'NONE'} | actor={actor or 'UNKNOWN'} | "
        "natural_proof=false | github_scheduled_natural=false"
    )


def _recent_runs(repo: str, run=subprocess.run) -> list[dict[str, Any]] | None:
    try:
        proc = run(
            ["gh", "run", "list", "--repo", repo, "--workflow", ORCHESTRATOR, "--limit", "100",
             "--json", "displayTitle,status,conclusion"],
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.SubprocessError:
        return None
    if proc.returncode:
        return None
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return None
    return data if isinstance(data, list) else None


def main(environ: Mapping[str, str] = os.environ, run=subprocess.run) -> int:
    origin = environ.get("TRIGGER_ORIGIN", "")
    tick = {"report_mode": environ.get("REPORT_MODE", ""), "report_slot": environ.get("REPORT_SLOT", "")}
    runs = _recent_runs(environ.get("GITHUB_REPOSITORY", ""), run) if origin == ORIGIN_EXTERNAL and enabled(environ) else []
    decision = decide(origin, tick, runs, environ)
    print(json.dumps(decision, sort_keys=True))
    out = environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"proceed={'true' if decision['action'] == 'PROCEED' else 'false'}\n")
            fh.write(f"reason={decision['reason']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
