from __future__ import annotations

"""Occurrence-local S05 bindings for non-PL workload and weather context."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.sources.report_time_competition_schedule import (
    collect_verified_non_pl_schedule,
)
from src.sources.weather_open_meteo import (
    collect_weather_context,
    load_config as load_weather_config,
)


def _weather_rows(
    payload: Mapping[str, Any] | None,
    *,
    planning_gw: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in (payload or {}).get("fixtures") or []:
        if not isinstance(raw, Mapping):
            continue
        try:
            event = int(raw.get("event") or -1)
        except (TypeError, ValueError):
            continue
        if event != int(planning_gw):
            continue
        selected = dict(
            raw.get("selected_evidence")
            or raw.get("current")
            or {}
        )
        weather = dict(selected.get("weather") or {})
        severity = str(selected.get("severity") or "").upper()
        if severity == "NORMAL":
            impact = "NORMAL"
        elif severity == "NOTABLE":
            impact = "LOW"
        elif severity in {"ADVERSE", "EXTREME"}:
            impact = "MATERIAL"
        else:
            impact = "UNAVAILABLE"
        state = str(raw.get("evidence_state") or "UNAVAILABLE")
        signals = [
            str(value)
            for value in selected.get("signals") or []
            if value
        ]
        condition = (
            f"{severity} ({', '.join(signals)})"
            if severity and signals
            else severity
            if severity
            else state
        )
        rows.append(
            {
                "fixture_id": raw.get("fixture_id"),
                "venue": raw.get("venue"),
                "kickoff": raw.get("kickoff_time"),
                "condition": condition,
                "state": state,
                "temperature_c": weather.get("temperature_c"),
                "precipitation_probability": weather.get(
                    "precipitation_probability_pct"
                ),
                "precipitation_mm_h": weather.get(
                    "precipitation_mm_h"
                ),
                "wind_kph": weather.get("wind_speed_kmh"),
                "wind_gust_kph": weather.get("wind_gust_kmh"),
                "fpl_impact": impact,
                "evidence_timestamp": selected.get(
                    "evidence_timestamp"
                ),
                "forecast_confidence": selected.get(
                    "forecast_confidence"
                ),
                "freshness": raw.get("freshness"),
                "provider": selected.get("provider") or payload.get(
                    "provider"
                ),
                "fetch_status": raw.get("fetch_status"),
                "error": raw.get("error"),
            }
        )
    return rows


def _category_for_competition(value: Any) -> str:
    name = str(value or "").casefold()
    if any(
        token in name
        for token in (
            "champions league",
            "europa league",
            "conference league",
        )
    ):
        return "CONTINENTAL_CLUB"
    if any(
        token in name
        for token in (
            "fa cup",
            "efl cup",
            "league cup",
            "carabao",
            "community shield",
        )
    ):
        return "DOMESTIC_CUP"
    if any(
        token in name
        for token in (
            "international",
            "africa cup",
            "afcon",
            "world cup",
            "nations league",
            "european championship",
            "copa america",
            "asian cup",
            "qualifier",
        )
    ):
        return "INTERNATIONAL"
    return "OTHER_COMPETITIVE"


def _verified_player_observation_events(
    *,
    bootstrap: Mapping[str, Any],
    runtime_data_root: Path,
    private_data_root: Path | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Bind existing verified report-time load observations when present.

    The producer owns verification. This consumer still fails closed per row:
    verified=true, a known Official FPL element and basic provenance are
    required. Missing input is fail-soft.
    """
    element_team = {
        int(row.get("id")): int(row.get("team"))
        for row in bootstrap.get("elements") or []
        if isinstance(row, Mapping)
        and row.get("id") is not None
        and row.get("team") is not None
    }
    candidates = [
        runtime_data_root / "data" / "competitive_load_observations.json",
        runtime_data_root
        / "data"
        / "v6"
        / "current"
        / "competitive_load_observations.json",
    ]
    if private_data_root is not None:
        candidates.insert(
            0,
            private_data_root / "competitive_load_observations.json",
        )
        candidates.insert(
            1,
            private_data_root
            / "data"
            / "competitive_load_observations.json",
        )

    payload: dict[str, Any] | None = None
    source_path: str | None = None
    for path in candidates:
        if not path.exists() or path.stat().st_size <= 0:
            continue
        try:
            import json

            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(loaded, dict)
            and loaded.get("contract")
            == "COMPETITIVE_LOAD_OBSERVATIONS_V1"
        ):
            payload = loaded
            source_path = str(path)
            break

    if payload is None:
        return [], {
            "status": "UNAVAILABLE",
            "accepted_rows": 0,
            "source_path": None,
        }

    rows: list[dict[str, Any]] = []
    rejected = 0
    for raw in payload.get("observations") or []:
        if not isinstance(raw, Mapping) or raw.get("verified") is not True:
            rejected += 1
            continue
        try:
            element = int(raw.get("element") or 0)
        except (TypeError, ValueError):
            rejected += 1
            continue
        team_id = element_team.get(element)
        if team_id is None or not raw.get("match_time"):
            rejected += 1
            continue
        if not raw.get("source") or not raw.get("source_url"):
            rejected += 1
            continue
        competition = str(raw.get("competition") or "International")
        rows.append(
            {
                "team_id": team_id,
                "player_id": element,
                "kickoff": raw.get("match_time"),
                "competition": competition,
                "competition_category": _category_for_competition(
                    competition
                ),
                "home_away": (
                    "H"
                    if str(raw.get("travel_context") or "").upper()
                    == "HOME"
                    else "A"
                    if str(raw.get("travel_context") or "").upper()
                    in {
                        "DOMESTIC_AWAY",
                        "EUROPEAN_AWAY",
                        "INTERNATIONAL_AWAY",
                        "LONG_HAUL_AWAY",
                    }
                    else None
                ),
                "opponent": raw.get("opponent"),
                "venue": raw.get("venue"),
                "minutes": raw.get("minutes"),
                "cross_border": str(
                    raw.get("travel_context") or ""
                ).upper()
                in {
                    "EUROPEAN_AWAY",
                    "INTERNATIONAL_AWAY",
                    "LONG_HAUL_AWAY",
                },
                "long_haul": bool(raw.get("long_haul"))
                or str(raw.get("travel_context") or "").upper()
                == "LONG_HAUL_AWAY",
                "timezone_shift_hours": raw.get(
                    "timezone_shift_hours"
                ),
                "return_to_club_interval_hours": raw.get(
                    "return_to_club_interval_hours"
                ),
                "confirmed_call_up": raw.get("confirmed_call_up"),
                "tournament_absence": raw.get(
                    "tournament_absence"
                ),
                "return_date": raw.get("return_date"),
                "injury_knock": raw.get("knock_or_injury_signal"),
                "reintegration_state": raw.get(
                    "reintegration_state"
                ),
                "travel_context": raw.get("travel_context"),
                "verified_source": raw.get("source"),
                "source_url": raw.get("source_url"),
                "verification_level": raw.get(
                    "verification_level"
                ),
                "verified": True,
            }
        )
    return rows, {
        "status": "VALIDATED" if rows else "NO_VALID_ROWS",
        "accepted_rows": len(rows),
        "rejected_rows": rejected,
        "source_path": source_path,
    }


def build_report_time_s05_inputs(
    *,
    bootstrap: Mapping[str, Any],
    fixtures: Sequence[Mapping[str, Any]],
    planning_gw: int,
    report_slot: str,
    output_dir: Path,
    runtime_data_root: Path,
    private_data_root: Path | None = None,
) -> dict[str, Any]:
    planning_fixtures = [
        dict(row)
        for row in fixtures
        if isinstance(row, Mapping)
        and int(row.get("event") or -1) == int(planning_gw)
    ]

    official_snapshot = {
        "bootstrap": dict(bootstrap),
        # S05 renders planning-GW conditions. Do not fetch unrelated fixtures.
        "fixtures": list(planning_fixtures),
    }

    with ThreadPoolExecutor(max_workers=2) as pool:
        club_future = pool.submit(
            collect_verified_non_pl_schedule,
            bootstrap=bootstrap,
            planning_fixtures=planning_fixtures,
            report_timestamp=report_slot,
        )
        weather_future = pool.submit(
            collect_weather_context,
            output_dir,
            official_snapshot=official_snapshot,
            persist=False,
        )

        # Local verified player evidence can be resolved while both network
        # enrichments are in flight.
        player_events, player_observation = (
            _verified_player_observation_events(
                bootstrap=bootstrap,
                runtime_data_root=runtime_data_root,
                private_data_root=private_data_root,
            )
        )

        try:
            club_schedule = club_future.result()
        except Exception as exc:
            club_schedule = {
                "status": "UNAVAILABLE",
                "events": [],
                "authority_complete": False,
                "error": f"{type(exc).__name__}: {exc}",
            }

        try:
            weather_payload = weather_future.result()
            weather_status = "AVAILABLE"
        except Exception as exc:
            weather_payload = {
                "provider": "open_meteo",
                "fixtures": [],
                "error": f"{type(exc).__name__}: {exc}",
            }
            weather_status = "UNAVAILABLE"

    weather_cfg = load_weather_config()
    max_days = float(
        (weather_cfg.get("forecast_policy") or {}).get(
            "max_horizon_days"
        )
        or 7
    )
    schedule_events = [
        *[
            dict(row)
            for row in club_schedule.get("events") or []
            if isinstance(row, Mapping)
        ],
        *player_events,
    ]
    return {
        "verified_schedule_events": schedule_events,
        "non_pl_schedule_authority": (
            club_schedule.get("authority_complete") is True
        ),
        "club_schedule": club_schedule,
        "player_observation": player_observation,
        "weather_payload": weather_payload,
        "weather_status": weather_status,
        "weather_rows": _weather_rows(
            weather_payload,
            planning_gw=planning_gw,
        ),
        "weather_forecast_horizon_hours": max_days * 24.0,
        "governance": {
            "v6_factual_plane_mutated": False,
            "weather_report_time_only": True,
            "weather_direct_model_mutation": False,
            "non_pl_context_only": True,
            "static_fatigue_penalty": False,
        },
    }
