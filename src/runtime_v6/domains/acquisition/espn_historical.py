from __future__ import annotations

"""Bounded independent ESPN historical match snapshots in the existing V6 poll.

Not FotMob, not a replacement for original FotMob matchDetails, and not a
canonical Official FPL / predeadline role, manager or injury identity.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from .http_client import utc_now


def verified_espn_events(data: Mapping[str, Any], dates: list[str]) -> list[int]:
    """Only completed league events with unambiguous ESPN event identity."""
    allowed = set(dates)
    ids: dict[int, str] = {}
    rejected: set[int] = set()
    for day in dates:
        obj = data.get("history_scoreboard_" + day)
        if not isinstance(obj, Mapping) or obj.get("status") != "AVAILABLE":
            continue
        raw = obj.get("json") or {}
        if not isinstance(raw, Mapping) or not isinstance(raw.get("events"), list):
            continue
        for event in raw["events"]:
            if not isinstance(event, Mapping):
                continue
            try:
                eid = int(event.get("id"))
            except (ValueError, TypeError):
                continue
            competitions = event.get("competitions") or []
            if eid <= 0 or not isinstance(competitions, list) or len(competitions) != 1:
                continue
            contest = competitions[0]
            if not isinstance(contest, Mapping) or str(contest.get("id")) != str(eid):
                continue
            status = contest.get("status") or {}
            completed = ((status.get("type") or {}).get("completed") is True
                         and (status.get("type") or {}).get("state") == "post")
            sides = contest.get("competitors") or []
            home = [s for s in sides if isinstance(s, Mapping) and s.get("homeAway") == "home"]
            away = [s for s in sides if isinstance(s, Mapping) and s.get("homeAway") == "away"]
            try:
                date = str(event["date"])[:10].replace("-", "")
            except KeyError:
                continue
            if not completed or len(home) != 1 or len(away) != 1 or date != day:
                continue
            if eid in ids:
                rejected.add(eid)
            ids[eid] = day
    return sorted(x for x in ids if x not in rejected and ids[x] in allowed)


def collect_espn_history(source: dict[str, Any], client: Any,
                         previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Same ESPN poll, separate capped independent archive, zero new scheduler."""
    from .adapters import collect_http, _failed_attempt

    payload = collect_http(source, client, previous)
    cfg = source.get("historical_tactics") or {}
    if cfg.get("enabled") is not True:
        return payload
    dates = sorted(set(str(x) for x in cfg.get("dates_yyyymmdd") or []))
    if not dates or any(len(day) != 8 or not day.isascii() or not day.isdecimal()
                        for day in dates):
        payload["historical_tactics_coverage"] = {
            "status": "CONFIG_INVALID", "independent_source": "ESPN",
            "numeric_pstart_effect": "NONE",
        }
        return payload
    day_wib = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Jakarta")).date().isoformat()
    prior = dict((previous or {}).get("historical_tactics_coverage") or {})
    spent = int(prior.get("reserved_attempts_today") or 0) if prior.get("date_wib") == day_wib else 0
    budget = max(0, int(cfg.get("daily_request_budget") or 0))
    retries = max(1, int(client.retry_attempts))
    cap = min(10, max(0, int(cfg.get("max_requests_per_cycle") or 0)))
    slots = min(cap, max(0, (budget - spent) // retries))
    old = (previous or {}).get("data") or {}
    if not isinstance(payload.get("data"), dict):
        payload["data"] = {}

    def retain(key: str) -> bool:
        value = old.get(key) or {}
        if (value.get("status") == "AVAILABLE" and isinstance(value.get("json"), dict)
                and isinstance(value.get("sha256"), str) and len(value["sha256"]) == 64):
            payload["data"][key] = {**value, "data_origin": "HISTORICAL_ESPN_CACHE"}
            return True
        return False

    for date in dates:
        retain("history_scoreboard_" + date)
    requests: list[dict[str, Any]] = []
    for date in dates:
        if len(requests) >= slots:
            break
        if "history_scoreboard_" + date not in payload["data"]:
            requests.append({
                "id": "history_scoreboard_" + date,
                "url": str(cfg["scoreboard_url_template"]).format(date=date),
                "expect": "json", "max_body_bytes": 3000000,
                "validation": {"required_json_paths": ["leagues", "events"]},
            })
    remaining = slots - len(requests)
    events = verified_espn_events(payload["data"], dates)
    # Priority IDs must already be present in a verified, completed ESPN
    # scoreboard. Unrecognized IDs are ignored, never directly fetched.
    requested_priority = cfg.get("priority_summary_event_ids") or []
    if not isinstance(requested_priority, list):
        requested_priority = []
    priorities = {int(x) for x in requested_priority
                  if str(x).isascii() and str(x).isdecimal() and int(x) > 0}
    events.sort(key=lambda eid: (eid not in priorities, eid))
    for event in events:
        retain("history_summary_" + str(event))
    for event in events:
        if len(requests) >= slots or remaining <= 0:
            break
        key = "history_summary_" + str(event)
        if key not in payload["data"]:
            requests.append({
                "id": key,
                "url": str(cfg["summary_url_template"]).format(event_id=event),
                "expect": "json", "max_body_bytes": 3000000,
            })
            remaining -= 1
    attempts = []
    if requests:
        with ThreadPoolExecutor(max_workers=min(3, len(requests))) as pool:
            futures = {pool.submit(client.fetch, source, request): request for request in requests}
            for future in as_completed(futures):
                request = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = _failed_attempt(source, request, exc)
                attempts.append(result)
    fetched = 0
    for response in attempts:
        if (response.get("status") == "AVAILABLE"
                and isinstance(response.get("json"), dict)
                and isinstance(response.get("sha256"), str)
                and len(response["sha256"]) == 64):
            payload["data"][response["request_id"]] = {
                **response, "data_origin": "INDEPENDENT_ESPN_CYCLE"
            }
            fetched += 1
    spent += len(requests) * retries
    remaining_dates = sum("history_scoreboard_" + d not in payload["data"] for d in dates)
    confirmed_events = verified_espn_events(payload["data"], dates)
    summary_count = sum("history_summary_" + str(e) in payload["data"] for e in confirmed_events)
    complete = not remaining_dates and len(confirmed_events) == summary_count and bool(confirmed_events)
    health = {
        "status": "RETRIEVAL_COMPLETE" if complete else "PARTIAL",
        "source_id": "espn", "independence_group": "espn",
        "date_wib": day_wib,
        "reserved_attempts_today": spent, "daily_request_budget": budget,
        "history_dates_expected": len(dates),
        "history_dates_cached": len(dates) - remaining_dates,
        "verified_espn_events": len(confirmed_events),
        "event_summaries_cached": summary_count,
        "priority_event_ids_verified": sorted(set(confirmed_events) & priorities),
        "priority_summaries_cached": sum(
            "history_summary_" + str(eid) in payload["data"]
            for eid in set(confirmed_events) & priorities
        ),
        "priority_summaries_outstanding": sorted(
            eid for eid in set(confirmed_events) & priorities
            if "history_summary_" + str(eid) not in payload["data"]
        ),
        "requests_this_cycle": len(requests),
        "fetched_this_cycle": fetched,
        "failures_this_cycle": [
            {"request_id": a.get("request_id"), "status": a.get("status"),
             "http_status": a.get("http_status")}
            for a in attempts if a.get("status") != "AVAILABLE"
        ],
        "fotmob_matchdetails_coverage_not_modified": True,
        "official_fpl_fixture_identity_admission": "NOT_ASSERTED",
        "semantic_tactical_role_admission": "NOT_ASSERTED",
        "historical_predeadline_asof_proven": False,
        "numeric_pstart_effect": "NONE",
        "new_scheduler_created": False,
    }
    payload["historical_tactics_coverage"] = health
    payload.setdefault("coverage", {})["espn_historical_tactics"] = health
    payload["checked_at"] = utc_now()
    if fetched:
        payload["current_run_action"] = "FETCHED"
        payload["changed"] = True
    return payload
