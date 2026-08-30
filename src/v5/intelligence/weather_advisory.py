from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/intelligence/weather_context.json"
EVIDENCE_PRECEDENCE = (
    "LIVE_OBSERVED",
    "CLOSEST_TO_KICKOFF_OBSERVATION",
    "FRESH_FORECAST",
    "STALE_FORECAST",
)


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def classify_weather(observation: dict[str, Any]) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)
    governance = dict(cfg.get("governance") or {})
    raw = observation.get("weather") if isinstance(observation.get("weather"), dict) else observation
    precip = _float(raw.get("precipitation_mm_h")) or 0.0
    wind = _float(raw.get("wind_speed_kmh")) or 0.0
    gust = _float(raw.get("wind_gust_kmh")) or 0.0
    temp = _float(raw.get("temperature_c"))
    severity = "NORMAL"
    signals: list[str] = []
    for label in ("EXTREME", "ADVERSE", "NOTABLE"):
        band = (cfg.get("severity") or {}).get(label) or {}
        hit: list[str] = []
        if wind >= float(band.get("wind_speed_kmh") or 1e9):
            hit.append("wind_speed")
        if gust >= float(band.get("wind_gust_kmh") or 1e9):
            hit.append("wind_gust")
        if precip >= float(band.get("precipitation_mm_h") or 1e9):
            hit.append("precipitation_intensity")
        if temp is not None and band.get("cold_c") is not None and temp <= float(band["cold_c"]):
            hit.append("cold")
        if temp is not None and band.get("heat_c") is not None and temp >= float(band["heat_c"]):
            hit.append("heat")
        if hit:
            severity = label
            signals = hit
            break
    return {
        "status": "AVAILABLE" if raw else "UNAVAILABLE",
        "mode": "SHADOW_ADVISORY_ONLY",
        "source_kind": observation.get("source_kind") or observation.get("evidence_kind") or "FORECAST_ADVISORY",
        "evidence_state": observation.get("evidence_state") or "FORECAST",
        "severity": severity,
        "signals": signals,
        "weather": {
            "temperature_c": temp,
            "precipitation_probability_pct": _float(raw.get("precipitation_probability_pct")),
            "precipitation_mm_h": precip,
            "wind_speed_kmh": wind,
            "wind_gust_kmh": gust,
            "weather_code": raw.get("weather_code"),
        },
        "decision_effect": "CONTEXT_ONLY_NO_DIRECT_SCORE_MUTATION",
        "post_match_attribution_label": governance.get("post_match_attribution_label", "POSSIBLE_CONTRIBUTING_FACTOR"),
        "governance": governance,
    }


def forecast_is_fresh(snapshot: dict[str, Any], *, now: datetime | None = None) -> bool:
    cfg = load_json_config(CONFIG)
    fetched = _parse_dt(snapshot.get("fetched_at"))
    if fetched is None:
        return False
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    confidence = str(snapshot.get("forecast_confidence") or "LOW")
    max_age = float(((cfg.get("forecast_policy") or {}).get("freshness_hours") or {}).get(confidence) or 0.0)
    return max(0.0, (current - fetched).total_seconds() / 3600.0) <= max_age


def select_evidence(
    *,
    live_observation: dict[str, Any] | None = None,
    closest_to_kickoff_observation: dict[str, Any] | None = None,
    forecast_snapshots: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    if isinstance(live_observation, dict):
        return {**live_observation, "evidence_kind": "LIVE_OBSERVED", "evidence_state": "LIVE_OBSERVED"}
    if isinstance(closest_to_kickoff_observation, dict):
        return {
            **closest_to_kickoff_observation,
            "evidence_kind": "CLOSEST_TO_KICKOFF_OBSERVATION",
            "evidence_state": "CLOSEST_TO_KICKOFF",
        }
    snapshots = [dict(row) for row in forecast_snapshots or [] if isinstance(row, dict)]
    if not snapshots:
        return None
    snapshots.sort(key=lambda row: str(row.get("fetched_at") or ""))
    latest = snapshots[-1]
    fresh = forecast_is_fresh(latest, now=now)
    return {
        **latest,
        "evidence_kind": "FRESH_FORECAST" if fresh else "STALE_FORECAST",
        "evidence_state": "FORECAST",
        "freshness": "FRESH" if fresh else "STALE",
    }


def assert_advisory_governance() -> None:
    governance = load_json_config(CONFIG).get("governance") or {}
    required_false = (
        "v5_production_decision_authority",
        "quantitative_weather_signal_consumption",
        "may_directly_change_xpts",
        "may_directly_change_xmins",
        "may_directly_change_captaincy",
        "may_directly_change_starting_xi",
        "may_directly_change_transfer_decision",
        "may_directly_change_watchlist_membership",
        "weather_caused_label_allowed",
    )
    if not governance.get("advisory_only", False) or not governance.get("shadow_evidence_allowed", False):
        raise RuntimeError("V5 weather governance must remain SHADOW_ADVISORY_ONLY")
    if any(bool(governance.get(key)) for key in required_false):
        raise RuntimeError("V5 weather governance grants forbidden production authority")
