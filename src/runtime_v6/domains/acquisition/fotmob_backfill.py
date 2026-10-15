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
    use_public_ssr = cfg.get("public_page_fallback_enabled") is True
    api_first = use_public_ssr and cfg.get("retrieval_strategy") == "API_THEN_PUBLIC_PAGE"
    # Reserve both possible requests and all retries up front: an unsuccessful
    # API fetch must not make the page fallback exceed today's FotMob quota.
    per_match_reservation = retries * (2 if api_first else 1)
    slots = min(cap, max(0, (budget - used) // per_match_reservation))

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

    def fetch_detail(native: int) -> dict[str, Any]:
        """API first; use provider's public page only for safe recoverable errors."""
        def request_for(page: bool) -> dict[str, Any]:
            request: dict[str, Any] = {
                "id": f"match_details_{native}",
                "url": str(
                    cfg["public_page_url_template"] if page
                    else cfg["endpoint_template"]
                ).format(match_id=native),
                "expect": "text" if page else "json",
                "max_body_bytes": (
                    min(2500000, max(10000, int(cfg.get("public_page_max_body_bytes") or 1500000)))
                    if page else min(750000, max(10000, int(cfg.get("max_body_bytes") or 450000)))
                ),
            }
            if not page:
                request["validation"] = {"required_json_paths": ["general.matchId", "content.lineup"]}
            return request

        def attempt(page: bool) -> dict[str, Any]:
            request = request_for(page)
            try:
                return client.fetch(source, request)
            except Exception as exc:
                return _failed_attempt(source, request, exc)

        page = use_public_ssr and not api_first
        outcome = attempt(page)
        if (api_first and outcome.get("status") in
                {"INVALID_PAYLOAD", "TRUNCATED", "UNAVAILABLE"}
                and outcome.get("http_status") not in {401, 403, 429}):
            primary_failure = {
                "status": outcome.get("status"),
                "http_status": outcome.get("http_status"),
                "error": outcome.get("error"),
            }
            outcome = attempt(True)
            page = True
            outcome["api_primary_failure"] = primary_failure
            outcome["attempted_public_page_fallback"] = True
        if page and outcome.get("status") == "AVAILABLE":
            from .fotmob_public_page import extract_verified_page_matchdetails
            parsed = extract_verified_page_matchdetails(outcome.get("body"), native)
            if parsed is None:
                outcome = {
                    **outcome, "status": "INVALID_PAYLOAD",
                    "error": "FOTMOB_PUBLIC_PAGE_SCHEMA_OR_ID_MISMATCH",
                    "retrieval_method": "SSR_REJECTED",
                }
            else:
                outcome = {
                    **outcome, "json": parsed,
                    "retrieval_method": "FOTMOB_PUBLIC_PAGE_SSR",
                    "source_original_html_retained": True,
                    "source_raw_html_sha256": outcome.get("sha256"),
                    "not_original_api_matchdetails_response": True,
                    "historical_predeadline_asof_proven": False,
                }
        return outcome

    if scheduled:
        with ThreadPoolExecutor(max_workers=min(3, len(scheduled))) as pool:
            futures = {pool.submit(fetch_detail, native): native for native in scheduled}
            for future in as_completed(futures):
                native = futures[future]
                results[native] = future.result()

    fetched = 0
    fetched_public_ssr = 0
    attempts = [results[n] for n in scheduled]
    for row in attempts:
        if (row.get("status") == "AVAILABLE"
                and isinstance(row.get("json"), dict)
                and isinstance(row.get("sha256"), str)
                and len(row["sha256"]) == 64):
            payload["data"][str(row["request_id"])] = {**row, "data_origin": "CURRENT_CYCLE"}
            fetched += 1
            fetched_public_ssr += int(row.get("retrieval_method") == "FOTMOB_PUBLIC_PAGE_SSR")
    # Reserve worst-case HTTP retries; no uncontrolled request amplification.
    used += len(scheduled) * per_match_reservation
    coverage = {
        "status": "RETRIEVAL_COMPLETE" if candidates and len(candidates) == retained + fetched else "PARTIAL",
        "date_wib": day,
        "reserved_attempts_today": used,
        "daily_request_budget": budget,
        "candidate_finalized_fixtures": len(candidates),
        "cached_finalized_match_details": retained,
        "total_usable_finalized_match_details": retained + fetched,
        "fetched_this_cycle": fetched,
        "fetched_public_page_ssr_this_cycle": fetched_public_ssr,
        "cached_public_page_ssr_details": sum(
            payload["data"].get("match_details_" + str(n), {}).get("retrieval_method")
            == "FOTMOB_PUBLIC_PAGE_SSR" for n in candidates
        ),
        "public_page_ssr_enabled": use_public_ssr,
        "retrieval_strategy": "API_THEN_PUBLIC_PAGE" if api_first else (
            "PUBLIC_PAGE_ONLY" if use_public_ssr else "API_ONLY"
        ),
        "api_first_public_fallback_attempts": sum(
            bool(x.get("attempted_public_page_fallback")) for x in attempts
        ),
        "worst_case_http_attempts_reserved_this_cycle": len(scheduled) * per_match_reservation,
        "same_daily_fotmob_budget_for_api_and_page": True,
        "public_page_original_html_sha_required": True,
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
