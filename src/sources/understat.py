from __future__ import annotations

import codecs
import json
import re
import time
from datetime import datetime, timezone
from typing import Any

import requests

from src.utils import CONFIG, DATA, atomic_json, iso_now, parse_dt, read_json

POLICY_FILE = CONFIG / "intelligence" / "understat_tactical.json"
CACHE = DATA / "stats" / "understat_epl_2026.json"

_EMBEDDED_RE = re.compile(
    r"(?:var|let|const)\s+(?P<name>[A-Za-z0-9_]+)\s*=\s*JSON\.parse\((?P<quote>['\"])(?P<body>.*?)(?P=quote)\)\s*;",
    re.DOTALL,
)


def _policy() -> dict:
    return read_json(POLICY_FILE, {}) or {}


def _transport_revision(policy: dict | None = None) -> str:
    payload = policy or _policy()
    return str((payload.get("network") or {}).get("transport_revision") or "")


def _age_minutes(stamp: str | None) -> float | None:
    dt = parse_dt(stamp) if stamp else None
    if not dt:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 60.0)


def _decode_embedded(body: str) -> Any:
    # Backward-compatible parser for historical fixtures/tests. Current
    # production acquisition uses Understat's XHR JSON endpoint and never
    # executes JavaScript from the landing page.
    decoded = codecs.decode(body.encode("utf-8"), "unicode_escape")
    return json.loads(decoded)


def parse_embedded_json(html: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for match in _EMBEDDED_RE.finditer(html or ""):
        name = match.group("name")
        try:
            out[name] = _decode_embedded(match.group("body"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return out


def _rows(value: Any) -> list[dict]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        return [row for row in value.values() if isinstance(row, dict)]
    return []


def _is_completed_fixture(row: dict) -> bool:
    if row.get("isResult") is True or str(row.get("isResult") or "").lower() in {"true", "1"}:
        return True
    goals = row.get("goals")
    if isinstance(goals, dict):
        return goals.get("h") is not None and goals.get("a") is not None
    return row.get("h_goals") is not None and row.get("a_goals") is not None


def latest_completed_fixture(embedded: dict[str, Any]) -> dict | None:
    completed = []
    for row in _rows(embedded.get("datesData")):
        if not _is_completed_fixture(row):
            continue
        stamp = str(row.get("datetime") or row.get("date") or "")
        if stamp:
            completed.append((stamp, row))
    return max(completed, key=lambda item: item[0])[1] if completed else None


def _validate(payload: dict) -> tuple[bool, list[str]]:
    defects = []
    embedded = payload.get("embedded") or {}
    teams = embedded.get("teamsData")
    players = embedded.get("playersData")
    dates = embedded.get("datesData")
    if not isinstance(teams, (dict, list)):
        defects.append("teamsData_missing_or_invalid")
    if not isinstance(players, (dict, list)):
        defects.append("playersData_missing_or_invalid")
    if not isinstance(dates, (dict, list)):
        defects.append("datesData_missing_or_invalid")
    return not defects, defects


def _freshness(age: float | None, policy: dict) -> str:
    cache = policy.get("cache") or {}
    if age is None:
        return "UNKNOWN"
    if age <= float(cache.get("fresh_minutes") or 360):
        return "FRESH"
    if age <= float(cache.get("stale_after_minutes") or 2880):
        return "STALE"
    return "EXPIRED"


def _failure(error: str, previous: dict | None = None) -> dict:
    policy = _policy()
    revision = _transport_revision(policy)
    previous = previous or read_json(CACHE, {}) or {}
    age = _age_minutes(previous.get("fetched_at")) if previous else None
    if previous and (policy.get("cache") or {}).get("retain_last_known_good", True):
        valid, defects = _validate(previous)
        if valid:
            return {
                **previous,
                "source_availability": "STALE_FALLBACK",
                "freshness": _freshness(age, policy),
                "fallback": True,
                "refresh_error": error,
                "refresh_attempted_at": iso_now(),
                "refresh_transport_revision": revision,
                "cache_age_minutes": round(age, 2) if age is not None else None,
                "schema_valid": True,
                "schema_defects": defects,
            }
    return {
        "contract": "UNDERSTAT_RAW_SOURCE_V1",
        "source": "Understat",
        "transport_revision": revision,
        "refresh_transport_revision": revision,
        "source_availability": "UNAVAILABLE",
        "freshness": "UNKNOWN",
        "fetched_at": None,
        "source_timestamp": None,
        "latest_fixture_represented": None,
        "refresh_attempted_at": iso_now(),
        "fallback": False,
        "schema_valid": False,
        "schema_defects": ["source_unavailable"],
        "error": error,
        "embedded": {},
    }


def _request_json(url: str, policy: dict, session: requests.Session | None = None) -> tuple[dict[str, Any], int]:
    cfg = policy.get("network") or {}
    configured_attempts = max(1, int(cfg.get("max_attempts") or 3))
    request_budget = max(1, int(cfg.get("max_requests_per_refresh") or configured_attempts))
    attempts = min(configured_attempts, request_budget)
    timeout = float(cfg.get("timeout_seconds") or 12)
    backoff = list(cfg.get("backoff_seconds") or [0.5, 1.0])
    minimum_interval = max(0.0, float(cfg.get("minimum_request_interval_seconds") or 0.0))
    headers = {
        "User-Agent": str(cfg.get("user_agent") or "FPL-iphoenk-engine"),
        "X-Requested-With": "XMLHttpRequest",
    }
    client = session or requests.Session()
    last_error: Exception | None = None
    calls = 0
    for attempt in range(attempts):
        try:
            calls += 1
            response = client.get(url, timeout=timeout, headers=headers)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Understat XHR response is not a JSON object")
            return payload, calls
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < attempts - 1:
                delay = float(backoff[min(attempt, len(backoff) - 1)]) if backoff else 0.0
                time.sleep(max(minimum_interval, max(0.0, delay)))
    raise RuntimeError(f"Understat request failed after {calls} bounded attempts: {last_error}")


def _normalize_ajax_payload(payload: dict[str, Any]) -> dict[str, Any]:
    # Keep the established V3 normalized raw contract stable while adapting
    # only the transport boundary to Understat's current XHR response keys.
    return {
        "teamsData": payload.get("teams"),
        "playersData": payload.get("players"),
        "datesData": payload.get("dates"),
    }


def sync(*, force: bool = False, session: requests.Session | None = None) -> dict:
    policy = _policy()
    network = policy.get("network") or {}
    revision = _transport_revision(policy)
    cached = read_json(CACHE, {}) or {}
    age = _age_minutes(cached.get("fetched_at")) if cached else None
    ttl = float((policy.get("cache") or {}).get("raw_ttl_minutes") or 360)
    valid, _ = _validate(cached) if cached else (False, [])
    same_transport = bool(revision) and str(cached.get("transport_revision") or "") == revision
    if not force and cached and valid and same_transport and age is not None and age <= ttl:
        return {
            **cached,
            "runtime_reused": True,
            "cache_age_minutes": round(age, 2),
            "freshness": _freshness(age, policy),
        }

    base = str(network.get("base_url") or "https://understat.com").rstrip("/")
    league = str(policy.get("league") or "EPL")
    season = int(policy.get("season_start_year") or 2026)
    endpoint_template = str(network.get("endpoint_template") or "getLeagueData/{league}/{season}")
    endpoint = endpoint_template.format(league=league, season=season).lstrip("/")
    url = f"{base}/{endpoint}"
    landing_url = f"{base}/league/{league}/{season}"
    started = time.perf_counter()
    try:
        ajax_payload, request_count = _request_json(url, policy, session=session)
        embedded = _normalize_ajax_payload(ajax_payload)
        latest = latest_completed_fixture(embedded)
        latest_stamp = (latest or {}).get("datetime") or (latest or {}).get("date")
        payload = {
            "contract": "UNDERSTAT_RAW_SOURCE_V1",
            "source": "Understat",
            "source_tier": "dynamic_tactical_enrichment",
            "league": league,
            "season_start_year": season,
            "transport_revision": revision,
            "refresh_transport_revision": revision,
            "source_url": url,
            "source_landing_url": landing_url,
            "fetched_at": iso_now(),
            # The XHR payload does not advertise a separate publication
            # timestamp. The latest completed match represented is retained as
            # source-observation context rather than inventing an update SLA.
            "source_timestamp": latest_stamp,
            "latest_fixture_represented": {
                "id": (latest or {}).get("id"),
                "datetime": latest_stamp,
            } if latest else None,
            "source_availability": "AVAILABLE",
            "freshness": "FRESH",
            "fallback": False,
            "runtime_reused": False,
            "cache_age_minutes": 0.0,
            "request_count": request_count,
            "request_budget": max(1, int(network.get("max_requests_per_refresh") or network.get("max_attempts") or 1)),
            "request_strategy": "single_league_xhr_snapshot_no_per_player_network_calls",
            "embedded": embedded,
            "fetch_duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
            "provenance": {
                "provider": "Understat",
                "url": url,
                "landing_url": landing_url,
                "transport": "HTTPS_JSON_XHR",
                "transport_revision": revision,
                "adapter": "src.sources.understat",
            },
        }
        valid, defects = _validate(payload)
        payload["schema_valid"] = valid
        payload["schema_defects"] = defects
        if not valid:
            return _failure(";".join(defects), previous=cached)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(CACHE, payload)
        return payload
    except Exception as exc:  # fail-soft optional enrichment boundary
        return _failure(f"{type(exc).__name__}: {exc}", previous=cached)


def load() -> dict:
    payload = read_json(CACHE, {}) or {}
    if not payload:
        return _failure("no_cached_understat_snapshot")
    age = _age_minutes(payload.get("fetched_at"))
    return {
        **payload,
        "runtime_reused": True,
        "cache_age_minutes": round(age, 2) if age is not None else None,
        "freshness": _freshness(age, _policy()),
    }