from __future__ import annotations

"""Bounded match-level tactical backfill INSIDE the existing V6 FotMob poll.

Retrieval evidence is retrospective only and has no P(start) authority.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .source_native import _fotmob_match_rows
from .http_client import utc_now


def finalized_match_ids(league: dict[str, Any], cfg: dict[str, Any]) -> list[int]:
    allowed = {int(v) for v in cfg.get("historical_gws") or []
               if str(v).isdigit() and 1 <= int(v) <= 38}
    priority = {int(v) for v in cfg.get("priority_native_team_ids") or []
                if str(v).isdigit() and int(v) > 0}
    candidates: dict[int, tuple[int, int]] = {}
    conflicted: set[int] = set()
    # _fotmob_match_rows coalesces native IDs. Detect conflicts against the
    # uncoalesced provider list first, so a third duplicate cannot re-admit.
    direct_rows = league.get("matches") or []
    if isinstance(direct_rows, list):
        seen: set[int] = set()
        for raw in direct_rows:
            if not isinstance(raw, dict) or not str(raw.get("id")).isdigit():
                continue
            native = int(raw["id"])
            if native in seen:
                conflicted.add(native)
            seen.add(native)
    for row in _fotmob_match_rows(league):
        native, gw = row.get("id"), row.get("round", row.get("stage"))
        status = row.get("status") or {}
        if (not str(native).isdigit() or int(native) <= 0 or not str(gw).isdigit()
                or int(gw) not in allowed or not isinstance(status, dict)
                or status.get("finished") is not True or status.get("cancelled") is True):
            continue
        home, away = row.get("home") or {}, row.get("away") or {}
        if not isinstance(home, dict) or not isinstance(away, dict):
            continue
        ids = {str(home.get("id", row.get("hId"))), str(away.get("id", row.get("aId")))}
        rank = 0 if ids.intersection({str(v) for v in priority}) else 1
        key = int(native)
        if key in candidates or key in conflicted:
            conflicted.add(key)
            candidates.pop(key, None)
            continue
        candidates[key] = (rank, int(gw))
    return [key for key, value in sorted(candidates.items(), key=lambda pair: (*pair[1], pair[0]))]


def collect_fotmob(source: dict[str, Any], client: Any,
                   previous: dict[str, Any] | None = None) -> dict[str, Any]:
    # Lazy import prevents a circular dependency with acquisition adapters.
    from .adapters import collect_http, _failed_attempt

    payload = collect_http(source, client, previous)
    cfg = dict(source.get("match_details_history") or {})
    if cfg.get("enabled") is not True:
        return payload

    day = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Jakarta")).date().isoformat()
    prior_tracking = dict((previous or {}).get("match_details_history") or {})
    used = int(prior_tracking.get("reserved_attempts_today") or 0) if prior_tracking.get("date_wib") == day else 0
    budget = max(0, int(cfg.get("daily_request_budget") or 0))
    cap = max(0, min(12, int(cfg.get("max_backfill_requests_per_cycle") or 0)))
    retries = max(1, int(client.retry_attempts))
    slots = min(cap, max(0, (budget - used) // retries))

    league = (payload.get("data") or {}).get("league") or {}
    usable_league = (league.get("status") in {"AVAILABLE", "NOT_MODIFIED"}
                     and isinstance(league.get("json"), dict))
    candidates = finalized_match_ids(league["json"], cfg) if usable_league else []
    old_data = (previous or {}).get("data") or {}
    retained = 0
    for native in candidates:
        key = f"match_details_{native}"
        prior = old_data.get(key) or {}
        if (prior.get("status") == "AVAILABLE"
                and isinstance(prior.get("json"), dict)
                and isinstance(prior.get("sha256"), str)
                and len(prior["sha256"]) == 64):
            payload["data"][key] = {**prior, "data_origin": "FINALIZED_MATCH_DETAILS_CACHE"}
            retained += 1

    missing = [n for n in candidates if f"match_details_{n}" not in payload["data"]]
    scheduled = missing[:slots]
    results: dict[int, dict[str, Any]] = {}
    if scheduled:
        with ThreadPoolExecutor(max_workers=min(3, len(scheduled))) as pool:
            futures = {}
            for native in scheduled:
                request = {
                    "id": f"match_details_{native}",
                    "url": str(cfg["endpoint_template"]).format(match_id=native),
                    "expect": "json",
                    "max_body_bytes": min(750000, max(10000, int(cfg.get("max_body_bytes") or 450000))),
                    "validation": {"required_json_paths": ["general.matchId", "content.lineup"]},
                }
                futures[pool.submit(client.fetch, source, request)] = (native, request)
            for future in as_completed(futures):
                native, request = futures[future]
                try:
                    results[native] = future.result()
                except Exception as exc:
                    results[native] = _failed_attempt(source, request, exc)

    fetched = 0
    attempts = [results[n] for n in scheduled]
    for row in attempts:
        if (row.get("status") == "AVAILABLE"
                and isinstance(row.get("json"), dict)
                and isinstance(row.get("sha256"), str)
                and len(row["sha256"]) == 64):
            payload["data"][str(row["request_id"])] = {**row, "data_origin": "CURRENT_CYCLE"}
            fetched += 1
    # Reserve worst-case HTTP retries; no uncontrolled request amplification.
    used += len(scheduled) * retries
    coverage = {
        "status": "RETRIEVAL_COMPLETE" if candidates and len(candidates) == retained + fetched else "PARTIAL",
        "date_wib": day,
        "reserved_attempts_today": used,
        "daily_request_budget": budget,
        "candidate_finalized_fixtures": len(candidates),
        "cached_finalized_match_details": retained,
        "fetched_this_cycle": fetched,
        "remaining_without_usable_details": len(missing) - fetched,
        "attempted_this_cycle": len(attempts),
        "attempt_failures": [{"request_id": a.get("request_id"), "status": a.get("status"),
                              "http_status": a.get("http_status"), "error": a.get("error")}
                             for a in attempts if a.get("status") != "AVAILABLE"],
        "identity_and_tactical_admission": "NOT_ASSERTED",
        "historical_predeadline_asof_proven": False,
        "new_scheduler_created": False,
    }
    # Match-detail requests finish AFTER the base league request. Source
    # effective_at must reflect the completed enrichment, never the earlier
    # league poll timestamp or the logical scheduler slot.
    payload["checked_at"] = utc_now()
    if fetched:
        payload["current_run_action"] = "FETCHED"
    payload["match_details_history"] = coverage
    payload.setdefault("coverage", {})["fotmob_match_details"] = coverage
    if fetched:
        payload["changed"] = True
    return payload
