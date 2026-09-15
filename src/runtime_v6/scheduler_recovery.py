from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

DEFAULT_COOLDOWN_MINUTES = 60.0
DEFAULT_SETTLE_MINUTES = 20.0
ACTIVE_RUN_STATUSES = {"queued", "in_progress", "waiting", "requested", "pending"}


def _parse_dt(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _run_time(run: Mapping[str, Any]) -> datetime | None:
    return _parse_dt(run.get("run_started_at") or run.get("created_at") or run.get("updated_at"))


def _is_recovery_dispatch(run: Mapping[str, Any]) -> bool:
    if str(run.get("event") or "") != "workflow_dispatch":
        return False

    display_title = str(run.get("display_title") or "").strip().lower()
    if display_title == "v6 report_prefetch" or display_title.startswith("v6 report_prefetch "):
        return False
    if display_title == "v6 manual_recovery" or display_title.startswith("v6 manual_recovery "):
        return True

    # Legacy/ambiguous run metadata remains fail-closed. GitHub's workflow-runs API
    # does not expose workflow_dispatch inputs, so only an explicit report-prefetch
    # identity may bypass the recovery cooldown.
    title = " ".join(
        str(run.get(key) or "")
        for key in ("display_title", "name", "run_name")
    ).lower()
    if "report_prefetch" in title or "report prefetch" in title:
        return False
    if "manual_recovery" in title or "manual recovery" in title or "wave2_safe_recovery_critical" in title:
        return True
    return True


def decide_safe_recovery(
    watchdog: Mapping[str, Any] | None,
    workflow_runs: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    cooldown_minutes: float = DEFAULT_COOLDOWN_MINUTES,
    settle_minutes: float = DEFAULT_SETTLE_MINUTES,
) -> dict[str, Any]:
    """Decide whether a recovery-only manual acquisition may be dispatched.

    This controller is deliberately not a scheduler-health authority. It can request one
    governed manual recovery only after the independent watchdog is CRITICAL and after
    duplicate/in-flight/cooldown guards pass. A recovery request never becomes a
    ChatGPT scheduler proof and never repairs Wave-3 natural-slot evidence.
    """
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    watch = dict(watchdog or {})
    runs = [dict(row) for row in workflow_runs]

    base = {
        "controller_role": "SAFE_RECOVERY_ONLY",
        "normal_scheduler_authority": "CHATGPT_FPL_MASTER_MONITOR",
        "recovery_mode": "manual_recovery",
        "recovery_is_scheduler_proof": False,
        "recovery_counts_as_natural_wave3_slot": False,
        "may_edit_fpl_master_slot_title": False,
        "may_publish_runtime_directly": False,
        "watchdog_state": str(watch.get("state") or "UNKNOWN"),
        "watchdog_reason_code": str(watch.get("reason_code") or "UNKNOWN"),
    }

    if watch.get("state") != "CRITICAL":
        return {**base, "should_recover": False, "decision": "NOOP", "reason_code": "WATCHDOG_NOT_CRITICAL"}

    active = [
        row for row in runs
        if str(row.get("status") or "").lower() in ACTIVE_RUN_STATUSES
    ]
    if active:
        return {
            **base,
            "should_recover": False,
            "decision": "NOOP",
            "reason_code": "INGESTION_ALREADY_ACTIVE",
            "blocking_run_ids": [str(row.get("id") or "") for row in active],
        }

    recent_recovery: list[tuple[datetime, dict[str, Any]]] = []
    recent_core: list[tuple[datetime, dict[str, Any]]] = []
    for row in runs:
        when = _run_time(row)
        if when is None:
            continue
        age_minutes = max(0.0, (current - when).total_seconds() / 60.0)
        event = str(row.get("event") or "")
        if _is_recovery_dispatch(row) and age_minutes < cooldown_minutes:
            recent_recovery.append((when, row))
        if event in {"issues", "issue_comment"} and age_minutes < settle_minutes:
            recent_core.append((when, row))

    if recent_core:
        recent_core.sort(key=lambda item: item[0], reverse=True)
        return {
            **base,
            "should_recover": False,
            "decision": "NOOP",
            "reason_code": "RECENT_GOVERNED_CORE_EVENT_SETTLING",
            "blocking_run_id": str(recent_core[0][1].get("id") or ""),
        }

    if recent_recovery:
        recent_recovery.sort(key=lambda item: item[0], reverse=True)
        return {
            **base,
            "should_recover": False,
            "decision": "NOOP",
            "reason_code": "RECOVERY_COOLDOWN_ACTIVE",
            "blocking_run_id": str(recent_recovery[0][1].get("id") or ""),
        }

    return {
        **base,
        "should_recover": True,
        "decision": "DISPATCH_MANUAL_RECOVERY",
        "reason_code": "CRITICAL_WITH_NO_ACTIVE_OR_RECENT_RECOVERY",
    }


def _load_runs(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("workflow_runs") if isinstance(payload, dict) else payload
    return [dict(row) for row in (rows or [])]


def main() -> int:
    parser = argparse.ArgumentParser(description="Decide fail-closed V6 safe recovery")
    parser.add_argument("--watchdog", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--now")
    args = parser.parse_args()

    watchdog = json.loads(args.watchdog.read_text(encoding="utf-8"))
    runs = _load_runs(args.runs)
    config: dict[str, Any] = {}
    if args.config:
        config = json.loads(args.config.read_text(encoding="utf-8"))
    now = _parse_dt(args.now) if args.now else None
    result = decide_safe_recovery(
        watchdog,
        runs,
        now=now,
        cooldown_minutes=float(config.get("recovery_cooldown_minutes", DEFAULT_COOLDOWN_MINUTES)),
        settle_minutes=float(config.get("governed_event_settle_minutes", DEFAULT_SETTLE_MINUTES)),
    )
    rendered = json.dumps(result, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
