from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from src.v5.config_cache import load_json_config

CONFIG = "config/intelligence/source_fusion.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cache_path(cache_dir: Path, key: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in key)
    return cache_dir / f"{safe}.json"


def _load_cache(path: Path, ttl_seconds: int) -> dict[str, Any] | None:
    if not path.exists() or (_now().timestamp() - path.stat().st_mtime) > ttl_seconds:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _get(session: requests.Session, base: str, headers: dict[str, str], endpoint: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
    response = session.get(f"{base.rstrip('/')}/{endpoint.lstrip('/')}", headers=headers, params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("API-Football returned non-object payload")
    errors = payload.get("errors")
    if errors:
        raise RuntimeError(f"API-Football errors: {errors}")
    return payload


def _competition_class(key: str) -> str:
    if key.startswith("uefa_"):
        return "EUROPE"
    if key in {"fa_cup", "efl_cup"}:
        return "DOMESTIC_CUP"
    if key == "club_friendlies":
        return "FRIENDLY"
    return "OTHER"


def _resolve_league(session: requests.Session, cfg: dict[str, Any], headers: dict[str, str], competition_key: str, aliases: list[str]) -> dict[str, Any] | None:
    cache_dir = Path(str(cfg["cache_dir"]))
    ttl = int(cfg["cache_ttl_seconds"])
    cache = _cache_path(cache_dir, f"league_{competition_key}_{cfg['season']}")
    cached = _load_cache(cache, ttl)
    if cached:
        return cached.get("league") if isinstance(cached.get("league"), dict) else None
    for alias in aliases:
        payload = _get(
            session,
            str(cfg["base_url"]),
            headers,
            "leagues",
            {"search": alias, "season": int(cfg["season"])},
            float(cfg["timeout_seconds"]),
        )
        candidates = payload.get("response") or []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            league = item.get("league") if isinstance(item.get("league"), dict) else {}
            seasons = item.get("seasons") if isinstance(item.get("seasons"), list) else []
            if league.get("id") is None:
                continue
            if seasons and not any(int(s.get("year") or 0) == int(cfg["season"]) for s in seasons if isinstance(s, dict)):
                continue
            resolved = {"id": int(league["id"]), "name": league.get("name"), "type": league.get("type"), "alias": alias}
            _write_cache(cache, {"generated_at": _now().isoformat(), "league": resolved})
            return resolved
    _write_cache(cache, {"generated_at": _now().isoformat(), "league": None})
    return None


def _normalize_team_name(value: Any) -> str:
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def collect(bootstrap: dict[str, Any]) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)["api_football"]
    if not cfg.get("enabled", False):
        return {"source": "api_football", "status": "DISABLED", "fixtures": []}
    key = os.getenv(str(cfg["api_key_env"]), "").strip()
    if not key:
        return {
            "source": "api_football",
            "status": "UNAVAILABLE",
            "reason": "API_KEY_MISSING",
            "fixtures": [],
            "governance": {"fail_neutral": True, "missing_is_unavailable_not_zero": True},
        }
    headers = {str(cfg["api_key_header"]): key}
    cache_dir = Path(str(cfg["cache_dir"]))
    ttl = int(cfg["cache_ttl_seconds"])
    from_date = (_now() - timedelta(days=int(cfg["fixture_window_days_before"]))).date().isoformat()
    to_date = (_now() + timedelta(days=int(cfg["fixture_window_days_after"]))).date().isoformat()
    fpl_teams = {
        _normalize_team_name(team.get("name") or team.get("short_name")): {
            "fpl_team_id": int(team["id"]),
            "name": team.get("name") or team.get("short_name"),
        }
        for team in bootstrap.get("teams") or []
        if isinstance(team, dict) and team.get("id") is not None
    }
    fixtures: list[dict[str, Any]] = []
    resolved: dict[str, Any] = {}
    failures: list[dict[str, Any]] = []
    try:
        with requests.Session() as session:
            for index, (competition_key, aliases) in enumerate((cfg.get("competitions") or {}).items()):
                if index >= int(cfg.get("max_competition_requests_per_refresh") or 6):
                    break
                league = _resolve_league(session, cfg, headers, competition_key, list(aliases or []))
                resolved[competition_key] = league
                if not league:
                    failures.append({"competition": competition_key, "reason": "LEAGUE_UNRESOLVED"})
                    continue
                cache = _cache_path(cache_dir, f"fixtures_{competition_key}_{from_date}_{to_date}")
                cached = _load_cache(cache, ttl)
                if cached:
                    response_rows = cached.get("response") or []
                else:
                    payload = _get(
                        session,
                        str(cfg["base_url"]),
                        headers,
                        "fixtures",
                        {"league": int(league["id"]), "season": int(cfg["season"]), "from": from_date, "to": to_date},
                        float(cfg["timeout_seconds"]),
                    )
                    response_rows = payload.get("response") or []
                    _write_cache(cache, {"generated_at": _now().isoformat(), "response": response_rows})
                for item in response_rows:
                    if not isinstance(item, dict):
                        continue
                    fixture = item.get("fixture") if isinstance(item.get("fixture"), dict) else {}
                    teams = item.get("teams") if isinstance(item.get("teams"), dict) else {}
                    home = teams.get("home") if isinstance(teams.get("home"), dict) else {}
                    away = teams.get("away") if isinstance(teams.get("away"), dict) else {}
                    matched = []
                    for side in (home, away):
                        key_name = _normalize_team_name(side.get("name"))
                        if key_name in fpl_teams:
                            matched.append(fpl_teams[key_name])
                    if not matched:
                        continue
                    for club in matched:
                        fixtures.append({
                            "fixture_id": fixture.get("id"),
                            "kickoff_time": fixture.get("date"),
                            "competition_key": competition_key,
                            "competition_class": _competition_class(competition_key),
                            "competition_name": league.get("name"),
                            "fpl_team_id": club["fpl_team_id"],
                            "fpl_team_name": club["name"],
                            "home": home.get("name"),
                            "away": away.get("name"),
                            "status": ((fixture.get("status") or {}).get("short") if isinstance(fixture.get("status"), dict) else None),
                        })
    except Exception as exc:
        return {
            "source": "api_football",
            "status": "UNAVAILABLE",
            "reason": f"{type(exc).__name__}:{exc}",
            "fixtures": fixtures,
            "resolved_competitions": resolved,
            "failures": failures,
            "governance": {"fail_neutral": True, "missing_is_unavailable_not_zero": True},
        }
    return {
        "source": "api_football",
        "status": "ACTIVE" if fixtures else "DEGRADED",
        "generated_at": _now().isoformat(),
        "window": {"from": from_date, "to": to_date},
        "fixtures": fixtures,
        "resolved_competitions": resolved,
        "failures": failures,
        "international": {
            "status": "UNAVAILABLE",
            "reason": "player-national-team identity mapping not yet resolved",
            "callup_behavior": (cfg.get("international") or {}).get("callup_missing_behavior"),
            "travel_behavior": (cfg.get("international") or {}).get("travel_missing_behavior"),
        },
        "governance": {"enrichment_only": True, "never_overrides_official_fpl": True},
    }
