from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from src.sources.registry import source_config
from src.utils import DATA, ROOT
from src.version import ENGINE_VERSION

POLICY_PATH = ROOT / "config" / "runtime" / "collector_policy.json"


@lru_cache(maxsize=1)
def load_policy() -> dict:
    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    schedules = payload.get("schedules")
    if not isinstance(schedules, dict):
        raise RuntimeError("collector policy schedules missing")
    if str(payload.get("timezone") or "") != "Asia/Jakarta":
        raise RuntimeError("collector operational timezone must be Asia/Jakarta")
    if str(schedules.get("primary") or "").strip() != "30 * * * *":
        raise RuntimeError("collector primary schedule must evaluate every hour at :30")
    deadline_cfg = payload.get("deadline_day") or {}
    if float(deadline_cfg.get("window_hours") or 0) != 24:
        raise RuntimeError("deadline day window must be exactly 24 hours")
    match_cfg = payload.get("match_mode") or {}
    for key in ("current_scoring_gw_only", "requires_started_true", "requires_finished_false", "consolidated_report"):
        if match_cfg.get(key) is not True:
            raise RuntimeError(f"match mode policy missing {key}=true")
    return payload


def _local_tz() -> ZoneInfo:
    return ZoneInfo(str(load_policy().get("timezone") or "Asia/Jakarta"))


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def persisted_phase(path=None) -> dict:
    target = path or DATA / "latest.json"
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {
            "deadline": None,
            "scoring_gw": None,
            "generated_at": None,
            "is_live_event": False,
        }
    phase = payload.get("phase") or {}
    try:
        scoring_gw = int(phase.get("scoring_gw")) if phase.get("scoring_gw") is not None else None
    except (TypeError, ValueError):
        scoring_gw = None
    return {
        "deadline": _parse_dt(phase.get("deadline_time")),
        "scoring_gw": scoring_gw,
        "generated_at": _parse_dt(payload.get("generated_at")),
        "is_live_event": bool(phase.get("is_live_event")),
    }


def persisted_deadline(path=None) -> datetime | None:
    return persisted_phase(path).get("deadline")


def deadline_intensive(now_utc: datetime, deadline_utc: datetime | None) -> bool:
    if deadline_utc is None:
        return False
    now_utc = now_utc.astimezone(timezone.utc)
    deadline_utc = deadline_utc.astimezone(timezone.utc)
    delta = deadline_utc - now_utc
    if delta.total_seconds() < 0:
        return False
    hours = float((load_policy().get("deadline_day") or {}).get("window_hours") or 0)
    if hours <= 0:
        raise RuntimeError("collector deadline day window_hours must be positive")
    return delta <= timedelta(hours=hours)


def _fixture_event(fixture: dict) -> int | None:
    try:
        value = fixture.get("event")
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def fixture_match_window(
    now_utc: datetime,
    fixtures: list[dict],
    scoring_gw: int | None = None,
) -> bool:
    """Compatibility name: true only for an officially live current-scoring-GW PL fixture."""
    if scoring_gw is None:
        return False
    now_utc = now_utc.astimezone(timezone.utc)
    for fixture in fixtures or []:
        if _fixture_event(fixture) != int(scoring_gw):
            continue
        if fixture.get("started") is not True:
            continue
        if fixture.get("finished") is True:
            continue
        kickoff = _parse_dt(fixture.get("kickoff_time"))
        if kickoff is not None and kickoff > now_utc:
            continue
        return True
    return False


def _official_url(endpoint_path: str) -> str:
    source_id = str((load_policy().get("fixture_probe") or {}).get("official_source_id") or "official_fpl")
    base = str(source_config(source_id).get("api_base") or "").rstrip("/")
    path = str(endpoint_path or "").lstrip("/")
    if not base or not path:
        raise RuntimeError("collector Official source or endpoint missing")
    return f"{base}/{path}"


def _fixture_url() -> str:
    cfg = load_policy().get("fixture_probe") or {}
    return _official_url(str(cfg.get("endpoint_path") or ""))


def _phase_url() -> str:
    cfg = load_policy().get("official_phase_probe") or {}
    return _official_url(str(cfg.get("endpoint_path") or "bootstrap-static/"))


def fetch_match_window(
    now_utc: datetime,
    scoring_gw: int | None = None,
    timeout: int | None = None,
) -> bool:
    cfg = load_policy().get("fixture_probe") or {}
    request_timeout = int(timeout if timeout is not None else cfg.get("timeout_seconds") or 0)
    if request_timeout <= 0:
        raise RuntimeError("collector fixture probe timeout must be positive")
    try:
        req = Request(_fixture_url(), headers={"User-Agent": f"fpl-iphoenk-engine/{ENGINE_VERSION}"})
        with urlopen(req, timeout=request_timeout) as response:
            fixtures = json.loads(response.read().decode("utf-8"))
        return fixture_match_window(now_utc, fixtures, scoring_gw=scoring_gw)
    except Exception:
        return False


def fetch_official_phase(timeout: int | None = None) -> dict:
    cfg = load_policy().get("official_phase_probe") or {}
    request_timeout = int(timeout if timeout is not None else cfg.get("timeout_seconds") or 0)
    if request_timeout <= 0:
        raise RuntimeError("collector Official phase probe timeout must be positive")
    try:
        req = Request(_phase_url(), headers={"User-Agent": f"fpl-iphoenk-engine/{ENGINE_VERSION}"})
        with urlopen(req, timeout=request_timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        events = list(payload.get("events") or [])
        current = next((event for event in events if event.get("is_current") is True), None)
        nxt = next((event for event in events if event.get("is_next") is True), None)
        deadline_event = nxt or current
        scoring_gw = int(current.get("id")) if current and current.get("id") is not None else None
        return {
            "deadline": _parse_dt((deadline_event or {}).get("deadline_time")),
            "scoring_gw": scoring_gw,
            "fetched": True,
        }
    except Exception:
        return {"deadline": None, "scoring_gw": None, "fetched": False}


def direct_official_refresh_required(
    runtime_generated_at: datetime | None,
    now_utc: datetime,
    material_native_change: bool = False,
) -> bool:
    if material_native_change:
        return True
    if runtime_generated_at is None:
        return True
    age_minutes = max(
        0.0,
        (now_utc.astimezone(timezone.utc) - runtime_generated_at.astimezone(timezone.utc)).total_seconds() / 60.0,
    )
    max_age = float((load_policy().get("direct_official_refresh") or {}).get("max_runtime_age_minutes") or 30)
    return age_minutes > max_age


def final_review_at(deadline_utc: datetime | None) -> datetime | None:
    if deadline_utc is None:
        return None
    cfg = (load_policy().get("deadline_day") or {}).get("final_review") or {}
    local_deadline = deadline_utc.astimezone(_local_tz())
    overnight_hours = {int(hour) for hour in (cfg.get("overnight_deadline_hours") or [0, 1])}
    lead_minutes = (
        int(cfg.get("overnight_lead_minutes") or 180)
        if local_deadline.hour in overnight_hours
        else int(cfg.get("default_lead_minutes") or 90)
    )
    return deadline_utc.astimezone(timezone.utc) - timedelta(minutes=lead_minutes)


def final_review_due(now_utc: datetime, deadline_utc: datetime | None, grace_minutes: int = 0) -> bool:
    target = final_review_at(deadline_utc)
    if target is None:
        return False
    now_utc = now_utc.astimezone(timezone.utc)
    if grace_minutes <= 0:
        return now_utc.replace(second=0, microsecond=0) == target.replace(second=0, microsecond=0)
    return target <= now_utc < target + timedelta(minutes=grace_minutes)


def normal_report_mode(now_utc: datetime, hourly_checkpoint: bool | None = None) -> str | None:
    policy = load_policy()
    if hourly_checkpoint is None:
        hourly_checkpoint = now_utc.astimezone(_local_tz()).minute == int(
            policy.get("visible_checkpoint_minute") or 30
        )
    if not hourly_checkpoint:
        return None
    local = now_utc.astimezone(_local_tz())
    hhmm = local.strftime("%H:%M")
    normal = policy.get("normal_reports") or {}
    for key, mode in (
        ("deep_review", "NORMAL_DEEP_REVIEW"),
        ("midday_tactical", "NORMAL_MIDDAY"),
        ("night_tactical_price", "NORMAL_NIGHT"),
    ):
        if str(normal.get(key) or "") == hhmm:
            return mode
    if hourly_checkpoint:
        for key, mode in (
            ("deep_review", "NORMAL_DEEP_REVIEW"),
            ("midday_tactical", "NORMAL_MIDDAY"),
            ("night_tactical_price", "NORMAL_NIGHT"),
        ):
            target = str(normal.get(key) or "")
            if target and int(target.split(":", 1)[0]) == local.hour:
                return mode
    return None


def visible_report_decision(
    now_utc: datetime,
    deadline_utc: datetime | None,
    scoring_gw: int | None,
    fixtures: list[dict] | None = None,
    *,
    hourly_checkpoint: bool | None = None,
    final_review_grace_minutes: int = 0,
    critical_price_alert: bool = False,
    permitted_emergency: bool = False,
) -> dict:
    now_utc = now_utc.astimezone(timezone.utc)
    if hourly_checkpoint is None:
        hourly_checkpoint = now_utc.astimezone(_local_tz()).minute == int(
            load_policy().get("visible_checkpoint_minute") or 30
        )

    normal_mode = normal_report_mode(now_utc, hourly_checkpoint=hourly_checkpoint)
    live_current_gw = fixture_match_window(now_utc, fixtures or [], scoring_gw=scoring_gw)
    in_deadline_day = deadline_intensive(now_utc, deadline_utc)
    is_final = in_deadline_day and final_review_due(
        now_utc, deadline_utc, grace_minutes=final_review_grace_minutes
    )

    included: list[str] = []
    if normal_mode:
        included.append(normal_mode)
    if live_current_gw:
        included.append("MATCH_MODE")

    if is_final:
        primary = "DEADLINE_DAY_FINAL_REVIEW"
    elif in_deadline_day and hourly_checkpoint:
        primary = "DEADLINE_DAY"
    elif live_current_gw and hourly_checkpoint:
        primary = "MATCH_MODE"
    elif normal_mode:
        primary = normal_mode
    elif critical_price_alert:
        primary = "CRITICAL_PRICE_ALERT"
    elif permitted_emergency:
        primary = "PERMITTED_EMERGENCY"
    else:
        primary = None

    if primary:
        included = [primary] + [mode for mode in included if mode != primary]

    deadline_passed = bool(deadline_utc and now_utc > deadline_utc.astimezone(timezone.utc))
    at_deadline = bool(
        deadline_utc
        and now_utc.replace(second=0, microsecond=0)
        == deadline_utc.astimezone(timezone.utc).replace(second=0, microsecond=0)
    )
    return {
        "visible": primary is not None,
        "primary_mode": primary,
        "included_modes": included,
        "deadline_day": in_deadline_day,
        "final_review": is_final,
        "match_mode": live_current_gw,
        "normal_mode": normal_mode,
        "deadline_passed": deadline_passed,
        "transition_after_emit": "POST_DEADLINE_RECONCILIATION" if at_deadline else None,
        "system_state": "POST_DEADLINE_RECONCILIATION" if deadline_passed else "ACTIVE",
    }


def is_deep_stats_schedule(schedule_expr: str | None) -> bool:
    schedules = load_policy().get("schedules") or {}
    return (schedule_expr or "").strip() == str(schedules.get("deep_stats") or "").strip()


def is_primary_schedule(schedule_expr: str | None) -> bool:
    schedules = load_policy().get("schedules") or {}
    return (schedule_expr or "").strip() == str(schedules.get("primary") or "").strip()


def is_adaptive_schedule(schedule_expr: str | None) -> bool:
    schedules = load_policy().get("schedules") or {}
    return (schedule_expr or "").strip() == str(schedules.get("adaptive") or "").strip()


def should_collect(
    event_name: str,
    schedule_expr: str | None,
    now_utc: datetime,
    deadline_utc: datetime | None,
    match_window: bool,
) -> tuple[bool, str]:
    policy = load_policy()
    event_policy = policy.get("event_policy") or {}
    event_action = str(event_policy.get(event_name) or event_policy.get("unknown") or "COLLECT")
    if event_action == "TEST_ONLY":
        return False, "pull_request_test_only"
    if event_action == "COLLECT" and event_name != "schedule":
        return True, f"{event_name}_always"

    if event_name != "schedule":
        return True, "unknown_event_fail_open"

    schedule_expr = (schedule_expr or "").strip()
    if is_primary_schedule(schedule_expr):
        return True, "hourly_primary"
    if is_deep_stats_schedule(schedule_expr):
        return True, "daily_deep_stats"
    if is_adaptive_schedule(schedule_expr):
        final_grace = int((policy.get("deadline_day") or {}).get("final_review_grace_minutes") or 15)
        if deadline_intensive(now_utc, deadline_utc) and final_review_due(
            now_utc, deadline_utc, grace_minutes=final_grace
        ):
            return True, "adaptive_final_review"
        if match_window:
            return True, "adaptive_live_refresh"
        return False, "adaptive_slot_not_needed"
    return True, "unrecognized_schedule_fail_open"


def main() -> int:
    event = os.getenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    schedule_expr = os.getenv("FPL_SCHEDULE_EXPR", "")
    now = datetime.now(timezone.utc)

    persisted = persisted_phase()
    deadline = persisted.get("deadline")
    scoring_gw = persisted.get("scoring_gw")

    scheduled_governance_probe = event == "schedule" and (
        is_primary_schedule(schedule_expr) or is_adaptive_schedule(schedule_expr)
    )
    refresh_phase = scheduled_governance_probe and (
        direct_official_refresh_required(persisted.get("generated_at"), now)
        or deadline_intensive(now, deadline)
    )
    direct_phase = fetch_official_phase() if refresh_phase else {"fetched": False}
    if direct_phase.get("fetched"):
        direct_deadline = direct_phase.get("deadline")
        preserve_just_passed_deadline = bool(
            deadline
            and deadline <= now
            and now - deadline < timedelta(minutes=30)
        )
        if direct_deadline and not preserve_just_passed_deadline:
            deadline = direct_deadline
        scoring_gw = direct_phase.get("scoring_gw") or scoring_gw

    probe_match = scheduled_governance_probe
    match_window = fetch_match_window(now, scoring_gw=scoring_gw) if probe_match else False
    collect, reason = should_collect(event, schedule_expr, now, deadline, match_window)
    deep_stats = event == "schedule" and is_deep_stats_schedule(schedule_expr)

    final_grace = int((load_policy().get("deadline_day") or {}).get("final_review_grace_minutes") or 15)
    decision = visible_report_decision(
        now,
        deadline,
        scoring_gw,
        fixtures=[],
        hourly_checkpoint=(event == "schedule" and is_primary_schedule(schedule_expr)),
        final_review_grace_minutes=final_grace if event == "schedule" else 0,
    )
    if match_window:
        decision["match_mode"] = True
        if event == "schedule" and is_primary_schedule(schedule_expr) and not deadline_intensive(now, deadline):
            decision["visible"] = True
            decision["primary_mode"] = "MATCH_MODE"
            decision["included_modes"] = ["MATCH_MODE"] + [
                mode for mode in decision["included_modes"] if mode != "MATCH_MODE"
            ]
        elif "MATCH_MODE" not in decision["included_modes"]:
            decision["included_modes"].append("MATCH_MODE")

    if deadline_intensive(now, deadline):
        if final_review_due(now, deadline, grace_minutes=final_grace):
            decision["visible"] = True
            decision["primary_mode"] = "DEADLINE_DAY_FINAL_REVIEW"
            if "DEADLINE_DAY_FINAL_REVIEW" not in decision["included_modes"]:
                decision["included_modes"].insert(0, "DEADLINE_DAY_FINAL_REVIEW")
        elif event == "schedule" and is_primary_schedule(schedule_expr):
            decision["visible"] = True
            decision["primary_mode"] = "DEADLINE_DAY"
            if "DEADLINE_DAY" not in decision["included_modes"]:
                decision["included_modes"].insert(0, "DEADLINE_DAY")

    output = os.getenv("GITHUB_OUTPUT")
    lines = [
        f"should_collect={'true' if collect else 'false'}",
        f"reason={reason}",
        f"deadline_intensive={'true' if deadline_intensive(now, deadline) else 'false'}",
        f"match_window={'true' if match_window else 'false'}",
        f"deep_stats={'true' if deep_stats else 'false'}",
        f"visible_report={'true' if decision['visible'] else 'false'}",
        f"visible_mode={decision['primary_mode'] or 'SILENT'}",
        f"post_deadline_reconciliation={'true' if decision['system_state'] == 'POST_DEADLINE_RECONCILIATION' else 'false'}",
        f"direct_official_phase_refresh={'true' if direct_phase.get('fetched') else 'false'}",
    ]
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    print(json.dumps({
        "collect": collect,
        "reason": reason,
        "deadline": deadline.isoformat() if deadline else None,
        "scoring_gw": scoring_gw,
        "match_window": match_window,
        "deep_stats": deep_stats,
        "visible_report": decision,
        "direct_official_phase_refresh": bool(direct_phase.get("fetched")),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
