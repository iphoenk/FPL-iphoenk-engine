from __future__ import annotations

from collections import defaultdict
from time import perf_counter
from typing import Any

from src.intelligence.weather_advisory import (
    player_weather_sensitivity,
    system_weather_interactions,
    weather_uncertainty_advisory,
)
from src.utils import DATA, atomic_json, read_json

TACTICAL_OUT = DATA / "tactical_serving_v4.json"
WEATHER_OUT = DATA / "weather_context_v4.json"
PREDICTIONS = DATA / "predictions_v4.json"
UNIVERSE = DATA / "universe.json"
TACTICAL_EXTERNAL = DATA / "tactical_external_evidence.json"
COMPETITIVE_LOAD = DATA / "competitive_load_v4.json"

_INTERVAL_MULTIPLIER = {
    "NORMAL": 1.0,
    "NOTABLE": 1.08,
    "ADVERSE": 1.18,
    "EXTREME": 1.35,
}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return float(default)


def _weather_fixture(weather: dict, team: str | None, event: Any) -> dict:
    candidates = [
        row for row in weather.get("fixtures") or []
        if (event is None or row.get("event") == event)
        and team in {row.get("home_team"), row.get("away_team")}
    ]
    if not candidates:
        return {}
    return sorted(candidates, key=lambda row: (row.get("kickoff_time") or "", row.get("fixture_id") or 0))[0]


def _team_system(external: dict, team: str | None) -> dict:
    teams = external.get("teams") or {}
    return teams.get(str(team)) or {}


def _opponent_system(tactical: dict) -> dict:
    return {
        "observed_base_shape": tactical.get("observed_base_shape"),
        "build_up_press_block_traits": tactical.get("build_up_press_block_traits"),
        "transition_threat": tactical.get("transition_threat"),
        "central_wide_vulnerability": tactical.get("central_wide_vulnerability"),
        "set_piece_aerial_context": tactical.get("set_piece_aerial_context"),
        "recent_tactical_adjustment": tactical.get("recent_tactical_adjustment"),
    }


def _competitive_map(competitive: dict) -> dict[int, dict]:
    return {
        int(row.get("element") or 0): row
        for row in competitive.get("players") or []
        if row.get("element") is not None
    }


def _multifactor_support(
    pred: dict,
    tactical: dict,
    *,
    competitive_row: dict,
    is_owned: bool,
    replacement_context: dict | None,
) -> dict:
    first = ((pred.get("fixtures") or [{}])[0]) or {}
    xmins = first.get("xmins") or {}
    rates = first.get("rates") or {}
    checks = {
        "xmins": xmins.get("start_probability") is not None,
        "role": bool(tactical.get("player_role")),
        "underlying_statistics": any(rates.get(key) is not None for key in ("xg90", "xa90", "def_actions90", "saves90")),
        "tactical_fit": tactical.get("evidence_state") not in {None, "", "UNAVAILABLE"},
        "fixtures_3_5gw": pred.get("xpts_5") is not None and len(pred.get("fixtures") or []) >= 3,
        "strategic_10_15gw": pred.get("xpts_15") is not None,
        "rest_congestion": bool(competitive_row),
        "price_value": (pred.get("value") or {}).get("xpts5_per_million") is not None,
        "squad_structure": bool(is_owned or replacement_context),
    }
    return {
        "dimensions": checks,
        "complete": all(checks.values()),
        "weather_never_sufficient_alone": True,
    }


def _interval_advisory(pred: dict, weather_advisory: dict, severity: str) -> dict:
    first = ((pred.get("fixtures") or [{}])[0]) or {}
    mean = first.get("xpts")
    lower = first.get("lower80")
    upper = first.get("upper80")
    if mean is None or lower is None or upper is None:
        return {
            "base_mean_xpts": mean,
            "advisory_floor": lower,
            "advisory_ceiling": upper,
            "expected_xpts_mean_adjustment": 0.0,
            "interval_expansion_applied_to_prediction_model": False,
        }
    multiplier = _INTERVAL_MULTIPLIER.get(severity, 1.0)
    center = _f(mean)
    low_width = max(0.0, center - _f(lower, center))
    high_width = max(0.0, _f(upper, center) - center)
    return {
        "base_mean_xpts": round(center, 3),
        "base_lower80": round(_f(lower), 3),
        "base_upper80": round(_f(upper), 3),
        "advisory_floor": round(max(0.0, center - low_width * multiplier), 3),
        "advisory_ceiling": round(center + high_width * multiplier, 3),
        "advisory_interval_multiplier": multiplier,
        "confidence": weather_advisory.get("confidence"),
        "variance": weather_advisory.get("variance"),
        "expected_xpts_mean_adjustment": 0.0,
        "interval_expansion_applied_to_prediction_model": False,
    }


def _observed_vs_sustainable(attribution: dict) -> dict:
    incidents = list(attribution.get("credible_incidents") or [])
    observed_returns = [
        row.get("observed_return")
        for row in incidents
        if isinstance(row, dict) and row.get("observed_return") is not None
    ]
    return {
        "observed_return": observed_returns,
        "opportunity_generation_mechanism": (
            "POTENTIALLY_WEATHER_ASSOCIATED"
            if incidents else "NO_CREDIBLE_WEATHER_ASSOCIATED_INCIDENT"
        ),
        "repeatable_predictive_signal": "UNVALIDATED",
        "sustainable_attacking_expectation_adjustment": 0.0,
        "canonical_rule": "observed_return_is_not_sustainable_predictive_signal",
    }


def _row_weather(
    row: dict,
    *,
    pred: dict,
    weather: dict,
    external: dict,
    competitive_row: dict,
    is_owned: bool,
) -> dict:
    tactical = row.get("tactical") or {}
    first = ((pred.get("fixtures") or [{}])[0]) or {}
    fixture_weather = _weather_fixture(weather, row.get("team"), first.get("event"))
    selected = fixture_weather.get("selected_evidence")
    role = tactical.get("player_role") or row.get("position")
    sensitivity = player_weather_sensitivity(row.get("position"), selected, role)
    interactions = system_weather_interactions(
        selected,
        own_system=_team_system(external, row.get("team")),
        opponent_system=_opponent_system(tactical),
        role=role,
    )
    attribution = fixture_weather.get("live_attribution") or {
        "state": "NO_CREDIBLE_ATTRIBUTION",
        "confidence": "NONE",
        "label": "POSSIBLE_CONTRIBUTING_FACTOR",
        "credible_incidents": [],
        "causal_claim": False,
    }
    uncertainty = weather_uncertainty_advisory(
        selected,
        sensitivity=sensitivity,
        interactions=interactions,
        attribution=attribution,
    )
    severity = str((selected or {}).get("severity") or "NORMAL")
    support = _multifactor_support(
        pred,
        tactical,
        competitive_row=competitive_row,
        is_owned=is_owned,
        replacement_context=row.get("replacement_context"),
    )
    material_weather = severity in {"NOTABLE", "ADVERSE", "EXTREME"}
    interpretation = (
        "MULTIFACTOR_ADVISORY_ELIGIBLE"
        if material_weather and support["complete"]
        else "CONTEXT_ONLY_INSUFFICIENT_MULTIFACTOR_SUPPORT"
        if material_weather
        else "NEUTRAL"
    )
    return {
        "fixture_id": fixture_weather.get("fixture_id"),
        "event": fixture_weather.get("event"),
        "evidence_state": fixture_weather.get("evidence_state") or "UNAVAILABLE",
        "severity": severity,
        "selected_evidence": selected,
        "player_sensitivity": sensitivity,
        "system_interactions": interactions,
        "live_attribution": attribution,
        "uncertainty": {
            **uncertainty,
            **_interval_advisory(pred, uncertainty, severity),
        },
        "challenger_governance": {
            "support": support,
            "interpretation": interpretation,
            "weather_can_strengthen_or_weaken_interpretation": bool(material_weather and support["complete"]),
            "weather_can_independently_promote_player": False,
            "one_weather_associated_haul_can_promote": False,
        },
        "sustainability": _observed_vs_sustainable(attribution),
        "decision_isolation": {
            "xpts_mean_mutated": False,
            "xmins_mutated": False,
            "watchlist_rank_mutated": False,
            "xi_mutated": False,
            "captaincy_mutated": False,
            "transfer_mutated": False,
        },
    }


def apply_weather_overlay(
    tactical: dict | None = None,
    *,
    predictions: dict | None = None,
    universe: dict | None = None,
    weather: dict | None = None,
    external: dict | None = None,
    competitive: dict | None = None,
    write: bool = True,
) -> dict:
    started = perf_counter()
    tactical = tactical if tactical is not None else read_json(TACTICAL_OUT, {})
    predictions = predictions if predictions is not None else read_json(PREDICTIONS, {})
    universe = universe if universe is not None else read_json(UNIVERSE, {})
    weather = weather if weather is not None else read_json(WEATHER_OUT, {})
    external = external if external is not None else read_json(TACTICAL_EXTERNAL, {})
    competitive = competitive if competitive is not None else read_json(COMPETITIVE_LOAD, {})

    pmap = {
        int(row.get("element") or 0): row
        for row in predictions.get("players") or []
        if row.get("element") is not None
    }
    cmap = _competitive_map(competitive)
    health = weather.get("health") or {}
    for bucket, is_owned in (("owned", True), ("watchlist", False)):
        for row in tactical.get(bucket) or []:
            element = int(row.get("element") or 0)
            pred = pmap.get(element) or {}
            row.setdefault("tactical", {})["weather_context"] = _row_weather(
                row,
                pred=pred,
                weather=weather,
                external=external,
                competitive_row=cmap.get(element) or {},
                is_owned=is_owned,
            )

    tactical["weather_context"] = {
        "status": health.get("status") or "UNAVAILABLE",
        "reason": health.get("reason") or "WEATHER_ARTIFACT_UNAVAILABLE",
        "required_for_tactical_context": health.get("required_for_tactical_context", True),
        "tactical_context_completeness": health.get("tactical_context_completeness") or "PARTIAL",
        "fixture_count": weather.get("fixture_count", 0),
        "available_count": weather.get("available_count", 0),
        "material_count": weather.get("material_count", 0),
        "evidence_precedence": weather.get("evidence_precedence") or [],
        "runtime_dependency": "enrichment.weather_context",
        "overlay_ms": round((perf_counter() - started) * 1000.0, 2),
    }
    tactical.setdefault("guardrails", {}).update({
        "weather_is_runtime_enrichment_dependency": True,
        "weather_uncertainty_first": True,
        "weather_expected_xpts_mean_adjustment": 0.0,
        "weather_numeric_xpts_coefficient_applied": False,
        "weather_cannot_independently_promote_challenger": True,
        "weather_associated_return_not_sustainable_signal": True,
    })
    if write:
        atomic_json(TACTICAL_OUT, tactical)
    return tactical


if __name__ == "__main__":
    apply_weather_overlay()
