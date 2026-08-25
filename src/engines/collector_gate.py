from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

WIB = timezone(timedelta(hours=7))
FPL_FIXTURES = "https://fantasy.premierleague.com/api/fixtures/"
DATA = Path(__file__).resolve().parents[2] / "data"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def persisted_deadline(path: Path | None = None) -> datetime | None:
    p = path or DATA / "latest.json"
    try:
        payload = json.loads(p.read_text())
        return _parse_dt((payload.get("phase") or {}).get("deadline_time"))
    except Exception:
        return None


def deadline_intensive(now_utc: datetime, deadline_utc: datetime | None) -> bool:
    if deadline_utc is None:
        return False
    now_utc = now_utc.astimezone(timezone.utc)
    deadline_utc = deadline_utc.astimezone(timezone.utc)
    delta = deadline_utc - now_utc
    if delta.total_seconds() < 0:
        return False
    # Covers local deadline day and the preceding evening for late-midnight deadlines.
    return delta <= timedelta(hours=24) or now_utc.astimezone(WIB).date() == deadline_utc.astimezone(WIB).date()


def fixture_match_window(now_utc: datetime, fixtures: list[dict]) -> bool:
    now_utc = now_utc.astimezone(timezone.utc)
    for f in fixtures or []:
        kickoff = _parse_dt(f.get("kickoff_time"))
        if kickoff is None:
            continue
        if f.get("finished") is True:
            continue
        # Treat 15 min pre-kickoff through 3h15 after kickoff as active/relevant match window.
        if kickoff - timedelta(minutes=15) <= now_utc <= kickoff + timedelta(hours=3, minutes=15):
            return True
    return False


def fetch_match_window(now_utc: datetime, timeout: int = 8) -> bool:
    try:
        req = Request(FPL_FIXTURES, headers={"User-Agent": "fpl-iphoenk-engine/3.5.1"})
        with urlopen(req, timeout=timeout) as resp:
            fixtures = json.loads(resp.read().decode("utf-8"))
        return fixture_match_window(now_utc, fixtures)
    except Exception:
        # Fail-soft here: the hourly primary collector still runs regardless.
        return False


def should_collect(
    event_name: str,
    schedule_expr: str | None,
    now_utc: datetime,
    deadline_utc: datetime | None,
    match_window: bool,
) -> tuple[bool, str]:
    if event_name in {"push", "workflow_dispatch"}:
        return True, f"{event_name}_always"
    if event_name == "pull_request":
        return False, "pull_request_test_only"
    if event_name != "schedule":
        return True, "unknown_event_fail_open"

    schedule_expr = (schedule_expr or "").strip()
    if schedule_expr.startswith("55 "):
        return True, "hourly_primary"
    if schedule_expr.startswith("15 "):
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
    match_window = fetch_match_window(now) if event == "schedule" and schedule_expr.startswith("15 ") else False
    collect, reason = should_collect(event, schedule_expr, now, deadline, match_window)

    output = os.getenv("GITHUB_OUTPUT")
    lines = [
        f"should_collect={'true' if collect else 'false'}",
        f"reason={reason}",
        f"deadline_intensive={'true' if deadline_intensive(now, deadline) else 'false'}",
        f"match_window={'true' if match_window else 'false'}",
    ]
    if output:
        with open(output, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    print(json.dumps({"collect": collect, "reason": reason, "deadline": deadline.isoformat() if deadline else None, "match_window": match_window}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
