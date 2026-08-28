from __future__ import annotations

from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.intelligence.fixture_congestion import resolve_fixture_congestion
from src.v5.intelligence.xmins import estimate_xmins

CONFIG = "config/intelligence/xmins_v3.json"
MAX_FIXTURE_ROWS_PER_PLAYER = 5


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _flatten_projected_fixtures(player: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for gw in player.get("xpts_by_gw") or []:
        if not isinstance(gw, dict):
            continue
        for fixture in gw.get("fixtures") or []:
            if isinstance(fixture, dict) and fixture.get("kickoff_time"):
                rows.append(fixture)
    rows.sort(key=lambda row: (int(row.get("gw") or row.get("event") or 999), str(row.get("kickoff_time") or "")))
    return rows[:MAX_FIXTURE_ROWS_PER_PLAYER]


def _xmins_context(player: dict[str, Any], team_matches: int) -> dict[str, Any]:
    role = _dict(player.get("role"))
    context: dict[str, Any] = {
        "team_matches_played": int(team_matches),
        "role_start_probability": role.get("role_start_probability"),
        "rotation_risk": role.get("rotation_risk"),
    }
    historical = _dict(player.get("historical_prior"))
    if historical:
        context.update(
            {
                "prior_start_probability": historical.get("start_probability"),
                "starter_minutes_prior": historical.get("avg_minutes_when_start"),
                "prior_evidence_minutes": historical.get("minutes"),
                "prior_source": historical.get("source"),
                "prior_identity_match": historical.get("identity_match"),
            }
        )
    return context


def build_fixture_congestion_overlay(
    prediction: dict[str, Any],
    bootstrap: dict[str, Any],
    official_fixtures: list[dict[str, Any]],
    full_enrichment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = load_json_config(CONFIG).get("fixture_congestion") or {}
    mode = str(cfg.get("application_mode") or "SHADOW_ONLY")
    if mode != "SHADOW_ONLY":
        raise ValueError(f"fixture congestion overlay requires SHADOW_ONLY mode, got {mode}")

    enrichment = full_enrichment if isinstance(full_enrichment, dict) else {}
    schedule = _dict(enrichment.get("schedule"))
    bootstrap_players = {
        int(row["id"]): row
        for row in bootstrap.get("elements") or []
        if isinstance(row, dict) and row.get("id") is not None
    }
    strength = _dict(prediction.get("team_strength"))
    team_matches = {
        int(row.get("team_id")): int(row.get("matches_played") or 0)
        for row in strength.get("teams") or []
        if isinstance(row, dict) and row.get("team_id") is not None
    }

    players: dict[str, dict[str, Any]] = {}
    evaluated = 0
    with_rest_evidence = 0
    applied = 0
    max_abs_minutes_delta = 0.0
    max_abs_start_delta = 0.0

    for player in prediction.get("players") or []:
        if not isinstance(player, dict) or player.get("element") is None:
            continue
        element = int(player["element"])
        source_player = bootstrap_players.get(element)
        if not isinstance(source_player, dict):
            continue
        team_id = int(player.get("team_id") or source_player.get("team") or -1)
        role = _dict(player.get("role"))
        rotation_risk = role.get("rotation_risk")
        base_context = _xmins_context(player, team_matches.get(team_id, 0))
        baseline = _dict(player.get("xmins"))
        rows = []
        for fixture in _flatten_projected_fixtures(player):
            resolved = resolve_fixture_congestion(
                official_fixtures,
                schedule,
                team_id,
                fixture.get("kickoff_time"),
                rotation_risk,
            )
            factor = float(resolved.get("factor") or 1.0)
            adjusted = estimate_xmins(source_player, {**base_context, "congestion_factor": factor})
            start_delta = round(float(adjusted.get("start_probability") or 0.0) - float(baseline.get("start_probability") or 0.0), 6)
            minutes_delta = round(float(adjusted.get("expected_minutes") or 0.0) - float(baseline.get("expected_minutes") or 0.0), 3)
            evaluated += 1
            has_rest = (_dict(resolved.get("rest_context"))).get("status") == "ACTIVE"
            with_rest_evidence += int(has_rest)
            applied += int(bool(resolved.get("applied")))
            max_abs_minutes_delta = max(max_abs_minutes_delta, abs(minutes_delta))
            max_abs_start_delta = max(max_abs_start_delta, abs(start_delta))
            rows.append(
                {
                    "event": fixture.get("event") or fixture.get("gw"),
                    "kickoff_time": fixture.get("kickoff_time"),
                    "baseline": {
                        "start_probability": baseline.get("start_probability"),
                        "expected_minutes": baseline.get("expected_minutes"),
                    },
                    "shadow": {
                        "start_probability": adjusted.get("start_probability"),
                        "expected_minutes": adjusted.get("expected_minutes"),
                    },
                    "delta": {
                        "start_probability": start_delta,
                        "expected_minutes": minutes_delta,
                    },
                    "congestion": resolved,
                    "authoritative_xmins_replaced": False,
                }
            )
        players[str(element)] = {
            "application_mode": mode,
            "fixtures": rows,
            "evaluated_fixtures": len(rows),
            "fixtures_with_rest_evidence": sum(
                1 for row in rows if (_dict(_dict(row.get("congestion")).get("rest_context"))).get("status") == "ACTIVE"
            ),
            "applied_fixtures": sum(1 for row in rows if bool(_dict(row.get("congestion")).get("applied"))),
            "authoritative_xmins_replaced": False,
            "authoritative_xpts_replaced": False,
        }

    return {
        "schema_version": 1,
        "model": cfg.get("model"),
        "application_mode": mode,
        "calibration_status": cfg.get("calibration_status"),
        "promotion_requires_settled_backtest": bool(cfg.get("promotion_requires_settled_backtest", True)),
        "players": players,
        "summary": {
            "evaluated_fixtures": evaluated,
            "fixtures_with_rest_evidence": with_rest_evidence,
            "applied_fixtures": applied,
            "max_abs_expected_minutes_delta": round(max_abs_minutes_delta, 3),
            "max_abs_start_probability_delta": round(max_abs_start_delta, 6),
        },
        "governance": {
            "fixture_specific_rest_only": True,
            "global_calendar_minimum_forbidden": True,
            "authoritative_prediction_unchanged": True,
            "bounded_fixture_rows_per_player": MAX_FIXTURE_ROWS_PER_PLAYER,
        },
    }
