from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.utils import DATA, ROOT, atomic_json, iso_now, read_json

CONFIG_PATH = ROOT / "config" / "intelligence" / "weather_context.json"
OUT = DATA / "weather_context.json"
HEALTH_OUT = DATA / "weather_context_health.json"
INCIDENT_INPUT = DATA / "weather_observed_incidents.json"


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _fixture_incidents(payload: dict[str, Any], fixture_id: int, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    incident_cfg = cfg.get("observed_incidents") or {}
    allowed = {str(value) for value in incident_cfg.get("allowed_types") or []}
    required_class = str(incident_cfg.get("required_evidence_class") or "OBSERVED_MATCH_EVIDENCE")
    rows: list[dict[str, Any]] = []
    for raw in payload.get("incidents") or []:
        if not isinstance(raw, dict):
            continue
        try:
            raw_fixture_id = int(raw.get("fixture_id") or -1)
        except (TypeError, ValueError):
            continue
        incident_type = str(raw.get("incident_type") or "")
        evidence_class = str(raw.get("evidence_class") or "")
        if raw_fixture_id != fixture_id or incident_type not in allowed or evidence_class != required_class:
            continue
        if not raw.get("source") or not raw.get("observed_at"):
            continue
        linked_event = raw.get("football_event") if isinstance(raw.get("football_event"), dict) else None
        if linked_event and linked_event.get("verified") is not True:
            linked_event = None
        rows.append({
            "fixture_id": fixture_id,
            "incident_type": incident_type,
            "observed_at": raw.get("observed_at"),
            "player": raw.get("player"),
            "team": raw.get("team"),
            "description": raw.get("description"),
            "source": raw.get("source"),
            "source_reference": raw.get("source_reference"),
            "evidence_class": required_class,
            "football_event": ({**linked_event, "evidence_class": "FACT"} if linked_event else None),
            "alternative_explanations": list(raw.get("alternative_explanations") or []),
        })
    rows.sort(key=lambda row: str(row.get("observed_at") or ""))
    return rows


def build_attribution(incidents: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    incident_cfg = cfg.get("observed_incidents") or {}
    pattern_cfg = cfg.get("pattern_confidence") or {}
    governance = cfg.get("governance") or {}
    relationship = str(incident_cfg.get("relationship_label") or "POSSIBLE_CONTRIBUTING_FACTOR")
    threshold = max(2, int(pattern_cfg.get("material_advisory_min_similar_incidents") or 3))
    counts = Counter(str(row.get("incident_type") or "") for row in incidents)
    repeated = sorted(key for key, value in counts.items() if key and value >= threshold)
    pattern_confidence = (
        str(pattern_cfg.get("material_advisory_label") or "MATERIAL_ADVISORY")
        if repeated
        else str(pattern_cfg.get("isolated_incident") or "LOW")
    )
    required_alternatives = [str(value) for value in governance.get("alternative_explanations_required") or []]
    incident_rows = []
    for row in incidents:
        alternatives = list(dict.fromkeys([
            *required_alternatives,
            *[str(value) for value in row.get("alternative_explanations") or [] if value],
        ]))
        incident_rows.append({
            **row,
            "relationship_to_weather": relationship,
            "causality_claimed": False,
            "attribution_confidence": (
                pattern_confidence if str(row.get("incident_type")) in repeated else "LOW"
            ),
            "alternative_explanations": alternatives,
        })
    return {
        "incident_count": len(incident_rows),
        "similar_incident_counts": dict(sorted(counts.items())),
        "repeated_patterns": repeated,
        "pattern_confidence": pattern_confidence if incident_rows else "NONE",
        "relationship_label": relationship,
        "causality_claimed": False,
        "incidents": incident_rows,
        "sustainability": {
            "automatic_future_projection_increase": False,
            "weather_associated_return_is_not_sustainable_signal_by_default": True,
        },
    }


def _signal_dimensions(selected: dict[str, Any], cfg: dict[str, Any]) -> set[str]:
    interaction = cfg.get("tactical_interaction") or {}
    signals = set(str(value) for value in selected.get("signals") or [])
    dimensions: set[str] = set()
    if "precipitation_intensity" in signals:
        dimensions.update(str(value) for value in interaction.get("precipitation_sensitive") or [])
    if signals & {"wind_speed", "wind_gust"}:
        dimensions.update(str(value) for value in interaction.get("wind_sensitive") or [])
    if signals & {"cold", "heat"}:
        dimensions.update(str(value) for value in interaction.get("temperature_sensitive") or [])
    return dimensions


def _role_dimensions(position: str) -> set[str]:
    return {
        "GK": {"gk_distribution_handling", "set_pieces", "aerial_play"},
        "DEF": {"build_up", "high_line", "set_pieces", "aerial_play", "defensive_recovery"},
        "MID": {"build_up", "pressing", "transition", "set_pieces", "dribbling", "acceleration"},
        "FWD": {"transition", "set_pieces", "aerial_play", "dribbling", "acceleration"},
    }.get(str(position).upper(), set())


def _team_interaction(
    team_id: int,
    opponent_id: int,
    selected: dict[str, Any],
    team_profiles: dict[str, Any],
    role_profiles: dict[str, Any],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    teams = team_profiles.get("teams") or {}
    own = teams.get(str(team_id)) or {}
    opponent = teams.get(str(opponent_id)) or {}
    all_dimensions = [str(value) for value in (cfg.get("tactical_interaction") or {}).get("dimensions") or []]
    active = _signal_dimensions(selected, cfg)
    severity = str(selected.get("severity") or "NORMAL")
    system_fields = ("base_formation", "build_up", "pressing", "defensive_line", "transition", "set_piece_profile")
    own_evidence = any(own.get(field) is not None for field in system_fields)
    opponent_evidence = any(opponent.get(field) is not None for field in system_fields)
    dimension_rows = []
    for dimension in all_dimensions:
        elevated = dimension in active and severity != "NORMAL"
        dimension_rows.append({
            "dimension": dimension,
            "weather_relevant": elevated,
            "context": "HEIGHTENED_VARIANCE_CONTEXT" if elevated else "NORMAL_CONTEXT",
            "direct_projection_modifier": None,
            "direct_decision_modifier": None,
        })

    players = []
    for row in (role_profiles.get("players") or {}).values():
        try:
            player_team_id = int(row.get("team_id") or -1)
        except (TypeError, ValueError):
            continue
        if player_team_id != team_id:
            continue
        position = str(row.get("position") or "")
        relevant = sorted(active & _role_dimensions(position))
        if not relevant:
            continue
        players.append({
            "element": row.get("element"),
            "name": row.get("name"),
            "position": position,
            "role": row.get("role"),
            "role_evidence_confidence": row.get("confidence"),
            "weather_relevant_dimensions": relevant,
            "interpretation_only": True,
        })

    return {
        "team_id": team_id,
        "opponent_id": opponent_id,
        "own_system": {
            "base_formation": own.get("base_formation"),
            "build_up": own.get("build_up"),
            "pressing": own.get("pressing"),
            "defensive_line": own.get("defensive_line"),
            "transition": own.get("transition"),
            "set_piece_profile": own.get("set_piece_profile"),
            "evidence_available": own_evidence,
        },
        "opponent_system": {
            "base_formation": opponent.get("base_formation"),
            "build_up": opponent.get("build_up"),
            "pressing": opponent.get("pressing"),
            "defensive_line": opponent.get("defensive_line"),
            "transition": opponent.get("transition"),
            "set_piece_profile": opponent.get("set_piece_profile"),
            "evidence_available": opponent_evidence,
        },
        "dimensions": dimension_rows,
        "player_role_interactions": players,
        "interpretation_confidence": "MATERIAL" if own_evidence and opponent_evidence else "EVIDENCE_LIMITED",
        "allowed_context": {
            "tactical_interpretation": True,
            "uncertainty": severity != "NORMAL",
            "variance_context": "ELEVATED" if active else "BASELINE",
            "floor_context": "UNCERTAIN" if active else "BASELINE",
            "ceiling_context": "UNCERTAIN" if active else "BASELINE",
            "risk_context": severity,
        },
        "direct_xpts_modifier": None,
        "direct_xmins_modifier": None,
    }


def build_weather_health(weather: dict[str, Any]) -> dict[str, Any]:
    fixtures = [row for row in weather.get("fixtures") or [] if isinstance(row, dict)]
    total = len(fixtures)
    available = sum(1 for row in fixtures if row.get("selected_evidence") or row.get("current"))
    stale = sum(1 for row in fixtures if row.get("freshness") == "STALE")
    unavailable = total - available
    if total == 0:
        status = "PASS"
        reasons = ["NO_FIXTURES_IN_ACTIVE_WEATHER_WINDOW"]
    elif available == 0:
        status = "UNAVAILABLE"
        reasons = ["NO_REQUIRED_WEATHER_EVIDENCE_AVAILABLE"]
    elif unavailable > 0:
        status = "PARTIAL"
        reasons = ["WEATHER_EVIDENCE_COVERAGE_PARTIAL"]
        if stale:
            reasons.append("STALE_FORECAST_PRESENT")
    elif stale == total:
        status = "STALE"
        reasons = ["ONLY_STALE_FORECAST_EVIDENCE_AVAILABLE"]
    elif stale > 0:
        status = "PARTIAL"
        reasons = ["STALE_FORECAST_PRESENT"]
    else:
        status = "PASS"
        reasons = []
    return {
        "schema_version": 1,
        "contract": "WEATHER_CONTEXT_HEALTH_V1",
        "generated_at": iso_now(),
        "status": status,
        "allowed_statuses": ["PASS", "PARTIAL", "STALE", "UNAVAILABLE"],
        "fixture_count": total,
        "available_count": available,
        "stale_count": stale,
        "unavailable_count": unavailable,
        "tactical_context_complete": status == "PASS",
        "decision_blocking": False,
        "reasons": reasons,
    }


def build_weather_context(
    weather: dict[str, Any],
    team_profiles: dict[str, Any],
    role_profiles: dict[str, Any],
    incident_payload: dict[str, Any],
    cfg: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cfg = cfg or load_config()
    fixtures = []
    for row in weather.get("fixtures") or []:
        if not isinstance(row, dict):
            continue
        fixture_id = int(row.get("fixture_id") or 0)
        selected = row.get("selected_evidence") or row.get("current") or {}
        incidents = _fixture_incidents(incident_payload, fixture_id, cfg)
        attribution = build_attribution(incidents, cfg)
        home_id = int(row.get("home_team_id") or -1)
        away_id = int(row.get("away_team_id") or -1)
        tactical = []
        if selected and home_id > 0 and away_id > 0:
            tactical = [
                _team_interaction(home_id, away_id, selected, team_profiles, role_profiles, cfg),
                _team_interaction(away_id, home_id, selected, team_profiles, role_profiles, cfg),
            ]
        fixtures.append({
            "fixture_id": fixture_id,
            "event": row.get("event"),
            "home_team": row.get("home_team"),
            "away_team": row.get("away_team"),
            "kickoff_time": row.get("kickoff_time"),
            "venue": row.get("venue"),
            "evidence_state": row.get("evidence_state"),
            "evidence_precedence": row.get("evidence_precedence"),
            "freshness": row.get("freshness"),
            "selected_evidence": selected or None,
            "severity": selected.get("severity") if selected else None,
            "observed_incidents": incidents,
            "attribution": attribution,
            "tactical_interactions": tactical,
            "post_match_reconciled": bool(row.get("finished")),
        })

    health = build_weather_health(weather)
    governance = dict(cfg.get("governance") or {})
    context = {
        "schema_version": 1,
        "contract": "WEATHER_CONTEXT_V3_V1",
        "owner": "weather_context",
        "generated_at": iso_now(),
        "status": health["status"],
        "provider": weather.get("provider"),
        "fixtures": fixtures,
        "health": health,
        "governance": {
            **governance,
            "decision_authority": "NONE",
            "weather_class": "ENVIRONMENTAL_CONTEXT",
            "incident_class": "OBSERVED_MATCH_EVIDENCE",
            "relationship_label": "POSSIBLE_CONTRIBUTING_FACTOR",
            "weather_causality_claimed": False,
            "sustainable_projection_auto_increase": False,
        },
    }
    return context, health


def run() -> dict[str, Any]:
    weather = read_json(DATA / "fixture_weather.json", {})
    team_profiles = read_json(DATA / "tactical_team_profiles.json", {})
    role_profiles = read_json(DATA / "player_role_profiles.json", {})
    incident_payload = read_json(INCIDENT_INPUT, {"incidents": []})
    context, health = build_weather_context(weather, team_profiles, role_profiles, incident_payload)
    atomic_json(OUT, context)
    atomic_json(HEALTH_OUT, health)

    latest = read_json(DATA / "latest.json", {})
    latest["weather_context_summary"] = {
        "status": health.get("status"),
        "fixture_count": health.get("fixture_count"),
        "available_count": health.get("available_count"),
        "stale_count": health.get("stale_count"),
        "tactical_context_complete": health.get("tactical_context_complete"),
        "decision_authority": "NONE",
    }
    latest.setdefault("files", {})["weather_context"] = "data/weather_context.json"
    latest["files"]["weather_context_health"] = "data/weather_context_health.json"
    atomic_json(DATA / "latest.json", latest)
    print(json.dumps(latest["weather_context_summary"], ensure_ascii=False))
    return context


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
