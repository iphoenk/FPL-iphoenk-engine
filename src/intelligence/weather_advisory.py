from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

import requests

from src.utils import CONFIG, ROOT, iso_now, parse_dt

CONFIG_PATH = CONFIG / "intelligence" / "weather_context.json"

EVIDENCE_PRECEDENCE = {
    "LIVE_OBSERVED": 4,
    "CLOSEST_TO_KICKOFF_OBSERVATION": 3,
    "FRESH_FORECAST": 2,
    "STALE_FORECAST": 1,
}
PLAYER_DIMENSIONS = {
    "GK": ["handling", "distribution", "rebound_error_risk"],
    "DEF": ["footing", "turning_recovery", "clearances", "aerials", "build_up", "set_piece_defence"],
    "MID": ["first_touch", "press_resistance", "passing", "carrying", "transition_involvement", "set_pieces"],
    "FWD": ["acceleration", "dribbling", "transition_threat", "error_exploitation", "finishing_environment"],
}
INCIDENT_TYPES = {
    "SLIP", "HANDLING_ERROR", "MISCONTROL", "BALL_SKID", "CLEARANCE_ERROR",
    "REPEATED_TURNOVER", "SET_PIECE_DISRUPTION",
}


@lru_cache(maxsize=1)
def load_weather_policy() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_venues() -> dict[str, Any]:
    cfg = load_weather_policy()
    return json.loads((ROOT / str(cfg["venue_registry"])).read_text(encoding="utf-8"))


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = parse_dt(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return float(default)


def classify_weather(observation: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = policy or load_weather_policy()
    weather = observation.get("weather") or {}
    severity = "NORMAL"
    signals: list[str] = []
    for label in ("EXTREME", "ADVERSE", "NOTABLE"):
        level = (cfg.get("severity") or {}).get(label) or {}
        triggered: list[str] = []
        if _f(weather.get("wind_speed_kmh")) >= _f(level.get("wind_speed_kmh"), 1e9):
            triggered.append("wind_speed")
        if _f(weather.get("wind_gust_kmh")) >= _f(level.get("wind_gust_kmh"), 1e9):
            triggered.append("wind_gust")
        if _f(weather.get("precipitation_mm_h")) >= _f(level.get("precipitation_mm_h"), 1e9):
            triggered.append("precipitation_intensity")
        temp = weather.get("temperature_c")
        if temp is not None and _f(temp) <= _f(level.get("cold_c"), -1e9):
            triggered.append("cold")
        if temp is not None and _f(temp) >= _f(level.get("heat_c"), 1e9):
            triggered.append("heat")
        if triggered:
            severity, signals = label, triggered
            break
    governance = dict(cfg.get("governance") or {})
    return {
        **observation,
        "status": "AVAILABLE" if weather else "UNAVAILABLE",
        "mode": "ADVISORY_ONLY",
        "severity": severity,
        "signals": signals,
        "decision_effect": "CONTEXT_ONLY_NO_DIRECT_SCORE_MUTATION",
        "post_match_attribution_label": governance.get("post_match_attribution_label", "POSSIBLE_CONTRIBUTING_FACTOR"),
        "governance": governance,
    }


def assert_advisory_governance(policy: dict[str, Any] | None = None) -> None:
    governance = dict((policy or load_weather_policy()).get("governance") or {})
    forbidden = (
        "may_directly_change_xpts",
        "may_directly_change_xmins",
        "may_directly_change_captaincy",
        "may_directly_change_starting_xi",
        "may_directly_change_transfer_decision",
        "may_directly_change_watchlist_membership",
    )
    if governance.get("advisory_only") is not True or any(governance.get(key) is not False for key in forbidden):
        raise RuntimeError("weather governance must remain advisory-only with direct decision mutation forbidden")


def _venue_map() -> dict[str, dict[str, Any]]:
    registry = load_venues()
    default_tz = str(registry.get("default_timezone") or "Europe/London")
    return {
        str(row["team_name"]): {**row, "timezone": str(row.get("timezone") or default_tz)}
        for row in registry.get("venues") or []
        if row.get("team_name")
    }


def _forecast_for_fixture(
    venue: dict[str, Any],
    kickoff: datetime,
    *,
    fetcher=requests.get,
    now: datetime | None = None,
) -> dict[str, Any]:
    cfg = load_weather_policy()
    api = cfg.get("api") or {}
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    tz_name = str(venue.get("timezone") or "Europe/London")
    local = kickoff.astimezone(ZoneInfo(tz_name))
    fields = [str(x) for x in api.get("hourly_fields") or []]
    response = fetcher(
        str(api["forecast_url"]),
        params={
            "latitude": float(venue["latitude"]),
            "longitude": float(venue["longitude"]),
            "hourly": ",".join(fields),
            "timezone": tz_name,
            "start_date": local.date().isoformat(),
            "end_date": local.date().isoformat(),
        },
        timeout=float(api.get("request_timeout_seconds") or 10),
    )
    response.raise_for_status()
    hourly = (response.json() or {}).get("hourly") or {}
    times = list(hourly.get("time") or [])
    target = local.strftime("%Y-%m-%dT%H:00")
    if target not in times:
        raise ValueError("kickoff hour unavailable in weather response")
    idx = times.index(target)

    def value(name: str):
        values = hourly.get(name) or []
        return values[idx] if idx < len(values) else None

    raw = {
        "source_kind": "FRESH_FORECAST",
        "evidence_timestamp": current.isoformat(),
        "forecast_for": kickoff.isoformat(),
        "weather": {
            "temperature_c": value("temperature_2m"),
            "precipitation_probability_pct": value("precipitation_probability"),
            "precipitation_mm_h": value("precipitation"),
            "wind_speed_kmh": value("wind_speed_10m"),
            "wind_gust_kmh": value("wind_gusts_10m"),
            "weather_code": value("weather_code"),
        },
        "provenance": {
            "provider": cfg.get("provider_source_id"),
            "endpoint": str(api.get("forecast_url")),
            "venue": venue.get("venue"),
            "latitude": venue.get("latitude"),
            "longitude": venue.get("longitude"),
            "timezone": tz_name,
            "evidence_type": "FORECAST",
        },
    }
    return classify_weather(raw, cfg)


def _normalize_source_kind(row: dict[str, Any], *, now: datetime, kickoff: datetime | None, cfg: dict[str, Any]) -> str:
    raw = str(row.get("source_kind") or row.get("evidence_state") or "FRESH_FORECAST").upper()
    aliases = {
        "LIVE_OBSERVED_ADVISORY": "LIVE_OBSERVED",
        "OBSERVED": "CLOSEST_TO_KICKOFF_OBSERVATION",
        "FORECAST": "FRESH_FORECAST",
    }
    kind = aliases.get(raw, raw)
    stamp = _dt(row.get("evidence_timestamp") or row.get("fetched_at") or row.get("generated_at"))
    policy = cfg.get("evidence_policy") or {}
    if kind == "LIVE_OBSERVED":
        live_max = _f(policy.get("live_observed_max_age_minutes"), 90)
        if stamp is None or (now - stamp).total_seconds() / 60.0 > live_max:
            kind = "CLOSEST_TO_KICKOFF_OBSERVATION" if kickoff else "STALE_FORECAST"
    if kind in {"FRESH_FORECAST", "STALE_FORECAST"}:
        fresh = _f(policy.get("fresh_forecast_max_age_minutes"), 360)
        age = (now - stamp).total_seconds() / 60.0 if stamp else 1e9
        kind = "FRESH_FORECAST" if age <= fresh else "STALE_FORECAST"
    return kind if kind in EVIDENCE_PRECEDENCE else "STALE_FORECAST"


def select_weather_evidence(
    evidence: list[dict[str, Any]],
    *,
    kickoff: datetime | str | None = None,
    now: datetime | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    cfg = policy or load_weather_policy()
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    kick = _dt(kickoff)
    normalized: list[dict[str, Any]] = []
    for raw in evidence:
        if not isinstance(raw, dict) or not (raw.get("weather") or {}):
            continue
        row = classify_weather(dict(raw), cfg)
        kind = _normalize_source_kind(row, now=current, kickoff=kick, cfg=cfg)
        row["source_kind"] = kind
        normalized.append(row)
    if not normalized:
        return None

    live = [row for row in normalized if row["source_kind"] == "LIVE_OBSERVED"]
    if live:
        return max(live, key=lambda row: _dt(row.get("evidence_timestamp")) or datetime.min.replace(tzinfo=timezone.utc))

    observed = [row for row in normalized if row["source_kind"] == "CLOSEST_TO_KICKOFF_OBSERVATION"]
    if observed:
        if kick:
            return min(
                observed,
                key=lambda row: abs(((_dt(row.get("evidence_timestamp")) or datetime.min.replace(tzinfo=timezone.utc)) - kick).total_seconds()),
            )
        return max(observed, key=lambda row: _dt(row.get("evidence_timestamp")) or datetime.min.replace(tzinfo=timezone.utc))

    forecasts = sorted(
        normalized,
        key=lambda row: (
            EVIDENCE_PRECEDENCE[row["source_kind"]],
            _dt(row.get("evidence_timestamp")) or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    return forecasts[0] if forecasts else None


def player_weather_sensitivity(position: str, selected: dict[str, Any] | None, role: str | None = None) -> dict[str, Any]:
    position = str(position or "").upper()
    dimensions = PLAYER_DIMENSIONS.get(position, [])
    if not selected or selected.get("severity") == "NORMAL":
        return {
            "position": position,
            "archetype": role or position,
            "affected_dimensions": [],
            "risk_band": "NORMAL",
            "blanket_modifier_applied": False,
        }
    signals = set(selected.get("signals") or [])
    wet = "precipitation_intensity" in signals
    windy = bool(signals & {"wind_speed", "wind_gust"})
    heat_cold = bool(signals & {"heat", "cold"})
    affected: list[str] = []
    for dimension in dimensions:
        if wet and dimension in {
            "handling", "rebound_error_risk", "footing", "turning_recovery", "clearances", "build_up",
            "first_touch", "press_resistance", "passing", "carrying", "transition_involvement",
            "acceleration", "dribbling", "transition_threat", "error_exploitation", "finishing_environment",
        }:
            affected.append(dimension)
        if windy and dimension in {
            "distribution", "aerials", "set_piece_defence", "passing", "set_pieces", "finishing_environment",
        }:
            affected.append(dimension)
        if heat_cold and dimension in {"turning_recovery", "press_resistance", "carrying", "transition_involvement", "acceleration"}:
            affected.append(dimension)
    if not affected:
        affected = dimensions[:]
    risk = {"NOTABLE": "ELEVATED", "ADVERSE": "HIGH", "EXTREME": "VERY_HIGH"}.get(str(selected.get("severity")), "NORMAL")
    return {
        "position": position,
        "archetype": role or position,
        "affected_dimensions": list(dict.fromkeys(affected)),
        "risk_band": risk,
        "blanket_modifier_applied": False,
    }


def _text_blob(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_text_blob(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_text_blob(item) for item in value)
    return str(value or "").lower()


def system_weather_interactions(
    selected: dict[str, Any] | None,
    *,
    own_system: dict[str, Any] | None = None,
    opponent_system: dict[str, Any] | None = None,
    role: str | None = None,
) -> list[dict[str, Any]]:
    if not selected or selected.get("severity") == "NORMAL":
        return []
    own = _text_blob(own_system or {})
    opp = _text_blob(opponent_system or {})
    signals = set(selected.get("signals") or [])
    wet = "precipitation_intensity" in signals
    windy = bool(signals & {"wind_speed", "wind_gust"})
    interactions: list[dict[str, Any]] = []
    if wet and ("short" in own or "build" in own) and ("press" in opp or "aggressive" in opp):
        interactions.append({
            "interaction": "WET_SHORT_BUILDUP_VS_AGGRESSIVE_PRESS",
            "effect": "TURNOVER_AND_TRANSITION_VARIANCE_ELEVATED",
            "role": role,
        })
    if wet and ("high line" in own or "high defensive" in own or "high line" in opp or "high defensive" in opp):
        interactions.append({
            "interaction": "WET_SURFACE_WITH_HIGH_DEFENSIVE_LINE",
            "effect": "RECOVERY_AND_ERROR_DISTRIBUTION_VARIANCE_ELEVATED",
            "role": role,
        })
    if windy and any(term in f"{own} {opp}" for term in ("cross", "set piece", "set-piece", "aerial")):
        interactions.append({
            "interaction": "STRONG_WIND_WITH_DELIVERY_RELIANCE",
            "effect": "CROSS_AND_SET_PIECE_DELIVERY_VARIANCE_ELEVATED",
            "role": role,
        })
    return interactions


def attribute_live_weather_incidents(
    incidents: list[dict[str, Any]] | None,
    selected: dict[str, Any] | None,
) -> dict[str, Any]:
    credible = []
    for row in incidents or []:
        kind = str(row.get("type") or row.get("incident_type") or "").upper().replace(" ", "_")
        if kind not in INCIDENT_TYPES:
            continue
        if row.get("credible") is not True and row.get("verified") is not True:
            continue
        credible.append({**row, "incident_type": kind, "attribution": "POSSIBLE_CONTRIBUTING_FACTOR"})
    if not selected or selected.get("severity") == "NORMAL" or not credible:
        return {
            "state": "NONE",
            "confidence": "NONE",
            "label": "POSSIBLE_CONTRIBUTING_FACTOR",
            "credible_incidents": credible,
            "causal_claim": False,
        }
    repeated = len(credible) >= 2
    return {
        "state": "MATERIAL_ADVISORY" if repeated else "LOW_CONFIDENCE",
        "confidence": "MATERIAL_ADVISORY" if repeated else "LOW",
        "label": "POSSIBLE_CONTRIBUTING_FACTOR",
        "credible_incidents": credible,
        "causal_claim": False,
        "one_incident_never_material": True,
    }


def weather_uncertainty_advisory(
    selected: dict[str, Any] | None,
    sensitivity: dict[str, Any] | None = None,
    interactions: list[dict[str, Any]] | None = None,
    attribution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    severity = str((selected or {}).get("severity") or "NORMAL")
    material = bool(interactions) or str((attribution or {}).get("state")) == "MATERIAL_ADVISORY"
    if severity == "NORMAL":
        state = "BASELINE"
    elif severity == "NOTABLE" and not material:
        state = "ELEVATED"
    else:
        state = "HIGH"
    return {
        "state": state,
        "confidence": "BASELINE" if state == "BASELINE" else "REDUCED",
        "variance": "BASELINE" if state == "BASELINE" else "WIDER_ADVISORY",
        "floor_ceiling": "BASELINE" if state == "BASELINE" else "WIDER_ADVISORY",
        "tactical_risk": (sensitivity or {}).get("risk_band", "NORMAL"),
        "expected_xpts_mean_adjustment": 0.0,
        "numeric_weather_coefficient_applied": False,
        "uncertainty_first": True,
    }


def _weather_health(rows: list[dict[str, Any]], required: bool) -> tuple[str, str]:
    if not rows:
        return "PASS", "NO_RELEVANT_FIXTURES"
    selected = [row.get("selected_evidence") for row in rows if row.get("selected_evidence")]
    missing = sum(row.get("selected_evidence") is None for row in rows)
    if not selected:
        return ("UNAVAILABLE" if required else "PARTIAL"), "NO_WEATHER_EVIDENCE"
    kinds = {str(row.get("source_kind")) for row in selected}
    if missing:
        return "PARTIAL", "SOME_FIXTURES_UNAVAILABLE"
    if kinds == {"STALE_FORECAST"}:
        return "STALE", "ONLY_STALE_FORECAST_AVAILABLE"
    if "STALE_FORECAST" in kinds:
        return "PARTIAL", "MIXED_FRESH_AND_STALE_EVIDENCE"
    return "PASS", "GOVERNED_WEATHER_EVIDENCE_AVAILABLE"


def collect_weather_context(
    snapshot: dict[str, Any],
    *,
    previous: dict[str, Any] | None = None,
    live_evidence: dict[str, Any] | None = None,
    now: datetime | None = None,
    fetcher=requests.get,
) -> dict[str, Any]:
    assert_advisory_governance()
    cfg = load_weather_policy()
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    forecast_policy = cfg.get("forecast_policy") or {}
    max_days = _f(forecast_policy.get("max_horizon_days"), 7)
    post_hours = _f(forecast_policy.get("post_match_retention_hours"), 48)
    keep = max(1, int(forecast_policy.get("retain_evidence_per_fixture") or 12))
    required = bool((cfg.get("health") or {}).get("required_for_tactical_context", True))
    official = snapshot.get("official") or {}
    bootstrap = official.get("bootstrap") or {}
    teams = {int(row["id"]): str(row.get("name")) for row in bootstrap.get("teams") or [] if row.get("id") is not None}
    venues = _venue_map()
    prior_by_id = {str(row.get("fixture_id")): row for row in (previous or {}).get("fixtures") or []}
    live_by_id = {str(row.get("fixture_id")): row for row in (live_evidence or {}).get("fixtures") or []}
    fixture_rows: list[tuple[dict[str, Any], datetime, str, str, dict[str, Any] | None, list[dict[str, Any]]]] = []

    for fixture in official.get("fixtures") or []:
        kickoff = _dt(fixture.get("kickoff_time"))
        if kickoff is None:
            continue
        days_to = (kickoff - current).total_seconds() / 86400.0
        age_hours = (current - kickoff).total_seconds() / 3600.0
        if days_to > max_days or age_hours > post_hours:
            continue
        fixture_id = str(fixture.get("id"))
        home = teams.get(int(fixture.get("team_h") or -1), "Unknown")
        away = teams.get(int(fixture.get("team_a") or -1), "Unknown")
        venue = venues.get(home)
        history = [
            dict(row) for row in (prior_by_id.get(fixture_id) or {}).get("evidence_history") or []
            if isinstance(row, dict)
        ]
        live_row = live_by_id.get(fixture_id) or {}
        history.extend(dict(row) for row in live_row.get("evidence") or [] if isinstance(row, dict))
        fixture_rows.append((fixture, kickoff, home, away, venue, history))

    future_jobs: dict[Any, int] = {}
    fetched: dict[int, dict[str, Any]] = {}
    max_workers = max(1, min(int((cfg.get("api") or {}).get("max_concurrency") or 4), len(fixture_rows) or 1))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="v4-weather") as pool:
        for idx, (fixture, kickoff, _home, _away, venue, _history) in enumerate(fixture_rows):
            if venue is not None and kickoff >= current:
                future_jobs[pool.submit(_forecast_for_fixture, venue, kickoff, fetcher=fetcher, now=current)] = idx
        for future in as_completed(future_jobs):
            idx = future_jobs[future]
            try:
                fetched[idx] = future.result()
            except Exception as exc:
                fetched[idx] = {"error": f"{type(exc).__name__}: {exc}"}

    rows: list[dict[str, Any]] = []
    for idx, (fixture, kickoff, home, away, venue, history) in enumerate(fixture_rows):
        fetch_result = fetched.get(idx)
        fetch_error = None
        if fetch_result and fetch_result.get("weather"):
            history.append(fetch_result)
        elif fetch_result and fetch_result.get("error"):
            fetch_error = fetch_result["error"]
        history = history[-keep:]
        selected = select_weather_evidence(history, kickoff=kickoff, now=current, policy=cfg)
        live_incidents = (live_by_id.get(str(fixture.get("id"))) or {}).get("incidents") or []
        attribution = attribute_live_weather_incidents(live_incidents, selected)
        rows.append({
            "fixture_id": int(fixture.get("id") or 0),
            "event": fixture.get("event"),
            "home_team": home,
            "away_team": away,
            "kickoff_time": kickoff.isoformat(),
            "started": bool(fixture.get("started")),
            "finished": bool(fixture.get("finished")),
            "venue": (venue or {}).get("venue"),
            "venue_status": "RESOLVED" if venue else "UNAVAILABLE",
            "fetch_error": fetch_error,
            "selected_evidence": selected,
            "evidence_state": (selected or {}).get("source_kind") or "UNAVAILABLE",
            "severity": (selected or {}).get("severity") or "NORMAL",
            "live_attribution": attribution,
            "evidence_history": history,
        })

    health, reason = _weather_health(rows, required)
    tactical_completeness = "FULL" if health == "PASS" else "PARTIAL" if required else "OPTIONAL_PARTIAL"
    return {
        "schema_version": 1,
        "contract": "V4_WEATHER_CONTEXT_RUNTIME_V1",
        "model": cfg.get("model_id"),
        "generated_at": current.isoformat(),
        "provider": cfg.get("provider_source_id"),
        "evidence_precedence": list(EVIDENCE_PRECEDENCE),
        "health": {
            "status": health,
            "reason": reason,
            "required_for_tactical_context": required,
            "tactical_context_completeness": tactical_completeness,
        },
        "fixture_count": len(rows),
        "available_count": sum(row.get("selected_evidence") is not None for row in rows),
        "material_count": sum(row.get("severity") in {"NOTABLE", "ADVERSE", "EXTREME"} for row in rows),
        "fixtures": rows,
        "governance": {
            **dict(cfg.get("governance") or {}),
            "evidence_precedence_enforced": True,
            "player_archetype_specific": True,
            "system_interaction_required_for_tactical_interpretation": True,
            "uncertainty_first": True,
            "expected_xpts_mean_adjustment": 0.0,
            "numeric_weather_coefficient_applied": False,
        },
    }


def apply_weather_pipeline_health(
    health: dict[str, Any],
    weather: dict[str, Any] | None,
    tactical: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = dict(health)
    weather_health = (weather or {}).get("health") or {}
    status = str(weather_health.get("status") or "UNAVAILABLE").upper()
    if status not in {"PASS", "PARTIAL", "STALE", "UNAVAILABLE"}:
        status = "UNAVAILABLE"
    required = bool(weather_health.get("required_for_tactical_context", True))
    tactical_completeness = str(
        ((tactical or {}).get("weather_context") or {}).get("tactical_context_completeness")
        or weather_health.get("tactical_context_completeness")
        or ("FULL" if status == "PASS" else "PARTIAL" if required else "OPTIONAL_PARTIAL")
    )
    out["weather_context"] = {
        "status": status,
        "provider": (weather or {}).get("provider"),
        "model": (weather or {}).get("model"),
        "fixture_count": (weather or {}).get("fixture_count"),
        "available_count": (weather or {}).get("available_count"),
        "material_count": (weather or {}).get("material_count"),
        "required_for_tactical_context": required,
        "tactical_context_completeness": tactical_completeness,
        "reason": weather_health.get("reason"),
    }
    out["engine_pipeline_health"] = {
        "Core Pipeline": out.get("pipeline_health"),
        "Weather Context": status,
        "Tactical Context Completeness": tactical_completeness,
    }
    out.setdefault("governance", {})["weather_unavailable_downgrades_tactical_completeness"] = True
    out["governance"]["weather_does_not_false-red_core_pipeline"] = True
    return out
