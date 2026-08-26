from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import requests

from src.v5.config_cache import load_json_config
from src.v5.sources.season import season_authority

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


def _header_value(headers: requests.structures.CaseInsensitiveDict[str], names: list[str]) -> str | None:
    for name in names:
        value = headers.get(name)
        if value not in (None, ""):
            return str(value)
    return None


def _get(
    session: requests.Session,
    cfg: dict[str, Any],
    headers: dict[str, str],
    endpoint: str,
    params: dict[str, Any],
    observability: dict[str, Any],
) -> dict[str, Any]:
    response = session.get(
        f"{str(cfg['base_url']).rstrip('/')}/{endpoint.lstrip('/')}",
        headers=headers,
        params=params,
        timeout=float(cfg["timeout_seconds"]),
    )
    observability["network_requests"] += 1
    endpoint_requests = observability.setdefault("endpoint_requests", {})
    endpoint_requests[endpoint] = int(endpoint_requests.get(endpoint) or 0) + 1
    rate_cfg = cfg.get("rate_limit_headers") if isinstance(cfg.get("rate_limit_headers"), dict) else {}
    remaining = _header_value(response.headers, list(rate_cfg.get("remaining") or []))
    limit = _header_value(response.headers, list(rate_cfg.get("limit") or []))
    if remaining is not None:
        observability["quota_remaining"] = remaining
    if limit is not None:
        observability["quota_limit"] = limit
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


def _resolve_league(
    session: requests.Session,
    cfg: dict[str, Any],
    headers: dict[str, str],
    competition_key: str,
    aliases: list[str],
    season_start_year: int,
    observability: dict[str, Any],
) -> dict[str, Any] | None:
    cache_dir = Path(str(cfg["cache_dir"]))
    ttl = int(cfg["cache_ttl_seconds"])
    cache = _cache_path(cache_dir, f"league_{competition_key}_{season_start_year}")
    cached = _load_cache(cache, ttl)
    if cached is not None:
        observability["cache_hits"] += 1
        observability["league_cache_hits"] += 1
        return cached.get("league") if isinstance(cached.get("league"), dict) else None
    for alias in aliases:
        payload = _get(
            session,
            cfg,
            headers,
            "leagues",
            {"search": alias, "season": season_start_year},
            observability,
        )
        candidates = payload.get("response") or []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            league = item.get("league") if isinstance(item.get("league"), dict) else {}
            seasons = item.get("seasons") if isinstance(item.get("seasons"), list) else []
            if league.get("id") is None:
                continue
            if seasons and not any(
                int(s.get("year") or 0) == season_start_year for s in seasons if isinstance(s, dict)
            ):
                continue
            resolved = {
                "id": int(league["id"]),
                "name": league.get("name"),
                "type": league.get("type"),
                "matched_alias": alias,
            }
            _write_cache(cache, {"generated_at": _now().isoformat(), "league": resolved})
            return resolved
    _write_cache(cache, {"generated_at": _now().isoformat(), "league": None})
    return None


def _normalize_team_name(value: Any) -> str:
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def _official_team_candidates(bootstrap: dict[str, Any], include_short: bool) -> dict[int, dict[str, Any]]:
    candidates: dict[int, dict[str, Any]] = {}
    for team in bootstrap.get("teams") or []:
        if not isinstance(team, dict) or team.get("id") is None:
            continue
        team_id = int(team["id"])
        names = [team.get("name")]
        if include_short:
            names.append(team.get("short_name"))
        aliases = sorted({_normalize_team_name(name) for name in names if _normalize_team_name(name)})
        candidates[team_id] = {
            "fpl_team_id": team_id,
            "name": team.get("name") or team.get("short_name"),
            "aliases": aliases,
        }
    return candidates


def _match_team(api_name: Any, candidates: dict[int, dict[str, Any]], cfg: dict[str, Any]) -> tuple[dict[str, Any] | None, str, float]:
    normalized = _normalize_team_name(api_name)
    if not normalized:
        return None, "UNMATCHED", 0.0
    exact = [row for row in candidates.values() if normalized in row["aliases"]]
    if len(exact) == 1:
        return exact[0], "EXACT", 1.0
    scored = []
    for row in candidates.values():
        score = max((SequenceMatcher(None, normalized, alias).ratio() for alias in row["aliases"]), default=0.0)
        scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        return None, "UNMATCHED", 0.0
    best_score, best = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    match_cfg = cfg.get("team_matching") if isinstance(cfg.get("team_matching"), dict) else {}
    minimum = float(match_cfg.get("minimum_similarity") or 0.0)
    margin = float(match_cfg.get("minimum_unique_margin") or 0.0)
    if best_score >= minimum and (best_score - second_score) >= margin:
        return best, "FUZZY", round(best_score, 4)
    return None, "UNMATCHED", round(best_score, 4)


def _base_observability(cfg: dict[str, Any], credential_present: bool) -> dict[str, Any]:
    return {
        "credential_present": credential_present,
        "network_requests": 0,
        "endpoint_requests": {},
        "cache_hits": 0,
        "league_cache_hits": 0,
        "fixture_cache_hits": 0,
        "competitions_attempted": 0,
        "competitions_resolved": 0,
        "fixtures_returned": 0,
        "fixtures_matched_to_fpl_teams": 0,
        "team_matches_exact": 0,
        "team_matches_fuzzy": 0,
        "team_matches_unmatched": 0,
        "quota_remaining": None,
        "quota_limit": None,
        "cache_ttl_seconds": int(cfg.get("cache_ttl_seconds") or 0),
    }


def collect(bootstrap: dict[str, Any]) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)["api_football"]
    season = season_authority()
    season_start_year = int(season["start_year"])
    if not cfg.get("enabled", False):
        return {"source": "api_football", "status": "DISABLED", "fixtures": [], "season": season}
    key = os.getenv(str(cfg["api_key_env"]), "").strip()
    observability = _base_observability(cfg, bool(key))
    if not key:
        return {
            "source": "api_football",
            "status": "UNAVAILABLE",
            "reason": "API_KEY_MISSING",
            "fixtures": [],
            "season": season,
            "observability": observability,
            "governance": {"fail_neutral": True, "missing_is_unavailable_not_zero": True},
        }
    headers = {str(cfg["api_key_header"]): key}
    cache_dir = Path(str(cfg["cache_dir"]))
    ttl = int(cfg["cache_ttl_seconds"])
    from_date = (_now() - timedelta(days=int(cfg["fixture_window_days_before"]))).date().isoformat()
    to_date = (_now() + timedelta(days=int(cfg["fixture_window_days_after"]))).date().isoformat()
    match_cfg = cfg.get("team_matching") if isinstance(cfg.get("team_matching"), dict) else {}
    fpl_teams = _official_team_candidates(bootstrap, bool(match_cfg.get("include_official_short_name", True)))
    fixtures: list[dict[str, Any]] = []
    resolved: dict[str, Any] = {}
    failures: list[dict[str, Any]] = []
    try:
        with requests.Session() as session:
            for index, (competition_key, aliases) in enumerate((cfg.get("competitions") or {}).items()):
                if index >= int(cfg.get("max_competition_requests_per_refresh") or len(cfg.get("competitions") or {})):
                    break
                observability["competitions_attempted"] += 1
                league = _resolve_league(
                    session,
                    cfg,
                    headers,
                    competition_key,
                    list(aliases or []),
                    season_start_year,
                    observability,
                )
                resolved[competition_key] = league
                if not league:
                    failures.append({"competition": competition_key, "reason": "LEAGUE_UNRESOLVED"})
                    continue
                observability["competitions_resolved"] += 1
                cache = _cache_path(cache_dir, f"fixtures_{competition_key}_{season_start_year}_{from_date}_{to_date}")
                cached = _load_cache(cache, ttl)
                if cached is not None:
                    observability["cache_hits"] += 1
                    observability["fixture_cache_hits"] += 1
                    response_rows = cached.get("response") or []
                else:
                    payload = _get(
                        session,
                        cfg,
                        headers,
                        "fixtures",
                        {"league": int(league["id"]), "season": season_start_year, "from": from_date, "to": to_date},
                        observability,
                    )
                    response_rows = payload.get("response") or []
                    _write_cache(cache, {"generated_at": _now().isoformat(), "response": response_rows})
                observability["fixtures_returned"] += len(response_rows)
                for item in response_rows:
                    if not isinstance(item, dict):
                        continue
                    fixture = item.get("fixture") if isinstance(item.get("fixture"), dict) else {}
                    teams = item.get("teams") if isinstance(item.get("teams"), dict) else {}
                    home = teams.get("home") if isinstance(teams.get("home"), dict) else {}
                    away = teams.get("away") if isinstance(teams.get("away"), dict) else {}
                    matched_clubs: list[dict[str, Any]] = []
                    for side in (home, away):
                        matched, mode, similarity = _match_team(side.get("name"), fpl_teams, cfg)
                        if matched is None:
                            observability["team_matches_unmatched"] += 1
                            continue
                        observability[f"team_matches_{mode.casefold()}"] += 1
                        matched_clubs.append({**matched, "match_mode": mode, "similarity": similarity})
                    for club in matched_clubs:
                        fixtures.append({
                            "fixture_id": fixture.get("id"),
                            "kickoff_time": fixture.get("date"),
                            "competition_key": competition_key,
                            "competition_class": _competition_class(competition_key),
                            "competition_name": league.get("name"),
                            "fpl_team_id": club["fpl_team_id"],
                            "fpl_team_name": club["name"],
                            "identity_match_mode": club["match_mode"],
                            "identity_similarity": club["similarity"],
                            "home": home.get("name"),
                            "away": away.get("name"),
                            "status": ((fixture.get("status") or {}).get("short") if isinstance(fixture.get("status"), dict) else None),
                        })
        observability["fixtures_matched_to_fpl_teams"] = len(fixtures)
    except Exception as exc:
        return {
            "source": "api_football",
            "status": "UNAVAILABLE",
            "reason": f"{type(exc).__name__}:{exc}",
            "fixtures": fixtures,
            "season": season,
            "resolved_competitions": resolved,
            "failures": failures,
            "observability": observability,
            "governance": {"fail_neutral": True, "missing_is_unavailable_not_zero": True},
        }
    resolved_count = int(observability["competitions_resolved"])
    return {
        "source": "api_football",
        "status": "ACTIVE" if resolved_count > 0 else "DEGRADED",
        "evidence_status": "AVAILABLE" if fixtures else "EMPTY_WINDOW_OR_NO_FPL_TEAM_MATCH",
        "generated_at": _now().isoformat(),
        "season": season,
        "window": {"from": from_date, "to": to_date},
        "fixtures": fixtures,
        "resolved_competitions": resolved,
        "failures": failures,
        "observability": observability,
        "international": {
            "status": "UNAVAILABLE",
            "reason": "player-national-team identity mapping not yet resolved",
            "callup_behavior": (cfg.get("international") or {}).get("callup_missing_behavior"),
            "travel_behavior": (cfg.get("international") or {}).get("travel_missing_behavior"),
        },
        "governance": {
            "enrichment_only": True,
            "never_overrides_official_fpl": True,
            "league_ids_resolved_dynamically": bool(cfg.get("resolve_league_ids_dynamically")),
            "club_identity_has_no_hardcoded_team_alias_map": True,
        },
    }
