from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

WIB = ZoneInfo("Asia/Jakarta")
LONDON = ZoneInfo("Europe/London")
DEFAULT_REPO = "iphoenk/FPL-iphoenk-engine"
WORKFLOW = "fpl-external-clock-fallback.yml"


def resolve_tick(now: datetime) -> dict[str, str]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    observed_utc = now.astimezone(timezone.utc)
    observed_wib = observed_utc.astimezone(WIB)
    logical = observed_wib.replace(minute=0, second=0, microsecond=0)

    candidates: list[tuple[str, datetime]] = []
    for day_offset in (-1, 0, 1):
        day = (observed_wib + timedelta(days=day_offset)).date()
        for hour, minute in ((4, 30), (12, 30), (21, 30)):
            candidates.append(
                (
                    "DEEP",
                    datetime(
                        day.year,
                        day.month,
                        day.day,
                        hour,
                        minute,
                        tzinfo=WIB,
                    ),
                )
            )

    observed_london = observed_utc.astimezone(LONDON)
    for day_offset in (-1, 0, 1):
        day = (observed_london + timedelta(days=day_offset)).date()
        london_slot = datetime(
            day.year,
            day.month,
            day.day,
            23,
            30,
            tzinfo=LONDON,
        )
        candidates.append(("PRICE", london_slot.astimezone(WIB)))

    eligible: list[tuple[float, str, datetime]] = []
    for mode, slot in candidates:
        delta = observed_wib - slot
        if timedelta(minutes=-5) <= delta <= timedelta(minutes=60):
            eligible.append((abs(delta.total_seconds()), mode, slot))

    report_mode = "NONE"
    report_slot = ""
    checkpoint_time = ""
    if eligible:
        _, report_mode, slot = min(eligible, key=lambda row: row[0])
        report_slot = slot.isoformat()
        checkpoint_time = slot.strftime("%H:%M")

    return {
        "logical_slot": logical.isoformat(),
        "observed_at": observed_wib.isoformat(),
        "report_mode": report_mode,
        "report_slot": report_slot,
        "checkpoint_time": checkpoint_time,
    }


def dispatch(inputs: dict[str, str]) -> None:
    token = str(os.getenv("FPL_GITHUB_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("FPL_GITHUB_TOKEN is required")

    repo = str(os.getenv("FPL_GITHUB_REPO") or DEFAULT_REPO).strip()
    url = (
        f"https://api.github.com/repos/{repo}/actions/workflows/"
        f"{WORKFLOW}/dispatches"
    )
    payload = json.dumps({"ref": "main", "inputs": inputs}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "fpl-render-external-clock",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status != 204:
                raise RuntimeError(
                    f"unexpected GitHub workflow-dispatch status: {response.status}"
                )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub workflow dispatch failed: HTTP {exc.code}: {detail}"
        ) from exc


def main() -> int:
    inputs = resolve_tick(datetime.now(timezone.utc))
    print(json.dumps({"event": "external_clock_tick", **inputs}, sort_keys=True))
    dispatch(inputs)
    print(
        json.dumps(
            {
                "event": "external_clock_dispatch_accepted",
                "workflow": WORKFLOW,
                "logical_slot": inputs["logical_slot"],
                "report_mode": inputs["report_mode"],
                "report_slot": inputs["report_slot"] or None,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
