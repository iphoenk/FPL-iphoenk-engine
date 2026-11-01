"""Bounded public-only Official FPL LIVE kickoff gate for the existing clock.

NO scheduler, no workflow dispatch and no OIDC/token/private-repository access.
This is a kickoff transition detector, not a report scorer. Later verified
changes can still be surfaced by the existing ChatGPT HH:30 task.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from src.engines.v12_delivery_schedule import assess_verified_match_materiality

WIB = ZoneInfo("Asia/Jakarta")
BASE = "https://fantasy.premierleague.com/api"
OWNER = 3462711
MAX_BYTES = 2_000_000
PUBLIC_TIMEOUT_SECONDS = 6
FETCH = Callable[[str], Any]


def _official_json(path: str) -> Any:
    """Exact allowlisted public Official FPL GET. No auth material is loaded."""
    if path not in {"fixtures/", "bootstrap-static/"} and not (
        path.startswith(f"entry/{OWNER}/event/")
        and path.endswith("/picks/")
        and path.removeprefix(f"entry/{OWNER}/event/").removesuffix("/picks/").isdigit()
    ):
        raise ValueError("PUBLIC_ENDPOINT_NOT_ALLOWLISTED")
    request = Request(
        BASE + "/" + path, method="GET",
        headers={"Accept": "application/json", "User-Agent": "FPL-Github-Clock-Public-MATCH"},
    )
    with urlopen(request, timeout=PUBLIC_TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise ValueError("OFFICIAL_PUBLIC_HTTP_NOT_200")
        payload = response.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError("OFFICIAL_PUBLIC_PAYLOAD_TOO_LARGE")
    return json.loads(payload.decode("utf-8"))


def _aware(value: Any) -> datetime:
    instant = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("OFFICIAL_TIMESTAMP_NOT_AWARE")
    return instant


def _first_halfhour_at_or_after(kickoff: datetime) -> datetime:
    local = kickoff.astimezone(WIB)
    candidate = local.replace(minute=30, second=0, microsecond=0)
    if candidate < local:
        candidate += timedelta(hours=1)
    return candidate


def public_kickoff_match_candidate(
    observed_at: datetime,
    *,
    fetch: FETCH = _official_json,
) -> dict[str, str] | None:
    """Create one MATCH candidate at the FIRST HH:30 after a verified kickoff.

    The existing GitHub clock calls this only when its DEEP/PRICE selector is
    NONE. The first-checkpoint invariant prevents repeat every-hour MATCH
    dispatch for the same fixture, and all failures leave the core tick intact.
    """
    now = _aware(observed_at).astimezone(WIB)
    if now.minute < 25:
        return None
    fixtures = fetch("fixtures/")
    if not isinstance(fixtures, list):
        return None
    live = []
    for row in fixtures:
        if not isinstance(row, Mapping):
            continue
        if row.get("started") is not True or row.get("finished") is not False:
            continue
        if row.get("finished_provisional") is True:
            continue
        if any(type(row.get(k)) is not int or row[k] <= 0 for k in
               ("id", "event", "team_h", "team_a")):
            continue
        try:
            kickoff = _aware(row["kickoff_time"])
        except (KeyError, TypeError, ValueError):
            continue
        slot = _first_halfhour_at_or_after(kickoff)
        delta = now - slot
        if (kickoff <= now
            and timedelta(0) <= delta <= timedelta(minutes=60)
            and slot.hour == now.hour and slot.date() == now.date()):
            live.append((slot, row))
    if not live:
        return None
    bootstrap = fetch("bootstrap-static/")
    events = (bootstrap or {}).get("events") if isinstance(bootstrap, Mapping) else None
    elements = (bootstrap or {}).get("elements") if isinstance(bootstrap, Mapping) else None
    if not isinstance(events, list) or not isinstance(elements, list):
        return None
    event_by_id = {
        e["id"]: e for e in events
        if isinstance(e, Mapping) and type(e.get("id")) is int
    }
    teams = {
        p["id"]: p.get("team") for p in elements
        if isinstance(p, Mapping) and type(p.get("id")) is int
    }
    for slot, fixture in sorted(live, key=lambda pair: (pair[0], pair[1]["id"])):
        gw = fixture["event"]
        event = event_by_id.get(gw)
        if not event or event.get("is_current") is not True:
            continue
        try:
            if _aware(event["deadline_time"]) > now:
                continue
        except (KeyError, ValueError, TypeError):
            continue
        published = fetch(f"entry/{OWNER}/event/{gw}/picks/")
        if not isinstance(published, Mapping):
            continue
        picks = published.get("picks")
        if not isinstance(picks, list) or len(picks) != 15:
            continue
        if (any(type(p.get("element")) is not int
                or type(p.get("position")) is not int
                or type(p.get("multiplier")) is not int
                for p in picks if isinstance(p, Mapping))
            or not all(isinstance(p, Mapping) for p in picks)):
            continue
        ids = [p["element"] for p in picks]
        if (len(set(ids)) != 15 or min(ids) <= 0
            or {p["position"] for p in picks} != set(range(1, 16))
            or sum(p.get("is_captain") is True for p in picks) != 1
            or sum(p.get("is_vice_captain") is True for p in picks) != 1):
            continue
        owner_fixture = any(teams.get(pid) in {fixture["team_h"], fixture["team_a"]} for pid in ids)
        # Nonowner fixtures can be included in the next regular report; at
        # night only owner-relevant kickoff may generate an additional alert.
        if not owner_fixture:
            continue
        proof = {
            "authority": "OFFICIAL_FPL",
            "owner_locked_picks_verified": True,
            "official_event_facts_verified": True,
            "scoring_gw": gw,
            "official_fixture_id": fixture["id"],
            "checked_at": now.isoformat(),
            "event_kind": "OWNER_MATCH_STARTED",
            # At the unique first post-kickoff checkpoint, Official started=True
            # plus Official kickoff identity proves the schedule-to-LIVE edge.
            "previous_value": "NOT_STARTED",
            "current_value": "LIVE",
            "owner_fixture_verified": True,
        }
        material = assess_verified_match_materiality(proof, observed_at=now)
        if not material["eligible"]:
            continue
        return {
            "report_mode": "MATCH",
            "report_slot": slot.isoformat(),
            "checkpoint_time": slot.strftime("%H:%M"),
            "match_public_proof": "OFFICIAL_FPL_OWNER_KICKOFF",
            "match_gw": str(gw),
            "match_fixture_id": str(fixture["id"]),
            "match_event_key": material["event_key"],
        }
    return None
