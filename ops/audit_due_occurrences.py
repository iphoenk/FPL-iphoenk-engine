"""Read-only collector and CLI for the missed-slot audit.

Collects independent evidence for each due DEEP/PRICE occurrence:

* private repository readback of the exact occurrence directory, assembled the
  same way the occurrence orchestrator does and judged by the canonical
  ``classify_occurrence`` terminality verifier (workflow success is ignored);
* orchestrator run state (queued/in-progress/terminal-failed) for the exact
  occurrence, taken from the run title.

It never dispatches, comments, publishes or back-fills, and it always exits 0
so an audit fault can never stop the existing GitHub clock. Evidence-source
failures are reported as UNKNOWN for the affected occurrences.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from ops.occurrence_reconciliation import (
    build_audit_record,
    classify_due_occurrences,
    occurrence_id,
)
from src.engines.v12_occurrence_terminality import classify_occurrence

PRIVATE_REPO = "iphoenk/fpl-reports-private"
ORCHESTRATOR = "fpl-master-occurrence-orchestrator.yml"
_RUN_TITLE = re.compile(r"^FPL \S+ occurrence (DEEP|PRICE|MATCH) (\S+)$")
_ACTIVE_STATUSES = {"queued", "in_progress", "waiting", "requested", "pending"}
_FAILED_CONCLUSIONS = {"failure", "cancelled", "timed_out", "startup_failure"}
_SERVING = {"DEEP": "deep.json", "PRICE": "price.json", "MATCH": "match.json"}


class NotFound(Exception):
    """The private path does not exist (definitive absence)."""


class ReadError(Exception):
    """The evidence source could not be read (not evidence of absence)."""


class Reader(Protocol):
    def read_bytes(self, path: str) -> bytes: ...
    def list_dir(self, path: str) -> list[str]: ...


def slot_token(slot: str) -> str:
    return (
        slot.replace(":", "").replace("+", "_plus_").replace("-", "").replace("T", "_")
    )


def season_for(slot: str) -> str:
    dt = datetime.fromisoformat(slot)
    start = dt.year if dt.month >= 7 else dt.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def _json(reader: Reader, path: str) -> dict[str, Any]:
    try:
        value = json.loads(reader.read_bytes(path).decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ReadError(f"INVALID_JSON:{path}") from exc
    if not isinstance(value, dict):
        raise ReadError(f"INVALID_JSON_OBJECT:{path}")
    return value


def find_history_dir(reader: Reader, slot: str, *, max_gw_dirs: int = 4) -> str:
    season = season_for(slot)
    base = f"reports/{season}"
    gws = sorted(
        (n for n in reader.list_dir(base) if re.fullmatch(r"gw_\d+", n)),
        key=lambda n: int(n.split("_", 1)[1]),
        reverse=True,
    )[:max_gw_dirs]
    token = slot_token(slot)
    for gw in gws:
        if token in reader.list_dir(f"{base}/{gw}"):
            return f"{base}/{gw}/{token}"
    raise NotFound(f"{base}/*/{token}")


def build_evidence(
    reader: Reader, mode: str, slot: str
) -> dict[str, Any]:
    """Assemble the orchestrator's evidence dict from an exact history dir."""
    oid = occurrence_id(mode, slot)
    history = find_history_dir(reader, slot)
    body_name = "serving_report.md" if mode == "DEEP" else "report_body.md"
    serving = _json(reader, f"{history}/digest.json")
    receipt = _json(reader, f"{history}/delivery_receipt.json")
    stage3 = _json(reader, f"{history}/stage3_acceptance.json")
    body = reader.read_bytes(f"{history}/{body_name}")
    body_sha = hashlib.sha256(body).hexdigest()
    expected_sha = str(serving.get("canonical_body_sha256") or "")
    stage3_status = str(stage3.get("status") or "").strip().upper()

    latest_mode = _json(reader, f"latest/{_SERVING[mode]}")
    latest_slot = str(latest_mode.get("report_slot") or "")
    latest_same = (
        latest_mode.get("report_mode") == mode
        and latest_slot == slot
        and latest_mode.get("occurrence_id") == oid
    )
    if mode == "DEEP":
        latest_sha = hashlib.sha256(reader.read_bytes("latest/report.md")).hexdigest()
    else:
        latest_sha = str(latest_mode.get("canonical_body_sha256") or "")
    # The pointer may legitimately have moved on to a later occurrence of the
    # same mode; a pointer that is OLDER than this slot is stale and rejected.
    later = bool(latest_slot) and latest_mode.get("report_mode") == mode and (
        datetime.fromisoformat(latest_slot) > datetime.fromisoformat(slot)
    )
    if latest_same:
        advanced, latest_body_sha = latest_sha == body_sha, latest_sha
    elif later:
        advanced, latest_body_sha = True, expected_sha  # superseded, not stale
    else:
        advanced, latest_body_sha = False, latest_sha

    if mode == "DEEP":
        try:
            delivery = _json(reader, f"{history}/delivery_status.json")
        except NotFound:
            delivery = {}
        delivery_status = str(delivery.get("delivery_status") or "").strip().upper()
        root_failure = str(delivery.get("root_failure") or "").strip().upper()
    else:
        root_failure = str(serving.get("root_failure") or "").strip().upper()
        delivery_status = str(
            serving.get("delivery_status")
            or (
                "READY_FULL"
                if str(serving.get("runner_status") or "").upper() == "PASS"
                else "READY_DEGRADED"
            )
        ).strip().upper()
        delivery = {
            "occurrence_id": serving.get("occurrence_id"),
            "report_slot": serving.get("report_slot"),
            "report_mode": serving.get("report_mode"),
            "delivery_status": delivery_status,
            "root_failure": root_failure,
        }

    exact_publication = receipt.get("private_delivery_status") == "PASS" and (
        receipt.get("serving_snapshot_published") is True
        if mode == "DEEP"
        else (
            serving.get("report_mode") == mode
            and serving.get("report_slot") == slot
            and serving.get("occurrence_id") == oid
            and expected_sha == body_sha
        )
    )
    return {
        "report_mode": mode,
        "report_slot": slot,
        "occurrence_id": oid,
        "serving": {**serving, "canonical_body_sha256": expected_sha},
        "delivery": delivery,
        "historical": {
            "exists": bool(body),
            "path": f"{history}/{body_name}",
            "body_size": len(body),
            "body_sha256": body_sha,
            "receipt_body_sha256": str(receipt.get("canonical_body_sha256") or ""),
            "digest_body_sha256": str(serving.get("canonical_body_sha256") or ""),
            "receipt_report_slot": str(receipt.get("report_slot") or ""),
            "receipt_report_mode": str(receipt.get("report_mode") or ""),
        },
        "latest": {
            "exists": bool(latest_mode),
            "advanced": advanced,
            "body_sha256": latest_body_sha,
        },
        "private_delivery_status": receipt.get("private_delivery_status"),
        "exact_publication": exact_publication,
        "stage3": {
            "validation": stage3_status,
            "action": serving.get("stage3_action") or "WAIT",
            "engineering_closure_blocks_report": stage3.get(
                "engineering_closure_blocks_report"
            )
            is True,
        },
        "degradation": {
            "governed": delivery_status
            in {"READY_DEGRADED", "READY_DEGRADED_PUBLIC_FIRST"}
            and root_failure
            in {
                "ANALYTICS_INCOMPLETE",
                "BLOCKED_UPSTREAM",
                "PREFETCH_NOT_TERMINAL",
                "SOURCE_EVIDENCE_INCOMPLETE",
                "PUBLIC_FIRST_PERSONAL_UNAVAILABLE",
            }
            and stage3.get("engineering_closure_blocks_report") is not True,
            "attributable": bool(root_failure),
            "reason": root_failure,
        },
        "personal_authority_violation": receipt.get("personal_authority_violation")
        is True,
        "privacy_violation": receipt.get("privacy_validation_status") != "PASS",
        "fabricated_evidence": receipt.get("fabricated_evidence") is True,
        "mandatory_math_failure": stage3.get("mandatory_math_failure") is True
        or stage3.get("engineering_closure_blocks_report") is True,
    }


def verify_occurrence(reader: Reader, mode: str, slot: str) -> tuple[str, Any]:
    """Return ("VERIFIED"|"NOT_FOUND"|"ERROR", classify_occurrence result|reason)."""
    try:
        evidence = build_evidence(reader, mode, slot)
    except NotFound as exc:
        return "NOT_FOUND", str(exc)
    except ReadError as exc:
        return "ERROR", str(exc)
    return "VERIFIED", classify_occurrence(evidence)


def classify_runs(
    runs: Sequence[Mapping[str, Any]]
) -> tuple[set[str], set[str]]:
    """Split orchestrator runs into (active, terminal-failed) occurrence ids.

    A successful run is intentionally ignored: success is not publication
    evidence, only private readback is.
    """
    active: set[str] = set()
    failed: set[str] = set()
    for run in runs:
        match = _RUN_TITLE.match(str(run.get("display_title") or ""))
        if not match:
            continue
        oid = occurrence_id(match.group(1), match.group(2))
        if str(run.get("status") or "") in _ACTIVE_STATUSES:
            active.add(oid)
        elif str(run.get("conclusion") or "") in _FAILED_CONCLUSIONS:
            failed.add(oid)
    return active, failed


def audit(
    now: datetime,
    reader: Reader,
    runs: Callable[[], Sequence[Mapping[str, Any]]],
    lookback_hours: int = 36,
) -> dict[str, Any]:
    from ops.render_external_clock import due_report_occurrences

    due = due_report_occurrences(now, lookback_hours)
    verified: dict[str, Any] = {}
    unknown: dict[str, str] = {}
    for row in due:
        oid = occurrence_id(row["report_mode"], row["report_slot"])
        outcome, payload = verify_occurrence(reader, row["report_mode"], row["report_slot"])
        if outcome == "VERIFIED":
            verified[oid] = payload
        elif outcome == "ERROR":
            unknown[oid] = f"PRIVATE_READBACK:{payload}"
    active: set[str] = set()
    failed: set[str] = set()
    try:
        active, failed = classify_runs(runs())
    except ReadError as exc:
        for row in due:
            oid = occurrence_id(row["report_mode"], row["report_slot"])
            unknown.setdefault(oid, f"RUNS_API:{exc}")
    rows = classify_due_occurrences(
        now,
        verified=verified,
        active=active,
        failed=failed,
        unknown=unknown,
        lookback_hours=lookback_hours,
    )
    return build_audit_record(now, rows, lookback_hours)


class GhReader:
    """`gh api` backed private-repo reader; the token never reaches logs."""

    def __init__(self, token: str, repo: str = PRIVATE_REPO, run: Callable[..., Any] = subprocess.run):
        self._token, self._repo, self._run = token, repo, run

    def _gh(self, args: list[str]) -> str:
        proc = self._run(
            ["gh", "api", *args],
            env={**os.environ, "GH_TOKEN": self._token},
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode:
            err = (proc.stderr or "") + (proc.stdout or "")
            if "HTTP 404" in err:
                raise NotFound(args[0])
            lines = err.strip().splitlines()
            detail = lines[-1][:120] if lines else ""
            raise ReadError(f"GH_API_FAILED:{detail}" if detail else "GH_API_FAILED")
        return proc.stdout

    def read_bytes(self, path: str) -> bytes:
        out = self._gh([f"/repos/{self._repo}/contents/{path}?ref=main", "--jq", ".content"])
        return base64.b64decode("".join(out.split()))

    def list_dir(self, path: str) -> list[str]:
        out = self._gh([f"/repos/{self._repo}/contents/{path}?ref=main", "--jq", ".[].name"])
        return [line for line in out.splitlines() if line]


def gh_runs(repo: str, since: datetime, run: Callable[..., Any] = subprocess.run) -> list[dict[str, Any]]:
    created = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    proc = run(
        [
            "gh", "api", "--paginate",
            f"/repos/{repo}/actions/workflows/{ORCHESTRATOR}/runs?per_page=100&created=>={created}",
            "--jq", ".workflow_runs[] | {display_title, status, conclusion}",
        ],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode:
        raise ReadError("RUNS_API_FAILED")
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lookback-hours", type=int, default=36)
    parser.add_argument("--output", default="missed-slot-audit.json")
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    repo = os.environ.get("GITHUB_REPOSITORY", "iphoenk/FPL-iphoenk-engine")
    token = os.environ.get("FPL_PRIVATE_REPORTS_TOKEN", "")
    try:
        if not token:
            raise ReadError("PRIVATE_TOKEN_UNAVAILABLE")
        from datetime import timedelta

        record = audit(
            now,
            GhReader(token),
            lambda: gh_runs(repo, now - timedelta(hours=args.lookback_hours + 2)),
            args.lookback_hours,
        )
    except Exception as exc:  # audit must never break the clock
        from ops.render_external_clock import due_report_occurrences

        due = due_report_occurrences(now, args.lookback_hours)
        rows = [
            {
                "occurrence_id": occurrence_id(r["report_mode"], r["report_slot"]),
                "report_mode": r["report_mode"],
                "report_slot": r["report_slot"],
                "checkpoint_time": r["checkpoint_time"],
                "age_minutes": None,
                "state": "UNKNOWN",
                "reason": f"AUDIT_FAULT:{type(exc).__name__}",
            }
            for r in due
        ]
        record = build_audit_record(now, rows, args.lookback_hours)
    Path(args.output).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"event": "FPL_MISSED_SLOT_AUDIT", "counts": record["counts"], "all_due_verified": record["all_due_verified"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
