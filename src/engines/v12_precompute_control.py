from __future__ import annotations

"""D-P2 report precompute control.

This controller owns no factual acquisition, scheduler slot, model, or
publication. It validates an owner-requested future visible report occurrence,
waits conceptually for the Revision-6 T-15 window, and hands the unchanged
occurrence identity to the existing governed V6 report-prefetch transport.
"""

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import math
from pathlib import Path
import shlex
from typing import Any
from zoneinfo import ZoneInfo

from .v12_dp2_p6_handoff import occurrence_id
from .v12_delivery_schedule import (
    deadline_checkpoints,
    is_price_checkpoint,
    load_delivery_schedule,
    precompute_window,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "delivery" / "v12_precompute_control.json"


class PrecomputeControlError(ValueError):
    pass


@dataclass(frozen=True)
class PrecomputePlan:
    report_kind: str
    logical_slot: str
    reason: str
    release_at: str
    freeze_target_at: str
    wait_seconds: int
    dispatch_mode: str
    dispatch_reason: str
    dispatch_workflow: str
    warm_worker_workflow: str
    occurrence_id: str
    counts_as_core_slot: bool
    advances_scheduler_proof: bool


def load_precompute_control(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("authority") != "FPL_V12_D_P2_PRECOMPUTE_CONTROL":
        raise PrecomputeControlError("unsupported D-P2 precompute authority")
    if payload.get("role") != "REPORT_PRECOMPUTE_ONLY":
        raise PrecomputeControlError("D-P2 role must remain REPORT_PRECOMPUTE_ONLY")
    required_false = (
        "schedule_trigger_enabled",
        "may_complete_core_operational_slot",
        "may_advance_scheduler_proof",
        "may_edit_core_issue_title",
        "may_acquire_facts_directly",
        "may_publish_runtime_directly",
    )
    for key in required_false:
        if payload.get(key) is not False:
            raise PrecomputeControlError(f"D-P2 authority must be false: {key}")
    if payload.get("cancel_in_progress") is not False:
        raise PrecomputeControlError("D-P2 cancel_in_progress must remain false")
    if payload.get("preserve_report_occurrence_identity") is not True:
        raise PrecomputeControlError("D-P2 must preserve report occurrence identity")
    if payload.get("warm_worker_downstream_only") is not True:
        raise PrecomputeControlError("P6 warm worker must remain downstream-only")
    if payload.get("warm_worker_may_advance_scheduler_proof") is not False:
        raise PrecomputeControlError("P6 warm worker may not advance scheduler proof")
    if payload.get("warm_worker_may_edit_core_issue_title") is not False:
        raise PrecomputeControlError("P6 warm worker may not edit core issue title")
    if str(payload.get("warm_worker_workflow") or "") != "v12-p6-warm-worker.yml":
        raise PrecomputeControlError("unexpected P6 warm-worker workflow")
    return payload


def _aware_iso(value: str, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise PrecomputeControlError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PrecomputeControlError(f"{label} must be timezone-aware")
    return parsed


def _parse_command(command: str, *, expected: str) -> dict[str, str]:
    tokens = shlex.split(str(command or "").strip())
    if not tokens or tokens[0] != expected:
        raise PrecomputeControlError("D-P2 command marker mismatch")
    values: dict[str, str] = {}
    for token in tokens[1:]:
        if "=" not in token:
            raise PrecomputeControlError(f"malformed D-P2 token: {token}")
        key, value = token.split("=", 1)
        if not key or not value or key in values:
            raise PrecomputeControlError(f"invalid D-P2 token: {token}")
        values[key] = value
    allowed = {"report_kind", "logical_slot", "reason", "official_deadline"}
    unknown = set(values) - allowed
    if unknown:
        raise PrecomputeControlError(f"unsupported D-P2 arguments: {sorted(unknown)}")
    required = {"report_kind", "logical_slot", "reason"}
    missing = required - set(values)
    if missing:
        raise PrecomputeControlError(f"missing D-P2 arguments: {sorted(missing)}")
    if any(ch.isspace() for ch in values["reason"]):
        raise PrecomputeControlError("D-P2 reason must be one token")
    return values


def _validate_target(
    report_kind: str,
    target: datetime,
    *,
    official_deadline: datetime | None,
) -> None:
    schedule = load_delivery_schedule()
    if report_kind == "05:30_price":
        if not is_price_checkpoint(target, policy=schedule):
            raise PrecomputeControlError("PRICE target is not 23:30 Europe/London")
        return

    if report_kind == "full_master":
        local = target.astimezone(ZoneInfo("Asia/Jakarta"))
        fixed = set(schedule["fixed_deep_local_times"])
        if f"{local.hour:02d}:{local.minute:02d}" in fixed:
            return
        if official_deadline is not None:
            matches = [
                row
                for row in deadline_checkpoints(official_deadline, policy=schedule)
                if row.at == target and row.contract == "DEEP"
            ]
            if len(matches) == 1:
                return
        raise PrecomputeControlError("full_master target is not a governed DEEP occurrence")

    if report_kind == "deadline_review":
        if official_deadline is None:
            raise PrecomputeControlError("deadline_review requires official_deadline")
        matches = [
            row
            for row in deadline_checkpoints(official_deadline, policy=schedule)
            if row.at == target
        ]
        if len(matches) != 1:
            raise PrecomputeControlError("deadline target is not an exact governed checkpoint")
        return

    raise PrecomputeControlError(f"unsupported D-P2 report_kind={report_kind}")


def evaluate_precompute_request(
    command: str,
    *,
    now: datetime,
    config_path: Path = DEFAULT_CONFIG,
) -> PrecomputePlan:
    config = load_precompute_control(config_path)
    if now.tzinfo is None or now.utcoffset() is None:
        raise PrecomputeControlError("now must be timezone-aware")
    values = _parse_command(command, expected=str(config["trigger_command"]))
    report_kind = values["report_kind"]
    if report_kind not in set(config["allowed_report_kinds"]):
        raise PrecomputeControlError(f"report_kind not allowed for D-P2: {report_kind}")

    target = _aware_iso(values["logical_slot"], label="logical_slot")
    official_deadline = (
        _aware_iso(values["official_deadline"], label="official_deadline")
        if values.get("official_deadline")
        else None
    )
    _validate_target(report_kind, target, official_deadline=official_deadline)

    if target <= now:
        raise PrecomputeControlError("D-P2 cannot backfill or target a completed occurrence")
    horizon_seconds = (target - now).total_seconds()
    if horizon_seconds > int(config["max_horizon_minutes"]) * 60:
        raise PrecomputeControlError("D-P2 target is outside the bounded next-occurrence horizon")

    release_at, freeze_target_at = precompute_window(target)
    if now > freeze_target_at:
        raise PrecomputeControlError("D-P2 freeze-target window already missed")
    wait_seconds = max(0, math.ceil((release_at - now).total_seconds()))

    return PrecomputePlan(
        report_kind=report_kind,
        logical_slot=target.isoformat(),
        reason=values["reason"],
        release_at=release_at.isoformat(),
        freeze_target_at=freeze_target_at.isoformat(),
        wait_seconds=wait_seconds,
        dispatch_mode=str(config["dispatch_mode"]),
        dispatch_reason=str(config["dispatch_reason"]),
        dispatch_workflow=str(config["dispatch_workflow"]),
        warm_worker_workflow=str(config["warm_worker_workflow"]),
        occurrence_id=occurrence_id(
            report_kind=report_kind,
            logical_slot=target.isoformat(),
        ),
        counts_as_core_slot=False,
        advances_scheduler_proof=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="V12 D-P2 precompute controller")
    parser.add_argument("--command", required=True)
    parser.add_argument("--now")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--output")
    args = parser.parse_args()
    now = _aware_iso(args.now, label="now") if args.now else datetime.now().astimezone()
    plan = evaluate_precompute_request(
        args.command,
        now=now,
        config_path=Path(args.config),
    )
    payload = asdict(plan)
    rendered = json.dumps(payload, sort_keys=True)
    if args.output:
        Path(args.output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
