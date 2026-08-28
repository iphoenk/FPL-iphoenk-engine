from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any

import requests

from src.v5.config_cache import load_json_config
from src.v5.runtime_normalization import parse_utc_timestamp

CONFIG = "config/intelligence/historical_priors.json"


def _cfg() -> dict[str, Any]:
    data = load_json_config(CONFIG)
    if not isinstance(data.get("source"), dict) or not isinstance(data.get("governance"), dict):
        raise RuntimeError("invalid V5 historical prior registry")
    return data


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(now: datetime | None = None) -> str:
    return (now or _now()).astimezone(timezone.utc).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value in (None, "") else value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _norm_name(value: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in value).split())


def _previous_season_label(season: str | None) -> str:
    text = str(season or "").strip()
    if not text:
        raise RuntimeError("historical prior requires truth-service season")
    try:
        start = int(text[:4]) - 1
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid truth-service season for historical prior: {text}") from exc
    return f"{start}-{str(start + 1)[-2:]}"


def is_fresh(prior: dict[str, Any] | None, *, now: datetime | None = None) -> bool:
    if not isinstance(prior, dict) or not prior.get("players"):
        return False
    generated = parse_utc_timestamp(prior.get("generated_at") or prior.get("fetched_at"))
    if generated is None:
        return False
    age_hours = ((now or _now()) - generated).total_seconds() / 3600.0
    return age_hours <= float(_cfg().get("refresh_hours") or 168)


def build_prior_index(elements: list[dict[str, Any]], rows: list[dict[str, Any]], *, season: str, source: str) -> dict[str, Any]:
    cfg = _cfg()
    starter = cfg.get("starter_prior") or {}
    attack = cfg.get("attacking_prior") or {}
    by_code = {str(row.get("code")): row for row in rows if row.get("code") not in (None, "")}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        full = _norm_name(f"{row.get('first_name', '')} {row.get('second_name', '')}")
        if full:
            by_name.setdefault(full, []).append(row)

    minimum_minutes = float(starter.get("minimum_minutes") or 180)
    team_matches = max(1.0, float(starter.get("season_team_matches") or 38))
    team_weight = float(starter.get("team_start_share_weight") or 0.35)
    conditional_weight = float(starter.get("conditional_start_share_weight") or 0.65)
    probability_floor = float(starter.get("probability_floor") or 0.08)
    probability_ceiling = float(starter.get("probability_ceiling") or 0.97)
    attack_minimum = float(attack.get("minimum_minutes") or 180)
    full_weight_minutes = max(1.0, float(attack.get("full_weight_minutes") or 1800))
    max_attack_weight = _clamp(float(attack.get("maximum_player_weight") or 0.75), 0.0, 1.0)

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
            full = _norm_name(f"{player.get('first_name', '')} {player.get('second_name', '')}")
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
            probability_floor,
            probability_ceiling,
        )
        avg_minutes_when_start = _clamp(minutes / max(1.0, starts), 45.0, 90.0) if starts > 0 else 60.0

        xg90 = _f(row.get("expected_goals_per_90"), -1.0)
        xa90 = _f(row.get("expected_assists_per_90"), -1.0)
        if xg90 < 0 and minutes > 0:
            xg90 = 90.0 * max(0.0, _f(row.get("expected_goals"))) / minutes
        if xa90 < 0 and minutes > 0:
            xa90 = 90.0 * max(0.0, _f(row.get("expected_assists"))) / minutes
        attack_weight = 0.0
        if minutes >= attack_minimum:
            attack_weight = min(max_attack_weight, minutes / full_weight_minutes * max_attack_weight)

        priors[str(int(player["id"]))] = {
            "element": int(player["id"]),
            "web_name": player.get("web_name"),
            "minutes": round(minutes, 1),
            "starts": round(starts, 1),
            "team_start_share": round(team_start_share, 4),
            "conditional_start_share": round(conditional_start_share, 4),
            "start_probability": round(start_probability, 4),
            "avg_minutes_when_start": round(avg_minutes_when_start, 1),
            "xg90": round(max(0.0, xg90), 4),
            "xa90": round(max(0.0, xa90), 4),
            "attacking_prior_weight": round(attack_weight, 4),
            "source": f"{source}:{season}",
            "identity_match": identity_match,
        }

    return {
        "generated_at": _iso(),
        "status": "READY",
        "model": cfg.get("model_id"),
        "season": season,
        "source": source,
        "players": priors,
        "coverage": {
            "current_players": len(elements),
            "matched_with_usable_prior": len(priors),
            "coverage_ratio": round(len(priors) / max(1, len(elements)), 4),
            "matched_by_stable_code": matched_by_code,
            "matched_by_unique_full_name": matched_by_name,
            "rejected_low_minutes": rejected_low_minutes,
        },
        "governance": cfg.get("governance") or {},
    }


def _fetch_rows(season: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source = _cfg()["source"]
    base = str(source.get("base_url") or "").rstrip("/")
    if not base:
        raise RuntimeError("historical prior source base_url is required")
    timeout = float(source.get("timeout_seconds") or 25)
    last_error: str | None = None
    for filename in source.get("filenames") or []:
        url = f"{base}/{season}/{filename}"
        try:
            response = requests.get(url, timeout=timeout, headers={"Accept": "text/csv,*/*"})
            response.raise_for_status()
            rows = list(csv.DictReader(io.StringIO(response.text)))
            if not rows:
                raise RuntimeError("empty historical prior CSV")
            required = {"first_name", "second_name", "minutes"}
            columns = set(rows[0])
            if not required.issubset(columns):
                raise RuntimeError(f"historical prior schema missing: {sorted(required - columns)}")
            return rows, {"url": url, "filename": filename, "row_count": len(rows)}
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
    raise RuntimeError(f"historical prior source unavailable: {last_error}")


def resolve_prior(
    bootstrap: dict[str, Any],
    rules: dict[str, Any],
    *,
    previous_prior: dict[str, Any] | None = None,
    allow_network_refresh: bool = False,
) -> dict[str, Any]:
    previous = previous_prior if isinstance(previous_prior, dict) else {}
    if is_fresh(previous):
        return {**previous, "fetch_mode": "PERSISTED_CACHE", "cache_fresh": True}

    cfg = _cfg()
    source = cfg["source"]
    permitted = bool(source.get("allow_network_refresh", True)) and bool(allow_network_refresh)
    season = _previous_season_label(rules.get("season"))
    if permitted:
        try:
            rows, source_meta = _fetch_rows(season)
            prior = build_prior_index(
                list(bootstrap.get("elements") or []),
                rows,
                season=season,
                source=str(source.get("provider") or "historical-source"),
            )
            return {
                **prior,
                "fetch_mode": "NETWORK_REFRESH",
                "cache_fresh": True,
                "source_meta": source_meta,
            }
        except Exception as exc:
            if previous.get("players") and bool((cfg.get("governance") or {}).get("network_failure_may_use_stale_prior", True)):
                return {
                    **previous,
                    "status": "STALE",
                    "fetch_mode": "STALE_PRIOR_FALLBACK",
                    "cache_fresh": False,
                    "refresh_error": f"{type(exc).__name__}: {exc}",
                }
            return {
                "generated_at": _iso(),
                "status": "UNAVAILABLE",
                "model": cfg.get("model_id"),
                "season": season,
                "players": {},
                "coverage": {"current_players": len(bootstrap.get("elements") or []), "matched_with_usable_prior": 0, "coverage_ratio": 0.0},
                "fetch_mode": "NETWORK_FAILED_NO_PRIOR",
                "cache_fresh": False,
                "refresh_error": f"{type(exc).__name__}: {exc}",
                "governance": cfg.get("governance") or {},
            }

    if previous.get("players"):
        return {**previous, "fetch_mode": "STALE_PRIOR_NO_REFRESH", "cache_fresh": False}
    return {
        "generated_at": _iso(),
        "status": "UNAVAILABLE",
        "model": cfg.get("model_id"),
        "season": season,
        "players": {},
        "coverage": {"current_players": len(bootstrap.get("elements") or []), "matched_with_usable_prior": 0, "coverage_ratio": 0.0},
        "fetch_mode": "NO_PRIOR_NO_REFRESH",
        "cache_fresh": False,
        "governance": cfg.get("governance") or {},
    }
