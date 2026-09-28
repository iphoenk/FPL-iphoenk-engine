from __future__ import annotations

"""Governed report-time non-PL club schedule acquisition for V12 S05.

This module is intentionally outside the V6 factual plane. Official FPL remains
the Premier League fixture authority. Public competition schedules are used
only as verified workload/rest/travel context and never mutate xPts/xMins or
decision mathematics directly.
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode

import requests

from src.utils import ROOT

CONFIG_PATH = (
    ROOT / "config" / "intelligence" / "report_time_competition_schedule.json"
)


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _identity_key(value: Any) -> str:
    return "".join(
        ch
        for ch in str(value or "").casefold()
        if ch.isalnum()
    )


def _official_team_indexes(
    bootstrap: Mapping[str, Any],
) -> tuple[dict[str, int], dict[str, int]]:
    """Build deterministic exact indexes. No fuzzy name matching is allowed."""
    by_abbreviation: dict[str, int] = {}
    by_name: dict[str, int] = {}
    for row in bootstrap.get("teams") or []:
        if not isinstance(row, Mapping) or row.get("id") is None:
            continue
        team_id = int(row["id"])
        short = str(row.get("short_name") or "").strip().upper()
        if short:
            by_abbreviation[short] = team_id
        for field in ("name", "short_name"):
            key = _identity_key(row.get(field))
            if key:
                by_name[key] = team_id
    return by_abbreviation, by_name


def _provider_team_id(
    team: Mapping[str, Any],
    *,
    by_abbreviation: Mapping[str, int],
    by_name: Mapping[str, int],
) -> int | None:
    abbreviation = str(team.get("abbreviation") or "").strip().upper()
    if abbreviation and abbreviation in by_abbreviation:
        return int(by_abbreviation[abbreviation])
    for field in ("displayName", "shortDisplayName", "name", "location"):
        key = _identity_key(team.get(field))
        if key and key in by_name:
            return int(by_name[key])
    return None


def _event_datetime(event: Mapping[str, Any]) -> datetime | None:
    competition = next(
        (
            row
            for row in event.get("competitions") or []
            if isinstance(row, Mapping)
        ),
        {},
    )
    return _dt(
        competition.get("date")
        or competition.get("startDate")
        or event.get("date")
    )


def _competition_rows(
    *,
    payload: Mapping[str, Any],
    competition_cfg: Mapping[str, Any],
    bootstrap: Mapping[str, Any],
    floor: datetime,
    ceiling: datetime,
    source_url: str,
) -> list[dict[str, Any]]:
    by_abbreviation, by_name = _official_team_indexes(bootstrap)
    rows: list[dict[str, Any]] = []
    for event in payload.get("events") or []:
        if not isinstance(event, Mapping):
            continue
        kickoff = _event_datetime(event)
        if kickoff is None or kickoff < floor or kickoff > ceiling:
            continue
        contest = next(
            (
                row
                for row in event.get("competitions") or []
                if isinstance(row, Mapping)
            ),
            {},
        )
        competitors = [
            dict(row)
            for row in contest.get("competitors") or []
            if isinstance(row, Mapping)
        ]
        if len(competitors) < 2:
            continue
        venue = dict(contest.get("venue") or {})
        address = dict(venue.get("address") or {})
        venue_country = str(address.get("country") or "").strip()
        for competitor in competitors:
            provider_team = dict(competitor.get("team") or {})
            team_id = _provider_team_id(
                provider_team,
                by_abbreviation=by_abbreviation,
                by_name=by_name,
            )
            if team_id is None:
                continue
            opponent = next(
                (
                    other
                    for other in competitors
                    if other is not competitor
                ),
                {},
            )
            opponent_team = dict(opponent.get("team") or {})
            home_away = str(competitor.get("homeAway") or "").upper()
            category = str(
                competition_cfg.get("category") or "OTHER_COMPETITIVE"
            ).upper()
            continental_away = (
                category == "CONTINENTAL_CLUB" and home_away == "AWAY"
            )
            uk_countries = {
                "england",
                "scotland",
                "wales",
                "northern ireland",
                "united kingdom",
                "uk",
            }
            cross_border = bool(
                continental_away
                and venue_country
                and venue_country.casefold() not in uk_countries
            )
            rows.append(
                {
                    "team_id": team_id,
                    "player_id": None,
                    "kickoff": kickoff.isoformat(),
                    "competition": competition_cfg.get("name"),
                    "competition_category": category,
                    "home_away": (
                        "H"
                        if home_away == "HOME"
                        else "A"
                        if home_away == "AWAY"
                        else None
                    ),
                    "opponent": (
                        opponent_team.get("displayName")
                        or opponent_team.get("shortDisplayName")
                        or opponent_team.get("name")
                    ),
                    "venue": venue.get("fullName"),
                    "venue_country": venue_country or None,
                    "cross_border": cross_border,
                    "long_haul": False,
                    "timezone_shift_hours": None,
                    "travel_context": (
                        "EUROPEAN_AWAY"
                        if continental_away
                        else "DOMESTIC_AWAY"
                        if home_away == "AWAY"
                        else "HOME"
                        if home_away == "HOME"
                        else "UNKNOWN"
                    ),
                    "verified_source": "ESPN_PUBLIC_COMPETITION_SCHEDULE",
                    "source_url": source_url,
                    "source_native_event_id": event.get("id"),
                    "source_status": (
                        ((contest.get("status") or {}).get("type") or {}).get(
                            "name"
                        )
                    ),
                    "minutes": None,
                    "verified": True,
                }
            )
    return rows


def _fetch_one(
    *,
    provider: Mapping[str, Any],
    competition_cfg: Mapping[str, Any],
    start_date: str,
    end_date: str,
) -> tuple[str, dict[str, Any], str]:
    slug = str(competition_cfg["slug"])
    base = str(provider["base_url"]).rstrip("/")
    params = {
        "dates": f"{start_date}-{end_date}",
        "limit": "1000",
    }
    url = f"{base}/{slug}/scoreboard"
    response = requests.get(
        url,
        params=params,
        timeout=float(provider.get("request_timeout_seconds") or 6),
        headers={"User-Agent": "FPL-V12-Report-Time/1.0"},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("competition schedule response is not an object")
    source_url = getattr(response, "url", None) or f"{url}?{urlencode(params)}"
    return slug, payload, str(source_url)


def collect_verified_non_pl_schedule(
    *,
    bootstrap: Mapping[str, Any],
    planning_fixtures: Sequence[Mapping[str, Any]],
    report_timestamp: Any,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Fetch bounded public club schedules and return fail-soft workload context."""
    cfg = dict(config or load_config())
    provider = dict(cfg.get("provider") or {})
    competitions = [
        dict(row)
        for row in cfg.get("competitions") or []
        if isinstance(row, Mapping)
    ]
    report_dt = _dt(report_timestamp) or datetime.now(timezone.utc)
    lookback_days = max(1, int(provider.get("lookback_days") or 21))
    planning_datetimes = [
        dt
        for row in planning_fixtures
        if isinstance(row, Mapping)
        and (dt := _dt(row.get("kickoff_time"))) is not None
    ]
    ceiling = max(planning_datetimes, default=report_dt)
    floor = report_dt - timedelta(days=lookback_days)
    start_date = floor.strftime("%Y%m%d")
    end_date = ceiling.strftime("%Y%m%d")
    max_workers = max(
        1,
        min(
            len(competitions) or 1,
            int(provider.get("max_parallel_requests") or 5),
        ),
    )

    rows: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    if competitions:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    _fetch_one,
                    provider=provider,
                    competition_cfg=competition,
                    start_date=start_date,
                    end_date=end_date,
                ): competition
                for competition in competitions
            }
            for future in as_completed(futures):
                competition = futures[future]
                slug = str(competition.get("slug") or "")
                try:
                    _, payload, source_url = future.result()
                    current_rows = _competition_rows(
                        payload=payload,
                        competition_cfg=competition,
                        bootstrap=bootstrap,
                        floor=floor,
                        ceiling=ceiling,
                        source_url=source_url,
                    )
                    rows.extend(current_rows)
                    checks.append(
                        {
                            "competition": competition.get("name"),
                            "slug": slug,
                            "status": "PASS",
                            "matched_pl_team_events": len(current_rows),
                        }
                    )
                except Exception as exc:
                    checks.append(
                        {
                            "competition": competition.get("name"),
                            "slug": slug,
                            "status": "FAILED",
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )

    rows.sort(
        key=lambda row: (
            str(row.get("kickoff") or ""),
            int(row.get("team_id") or -1),
            str(row.get("competition") or ""),
        )
    )
    success_count = sum(1 for row in checks if row.get("status") == "PASS")
    if success_count == len(competitions) and competitions:
        status = "COMPLETE"
    elif success_count:
        status = "PARTIAL"
    else:
        status = "UNAVAILABLE"
    return {
        "schema_version": 1,
        "contract": cfg.get("contract"),
        "status": status,
        "source_id": provider.get("source_id"),
        "report_timestamp": report_dt.isoformat(),
        "window_start": floor.isoformat(),
        "window_end": ceiling.isoformat(),
        "events": rows,
        "event_count": len(rows),
        "checks": sorted(checks, key=lambda row: str(row.get("slug") or "")),
        "successful_competitions": success_count,
        "configured_competitions": len(competitions),
        "authority_complete": status == "COMPLETE",
        "governance": dict(cfg.get("governance") or {}),
    }
