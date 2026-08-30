from __future__ import annotations

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


def classify_weather(observation: dict[str, Any] | None) -> dict[str, Any]:
    """Return shadow/advisory weather evidence with zero direct decision authority."""
    cfg = load_json_config(CONFIG)
    governance = dict(cfg.get("governance") or {})
    raw = dict(observation or {})
    weather = raw.get("weather") if isinstance(raw.get("weather"), dict) else raw
    precip = _float(weather.get("precipitation_mm_h")) or 0.0
    wind = _float(weather.get("wind_speed_kmh")) or 0.0
    gust = _float(weather.get("wind_gust_kmh")) or 0.0
    temp = _float(weather.get("temperature_c"))
    severity = "NORMAL"
    signals: list[str] = []
    for label in ("EXTREME", "ADVERSE", "NOTABLE"):
        band = (cfg.get("severity") or {}).get(label) or {}
        current: list[str] = []
        if wind >= float(band.get("wind_speed_kmh") or 1e9): current.append("wind_speed")
        if gust >= float(band.get("wind_gust_kmh") or 1e9): current.append("wind_gust")
        if precip >= float(band.get("precipitation_mm_h") or 1e9): current.append("precipitation_intensity")
        if temp is not None and temp <= float(band.get("cold_c") if band.get("cold_c") is not None else -1e9): current.append("cold")
        if temp is not None and temp >= float(band.get("heat_c") if band.get("heat_c") is not None else 1e9): current.append("heat")
        if current:
            severity, signals = label, current
            break
    return {
        "status": "AVAILABLE" if observation else "UNAVAILABLE",
        "mode": "SHADOW_ADVISORY_ONLY",
        "source_kind": str(raw.get("source_kind") or raw.get("observation_kind") or "FORECAST_ADVISORY"),
        "severity": severity,
        "signals": signals,
        "weather": {
            "temperature_c": temp,
            "precipitation_probability_pct": _float(weather.get("precipitation_probability_pct")),
            "precipitation_mm_h": precip,
            "wind_speed_kmh": wind,
            "wind_gust_kmh": gust,
            "weather_code": weather.get("weather_code"),
        },
        "decision_effect": "CONTEXT_ONLY_NO_DIRECT_SCORE_MUTATION",
        "post_match_attribution_label": governance.get("post_match_attribution_label", "POSSIBLE_CONTRIBUTING_FACTOR"),
        "governance": governance,
    }


def assert_advisory_governance() -> None:
    g = load_json_config(CONFIG).get("governance") or {}
    forbidden = (
        "may_directly_change_xpts", "may_directly_change_xmins", "may_directly_change_captaincy",
        "may_directly_change_starting_xi", "may_directly_change_transfer_decision",
        "may_directly_change_watchlist_membership",
    )
    if not g.get("advisory_only") or any(bool(g.get(key)) for key in forbidden):
        raise RuntimeError("V5 weather must remain shadow/advisory-only")
