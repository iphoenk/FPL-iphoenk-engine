from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import requests

from src.models.player_identity import norm_name
from src.sources.official_fpl import get_json
from src.utils import CONFIG, DATA, ROOT, atomic_json, parse_dt, read_json

POLICY_PATH = ROOT / "config" / "intelligence" / "historical_priors.json"
RAW_OUT = DATA / "stats" / "vaastav_previous_season.json"
PRIOR_OUT = DATA / "prior_season.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value in (None, "") else value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@lru_cache(maxsize=1)
def load_policy() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _previous_season_label() -> str:
    configured = str((read_json(CONFIG / "sources.json", {}) or {}).get("season") or "2026-2027")
    try:
        start = int(configured[:4]) - 1
    except (TypeError, ValueError):
        start = 2025
    return f"{start}-{str(start + 1)[-2:]}"


def _raw_base() -> str:
    sources = read_json(CONFIG / "sources.json", {}) or {}
    return str((sources.get("vaastav") or {}).get(
        "raw_base",
        "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data",
    )).rstrip("/")


def _fresh_cached_payload(payload: dict[str, Any]) -> bool:
    if payload.get("status") != "LIVE" or payload.get("data_mode") != "PREVIOUS_SEASON_SNAPSHOT":
        return False
    fetched = parse_dt(payload.get("fetched_at"))
    if not fetched:
        return False
    max_age = float(load_policy().get("refresh_hours") or 168)
    age_hours = (datetime.now(timezone.utc) - fetched).total_seconds() / 3600.0
    return age_hours <= max_age


def _fetch_previous_season() -> tuple[dict[str, Any], str]:
    cached = read_json(RAW_OUT, {})
    if _fresh_cached_payload(cached):
        return cached, "PERSISTED_CACHE"

    policy = load_policy()
    source = policy.get("source") or {}
    season = _previous_season_label()
    timeout = int(source.get("timeout_seconds") or 25)
    last_error = None
    for filename in source.get("filenames") or ["players_raw.csv", "cleaned_players.csv"]:
        url = f"{_raw_base()}/{season}/{filename}"
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            rows = list(csv.DictReader(io.StringIO(response.text)))
            if not rows:
                raise RuntimeError("empty CSV")
            columns = set(rows[0])
            required = {"first_name", "second_name", "minutes"}
            if not required.issubset(columns):
                raise RuntimeError(f"schema missing required columns: {sorted(required - columns)}")
            payload = {
                "source": source.get("provider") or "vaastav/Fantasy-Premier-League",
                "season": season,
                "fetched_at": _now(),
                "source_url": url,
                "row_count": len(rows),
                "data_mode": "PREVIOUS_SEASON_SNAPSHOT",
                "status": "LIVE",
                "schema_columns": sorted(columns),
                "rows": rows,
            }
            atomic_json(RAW_OUT, payload)
            return payload, "NETWORK_REFRESH"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"

    if cached.get("rows") and cached.get("data_mode") == "PREVIOUS_SEASON_SNAPSHOT":
        fallback = dict(cached)
        fallback["cache_warning"] = last_error
        return fallback, "STALE_CACHE_FALLBACK"
    raise RuntimeError(f"previous-season source unavailable and no cache: {last_error}")


def build_prior_index(elements: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
    policy = load_policy()
    starter_cfg = policy.get("starter_prior") or {}
    attack_cfg = policy.get("attacking_prior") or {}
    rows = list(payload.get("rows") or [])
    by_code = {str(row.get("code")): row for row in rows if row.get("code") not in (None, "")}
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        full = norm_name(f"{row.get('first_name', '')} {row.get('second_name', '')}")
        if full:
            by_name[full].append(row)

    minimum_minutes = float(starter_cfg.get("minimum_minutes") or 180)
    team_matches = max(1.0, float(starter_cfg.get("season_team_matches") or 38))
    team_weight = float(starter_cfg.get("team_start_share_weight") or 0.35)
    conditional_weight = float(starter_cfg.get("conditional_start_share_weight") or 0.65)
    floor = float(starter_cfg.get("probability_floor") or 0.08)
    ceiling = float(starter_cfg.get("probability_ceiling") or 0.97)
    attack_min_minutes = float(attack_cfg.get("minimum_minutes") or 180)
    full_weight_minutes = max(1.0, float(attack_cfg.get("full_weight_minutes") or 1800))
    max_attack_weight = _clamp(float(attack_cfg.get("maximum_player_weight") or 0.75), 0.0, 1.0)

    priors: dict[str, dict[str, Any]] = {}
    matched_by_code = 0
    matched_by_name = 0
    rejected_low_minutes = 0
    for player in elements:
        row = by_code.get(str(player.get("code")))
        identity_match = "stable_player_code" if row else None
        if row is not None:
            matched_by_code += 1
        if row is None:
            full = norm_name(f"{player.get('first_name', '')} {player.get('second_name', '')}")
            candidates = by_name.get(full, [])
            if len(candidates) == 1:
                row = candidates[0]
                identity_match = "unique_full_name"
                matched_by_name += 1
        if row is None:
            continue

        minutes = max(0.0, _f(row.get("minutes")))
        starts = max(0.0, _f(row.get("starts")))
        if minutes < minimum_minutes:
            rejected_low_minutes += 1
            continue
        minutes_equivalent = max(starts, minutes / 90.0, 1.0)
        team_start_share = _clamp(starts / team_matches, 0.0, 1.0)
        conditional_start_share = _clamp(starts / minutes_equivalent, 0.0, 1.0)
        start_probability = _clamp(
            team_weight * team_start_share + conditional_weight * conditional_start_share,
            floor,
            ceiling,
        )
        avg_start_minutes = _clamp(minutes / max(1.0, starts), 45.0, 90.0) if starts > 0 else 60.0

        xg90 = _f(row.get("expected_goals_per_90"), -1.0)
        xa90 = _f(row.get("expected_assists_per_90"), -1.0)
        if xg90 < 0 and minutes > 0:
            xg90 = 90.0 * max(0.0, _f(row.get("expected_goals"))) / minutes
        if xa90 < 0 and minutes > 0:
            xa90 = 90.0 * max(0.0, _f(row.get("expected_assists"))) / minutes
        attack_weight = 0.0
        if minutes >= attack_min_minutes:
            attack_weight = min(max_attack_weight, minutes / full_weight_minutes * max_attack_weight)

        priors[str(int(player["id"]))] = {
            "element": int(player["id"]),
            "web_name": player.get("web_name"),
            "minutes": round(minutes, 1),
            "starts": round(starts, 1),
            "team_start_share": round(team_start_share, 4),
            "conditional_start_share": round(conditional_start_share, 4),
            "start_probability": round(start_probability, 4),
            "avg_minutes_when_start": round(avg_start_minutes, 1),
            "xg90": round(max(0.0, xg90), 4),
            "xa90": round(max(0.0, xa90), 4),
            "attacking_prior_weight": round(attack_weight, 4),
            "source": f"{payload.get('source')}:{payload.get('season')}",
            "identity_match": identity_match,
        }

    return {
        "generated_at": _now(),
        "model": policy.get("model_id"),
        "season": payload.get("season"),
        "source": payload.get("source"),
        "players": priors,
        "coverage": {
            "current_players": len(elements),
            "matched_with_usable_prior": len(priors),
            "coverage_ratio": round(len(priors) / max(1, len(elements)), 4),
            "matched_by_stable_code": matched_by_code,
            "matched_by_unique_full_name": matched_by_name,
            "rejected_low_minutes": rejected_low_minutes,
        },
        "governance": policy.get("governance") or {},
    }


def run() -> dict[str, Any]:
    bootstrap, health = get_json("bootstrap-static/")
    if not bootstrap:
        raise RuntimeError(f"Official bootstrap unavailable for historical prior service: {health.get('status')}")
    payload, fetch_mode = _fetch_previous_season()
    prior = build_prior_index(list(bootstrap.get("elements") or []), payload)
    prior["fetch_mode"] = fetch_mode
    prior["source_health"] = health.get("status")
    atomic_json(PRIOR_OUT, prior)

    latest = read_json(DATA / "latest.json", {})
    latest.setdefault("files", {}).update({
        "prior_season": "data/prior_season.json",
        "vaastav_previous_season": "data/stats/vaastav_previous_season.json",
    })
    latest["historical_prior_summary"] = {
        "model": prior.get("model"),
        "season": prior.get("season"),
        "fetch_mode": fetch_mode,
        "coverage": prior.get("coverage"),
    }
    atomic_json(DATA / "latest.json", latest)
    return prior


if __name__ == "__main__":
    out = run()
    print(json.dumps({
        "model": out.get("model"),
        "season": out.get("season"),
        "fetch_mode": out.get("fetch_mode"),
        "coverage": out.get("coverage"),
    }, ensure_ascii=False))
