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
CI_DEPLOYMENT_ROLE = "CI_DEPLOYMENT_EXHAUSTIVE_REFRESH"
PRECOMPUTE_EXECUTION_MODE = "EXHAUSTIVE_PRECOMPUTE"
LEGACY_RUNTIME_WORKFLOW = "V3 Runtime"
SHARDED_PRECOMPUTE_WORKFLOW = "V3 Package Precompute"


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
    recovery = policy.get("checkpoint_recovery") or {}
    if recovery.get("enabled") is not True:
        raise RuntimeError("checkpoint recovery policy must be enabled")
    if int(recovery.get("wake_interval_minutes") or 0) != 5:
        raise RuntimeError("checkpoint recovery wake interval must remain exactly 5 minutes")
    if recovery.get("never_create_second_checkpoint_authority") is not True:
        raise RuntimeError("checkpoint recovery may not create a second checkpoint authority")
    return policy


def is_precompute_schedule(schedule_expr: str | None) -> bool:
    schedules = _policy().get("schedules") or {}
    return (schedule_expr or "").strip() == str(schedules.get("precompute") or "").strip()


def _local_tz():
    return collector_gate._local_tz()


def target_checkpoint_for_precompute(now_utc: datetime) -> datetime:
    local = now_utc.astimezone(timezone.utc).astimezone(_local_tz())
    target_minute = int(_policy().get("visible_checkpoint_minute") or 30)
    candidate = local.replace(minute=target_minute, second=0, microsecond=0)
    if local.minute >= 45:
        candidate += timedelta(hours=1)
    return candidate.astimezone(timezone.utc)


def current_logical_checkpoint(now_utc: datetime) -> datetime:
    local = now_utc.astimezone(timezone.utc).astimezone(_local_tz())
    target_minute = int(_policy().get("visible_checkpoint_minute") or 30)
    candidate = local.replace(minute=target_minute, second=0, microsecond=0)
    if local.minute < target_minute:
        candidate -= timedelta(hours=1)
    return candidate.astimezone(timezone.utc)


def _manifest_precompute_valid(manifest: dict[str, Any], *, target_utc: datetime, source_commit: str) -> bool:
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
    if checkpoint.get("materialization_complete") is not True:
        return False
    if str(manifest.get("source_commit") or "") != str(source_commit or ""):
        return False
    return True


def _manifest_satisfies_checkpoint(manifest: dict[str, Any], *, target_utc: datetime, source_commit: str) -> bool:
    target_utc = target_utc.astimezone(timezone.utc)
    checkpoint = manifest.get("checkpoint") or {}
    if checkpoint.get("materialization_complete") is not True:
        return False
    if str(manifest.get("source_commit") or "") != str(source_commit or ""):
        return False
    if _manifest_precompute_valid(manifest, target_utc=target_utc, source_commit=source_commit):
        return True
    generated_at = _parse_dt(manifest.get("generated_at"))
    return generated_at is not None and generated_at >= target_utc


def _adaptive_recovery_target(now_utc: datetime) -> tuple[str | None, datetime | None]:
    local = now_utc.astimezone(timezone.utc).astimezone(_local_tz())
    target_minute = int(_policy().get("visible_checkpoint_minute") or 30)
    lead_minutes = int((_policy().get("precompute") or {}).get("lead_minutes") or 15)
    precompute_minute = target_minute - lead_minutes
    if precompute_minute < local.minute < target_minute:
        target = local.replace(minute=target_minute, second=0, microsecond=0)
        return "PRECOMPUTE", target.astimezone(timezone.utc)
    if local.minute > target_minute or local.minute < precompute_minute:
        return "CURRENT", current_logical_checkpoint(now_utc)
    return None, None


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
    decision = collector_gate.visible_report_decision(target, deadline, scoring_gw, fixtures=[], hourly_checkpoint=True, final_review_grace_minutes=grace)
    if match_window and not collector_gate.deadline_intensive(target, deadline):
        decision["visible"] = True
        decision["primary_mode"] = "MATCH_MODE"
        decision["match_mode"] = True
    on_time = now_utc.astimezone(timezone.utc) < target
    return {
        "should_collect": True,
        "reason": "precompute_next_checkpoint" if on_time else "late_precompute_recovery",
        "deadline_intensive": False,
        "match_window": False,
        "deep_stats": False,
        "visible_report": False,
        "visible_mode": PRECOMPUTE_EXECUTION_MODE,
        "post_deadline_reconciliation": False,
        "direct_official_phase_refresh": bool(direct.get("fetched")),
        "snapshot_role": PRECOMPUTE_ROLE if on_time else LATE_PRECOMPUTE_ROLE,
        "target_checkpoint_utc": target.isoformat(),
        "target_checkpoint_local": target.astimezone(_local_tz()).isoformat(),
        "target_visible_report": bool(decision.get("visible")),
        "target_visible_mode": decision.get("primary_mode") or "SILENT",
        "target_deadline_intensive": collector_gate.deadline_intensive(target, deadline),
        "target_match_window": match_window,
        "target_post_deadline_reconciliation": decision.get("system_state") == "POST_DEADLINE_RECONCILIATION",
    }


def _ci_deployment_decision(now_utc: datetime) -> dict[str, Any]:
    """Publish exhaustive truth after green main CI without becoming checkpoint authority."""
    result = _precompute_decision(now_utc)
    result.update({
        "reason": "post_ci_exhaustive_deployment_refresh",
        "snapshot_role": CI_DEPLOYMENT_ROLE,
        "visible_report": False,
    })
    return result


def _checkpoint_recovery_decision(now_utc: datetime, target: datetime) -> dict[str, Any]:
    target = target.astimezone(timezone.utc)
    persisted = collector_gate.persisted_phase()
    deadline = persisted.get("deadline")
    scoring_gw = persisted.get("scoring_gw")
    direct = collector_gate.fetch_official_phase()
    if direct.get("fetched"):
        deadline = direct.get("deadline") or deadline
        scoring_gw = direct.get("scoring_gw") or scoring_gw
    match_window = collector_gate.fetch_match_window(now_utc, scoring_gw=scoring_gw)
    grace = int((collector_gate.load_policy().get("deadline_day") or {}).get("final_review_grace_minutes") or 15)
    decision = collector_gate.visible_report_decision(target, deadline, scoring_gw, fixtures=[], hourly_checkpoint=True, final_review_grace_minutes=grace)
    if match_window and not collector_gate.deadline_intensive(target, deadline):
        decision["visible"] = True
        decision["primary_mode"] = "MATCH_MODE"
        decision["match_mode"] = True
        if "MATCH_MODE" not in decision["included_modes"]:
            decision["included_modes"].insert(0, "MATCH_MODE")
    return {
        "should_collect": True,
        "reason": "adaptive_missing_checkpoint_recovery",
        "deadline_intensive": collector_gate.deadline_intensive(target, deadline),
        "match_window": match_window,
        "deep_stats": decision.get("primary_mode") == "NORMAL_DEEP_REVIEW",
        "visible_report": bool(decision.get("visible")),
        "visible_mode": decision.get("primary_mode") or "SILENT",
        "post_deadline_reconciliation": decision.get("system_state") == "POST_DEADLINE_RECONCILIATION",
        "direct_official_phase_refresh": bool(direct.get("fetched")),
        "snapshot_role": PRIMARY_FALLBACK_ROLE,
        "target_checkpoint_utc": target.isoformat(),
        "target_checkpoint_local": target.astimezone(_local_tz()).isoformat(),
        "target_visible_report": bool(decision.get("visible")),
        "target_visible_mode": decision.get("primary_mode") or "SILENT",
    }


def _sharded_current_recovery_decision(now_utc: datetime, target: datetime) -> dict[str, Any]:
    """Convert a missed current checkpoint into one late exhaustive shard recovery."""
    base = _checkpoint_recovery_decision(now_utc, target)
    return {
        **base,
        "reason": "adaptive_missing_current_checkpoint_sharded_exhaustive_recovery",
        "deadline_intensive": False,
        "match_window": False,
        "deep_stats": False,
        "visible_report": False,
        "visible_mode": PRECOMPUTE_EXECUTION_MODE,
        "post_deadline_reconciliation": False,
        "snapshot_role": LATE_PRECOMPUTE_ROLE,
        "target_deadline_intensive": bool(base.get("deadline_intensive")),
        "target_match_window": bool(base.get("match_window")),
        "target_post_deadline_reconciliation": bool(base.get("post_deadline_reconciliation")),
        "target_visible_report": bool(base.get("visible_report")),
        "target_visible_mode": base.get("visible_mode") or "SILENT",
    }


def _delegated_result(reason: str) -> dict[str, Any]:
    return {
        "should_collect": False,
        "reason": reason,
        "deadline_intensive": False,
        "match_window": False,
        "deep_stats": False,
        "visible_report": False,
        "visible_mode": "SILENT",
        "post_deadline_reconciliation": False,
        "direct_official_phase_refresh": False,
        "snapshot_role": "SHARDED_PRECOMPUTE_DELEGATED",
        "target_checkpoint_utc": "",
        "target_checkpoint_local": "",
        "target_visible_report": False,
        "target_visible_mode": "SILENT",
    }


def main() -> int:
    hydration_assurance = verify_runtime_snapshot()
    print(json.dumps({"runtime_hydration_assurance": hydration_assurance}, ensure_ascii=False))
    event = os.getenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    workflow = os.getenv("GITHUB_WORKFLOW", "")
    schedule_expr = os.getenv("FPL_SCHEDULE_EXPR", "")
    source_commit = os.getenv("SOURCE_COMMIT", os.getenv("GITHUB_SHA", ""))
    now = datetime.now(timezone.utc)

    if workflow == LEGACY_RUNTIME_WORKFLOW and event == "workflow_run":
        result = _delegated_result("ci_exhaustive_refresh_delegated_to_sharded_precompute_workflow")
        _append_outputs(result)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if workflow == LEGACY_RUNTIME_WORKFLOW and event == "schedule" and is_precompute_schedule(schedule_expr):
        result = _delegated_result("scheduled_exhaustive_precompute_delegated_to_sharded_workflow")
        _append_outputs(result)
        print(json.dumps(result, ensure_ascii=False))
        return 0

    if event == "workflow_run":
        result = _ci_deployment_decision(now)
        _append_outputs(result)
        print(json.dumps(result, ensure_ascii=False))
        return 0
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
        _append_outputs({"snapshot_role": PRIMARY_FALLBACK_ROLE, "target_checkpoint_utc": target.isoformat(), "target_checkpoint_local": target.astimezone(_local_tz()).isoformat()})
        return rc
    if event == "schedule" and collector_gate.is_adaptive_schedule(schedule_expr):
        manifest = read_json(MANIFEST_PATH, {})
        recovery_kind, target = _adaptive_recovery_target(now)
        if recovery_kind == "PRECOMPUTE" and target is not None:
            if not _manifest_precompute_valid(manifest, target_utc=target, source_commit=source_commit):
                if workflow == LEGACY_RUNTIME_WORKFLOW:
                    result = _delegated_result("adaptive_missing_precompute_delegated_to_sharded_workflow")
                    result["target_checkpoint_utc"] = target.isoformat()
                    result["target_checkpoint_local"] = target.astimezone(_local_tz()).isoformat()
                else:
                    result = _precompute_decision(now)
                    result["reason"] = "adaptive_missing_precompute_recovery"
                _append_outputs(result)
                print(json.dumps(result, ensure_ascii=False))
                return 0
        elif recovery_kind == "CURRENT" and target is not None:
            if not _manifest_satisfies_checkpoint(manifest, target_utc=target, source_commit=source_commit):
                if workflow == LEGACY_RUNTIME_WORKFLOW:
                    result = _delegated_result("adaptive_missing_current_checkpoint_delegated_to_sharded_workflow")
                    result["target_checkpoint_utc"] = target.isoformat()
                    result["target_checkpoint_local"] = target.astimezone(_local_tz()).isoformat()
                elif workflow == SHARDED_PRECOMPUTE_WORKFLOW:
                    result = _sharded_current_recovery_decision(now, target)
                else:
                    result = _checkpoint_recovery_decision(now, target)
                _append_outputs(result)
                print(json.dumps(result, ensure_ascii=False))
                return 0
    rc = collector_gate.main()
    _append_outputs({"snapshot_role": "ADAPTIVE_OR_MANUAL_REFRESH"})
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
