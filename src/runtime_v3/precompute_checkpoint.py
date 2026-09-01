from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from src.engines import collector_gate
from src.runtime_v3.runtime_hydration_guard import verify_runtime_snapshot
from src.utils import DATA, read_json

MANIFEST_PATH = DATA / "runtime_manifest.json"
PRECOMPUTE_ROLE = "PRECOMPUTE_NEXT_CHECKPOINT"
LATE_PRECOMPUTE_ROLE = "LATE_PRECOMPUTE_RECOVERY"
PRIMARY_FALLBACK_ROLE = "PRIMARY_FALLBACK_CURRENT_CHECKPOINT"


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _append_outputs(values: dict[str, Any]) -> None:
    output = os.getenv("GITHUB_OUTPUT")
    if not output:
        return
    with open(output, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            if isinstance(value, bool):
                rendered = "true" if value else "false"
            elif value is None:
                rendered = ""
            else:
                rendered = str(value)
            handle.write(f"{key}={rendered}\n")


def _policy() -> dict[str, Any]:
    policy = collector_gate.load_policy()
    precompute = policy.get("precompute") or {}
    if precompute.get("enabled") is not True:
        raise RuntimeError("precompute checkpoint policy must be enabled")
    if int(precompute.get("lead_minutes") or 0) != 15:
        raise RuntimeError("precompute lead must remain exactly 15 minutes")
    if int(precompute.get("target_minute") or -1) != int(policy.get("visible_checkpoint_minute") or 30):
        raise RuntimeError("precompute target minute must match visible checkpoint minute")
    if precompute.get("internal_only_silent") is not True:
        raise RuntimeError("precompute checkpoint must remain internal-only/silent")
    return policy


def is_precompute_schedule(schedule_expr: str | None) -> bool:
    schedules = _policy().get("schedules") or {}
    return (schedule_expr or "").strip() == str(schedules.get("precompute") or "").strip()


def _local_tz():
    return collector_gate._local_tz()


def target_checkpoint_for_precompute(now_utc: datetime) -> datetime:
    """Resolve the logical :30 target for a physical :15 precompute."""
    local = now_utc.astimezone(timezone.utc).astimezone(_local_tz())
    target_minute = int(_policy().get("visible_checkpoint_minute") or 30)
    candidate = local.replace(minute=target_minute, second=0, microsecond=0)
    if local.minute >= 45:
        candidate += timedelta(hours=1)
    return candidate.astimezone(timezone.utc)


def current_logical_checkpoint(now_utc: datetime) -> datetime:
    """Resolve the most recent logical :30 checkpoint for a primary heartbeat."""
    local = now_utc.astimezone(timezone.utc).astimezone(_local_tz())
    target_minute = int(_policy().get("visible_checkpoint_minute") or 30)
    candidate = local.replace(minute=target_minute, second=0, microsecond=0)
    if local.minute < target_minute:
        candidate -= timedelta(hours=1)
    return candidate.astimezone(timezone.utc)


def _manifest_precompute_valid(
    manifest: dict[str, Any],
    *,
    target_utc: datetime,
    source_commit: str,
) -> bool:
    """Validate a published precompute for one exact logical checkpoint.

    Runtime-branch presence is publication proof. Freshness is derived from the
    immutable generated_at/target timestamps, never filesystem mtime or a
    self-asserted freshness boolean.
    """
    checkpoint = manifest.get("checkpoint") or {}
    generated_at = _parse_dt(manifest.get("generated_at"))
    target = _parse_dt(checkpoint.get("target_checkpoint"))
    target_utc = target_utc.astimezone(timezone.utc)
    if str(checkpoint.get("snapshot_role") or "") != PRECOMPUTE_ROLE:
        return False
    if target is None or target != target_utc:
        return False
    if generated_at is None or generated_at > target_utc:
        return False
    if checkpoint.get("materialization_complete") is False:
        return False
    if str(manifest.get("source_commit") or "") != str(source_commit or ""):
        return False
    return True


def _precompute_decision(now_utc: datetime) -> dict[str, Any]:
    target = target_checkpoint_for_precompute(now_utc)
    persisted = collector_gate.persisted_phase()
    deadline = persisted.get("deadline")
    scoring_gw = persisted.get("scoring_gw")

    direct = collector_gate.fetch_official_phase()
    if direct.get("fetched"):
        deadline = direct.get("deadline") or deadline
        scoring_gw = direct.get("scoring_gw") or scoring_gw

    match_window = collector_gate.fetch_match_window(now_utc, scoring_gw=scoring_gw)
    grace = int((collector_gate.load_policy().get("deadline_day") or {}).get("final_review_grace_minutes") or 15)
    decision = collector_gate.visible_report_decision(
        target,
        deadline,
        scoring_gw,
        fixtures=[],
        hourly_checkpoint=True,
        final_review_grace_minutes=grace,
    )
    if match_window and not collector_gate.deadline_intensive(target, deadline):
        decision["visible"] = True
        decision["primary_mode"] = "MATCH_MODE"
        decision["match_mode"] = True

    on_time = now_utc.astimezone(timezone.utc) < target
    return {
        "should_collect": True,
        "reason": "precompute_next_checkpoint" if on_time else "late_precompute_recovery",
        "deadline_intensive": collector_gate.deadline_intensive(target, deadline),
        "match_window": match_window,
        "deep_stats": decision.get("primary_mode") == "NORMAL_DEEP_REVIEW",
        "visible_report": False,
        "visible_mode": decision.get("primary_mode") or "SILENT",
        "post_deadline_reconciliation": decision.get("system_state") == "POST_DEADLINE_RECONCILIATION",
        "direct_official_phase_refresh": bool(direct.get("fetched")),
        "snapshot_role": PRECOMPUTE_ROLE if on_time else LATE_PRECOMPUTE_ROLE,
        "target_checkpoint_utc": target.isoformat(),
        "target_checkpoint_local": target.astimezone(_local_tz()).isoformat(),
        "target_visible_report": bool(decision.get("visible")),
        "target_visible_mode": decision.get("primary_mode") or "SILENT",
    }


def main() -> int:
    hydration_assurance = verify_runtime_snapshot()
    print(json.dumps({"runtime_hydration_assurance": hydration_assurance}, ensure_ascii=False))

    event = os.getenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    schedule_expr = os.getenv("FPL_SCHEDULE_EXPR", "")
    source_commit = os.getenv("SOURCE_COMMIT", os.getenv("GITHUB_SHA", ""))
    now = datetime.now(timezone.utc)

    if event == "schedule" and is_precompute_schedule(schedule_expr):
        result = _precompute_decision(now)
        _append_outputs(result)
        print(json.dumps(result, ensure_ascii=False))
        return 0

    if event == "schedule" and collector_gate.is_primary_schedule(schedule_expr):
        target = current_logical_checkpoint(now)
        manifest = read_json(MANIFEST_PATH, {})
        if _manifest_precompute_valid(manifest, target_utc=target, source_commit=source_commit):
            result = {
                "should_collect": False,
                "reason": "targeted_precompute_ready",
                "deadline_intensive": False,
                "match_window": False,
                "deep_stats": False,
                "visible_report": False,
                "visible_mode": "SILENT",
                "post_deadline_reconciliation": False,
                "direct_official_phase_refresh": False,
                "snapshot_role": "PRIMARY_HEARTBEAT_NOOP",
                "target_checkpoint_utc": target.isoformat(),
                "target_checkpoint_local": target.astimezone(_local_tz()).isoformat(),
                "target_visible_report": False,
                "target_visible_mode": "SILENT",
            }
            _append_outputs(result)
            print(json.dumps(result, ensure_ascii=False))
            return 0

        rc = collector_gate.main()
        _append_outputs({
            "snapshot_role": PRIMARY_FALLBACK_ROLE,
            "target_checkpoint_utc": target.isoformat(),
            "target_checkpoint_local": target.astimezone(_local_tz()).isoformat(),
        })
        return rc

    rc = collector_gate.main()
    _append_outputs({"snapshot_role": "ADAPTIVE_OR_MANUAL_REFRESH"})
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
