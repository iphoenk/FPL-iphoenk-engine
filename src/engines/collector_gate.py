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
    if not isinstance(payload.get("schedules"), dict):
        raise RuntimeError("collector policy schedules missing")
    return payload


def _local_tz() -> ZoneInfo:
    return ZoneInfo(str(load_policy().get("timezone") or "Asia/Jakarta"))


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def persisted_deadline(path=None) -> datetime | None:
    target = path or DATA / "latest.json"
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        return _parse_dt((payload.get("phase") or {}).get("deadline_time"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def deadline_intensive(now_utc: datetime, deadline_utc: datetime | None) -> bool:
    if deadline_utc is None:
        return False
    now_utc = now_utc.astimezone(timezone.utc)
    deadline_utc = deadline_utc.astimezone(timezone.utc)
    delta = deadline_utc - now_utc
    if delta.total_seconds() < 0:
        return False
    hours = float(load_policy().get("deadline_intensive_hours") or 0)
    if hours <= 0:
        raise RuntimeError("collector deadline_intensive_hours must be positive")
    tz = _local_tz()
    return delta <= timedelta(hours=hours) or now_utc.astimezone(tz).date() == deadline_utc.astimezone(tz).date()


def fixture_match_window(now_utc: datetime, fixtures: list[dict]) -> bool:
    now_utc = now_utc.astimezone(timezone.utc)
    cfg = load_policy().get("match_window") or {}
    before = timedelta(minutes=max(0, int(cfg.get("pre_kickoff_minutes") or 0)))
    after = timedelta(minutes=max(0, int(cfg.get("post_kickoff_minutes") or 0)))
    for fixture in fixtures or []:
        kickoff = _parse_dt(fixture.get("kickoff_time"))
        if kickoff is None or fixture.get("finished") is True:
            continue
        if kickoff - before <= now_utc <= kickoff + after:
            return True
    return False


def _fixture_url() -> str:
    cfg = load_policy().get("fixture_probe") or {}
    source_id = str(cfg.get("official_source_id") or "official_fpl")
    base = str(source_config(source_id).get("api_base") or "").rstrip("/")
    path = str(cfg.get("endpoint_path") or "").lstrip("/")
    if not base or not path:
        raise RuntimeError("collector fixture probe source or endpoint missing")
    return f"{base}/{path}"


def fetch_match_window(now_utc: datetime, timeout: int | None = None) -> bool:
    cfg = load_policy().get("fixture_probe") or {}
    request_timeout = int(timeout if timeout is not None else cfg.get("timeout_seconds") or 0)
    if request_timeout <= 0:
        raise RuntimeError("collector fixture probe timeout must be positive")
    try:
        req = Request(_fixture_url(), headers={"User-Agent": f"fpl-iphoenk-engine/{ENGINE_VERSION}"})
        with urlopen(req, timeout=request_timeout) as response:
            fixtures = json.loads(response.read().decode("utf-8"))
        return fixture_match_window(now_utc, fixtures)
    except Exception:
        return False


def is_deep_stats_schedule(schedule_expr: str | None) -> bool:
    schedules = load_policy().get("schedules") or {}
    return (schedule_expr or "").strip() == str(schedules.get("deep_stats") or "").strip()


def _report_checkpoint_schedules() -> set[str]:
    schedules = load_policy().get("schedules") or {}
    return {
        str(value).strip()
        for key, value in schedules.items()
        if str(key).startswith("report_") and str(value).strip()
    }


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

    schedules = policy.get("schedules") or {}
    schedule_expr = (schedule_expr or "").strip()
    if schedule_expr == str(schedules.get("primary") or "").strip():
        return True, "hourly_primary"
    if schedule_expr == str(schedules.get("deep_stats") or "").strip():
        return True, "daily_deep_stats"
    if schedule_expr in _report_checkpoint_schedules():
        return True, "scheduled_report_checkpoint"
    if schedule_expr == str(schedules.get("adaptive") or "").strip():
        if deadline_intensive(now_utc, deadline_utc):
            return True, "adaptive_deadline_window"
        if match_window:
            return True, "adaptive_match_window"
        return False, "adaptive_slot_not_needed"
    return True, "unrecognized_schedule_fail_open"


def main() -> int:
    event = os.getenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    schedule_expr = os.getenv("FPL_SCHEDULE_EXPR", "")
    now = datetime.now(timezone.utc)
    deadline = persisted_deadline()
    adaptive = (load_policy().get("schedules") or {}).get("adaptive")
    match_window = fetch_match_window(now) if event == "schedule" and schedule_expr.strip() == str(adaptive or "").strip() else False
    collect, reason = should_collect(event, schedule_expr, now, deadline, match_window)
    deep_stats = event == "schedule" and is_deep_stats_schedule(schedule_expr)

    output = os.getenv("GITHUB_OUTPUT")
    lines = [
        f"should_collect={'true' if collect else 'false'}",
        f"reason={reason}",
        f"deadline_intensive={'true' if deadline_intensive(now, deadline) else 'false'}",
        f"match_window={'true' if match_window else 'false'}",
        f"deep_stats={'true' if deep_stats else 'false'}",
    ]
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    print(json.dumps({
        "collect": collect,
        "reason": reason,
        "deadline": deadline.isoformat() if deadline else None,
        "match_window": match_window,
        "deep_stats": deep_stats,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())