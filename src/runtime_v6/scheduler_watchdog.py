from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .temporal import age_seconds, classify_incident, try_parse_timestamp

DEFAULT_WARNING_MINUTES = 90.0
DEFAULT_CRITICAL_MINUTES = 135.0


def _parse_dt(value: Any) -> datetime | None:
    return try_parse_timestamp(
        value,
        naive_timezone=timezone.utc,
        target_timezone=timezone.utc,
    )


def classify_scheduler_watchdog(
    runtime_control: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
    warning_minutes: float = DEFAULT_WARNING_MINUTES,
    critical_minutes: float = DEFAULT_CRITICAL_MINUTES,
) -> dict[str, Any]:
    """Classify scheduler continuity without becoming a scheduling authority.

    The watchdog only reads the latest authoritative ChatGPT scheduler proof. It never
    triggers acquisition, advances scheduler proof, publishes runtime data, or converts
    report-prefetch/manual-recovery evidence into a successful core slot.
    """
    control = dict(runtime_control or {})
    now_utc = try_parse_timestamp(
        now or datetime.now(timezone.utc),
        naive_timezone=timezone.utc,
        target_timezone=timezone.utc,
    )
    assert now_utc is not None

    proof_at = _parse_dt(
        control.get("expected_cycle_at")
        or control.get("last_chatgpt_scheduler_cycle_at")
        or control.get("last_processed_logical_slot")
    )
    proof_is_authoritative = (
        str(control.get("schedule_kind") or "").lower() == "chatgpt_scheduler"
        and control.get("chatgpt_scheduler_proof") is True
        and control.get("authoritative_runtime_snapshot") is True
    )

    if proof_at is None:
        return {
            "state": "CRITICAL",
            "reason_code": "SCHEDULER_PROOF_MISSING",
            "proof_age_minutes": None,
            "proof_at": None,
            "proof_is_authoritative": False,
            "watchdog_is_authority": False,
            "may_trigger_acquisition": False,
            "may_publish_runtime": False,
        }

    age_minutes = age_seconds(now=now_utc, earlier=proof_at) / 60.0

    if not proof_is_authoritative:
        state = "CRITICAL"
        reason = "AUTHORITATIVE_CHATGPT_PROOF_MISSING"
    else:
        incident = classify_incident(
            age_minutes=age_minutes,
            warning_after_minutes=warning_minutes,
            critical_after_minutes=critical_minutes,
        ).state
        if incident == "CRITICAL":
            state = "CRITICAL"
            reason = "SCHEDULER_PROOF_CRITICAL_AGE"
        elif incident == "WARNING":
            state = "WARNING"
            reason = "SCHEDULER_PROOF_WARNING_AGE"
        else:
            state = "HEALTHY"
            reason = "SCHEDULER_PROOF_FRESH"

    return {
        "state": state,
        "reason_code": reason,
        "proof_age_minutes": round(age_minutes, 3),
        "proof_at": proof_at.isoformat(),
        "proof_is_authoritative": proof_is_authoritative,
        "watchdog_is_authority": False,
        "may_trigger_acquisition": False,
        "may_publish_runtime": False,
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description="Classify V6 scheduler continuity")
    parser.add_argument("--runtime-control", required=True)
    parser.add_argument("--output")
    parser.add_argument("--now")
    parser.add_argument("--warning-minutes", type=float, default=DEFAULT_WARNING_MINUTES)
    parser.add_argument("--critical-minutes", type=float, default=DEFAULT_CRITICAL_MINUTES)
    args = parser.parse_args()

    payload = json.loads(Path(args.runtime_control).read_text(encoding="utf-8"))
    now = _parse_dt(args.now) if args.now else None
    result = classify_scheduler_watchdog(
        payload,
        now=now,
        warning_minutes=args.warning_minutes,
        critical_minutes=args.critical_minutes,
    )
    rendered = json.dumps(result, sort_keys=True)
    print(rendered)
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
