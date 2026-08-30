from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/intelligence/weather_context.json"


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _severity(weather: dict[str, Any], cfg: dict[str, Any]) -> tuple[str, list[str]]:
    precip = _float(weather.get("precipitation_mm_h")) or 0.0
    wind = _float(weather.get("wind_speed_kmh")) or 0.0
    gust = _float(weather.get("wind_gust_kmh")) or 0.0
    temp = _float(weather.get("temperature_c"))
    for label in ("EXTREME", "ADVERSE", "NOTABLE"):
        band = (cfg.get("severity") or {}).get(label) or {}
        signals: list[str] = []
        if wind >= float(band.get("wind_speed_kmh") or 1e9): signals.append("wind_speed")
        if gust >= float(band.get("wind_gust_kmh") or 1e9): signals.append("wind_gust")
        if precip >= float(band.get("precipitation_mm_h") or 1e9): signals.append("precipitation_intensity")
        if temp is not None and temp <= float(band.get("cold_c") if band.get("cold_c") is not None else -1e9): signals.append("cold")
        if temp is not None and temp >= float(band.get("heat_c") if band.get("heat_c") is not None else 1e9): signals.append("heat")
        if signals:
            return label, signals
    return "NORMAL", []


def _source_kind(snapshot: dict[str, Any]) -> str:
    raw = str(snapshot.get("source_kind") or snapshot.get("observation_kind") or "FRESH_FORECAST").upper()
    aliases = {"FORECAST_ADVISORY": "FRESH_FORECAST", "LIVE_OBSERVED_ADVISORY": "LIVE_OBSERVED", "CLOSEST_TO_KICKOFF": "CLOSEST_TO_KICKOFF_OBSERVATION"}
    return aliases.get(raw, raw)


def select_governed_snapshot(snapshots: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    cfg = load_json_config(CONFIG)
    precedence = list(cfg.get("evidence_precedence") or [])
    ranked = {kind: i for i, kind in enumerate(precedence)}
    valid = [dict(item) for item in (snapshots or []) if isinstance(item, dict)]
    if not valid:
        return None
    valid.sort(key=lambda item: (ranked.get(_source_kind(item), len(ranked)), -(_dt(item.get("evidence_timestamp") or item.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)).timestamp()))
    return valid[0]


def classify_weather(observation: dict[str, Any] | None, *, now: datetime | None = None) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)
    governance = dict(cfg.get("governance") or {})
    raw = dict(observation or {})
    weather = raw.get("weather") if isinstance(raw.get("weather"), dict) else raw
    severity, signals = _severity(weather, cfg)
    kind = _source_kind(raw)
    ts = _dt(raw.get("evidence_timestamp") or raw.get("timestamp"))
    age_h = None
    if ts:
        age_h = max(0.0, ((now or datetime.now(timezone.utc)) - ts.astimezone(timezone.utc)).total_seconds() / 3600.0)
    stale = kind == "STALE_FORECAST" or (age_h is not None and age_h > 12 and "FORECAST" in kind)
    confidence = _float(raw.get("confidence"))
    health = "UNAVAILABLE" if not observation else ("STALE" if stale else ("PARTIAL" if confidence is not None and confidence < 0.5 else "PASS"))
    state = {"LIVE_OBSERVED": "LIVE_OBSERVED", "CLOSEST_TO_KICKOFF_OBSERVATION": "CLOSEST_TO_KICKOFF", "POST_MATCH_RECONCILED": "POST_MATCH_RECONCILED"}.get(kind, "FORECAST")
    return {
        "status": "AVAILABLE" if observation else "UNAVAILABLE",
        "health": health,
        "mode": "SHADOW_ADVISORY_ONLY",
        "evidence_state": state,
        "source_kind": kind,
        "severity": severity,
        "signals": signals,
        "freshness_hours": round(age_h, 3) if age_h is not None else None,
        "confidence": confidence,
        "weather": {
            "temperature_c": _float(weather.get("temperature_c")),
            "precipitation_probability_pct": _float(weather.get("precipitation_probability_pct")),
            "precipitation_mm_h": _float(weather.get("precipitation_mm_h")) or 0.0,
            "wind_speed_kmh": _float(weather.get("wind_speed_kmh")) or 0.0,
            "wind_gust_kmh": _float(weather.get("wind_gust_kmh")) or 0.0,
            "weather_code": weather.get("weather_code"),
        },
        "decision_effect": "CONTEXT_ONLY_NO_DIRECT_SCORE_MUTATION",
        "post_match_attribution_label": "POSSIBLE_CONTRIBUTING_FACTOR",
        "governance": governance,
    }


def build_weather_shadow_evidence(*, snapshots: list[dict[str, Any]] | None = None, observed_effects: dict[str, Any] | None = None, interactions: dict[str, Any] | None = None, confounders: dict[str, Any] | None = None, calibration: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)
    selected = select_governed_snapshot(snapshots)
    context = classify_weather(selected)
    effects = {name: (observed_effects or {}).get(name) for name in cfg.get("observed_match_effects") or [] if (observed_effects or {}).get(name) is not None}
    required_confounders = list((cfg.get("governance") or {}).get("alternative_explanations_required") or [])
    controlled = {name: (confounders or {}).get(name) for name in required_confounders}
    cal = dict(calibration or {})
    checks = {name: bool(cal.get(name)) for name in cfg.get("validation_requirements") or []}
    sample = int(cal.get("sample_size") or 0)
    if cal.get("rejected_signal"):
        research_state = "REJECTED_SIGNAL"
    elif all(checks.values()) and checks:
        research_state = "VALIDATED_CANDIDATE"
    elif sample < int(cal.get("minimum_sample") or 30):
        research_state = "INSUFFICIENT_SAMPLE"
    elif any(checks.values()):
        research_state = "CALIBRATING"
    else:
        research_state = "EXPLORATORY"
    return {
        "schema_version": 1,
        "mode": "SHADOW_ADVISORY_ONLY",
        "weather_context": context,
        "forecast_snapshots": list(snapshots or []),
        "observed_match_effects": effects,
        "attribution": "POSSIBLE_CONTRIBUTING_FACTOR" if effects else None,
        "research_interactions": {name: (interactions or {}).get(name) for name in cfg.get("research_interactions") or []},
        "confounders": controlled,
        "candidate_signals": {name: None for name in cfg.get("candidate_signals") or []},
        "calibration": {"matched_non_weather_baseline_required": True, "checks": checks, **cal},
        "research_state": research_state,
        "sustainability": {name: None for name in (cfg.get("governance") or {}).get("sustainability_dimensions") or []},
        "promotion_gate": {"state": "SHADOW_ADVISORY_ONLY", "quantitative_signal_authorized": False, "requires_all_validation_and_explicit_governance": True},
    }


def assert_advisory_governance() -> None:
    g = load_json_config(CONFIG).get("governance") or {}
    forbidden = ("may_directly_change_xpts", "may_directly_change_xmins", "may_directly_change_captaincy", "may_directly_change_starting_xi", "may_directly_change_transfer_decision", "may_directly_change_watchlist_membership")
    if not g.get("advisory_only") or g.get("production_decision_authority") or g.get("weather_caused_label_allowed") or any(bool(g.get(key)) for key in forbidden):
        raise RuntimeError("V5 weather must remain shadow/advisory-only")
