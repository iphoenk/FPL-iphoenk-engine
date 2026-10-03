from __future__ import annotations

"""V12 natural analytic/report orchestration.

This module does not acquire V6 data and does not own player mathematics.
It composes already-governed V12 analytic outputs into complete human-facing
report structures while keeping repository-Python execution truth separate
from ChatGPT/V12 analytic execution truth.
"""

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from src.engines.price_radar import (
    DISPLAY_TIMEZONE,
    MODEL_THRESHOLD as EXISTING_PRICE_MODEL_THRESHOLD,
    OFFICIAL_MAX_AGE_SECONDS,
    OFFICIAL_UPDATE_TIMEZONE,
)
from src.engines.visible_content_proof import canonical_mode_contract
from src.engines.v12_competitive_window import resolve_competitive_window
from src.engines.v12_section_resolver import (
    resolve_section,
    validate_resolved_sections,
)


SECTION_STATES = frozenset({"COMPLETE", "PARTIAL", "DEGRADED", "UNAVAILABLE"})
POSITIONS = ("GK", "DEF", "MID", "FWD")
ACTION_STATES = frozenset({"WAIT", "PREPARE", "ACT"})
WATCHLIST_POSITION_FORMULAE = {
    "GK": {
        "formula_id": "V12_WATCH_GK_EVIDENCE_V1",
        "features": (
            "save_process",
            "shot_stopping",
            "clean_sheet_environment",
            "goals_conceded_environment",
            "penalty_save_evidence",
            "hierarchy_security",
        ),
    },
    "DEF": {
        "formula_id": "V12_WATCH_DEF_EVIDENCE_V1",
        "features": (
            "goal_process",
            "creation_process",
            "clean_sheet_environment",
            "defcon",
            "defensive_role",
            "matchup",
        ),
    },
    "MID": {
        "formula_id": "V12_WATCH_MID_EVIDENCE_V1",
        "features": (
            "goal_process",
            "creation_process",
            "penalty_process",
            "set_piece_process",
            "advanced_role",
            "matchup",
        ),
    },
    "FWD": {
        "formula_id": "V12_WATCH_FWD_EVIDENCE_V1",
        "features": (
            "goal_process",
            "creation_process",
            "penalty_process",
            "set_piece_process",
            "service_linkup",
            "matchup",
        ),
    },
}
PRICE_UP = frozenset({"RISE", "UP", "INCREASE", "RISING"})
PRICE_DOWN = frozenset({"FALL", "DOWN", "DECREASE", "FALLING"})
MACHINE_TERMS = (
    "issue #431",
    "mutation/readback",
    "natural_core_upkeep_gate",
    "authoritative_runtime_snapshot",
    "bound run id",
    "workflow run id",
)
SIGNAL_DELTA_FIELDS = (
    "availability",
    "p_start",
    "xmins",
    "role",
    "injury_news",
    "price",
    "fixture",
    "weather",
    "decision_route",
)


class ReportOrchestrationError(ValueError):
    pass


def _status(value: Any, *, label: str) -> str:
    out = str(value or "").strip().upper()
    if out not in SECTION_STATES:
        raise ReportOrchestrationError(
            f"{label} status must be COMPLETE/PARTIAL/DEGRADED/UNAVAILABLE"
        )
    return out


def analytic_execution_truth(
    *,
    repository_python_qa_executed: bool,
    repository_python_execution_evidence: Mapping[str, Any] | None,
    valid_current_inputs: bool,
    chatgpt_v12_analytic_executed: bool,
    analytic_outputs: Mapping[str, Any] | None,
    model_timestamp: str | None = None,
) -> dict[str, Any]:
    """Represent two independent execution truths without conflating them."""
    repo_executed = bool(repository_python_qa_executed)
    repo_evidence = dict(repository_python_execution_evidence or {})
    if not repo_executed and repo_evidence:
        raise ReportOrchestrationError(
            "repository Python execution evidence cannot be claimed when execution=false"
        )
    if repo_executed and not repo_evidence:
        raise ReportOrchestrationError(
            "repository Python execution=true requires exact execution evidence"
        )

    chatgpt_executed = bool(chatgpt_v12_analytic_executed)
    outputs = dict(analytic_outputs or {})
    if chatgpt_executed and not valid_current_inputs:
        raise ReportOrchestrationError(
            "ChatGPT V12 analytic execution requires valid current factual inputs"
        )
    if chatgpt_executed and not outputs:
        raise ReportOrchestrationError(
            "ChatGPT V12 analytic execution requires current analytic outputs"
        )

    if chatgpt_executed:
        model_refresh = "CURRENT"
    elif valid_current_inputs:
        model_refresh = "NOT RUN"
    else:
        model_refresh = "PARTIAL"

    return {
        "repository_python": {
            "executed": repo_executed,
            "evidence": repo_evidence or None,
        },
        "chatgpt_v12_analytics": {
            "executed": chatgpt_executed,
            "valid_current_inputs": bool(valid_current_inputs),
            "model_refresh": model_refresh,
            "model_timestamp": model_timestamp,
            "outputs": outputs if chatgpt_executed else None,
        },
        "repository_python_nonexecution_suppresses_v12_analytics": False,
        "execution_truths_are_separate": True,
    }


def _watchlist_feature_family(row: Mapping[str, Any]) -> dict[str, Any]:
    position = str(row.get("position") or "").upper()
    contract = WATCHLIST_POSITION_FORMULAE.get(position) or {
        "formula_id": "UNSUPPORTED",
        "features": (),
    }
    supplied = dict(row.get("position_specific_evidence") or {})
    values = {
        key: supplied.get(key)
        for key in contract["features"]
    }
    present = [
        key
        for key, value in values.items()
        if value not in (None, "", "UNAVAILABLE")
    ]
    total = len(values)
    coverage = (len(present) / total) if total else 0.0
    return {
        "position": position,
        "formula_id": contract["formula_id"],
        "features": values,
        "present_features": present,
        "required_feature_count": total,
        "present_feature_count": len(present),
        "coverage": round(coverage, 6),
        "attacker_xgi_gate_required": False if position == "GK" else None,
        "decision_authority": False,
        "purpose": "POSITION_SPECIFIC_WATCHLIST_EVIDENCE_AND_ADMISSION",
    }


def _watchlist_admission(row: Mapping[str, Any], family: Mapping[str, Any]) -> dict[str, Any]:
    # Reuse the existing Stage-C security screen. This is an admission gate,
    # not a second xMins/P(start) model or a transfer decision authority.
    from src.models.v12_stagec_universe_scanner import load_config as load_stagec_config

    thresholds = dict(load_stagec_config().get("signal_thresholds") or {})
    minimum_xmins = float(thresholds.get("secure_xmins") or 70.0)
    minimum_p_start = float(thresholds.get("secure_p_start") or 0.75)
    maximum_p_dnp = max(0.0, 1.0 - minimum_p_start)

    def number(value: Any) -> float | None:
        try:
            out = float(value)
        except (TypeError, ValueError):
            return None
        return out

    xmins = number(row.get("xmins"))
    p_start = number(row.get("p_start"))
    p_dnp = number(row.get("p_dnp"))
    p_available = number(row.get("p_available"))
    feature_coverage = number(family.get("coverage")) or 0.0
    lineage = dict(row.get("stage2_lineage") or {})
    evidence_complete = bool(
        lineage.get("lineage_complete", row.get("canonical_evaluation_complete"))
    )
    checks = {
        "availability_present": p_available is not None,
        "availability_supportable": p_available is not None and p_available >= minimum_p_start,
        "p_start_secure": p_start is not None and p_start >= minimum_p_start,
        "xmins_secure": xmins is not None and xmins >= minimum_xmins,
        "p_dnp_present": p_dnp is not None,
        "p_dnp_secure": p_dnp is not None and p_dnp <= maximum_p_dnp,
        "canonical_evidence_complete": evidence_complete,
        "position_specific_inputs_complete": feature_coverage >= 0.5,
    }
    admitted = all(checks.values())
    return {
        "admitted": admitted,
        "checks": checks,
        "minimum_xmins": minimum_xmins,
        "minimum_p_start": minimum_p_start,
        "maximum_p_dnp": round(maximum_p_dnp, 6),
        "threshold_source": "config/intelligence/v12_stagec_universe_scanner.json:signal_thresholds",
        "no_transfer_action_authority": True,
    }


def build_watchlist20(
    *,
    evaluated_universe: Sequence[Mapping[str, Any]],
    owned_element_ids: Sequence[int],
    universe_authority: str,
) -> dict[str, Any]:
    """Build Scanner20 plus an unpadded actionable subset from canonical V12 evidence."""
    authority = str(universe_authority or "").strip().upper()
    if authority not in {"FULL", "PARTIAL"}:
        raise ReportOrchestrationError("universe_authority must be FULL/PARTIAL")
    owned = {int(value) for value in owned_element_ids}
    rows: list[dict[str, Any]] = []
    scanned_ids: set[int] = set()
    for index, raw in enumerate(evaluated_universe):
        if not isinstance(raw, Mapping):
            continue
        element = raw.get("element_id")
        position = str(raw.get("position") or "").upper()
        if element is None or position not in POSITIONS:
            continue
        element = int(element)
        scanned_ids.add(element)
        if element in owned or raw.get("eligible") is False:
            continue
        if raw.get("canonical_evaluation_complete") is False:
            continue
        score = raw.get("football_score")
        canonical_rank = raw.get("canonical_rank")
        family = _watchlist_feature_family(raw)
        admission = _watchlist_admission(raw, family)
        rows.append(
            {
                **dict(raw),
                "element_id": element,
                "position": position,
                "position_specific_evidence": family,
                "admission_gate": admission,
                "watchlist_action": "WATCH",
                "_input_index": index,
                "_canonical_rank": canonical_rank,
                "_football_score": score,
            }
        )

    selected: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for position in POSITIONS:
        pool = [row for row in rows if row["position"] == position]

        def key(row: Mapping[str, Any]):
            rank = row.get("_canonical_rank")
            score = row.get("_football_score")
            coverage = float(
                ((row.get("position_specific_evidence") or {}).get("coverage"))
                or 0.0
            )
            if rank is not None:
                try:
                    return (0, float(rank), -coverage, int(row["_input_index"]))
                except (TypeError, ValueError):
                    pass
            if score is not None:
                try:
                    return (1, -float(score), -coverage, int(row["_input_index"]))
                except (TypeError, ValueError):
                    pass
            return (2, 0.0, -coverage, int(row["_input_index"]))

        pool.sort(key=key)
        chosen = pool[:5]
        counts[position] = len(chosen)
        selected.extend(chosen)

    actionable = [
        dict(row)
        for row in selected
        if bool((row.get("admission_gate") or {}).get("admitted"))
    ]

    for row in selected:
        row.pop("_input_index", None)
        row.pop("_canonical_rank", None)
        row.pop("_football_score", None)
    for row in actionable:
        row.pop("_input_index", None)
        row.pop("_canonical_rank", None)
        row.pop("_football_score", None)
        row["watchlist_action"] = "ACTIONABLE_MONITOR"
        row["action"] = "WATCH"

    complete = len(selected) == 20 and all(counts.get(pos) == 5 for pos in POSITIONS)
    if authority == "FULL" and complete:
        state = "COMPLETE"
        reason = None
    else:
        state = "DEGRADED" if selected else "UNAVAILABLE"
        missing = {pos: max(0, 5 - counts.get(pos, 0)) for pos in POSITIONS}
        reason = (
            "current canonical evaluated universe does not support exact 5/5/5/5"
            f"; missing={missing}"
        )
    return {
        "state": state,
        "available_count": len(selected),
        "expected_count": 20,
        "rows": selected,
        "scanner20": selected,
        "actionable_watchlist": actionable,
        "actionable_count": len(actionable),
        "position_counts": counts,
        "universe_authority": authority,
        "full_eligible_universe_scanned_count": len(scanned_ids),
        "owned_excluded": not bool(owned & {int(row["element_id"]) for row in selected}),
        "degradation_reason": reason,
        "selection_uses_existing_canonical_evaluation_only": True,
        "macro_weights": {
            "PROVEN_HISTORICAL": 0.20,
            "TACTICAL_ROLE": 0.25,
            "CURRENT_UNDERLYING": 0.30,
            "FIXTURE_SECURITY": 0.25,
        },
        "position_formulae": {
            pos: WATCHLIST_POSITION_FORMULAE[pos]["formula_id"]
            for pos in POSITIONS
        },
        "position_specific_evidence_is_watchlist_only": True,
        "actionable_watchlist_is_unpadded_subset": True,
        "watchlist_never_emits_act": True,
        "price_is_overlay_not_primary_authority": True,
        "new_player_score_created": False,
    }


def _calendar_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def build_calendar_workload_context(
    *,
    planning_gw: int,
    pl_fixtures: Sequence[Mapping[str, Any]],
    team_ids: Sequence[int],
    relevant_players: Sequence[Mapping[str, Any]],
    verified_schedule_events: Sequence[Mapping[str, Any]] = (),
    non_pl_schedule_authority: bool = False,
    report_timestamp: Any = None,
    weather_rows: Sequence[Mapping[str, Any]] = (),
    weather_forecast_horizon_hours: float | None = None,
) -> dict[str, Any]:
    """Build data-driven GW topology and descriptive workload/travel evidence.

    This consumes verified schedule evidence only. It never applies a static
    fatigue penalty and never mutates xPts, P(start), or xMins.
    """
    report_dt = _calendar_dt(report_timestamp)
    fixtures = [
        dict(row)
        for row in pl_fixtures
        if isinstance(row, Mapping) and int(row.get("event") or -1) == int(planning_gw)
    ]
    team_fixture_counts = {int(team): 0 for team in team_ids}
    for row in fixtures:
        for key in ("team_h", "team_a"):
            try:
                team = int(row.get(key))
            except (TypeError, ValueError):
                continue
            team_fixture_counts[team] = team_fixture_counts.get(team, 0) + 1

    doubles = sorted(team for team, count in team_fixture_counts.items() if count > 1)
    blanks = sorted(team for team, count in team_fixture_counts.items() if count == 0)
    rearranged = any(
        bool(row.get("rearranged") or row.get("rescheduled") or row.get("postponed_then_rearranged"))
        for row in fixtures
    )

    non_pl_schedule = [
        dict(row)
        for row in verified_schedule_events
        if isinstance(row, Mapping)
    ]
    pl_schedule: list[dict[str, Any]] = []
    for fixture in pl_fixtures:
        if not isinstance(fixture, Mapping):
            continue
        kickoff = fixture.get("kickoff_time")
        for side, opponent_side, home in (("team_h", "team_a", True), ("team_a", "team_h", False)):
            try:
                team_id = int(fixture.get(side))
                opponent_id = int(fixture.get(opponent_side))
            except (TypeError, ValueError):
                continue
            pl_schedule.append(
                {
                    "fixture_id": fixture.get("id"),
                    "team_id": team_id,
                    "opponent_team_id": opponent_id,
                    "kickoff": kickoff,
                    "competition": "Premier League",
                    "competition_category": "DOMESTIC_LEAGUE",
                    "home_away": "H" if home else "A",
                    "verified_source": "OFFICIAL_FPL_FIXTURE",
                }
            )
    normalized_schedule = pl_schedule + non_pl_schedule
    categories = {
        str(row.get("competition_category") or "").upper()
        for row in normalized_schedule
        if row.get("competition_category")
    }

    def event_dt(row: Mapping[str, Any]) -> datetime | None:
        return _calendar_dt(
            row.get("kickoff")
            or row.get("kickoff_time")
            or row.get("datetime")
        )

    # Workload/topology flags are scoped to the planning context, not the
    # repository's entire verified schedule history/future. The maximum
    # governed lookback is the existing 21-day workload horizon; future
    # non-PL evidence is relevant only through the latest planning-GW PL
    # kickoff. This prevents an old or distant-future international/cup event
    # from falsely labelling the current period or player load.
    planning_fixture_dts = [
        event_dt(row)
        for row in fixtures
        if event_dt(row) is not None
    ]
    context_floor = (
        report_dt - timedelta(days=21)
        if report_dt is not None
        else None
    )
    context_ceiling = max(planning_fixture_dts, default=None)

    def in_planning_context(dt: datetime) -> bool:
        if context_floor is not None and dt < context_floor:
            return False
        if context_ceiling is not None and dt > context_ceiling:
            return False
        return True

    relevant_non_pl_schedule = [
        row
        for row in non_pl_schedule
        if (dt := event_dt(row)) is not None and in_planning_context(dt)
    ]
    relevant_categories = {
        str(row.get("competition_category") or "").upper()
        for row in relevant_non_pl_schedule
        if row.get("competition_category")
    }
    has_international = "INTERNATIONAL" in relevant_categories
    has_non_pl = any(
        category in {"CONTINENTAL_CLUB", "DOMESTIC_CUP", "INTERNATIONAL", "GLOBAL_CLUB"}
        for category in relevant_categories
    )

    player_rows: list[dict[str, Any]] = []
    any_congested = False
    any_short_rest = False
    for raw_player in relevant_players:
        if not isinstance(raw_player, Mapping):
            continue
        element = raw_player.get("element_id", raw_player.get("element"))
        team_id = raw_player.get("team_id", raw_player.get("team"))
        try:
            element_i = int(element)
            team_i = int(team_id)
        except (TypeError, ValueError):
            continue

        team_events = [
            row for row in normalized_schedule
            if int(row.get("team_id") or -1) == team_i
            and (
                row.get("player_id") in (None, "", element_i)
                or int(row.get("player_id") or -1) == element_i
            )
        ]
        dated = [(event_dt(row), row) for row in team_events]
        dated = [(dt, row) for dt, row in dated if dt is not None]
        dated.sort(key=lambda item: item[0])

        upcoming_pl = []
        for fixture in fixtures:
            if team_i not in {
                int(fixture.get("team_h") or -1),
                int(fixture.get("team_a") or -1),
            }:
                continue
            upcoming_pl.append(fixture)
        next_pl_dt = min(
            (event_dt(row) for row in upcoming_pl if event_dt(row) is not None),
            default=None,
        )
        player_context_floor = (
            report_dt - timedelta(days=21)
            if report_dt is not None
            else None
        )
        player_context_ceiling = next_pl_dt or context_ceiling
        context_dated = [
            (dt, row)
            for dt, row in dated
            if (
                (player_context_floor is None or dt >= player_context_floor)
                and (player_context_ceiling is None or dt <= player_context_ceiling)
            )
        ]
        past_context_dated = [
            (dt, row)
            for dt, row in context_dated
            if report_dt is None or dt <= report_dt
        ]

        counts: dict[str, int] = {}
        minutes: dict[str, float | None] = {}
        for days in (3, 7, 14, 21):
            if report_dt is None:
                window_rows = []
            else:
                start = report_dt - timedelta(days=days)
                window_rows = [
                    row for dt, row in dated
                    if start <= dt <= report_dt
                ]
            counts[str(days)] = len(window_rows)
            minute_values = [
                float(row.get("minutes"))
                for row in window_rows
                if row.get("minutes") is not None
            ]
            minutes[str(days)] = (
                round(sum(minute_values), 1) if minute_values else None
            )

        previous_dt = max(
            (dt for dt, _ in dated if report_dt is not None and dt <= report_dt),
            default=None,
        )
        days_rest = (
            round((next_pl_dt - previous_dt).total_seconds() / 86400.0, 2)
            if previous_dt is not None and next_pl_dt is not None
            else None
        )
        short_rest = days_rest is not None and days_rest < 4.0
        congested = counts.get("7", 0) >= 3
        any_short_rest = any_short_rest or short_rest
        any_congested = any_congested or congested

        long_haul = any(
            bool(row.get("long_haul"))
            for _, row in past_context_dated
        )
        international = any(
            str(row.get("competition_category") or "").upper() == "INTERNATIONAL"
            for _, row in context_dated
        )
        domestic_cup = any(
            str(row.get("competition_category") or "").upper() == "DOMESTIC_CUP"
            for _, row in context_dated
        )
        continental = any(
            str(row.get("competition_category") or "").upper() == "CONTINENTAL_CLUB"
            for _, row in context_dated
        )
        tournament_absence = any(
            bool(row.get("tournament_absence"))
            for _, row in context_dated
        )
        non_pl_context = [
            (dt, row)
            for dt, row in context_dated
            if str(row.get("competition_category") or "").upper()
            != "DOMESTIC_LEAGUE"
        ]
        non_pl_competitions = sorted(
            {
                str(row.get("competition") or "UNSPECIFIED")
                for _, row in non_pl_context
            }
        )
        next_non_pl = next(
            (
                {
                    "competition": row.get("competition"),
                    "kickoff": dt.isoformat(),
                    "home_away": row.get("home_away"),
                    "opponent": row.get("opponent"),
                    "travel_context": row.get("travel_context"),
                }
                for dt, row in non_pl_context
                if report_dt is not None and dt > report_dt
            ),
            None,
        )
        next_non_pl_dt = (
            _calendar_dt(next_non_pl.get("kickoff"))
            if isinstance(next_non_pl, Mapping)
            else None
        )
        rest_after_next_non_pl_hours = (
            round(
                (next_pl_dt - next_non_pl_dt).total_seconds() / 3600.0,
                2,
            )
            if next_pl_dt is not None
            and next_non_pl_dt is not None
            and next_pl_dt >= next_non_pl_dt
            else None
        )
        reintegration = next(
            (
                row.get("reintegration_state")
                for _, row in reversed(past_context_dated)
                if row.get("reintegration_state")
            ),
            None,
        )

        if tournament_absence:
            load_state = "TOURNAMENT ABSENCE"
        elif reintegration:
            load_state = "REINTEGRATION WATCH"
        elif long_haul:
            load_state = "LONG-HAUL RETURN"
        elif international:
            load_state = "INTERNATIONAL DUTY"
        elif congested:
            load_state = "CONGESTED"
        elif short_rest:
            load_state = "SHORT REST"
        elif continental:
            load_state = "EUROPE MIDWEEK"
        elif domestic_cup:
            load_state = "DOMESTIC CUP LOAD"
        else:
            load_state = "NORMAL LOAD"

        projection_fixtures = [
            dict(row)
            for row in raw_player.get("planning_fixture_evidence") or []
            if isinstance(row, Mapping)
        ]
        by_fixture_id = {
            int(row.get("fixture_id")): row
            for row in projection_fixtures
            if row.get("fixture_id") is not None
        }
        player_fixtures = []
        for fixture in upcoming_pl:
            home = int(fixture.get("team_h") or -1) == team_i
            fixture_id = fixture.get("id")
            projected = (
                by_fixture_id.get(int(fixture_id))
                if fixture_id is not None
                else None
            ) or {}
            player_fixtures.append(
                {
                    "fixture_id": fixture_id,
                    "opponent_team_id": (
                        fixture.get("team_a") if home else fixture.get("team_h")
                    ),
                    "home": home,
                    "kickoff": fixture.get("kickoff_time"),
                    "xpts": projected.get("xpts"),
                    "xmins": projected.get("xmins"),
                    "p_start": projected.get("p_start"),
                    "matchup": projected.get("matchup"),
                    "rest_from_previous_fixture_hours": projected.get(
                        "rest_from_previous_fixture_hours"
                    ),
                }
            )
        blank = not player_fixtures
        player_rows.append(
            {
                "element_id": element_i,
                "player": raw_player.get("name") or raw_player.get("player"),
                "team_id": team_i,
                "gw_state": "BLANK" if blank else ("DOUBLE" if len(player_fixtures) > 1 else "NORMAL"),
                "planning_gw_fixtures": player_fixtures,
                "previous_match_datetime": previous_dt.isoformat() if previous_dt else None,
                "next_pl_fixture_datetime": next_pl_dt.isoformat() if next_pl_dt else None,
                "matches_last_days": counts,
                "minutes_last_days": minutes,
                "days_rest": days_rest,
                "load_state": load_state,
                "non_pl_competitions": non_pl_competitions,
                "next_non_pl_event": next_non_pl,
                "rest_hours_after_next_non_pl_to_pl": rest_after_next_non_pl_hours,
                "cross_border_travel": any(
                    bool(row.get("cross_border"))
                    for _, row in context_dated
                ),
                "long_haul": long_haul,
                "timezone_shift_hours": max(
                    [
                        abs(float(row.get("timezone_shift_hours")))
                        for _, row in context_dated
                        if row.get("timezone_shift_hours") is not None
                    ]
                    or [0.0]
                ),
                "return_to_club_interval_hours": next(
                    (
                        row.get("return_to_club_interval_hours")
                        for _, row in reversed(context_dated)
                        if row.get("return_to_club_interval_hours") is not None
                    ),
                    None,
                ),
                "tournament_absence": tournament_absence,
                "confirmed_call_up": any(
                    bool(row.get("confirmed_call_up"))
                    for _, row in context_dated
                ),
                "return_date": next(
                    (
                        row.get("return_date")
                        for _, row in reversed(context_dated)
                        if row.get("return_date")
                    ),
                    None,
                ),
                "injury_knock": next(
                    (
                        row.get("injury_knock")
                        for _, row in reversed(context_dated)
                        if row.get("injury_knock")
                    ),
                    None,
                ),
                "reintegration_state": reintegration,
            }
        )

    if doubles and blanks:
        topology = "MIXED_DGW_BGW"
    elif doubles:
        topology = "DOUBLE_GW"
    elif blanks:
        topology = "BLANK_GW"
    elif rearranged:
        topology = "REARRANGED_FIXTURE"
    elif has_international:
        topology = "INTERNATIONAL_BREAK"
    elif any_congested:
        topology = "CONGESTED_PERIOD"
    elif has_non_pl:
        topology = "NORMAL_WITH_MIDWEEK_COMPETITION"
    else:
        topology = "NORMAL_GW"

    weather_by_fixture = {
        int(row.get("fixture_id")): dict(row)
        for row in weather_rows
        if isinstance(row, Mapping) and row.get("fixture_id") is not None
    }
    weather: list[dict[str, Any]] = []
    for fixture in fixtures:
        fixture_id = fixture.get("id")
        kickoff = event_dt(fixture)
        bound = weather_by_fixture.get(int(fixture_id)) if fixture_id is not None else None
        if bound:
            weather.append(bound)
            continue
        inside = (
            report_dt is not None
            and kickoff is not None
            and weather_forecast_horizon_hours is not None
            and 0 <= (kickoff - report_dt).total_seconds() / 3600.0
            <= float(weather_forecast_horizon_hours)
        )
        weather.append(
            {
                "fixture_id": fixture_id,
                "kickoff": fixture.get("kickoff_time"),
                "state": (
                    "WEATHER UNAVAILABLE — REPORT-TIME SOURCE NOT BOUND"
                    if inside
                    else "WEATHER UNAVAILABLE — OUTSIDE RELIABLE FORECAST HORIZON"
                    if weather_forecast_horizon_hours is not None
                    else "WEATHER UNAVAILABLE — FORECAST HORIZON NOT AUTHORIZED"
                ),
                "fpl_impact": "UNAVAILABLE",
            }
        )

    complete_schedule_scope = bool(non_pl_schedule_authority)
    return {
        "state": "COMPLETE" if complete_schedule_scope else "DEGRADED",
        "planning_gw": int(planning_gw),
        "gw_topology": topology,
        "period_flags": {
            "double_gw_teams": doubles,
            "blank_gw_teams": blanks,
            "rearranged_fixture": rearranged,
            "international_schedule_present": has_international,
            "non_pl_schedule_present": has_non_pl,
            "congested_player_present": any_congested,
            "short_rest_player_present": any_short_rest,
        },
        "fixtures": fixtures,
        "verified_schedule_events": normalized_schedule,
        "competition_coverage": {
            "official_pl": True,
            "verified_non_pl_schedule_bound": complete_schedule_scope,
            "verified_non_pl_event_count": len(non_pl_schedule),
            "competition_names_data_driven": sorted(
                {
                    str(row.get("competition") or "UNSPECIFIED")
                    for row in normalized_schedule
                }
            ),
            "competition_categories_data_driven": sorted(categories),
        },
        "player_workload": player_rows,
        "weather": weather,
        "weather_nested_in_s05": True,
        "workload_feeds_p1_1_review_only": True,
        "static_fatigue_penalty_applied": False,
        "weather_mutates_football_model": False,
        "dgw_cross_fixture_covariance_claimed": False,
        "degradation_reason": (
            None
            if complete_schedule_scope
            else "verified non-PL first-team schedule source is not bound for this occurrence; PL topology remains authoritative"
        ),
    }

def _predictor_rows(artifact: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return predictor player rows; real V6 data.players is first-class."""
    data = artifact.get("data")
    if isinstance(data, Mapping) and isinstance(data.get("players"), list):
        return [
            dict(row)
            for row in data.get("players") or []
            if isinstance(row, Mapping)
        ]
    for key in ("rows", "players", "predictions"):
        value = artifact.get(key)
        if isinstance(value, list):
            return [dict(row) for row in value if isinstance(row, Mapping)]
    return []


def _real_predictor_schema(artifact: Mapping[str, Any]) -> bool:
    data = artifact.get("data")
    return isinstance(data, Mapping) and isinstance(data.get("players"), list)


def _finite_price_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _official_current_price(now_cost: Any) -> Any:
    value = _finite_price_number(now_cost)
    if value is None:
        return "UNAVAILABLE"
    # Official FPL now_cost uses tenths of £m; retain normalized FACT price.
    return round(value / 10.0, 1) if value >= 20.0 else round(value, 1)


def _parse_price_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


_PRICE_UK = ZoneInfo(OFFICIAL_UPDATE_TIMEZONE)
_PRICE_WIB = ZoneInfo(DISPLAY_TIMEZONE)


def _next_official_price_cycle(evidence_timestamp: Any, *, offset: int = 0) -> tuple[str, str] | tuple[None, None]:
    """Return the governed daily 00:00 Europe/London cycle and the same instant in WIB."""
    observed = _parse_price_dt(evidence_timestamp)
    if observed is None:
        return None, None
    local = observed.astimezone(_PRICE_UK)
    target_date = local.date() + timedelta(days=1 + max(0, int(offset)))
    uk_cycle = datetime(target_date.year, target_date.month, target_date.day, 0, 0, tzinfo=_PRICE_UK)
    return uk_cycle.isoformat(), uk_cycle.astimezone(_PRICE_WIB).isoformat()


def _visible_price_direction(projected_percent: Any) -> str:
    value = _finite_price_number(projected_percent)
    if value is None:
        return "UNAVAILABLE"
    if value > 0:
        return "RISE"
    if value < 0:
        return "FALL"
    return "NEUTRAL"


def _format_price_cycle(value: Any, *, wib: bool) -> str | None:
    parsed = _parse_price_dt(value)
    if parsed is None:
        return None
    local = parsed.astimezone(_PRICE_WIB if wib else _PRICE_UK)
    zone = "WIB" if wib else (local.tzname() or "UK")
    return f"{local.strftime('%d %b %Y • %H:%M')} {zone}"


def _governed_expected_cycle(
    projections: Any,
    *,
    evidence_timestamp: Any,
    locked_until: Any,
) -> dict[str, Any]:
    """Map the existing 0/1/2 predictor horizon to truthful calendar date states."""
    next_uk, next_wib = _next_official_price_cycle(evidence_timestamp, offset=0)
    base = {
        "next_official_price_cycle_uk": next_uk or "UNAVAILABLE",
        "next_official_price_cycle_wib": next_wib or "UNAVAILABLE",
        "cycles_to_expected_change": "UNAVAILABLE",
        "estimated_change_window": "UNAVAILABLE",
        "eta_context": None,
        "estimated_change_date_uk": None,
        "estimated_change_date_wib": None,
        "estimated_change_at_uk": None,
        "estimated_change_at_wib": None,
        "last_supported_projection_date_uk": None,
        "last_supported_projection_date_wib": None,
        "last_supported_projection_at_uk": None,
        "last_supported_projection_at_wib": None,
        "horizon_cycles": 0,
        "latest_supported_projection": None,
        "projection_offset": None,
        "date_state": "DATE_UNAVAILABLE",
        "date_state_complete": True,
        "degradation_reason": None,
        "eta_reason": None,
        "eta_uses_existing_threshold": True,
        "governed_threshold_percent": EXISTING_PRICE_MODEL_THRESHOLD,
        "horizon_extension_used": False,
        "governed_projection_offsets": (0, 1, 2),
    }
    if next_uk is None or next_wib is None:
        reason = "EVIDENCE_TIMESTAMP_UNAVAILABLE"
        base.update({"eta_reason": reason, "degradation_reason": reason})
        return base
    if not isinstance(projections, list):
        reason = "PREDICTOR_PROJECTIONS_UNAVAILABLE"
        base.update({"eta_reason": reason, "degradation_reason": reason})
        return base

    locked = _parse_price_dt(locked_until)
    candidates: list[tuple[int, float]] = []
    for item in projections:
        if not isinstance(item, Mapping):
            continue
        try:
            offset = int(item.get("offset"))
        except (TypeError, ValueError):
            continue
        # The existing governed predictor contract exposes only these offsets.
        if offset not in {0, 1, 2}:
            continue
        projected = _finite_price_number(item.get("projected_percent"))
        if projected is None:
            continue
        candidates.append((offset, projected))

    candidates.sort()
    if not candidates:
        reason = "NO_VALID_GOVERNED_PROJECTION_OFFSETS"
        base.update({"eta_reason": reason, "degradation_reason": reason})
        return base

    max_offset, latest_projection = candidates[-1]
    last_uk, last_wib = _next_official_price_cycle(evidence_timestamp, offset=max_offset)
    base.update(
        {
            "horizon_cycles": max_offset + 1,
            "latest_supported_projection": latest_projection,
            "last_supported_projection_at_uk": last_uk,
            "last_supported_projection_at_wib": last_wib,
            "last_supported_projection_date_uk": _format_price_cycle(last_uk, wib=False),
            "last_supported_projection_date_wib": _format_price_cycle(last_wib, wib=True),
        }
    )

    for offset, projected in candidates:
        if abs(projected) < EXISTING_PRICE_MODEL_THRESHOLD:
            continue
        cycle_uk, cycle_wib = _next_official_price_cycle(evidence_timestamp, offset=offset)
        if cycle_uk is None or cycle_wib is None:
            continue
        cycle_dt = _parse_price_dt(cycle_uk)
        if (
            locked is not None
            and cycle_dt is not None
            and cycle_dt.astimezone(timezone.utc) < locked.astimezone(timezone.utc)
        ):
            continue
        cycle_label = "NEXT CYCLE" if offset == 0 else f"{offset} CYCLE" if offset == 1 else f"{offset} CYCLES"
        wib_display = _format_price_cycle(cycle_wib, wib=True)
        base.update(
            {
                "cycles_to_expected_change": cycle_label,
                "estimated_change_window": wib_display or "UNAVAILABLE",
                "eta_context": wib_display,
                "estimated_change_date_uk": _format_price_cycle(cycle_uk, wib=False),
                "estimated_change_date_wib": wib_display,
                "estimated_change_at_uk": cycle_uk,
                "estimated_change_at_wib": cycle_wib,
                "projection_offset": offset,
                "date_state": "EXPECTED_CHANGE_DATE",
                "date_state_complete": True,
                "eta_reason": None,
                "degradation_reason": None,
            }
        )
        return base

    last_display = base["last_supported_projection_date_wib"]
    base.update(
        {
            "date_state": "NO_CROSSING_WITHIN_GOVERNED_HORIZON",
            "date_state_complete": True,
            "estimated_change_window": "UNAVAILABLE",
            "eta_context": (
                f"Belum terdeteksi berubah sampai {last_display}"
                if last_display
                else "NO EXPECTED CHANGE WITHIN GOVERNED HORIZON"
            ),
            "eta_reason": "NO_EXISTING_PREDICTOR_CYCLE_CROSSES_GOVERNED_THRESHOLD",
            "degradation_reason": None,
        }
    )
    return base


def _price_decision_impact(
    *,
    element_id: int,
    direction: str,
    owned_ids: set[int],
    target_ids: set[int],
) -> str:
    if element_id in owned_ids:
        if direction == "FALL":
            return "OWNED — FALL MAY REDUCE SELL VALUE"
        if direction == "RISE":
            return "OWNED — RISE; MONITOR SELL-VALUE / AFFORDABILITY EFFECT"
        return "OWNED — NEUTRAL PRICE SIGNAL"
    if element_id in target_ids:
        if direction == "RISE":
            return "TARGET — RISE MAY REMOVE AFFORDABILITY"
        if direction == "FALL":
            return "TARGET — FALL MAY IMPROVE AFFORDABILITY"
        return "TARGET — NEUTRAL PRICE SIGNAL"
    return "WATCH ONLY — NO BOUND PERSONAL ROUTE"


def _visible_price_contract(
    row: Mapping[str, Any],
    *,
    evidence_timestamp: Any,
    predictor_health: str,
    owned_ids: set[int],
    target_ids: set[int],
) -> dict[str, Any]:
    out = dict(row)
    direction = _visible_price_direction(out.get("projected_percent"))
    timing = _governed_expected_cycle(
        out.get("price_change_projections"),
        evidence_timestamp=evidence_timestamp,
        locked_until=out.get("locked_until"),
    )
    likelihood = out.get("likelihood")
    out.update(
        {
            "direction": direction,
            "official_or_provider_progress": out.get("price_change_percent", "UNAVAILABLE"),
            "prediction_strength": likelihood if likelihood is not None else "UNAVAILABLE",
            **timing,
            "estimate_source": "OFFICIAL_FPL_PRICE_CHANGE_PREDICTOR",
            "artifact_source": "official_price_predictor",
            "visible_source_label": (
                "Official FPL Price Change Predictor — official predictor guidance; "
                "not a guarantee of the next confirmed price change"
            ),
            "evidence_timestamp": evidence_timestamp or "UNAVAILABLE",
            "confidence": {
                "predictor_health": predictor_health,
                "native_likelihood": likelihood if likelihood is not None else "UNAVAILABLE",
                "calibrating": bool(out.get("calibrating")),
                "locked_until": out.get("locked_until"),
            },
            "impact_on_our_decision": _price_decision_impact(
                element_id=int(out["element_id"]),
                direction=direction,
                owned_ids=owned_ids,
                target_ids=target_ids,
            ),
        }
    )
    return out


def _offset_zero_projection(row: Mapping[str, Any]) -> Mapping[str, Any] | None:
    projections = row.get("price_change_projections")
    if not isinstance(projections, list):
        return None
    for projection in projections:
        if not isinstance(projection, Mapping):
            continue
        offset = projection.get("offset")
        try:
            is_zero = float(offset) == 0.0
        except (TypeError, ValueError):
            is_zero = False
        if is_zero:
            return projection
    return None


def _normalize_real_price_row(row: Mapping[str, Any]) -> dict[str, Any] | None:
    projection = _offset_zero_projection(row)
    if projection is None:
        return None
    projected = _finite_price_number(projection.get("projected_percent"))
    element = row.get("id")
    if projected is None or element is None:
        return None
    try:
        element_id = int(element)
    except (TypeError, ValueError):
        return None
    return {
        "element_id": element_id,
        "player": row.get("web_name") or f"element:{element_id}",
        "current_price": _official_current_price(row.get("now_cost")),
        "price_fact": "FACT",
        "projected_percent": projected,
        "likelihood": projection.get("likelihood"),
        "predictor_classification": "MODEL",
        "projection_offset": 0,
        "price_change_percent": row.get("price_change_percent"),
        "price_change_hourly_rate": row.get("price_change_hourly_rate"),
        "selected_by_percent": row.get("selected_by_percent"),
        "transfers_in_event": row.get("transfers_in_event"),
        "transfers_out_event": row.get("transfers_out_event"),
        "locked_until": row.get("price_change_locked_until"),
        "calibrating": row.get("price_change_calibrating"),
        "team": row.get("team"),
        "element_type": row.get("element_type"),
        "price_change_projections": [
            dict(item)
            for item in (row.get("price_change_projections") or [])
            if isinstance(item, Mapping)
        ],
    }


def _price_source_freshness(
    evidence_timestamp: Any,
    report_timestamp: Any,
    predictor_health: str,
) -> dict[str, Any]:
    observed = _parse_price_dt(evidence_timestamp)
    report = _parse_price_dt(report_timestamp)
    healthy = str(predictor_health or "").upper() in {"GREEN", "HEALTHY", "PASS", "CURRENT", "OK"}
    if observed is None or report is None:
        return {
            "source_age_minutes": None,
            "freshness": "UNKNOWN",
            "freshness_policy": "config/intelligence/price_radar.json:freshness.official_max_age_seconds",
        }
    age_minutes = max(0.0, (report - observed).total_seconds() / 60.0)
    return {
        "source_age_minutes": round(age_minutes, 1),
        "freshness": (
            "FRESH"
            if healthy and age_minutes * 60.0 <= OFFICIAL_MAX_AGE_SECONDS
            else "STALE"
        ),
        "freshness_policy": "config/intelligence/price_radar.json:freshness.official_max_age_seconds",
    }


def build_price20(
    *,
    predictor_artifact: Mapping[str, Any] | None,
    direction: str,
    owned_element_ids: Sequence[int] | None = None,
    target_element_ids: Sequence[int] | None = None,
    report_timestamp: Any = None,
) -> dict[str, Any]:
    """Consume current official_price_predictor output; never predict price itself."""
    if not predictor_artifact:
        return {
            "state": "UNAVAILABLE",
            "available_count": 0,
            "expected_count": 20,
            "rows": [],
            "degradation_reason": "current official_price_predictor artifact absent",
        }
    artifact = dict(predictor_artifact)
    health = str(
        artifact.get("health")
        or artifact.get("status")
        or artifact.get("source_health")
        or "UNKNOWN"
    ).upper()
    evidence_timestamp = artifact.get("checked_at") or artifact.get("generated_at")
    owned_ids = {int(value) for value in (owned_element_ids or ())}
    target_ids = {int(value) for value in (target_element_ids or ())}
    direction_token = str(direction or "").upper()
    if direction_token not in {"RISE", "FALL"}:
        raise ReportOrchestrationError("direction must be RISE/FALL")
    rows = _predictor_rows(artifact)

    if _real_predictor_schema(artifact):
        normalized = [
            _visible_price_contract(
                bound,
                evidence_timestamp=evidence_timestamp,
                predictor_health=health,
                owned_ids=owned_ids,
                target_ids=target_ids,
            )
            for row in rows
            if (bound := _normalize_real_price_row(row)) is not None
        ]
        if direction_token == "RISE":
            normalized.sort(
                key=lambda row: (-float(row["projected_percent"]), int(row["element_id"]))
            )
        else:
            normalized.sort(
                key=lambda row: (float(row["projected_percent"]), int(row["element_id"]))
            )
        selected = normalized[:20]
        usable_count = len(normalized)
        adapter = "V6_DATA_PLAYERS_OFFSET0"
    else:
        wanted = PRICE_UP if direction_token == "RISE" else PRICE_DOWN
        selected: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            token = str(
                row.get("risk_direction")
                or row.get("direction")
                or row.get("prediction")
                or ""
            ).upper()
            if token not in wanted:
                continue
            copied = dict(row)
            copied["_artifact_index"] = index
            selected.append(copied)

        def legacy_key(row: Mapping[str, Any]):
            for name in ("rank", "predictor_rank", "direction_rank"):
                if row.get(name) is not None:
                    try:
                        return (0, float(row[name]), int(row["_artifact_index"]))
                    except (TypeError, ValueError):
                        pass
            return (1, 0.0, int(row["_artifact_index"]))

        selected.sort(key=legacy_key)
        selected = selected[:20]
        for row in selected:
            row.pop("_artifact_index", None)
        usable_count = len(selected)
        adapter = "COMPACT_COMPAT"

    freshness = _price_source_freshness(
        evidence_timestamp,
        report_timestamp,
        health,
    )
    for row in selected:
        row.setdefault("date_state", "DATE_UNAVAILABLE")
        row.setdefault("date_state_complete", True)
        row.update(freshness)

    artifact_payload_hash = hashlib.sha256(
        json.dumps(
            artifact,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()

    enough = len(selected) == 20
    healthy = health in {"GREEN", "HEALTHY", "PASS", "CURRENT", "OK"}
    date_state_complete = (
        adapter != "V6_DATA_PLAYERS_OFFSET0"
        or all(bool(row.get("date_state_complete")) for row in selected)
    )
    missing_cycle_clock = (
        adapter == "V6_DATA_PLAYERS_OFFSET0"
        and any(
            row.get("next_official_price_cycle_uk") == "UNAVAILABLE"
            or row.get("next_official_price_cycle_wib") == "UNAVAILABLE"
            for row in selected
        )
    )
    invalid_eta_state = (
        adapter == "V6_DATA_PLAYERS_OFFSET0"
        and any(
            row.get("date_state") == "DATE_UNAVAILABLE"
            or bool(row.get("degradation_reason"))
            for row in selected
        )
    )
    # NO_CROSSING_WITHIN_GOVERNED_HORIZON is a healthy terminal predictor
    # outcome. It intentionally leaves expected-change-cycle fields unavailable
    # because no governed threshold crossing exists; that is not degradation.
    if enough and healthy and date_state_complete and not missing_cycle_clock and not invalid_eta_state:
        state = "COMPLETE"
    elif selected:
        state = "DEGRADED"
    else:
        state = "UNAVAILABLE"

    reason = None
    if state != "COMPLETE":
        if adapter == "V6_DATA_PLAYERS_OFFSET0" and not enough:
            reason = (
                f"official_price_predictor health={health}; "
                f"usable offset-0 {direction_token.lower()} rows={len(selected)}/20"
            )
        elif adapter == "V6_DATA_PLAYERS_OFFSET0" and not date_state_complete:
            incomplete = sum(not bool(row.get("date_state_complete")) for row in selected)
            reason = f"date-state terminal contract incomplete for {incomplete}/20 rows"
        elif adapter == "V6_DATA_PLAYERS_OFFSET0" and missing_cycle_clock:
            reason = "official_price_predictor evidence timestamp unavailable; official cycle timing cannot be derived"
        elif adapter == "V6_DATA_PLAYERS_OFFSET0" and invalid_eta_state:
            invalid = sum(
                row.get("date_state") == "DATE_UNAVAILABLE"
                or bool(row.get("degradation_reason"))
                for row in selected
            )
            reason = (
                f"official_price_predictor has genuinely unavailable/invalid ETA evidence "
                f"for {invalid}/20 rows"
            )
        else:
            reason = (
                f"official_price_predictor health={health}; "
                f"{direction_token.lower()} rows={len(selected)}/20"
            )
    return {
        "state": state,
        "available_count": len(selected),
        "expected_count": 20,
        "usable_eligible_rows": usable_count,
        "rows": selected,
        "predictor_health": health,
        "degradation_reason": reason,
        "artifact_adapter": adapter,
        "sort_contract": (
            "projected_percent DESC, id ASC"
            if direction_token == "RISE" and adapter == "V6_DATA_PLAYERS_OFFSET0"
            else "projected_percent ASC, id ASC"
            if direction_token == "FALL" and adapter == "V6_DATA_PLAYERS_OFFSET0"
            else "legacy compact predictor order"
        ),
        "current_price_classification": "FACT",
        "projection_classification": "MODEL",
        "visible_contract_fields": (
            "player",
            "current_price",
            "direction",
            "official_or_provider_progress",
            "prediction_strength",
            "next_official_price_cycle_uk",
            "next_official_price_cycle_wib",
            "cycles_to_expected_change",
            "estimated_change_window",
            "estimated_change_date_uk",
            "estimated_change_date_wib",
            "date_state",
            "last_supported_projection_date_wib",
            "horizon_cycles",
            "latest_supported_projection",
            "estimate_source",
            "evidence_timestamp",
            "source_age_minutes",
            "freshness",
            "confidence",
            "impact_on_our_decision",
        ),
        "uses_existing_predictor_only": True,
        "existing_eta_threshold_source": "config/intelligence/price_radar.json:model_interpretation.threshold_percent",
        "new_price_threshold_model_created": False,
        "new_price_predictor_created": False,
        "predictor_payload_hash": artifact_payload_hash,
        "horizon_extension_used": False,
        "governed_projection_offsets": (0, 1, 2),
        "date_state_complete_count": sum(
            bool(row.get("date_state_complete")) for row in selected
        ) if adapter == "V6_DATA_PLAYERS_OFFSET0" else None,
        "expected_change_date_count": sum(
            row.get("date_state") == "EXPECTED_CHANGE_DATE" for row in selected
        ) if adapter == "V6_DATA_PLAYERS_OFFSET0" else None,
        "no_crossing_count": sum(
            row.get("date_state") == "NO_CROSSING_WITHIN_GOVERNED_HORIZON" for row in selected
        ) if adapter == "V6_DATA_PLAYERS_OFFSET0" else None,
    }


def build_actionable_price_radar(
    *,
    owned15: Sequence[Mapping[str, Any]],
    predictor_artifact: Mapping[str, Any] | None = None,
    report_timestamp: Any = None,
) -> dict[str, Any]:
    """Always preserve owned identity; predictor evidence enriches but never removes OUR15."""
    artifact = dict(predictor_artifact or {})
    predictor_health = str(
        artifact.get("health")
        or artifact.get("status")
        or artifact.get("source_health")
        or "UNKNOWN"
    ).upper()
    evidence_timestamp = artifact.get("checked_at") or artifact.get("generated_at")
    freshness = _price_source_freshness(
        evidence_timestamp,
        report_timestamp,
        predictor_health,
    )
    predictor: dict[int, dict[str, Any]] = {}
    for row in _predictor_rows(artifact):
        raw_id = row.get("element_id", row.get("element", row.get("id")))
        if raw_id is None:
            continue
        try:
            predictor[int(raw_id)] = row
        except (TypeError, ValueError):
            continue

    identities: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw in owned15:
        if not isinstance(raw, Mapping):
            continue
        element = raw.get("element_id", raw.get("element"))
        if element is None:
            continue
        element = int(element)
        if element in seen:
            continue
        seen.add(element)

        pred_raw = dict(predictor.get(element) or {})
        normalized = _normalize_real_price_row(pred_raw) if pred_raw.get("price_change_projections") is not None else None
        visible = (
            _visible_price_contract(
                normalized,
                evidence_timestamp=evidence_timestamp,
                predictor_health=predictor_health,
                owned_ids={element},
                target_ids=set(),
            )
            if normalized is not None
            else None
        )
        raw_current = raw.get("current_price", raw.get("price"))
        current_price = (
            visible.get("current_price")
            if visible is not None and visible.get("current_price") != "UNAVAILABLE"
            else _official_current_price(raw_current)
            if raw_current is not None
            else "UNAVAILABLE"
        )
        raw_sell = raw.get("authenticated_sell_value", raw.get("selling_price"))
        sell_value = _official_current_price(raw_sell) if raw_sell is not None else "UNAVAILABLE"
        raw_sell_state = str(
            raw.get("sell_value_evidence_state")
            or raw.get("authenticated_evidence_state")
            or raw.get("authenticated_state")
            or ""
        ).upper()
        if sell_value == "UNAVAILABLE":
            sell_value_evidence_state = "UNAVAILABLE"
        elif raw_sell_state in {"CURRENT_AUTHENTICATED", "AUTH_CURRENT", "CURRENT"}:
            sell_value_evidence_state = "CURRENT_AUTHENTICATED"
        elif raw_sell_state in {"STALE_AUTHENTICATED_FALLBACK", "AUTH_STALE", "STALE"}:
            sell_value_evidence_state = "STALE_AUTHENTICATED_FALLBACK"
        else:
            sell_value_evidence_state = "AUTHENTICATED_FRESHNESS_UNPROVEN"

        identities.append(
            {
                "element_id": element,
                "name": raw.get("name") or (visible or {}).get("player"),
                "current_price": current_price,
                "price_fact": "FACT" if current_price != "UNAVAILABLE" else "UNAVAILABLE",
                "authenticated_sell_value": sell_value,
                "sell_value_evidence_state": sell_value_evidence_state,
                "predictor_direction": (visible or {}).get("direction", "UNAVAILABLE"),
                "predictor_progress": (visible or {}).get("official_or_provider_progress", "UNAVAILABLE"),
                "prediction_strength": (visible or {}).get("prediction_strength", "UNAVAILABLE"),
                "next_official_price_cycle_uk": (visible or {}).get("next_official_price_cycle_uk", "UNAVAILABLE"),
                "next_official_price_cycle_wib": (visible or {}).get("next_official_price_cycle_wib", "UNAVAILABLE"),
                "cycles_to_expected_change": (visible or {}).get("cycles_to_expected_change", "UNAVAILABLE"),
                "estimated_change_date_uk": (visible or {}).get("estimated_change_date_uk"),
                "estimated_change_date_wib": (visible or {}).get("estimated_change_date_wib"),
                "date_state": (visible or {}).get("date_state", "DATE_UNAVAILABLE"),
                "date_state_complete": bool((visible or {}).get("date_state_complete", True)),
                "date_state_reason": (
                    (visible or {}).get("degradation_reason")
                    or (None if visible is not None else "PREDICTOR_EVIDENCE_UNAVAILABLE")
                ),
                "last_supported_projection_date_wib": (visible or {}).get("last_supported_projection_date_wib"),
                "horizon_cycles": (visible or {}).get("horizon_cycles", 0),
                "latest_supported_projection": (visible or {}).get("latest_supported_projection"),
                "estimated_change_window": (visible or {}).get(
                    "estimated_change_window",
                    "UNAVAILABLE",
                ),
                "eta_context": (visible or {}).get("eta_context"),
                "eta_reason": (visible or {}).get(
                    "eta_reason",
                    "PREDICTOR_EVIDENCE_UNAVAILABLE" if visible is None else None,
                ),
                "estimate_source": (visible or {}).get("estimate_source", "OFFICIAL_FPL_PRICE_CHANGE_PREDICTOR" if pred_raw else "UNAVAILABLE"),
                "artifact_source": (visible or {}).get("artifact_source", "official_price_predictor" if pred_raw else "UNAVAILABLE"),
                "visible_source_label": (visible or {}).get(
                    "visible_source_label",
                    "Official FPL Price Change Predictor — official predictor guidance; not a guarantee of the next confirmed price change"
                    if pred_raw
                    else "UNAVAILABLE",
                ),
                "evidence_timestamp": (visible or {}).get("evidence_timestamp", evidence_timestamp or "UNAVAILABLE"),
                "source_age_minutes": freshness.get("source_age_minutes"),
                "freshness": freshness.get("freshness"),
                "freshness_policy": freshness.get("freshness_policy"),
                "confidence": (visible or {}).get("confidence", "UNAVAILABLE"),
                "sell_value_affordability_impact": (visible or {}).get(
                    "impact_on_our_decision",
                    "OWNED — PREDICTOR EVIDENCE UNAVAILABLE; DO NOT FABRICATE PRICE ACTION",
                ),
                "decision_implication": (visible or {}).get(
                    "impact_on_our_decision",
                    "OWNED — PREDICTOR EVIDENCE UNAVAILABLE; FOOTBALL DECISION CONTINUES",
                ),
                "predictor_projected_percent": (visible or {}).get("projected_percent", "UNAVAILABLE"),
                "predictor_classification": "MODEL" if pred_raw else "UNAVAILABLE",
                "predictor_evidence": pred_raw or None,
            }
        )

    complete = len(identities) == 15
    return {
        "state": "COMPLETE" if complete else ("DEGRADED" if identities else "UNAVAILABLE"),
        "available_count": len(identities),
        "expected_count": 15,
        "rows": identities,
        "identity_complete": complete,
        "predictor_complete_count": sum(
            row.get("predictor_direction") != "UNAVAILABLE" for row in identities
        ),
        "date_state_complete_count": sum(
            bool(row.get("date_state_complete")) for row in identities
        ),
        "degradation_reason": None if complete else "owned price identity coverage is not exact15",
        "price_alone_may_create_act": False,
    }


def build_icon_subscopes(
    *,
    submitted_picks: Sequence[Mapping[str, Any]] | None,
    submitted_denominator: int | None,
    standings: Sequence[Mapping[str, Any]] | None,
    standings_denominator: int | None,
    eo_rows: Sequence[Mapping[str, Any]] | None = None,
    rival_live_points: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Keep healthy ICON+ sub-scopes visible when another sub-scope is unavailable."""
    picks = [dict(row) for row in (submitted_picks or ()) if isinstance(row, Mapping)]
    standing_rows = [dict(row) for row in (standings or ()) if isinstance(row, Mapping)]
    eo = [dict(row) for row in (eo_rows or ()) if isinstance(row, Mapping)]
    live = [dict(row) for row in (rival_live_points or ()) if isinstance(row, Mapping)]

    if submitted_denominator is not None and len(picks) > int(submitted_denominator):
        raise ReportOrchestrationError("submitted pick coverage exceeds denominator")
    if standings_denominator is not None and len(standing_rows) > int(standings_denominator):
        raise ReportOrchestrationError("standings coverage exceeds denominator")

    picks_full = submitted_denominator is not None and len(picks) == int(submitted_denominator)
    standings_full = (
        standings_denominator is not None
        and len(standing_rows) == int(standings_denominator)
    )
    submitted_state = "COMPLETE" if picks_full else ("PARTIAL" if picks else "UNAVAILABLE")
    standings_state = (
        "COMPLETE" if standings_full else ("PARTIAL" if standing_rows else "UNAVAILABLE")
    )

    return {
        "submitted_picks_exposure": {
            "state": submitted_state,
            "available_count": len(picks),
            "expected_count": submitted_denominator,
            "rows": picks,
        },
        "live_standings_rank": {
            "state": standings_state,
            "available_count": len(standing_rows),
            "expected_count": standings_denominator,
            "rows": standing_rows,
        },
        "eo": {
            "state": "COMPLETE" if eo and picks_full else "UNAVAILABLE",
            "rows": eo if picks_full else [],
            "reason": None if eo and picks_full else "exact multiplier/coverage denominator unavailable",
        },
        "rival_live_points": {
            "state": "PARTIAL" if live else "UNAVAILABLE",
            "rows": live,
        },
        "subscopes_fail_operational_independently": True,
    }


def build_contextual_player_blocks(
    player_projection: Mapping[str, Any],
    *,
    fixture: Any | None = None,
) -> dict[str, Any]:
    """Nested human-facing player detail without changing DEEP top-level count."""
    contextual = dict(player_projection.get("contextual_dynamics") or {})
    fixture_contexts = [
        dict(row)
        for row in contextual.get("fixture_contexts") or []
        if isinstance(row, Mapping)
    ]
    selected = None
    if fixture is not None:
        selected = next(
            (
                row
                for row in fixture_contexts
                if str(row.get("fixture")) == str(fixture)
            ),
            None,
        )
    if selected is None and fixture_contexts:
        selected = fixture_contexts[0]
    if selected is None:
        return {
            "state": "UNAVAILABLE",
            "degradation_reason": "contextual trajectory/matchup evidence unavailable",
            "blocks": {},
        }

    matchup = dict(selected.get("matchup") or {})
    network = dict(selected.get("linkup_network") or {})
    relationships = [
        dict(row)
        for row in network.get("relationships") or []
        if isinstance(row, Mapping)
        and float(row.get("confidence") or 0.0) > 0.0
    ]
    relationships.sort(
        key=lambda row: (
            float(row.get("confidence") or 0.0),
            float(row.get("dependency_strength") or 0.0),
        ),
        reverse=True,
    )
    chains = [
        dict(row)
        for row in network.get("multi_player_chains") or []
        if isinstance(row, Mapping)
        and row.get("status") == "AVAILABLE"
        and float(row.get("confidence") or 0.0) > 0.0
    ]
    chains.sort(
        key=lambda row: (
            float(row.get("confidence") or 0.0),
            abs(float(row.get("multiplier") or 1.0) - 1.0),
        ),
        reverse=True,
    )
    return {
        "state": "COMPLETE",
        "fixture": selected.get("fixture"),
        "trajectory_classification": selected.get(
            "trajectory_classification"
        ),
        "latest_match_evidence": selected.get("latest_match_evidence"),
        "blocks": {
            "OPPONENT-SPECIFIC MATCHUP": {
                "historical_meetings": matchup.get("historical_meetings"),
                "result_evidence": (
                    matchup.get("result_process") or {}
                ).get("result_evidence"),
                "process_evidence": (
                    matchup.get("result_process") or {}
                ).get("process_evidence"),
                "tactical_similarity": matchup.get("tactical_similarity"),
                "sample_size": matchup.get("sample_size"),
                "bayesian_confidence": matchup.get("sample_shrinkage"),
                "current_relevance": matchup.get("tactical_similarity"),
                "classification": matchup.get("classification"),
                "opponent_history_scope": matchup.get("opponent_history_scope"),
                "prior_season_matchup_status": matchup.get(
                    "prior_season_matchup_status"
                ),
                "prior_season_meetings": matchup.get(
                    "prior_season_meetings"
                ),
            },
            "LINK-UP / COMBINATION NETWORK": {
                "PAIRWISE LINKS": relationships,
                "relationships": relationships,
                "relationship_count": len(relationships),
                "MULTI-PLAYER CHAINS": chains,
                "multi_player_chains": chains,
                "chain_count": len(chains),
                "insufficient_pairs_suppressed": True,
                "low_confidence_chains_suppressed": True,
            },
        },
    }


def build_post_match_universe_movers(
    post_match_scan: Mapping[str, Any] | None,
    *,
    post_match_deep_analysis: Mapping[str, Any] | None = None,
    limit_per_category: int = 5,
) -> dict[str, Any]:
    """Compact POST-MATCH Universe Movers block from the V12 broad scan.

    The block is descriptive evidence only. It does not create a transfer or
    mutate WAIT/PREPARE/ACT.
    """
    scan = dict(post_match_scan or {})
    deep = dict(post_match_deep_analysis or scan.get("deep_execution") or {})
    executed_ids = {
        int(value)
        for value in deep.get("executed_element_ids") or []
        if value is not None
    }
    players = [
        dict(row)
        for row in scan.get("material_players") or []
        if isinstance(row, Mapping)
    ]
    limit = max(1, int(limit_per_category))

    category_rules = (
        (
            "BREAKOUT / CONFIRMATION",
            {"BREAKOUT_PROCESS", "OUTPUT_CONFIRMING_PROCESS"},
        ),
        (
            "PROCESS UP — RETURNS NOT YET ARRIVED",
            {"UNDERLYING_IMPROVING_NO_RETURN"},
        ),
        (
            "ROLE / MINUTES RISERS",
            {"ROLE_BREAKOUT", "MINUTES_BREAKOUT", "SET_PIECE_GAIN"},
        ),
        (
            "LINK-UP RISERS",
            {"LINKUP_BREAKOUT"},
        ),
        (
            "REGRESSION / SELL-RISK",
            {
                "REGRESSION_RISK",
                "ROLE_DECLINE",
                "MINUTES_DECLINE",
                "LINKUP_BROKEN",
            },
        ),
        (
            "NOISE / DO NOT CHASE",
            {"OUTPUT_WITHOUT_PROCESS"},
        ),
    )

    def compact(row: Mapping[str, Any]) -> dict[str, Any]:
        latest = dict(row.get("latest_match") or {})
        comparison = dict(row.get("universe_comparison") or {})
        return {
            "element_id": row.get("element_id"),
            "name": row.get("name"),
            "position": row.get("position"),
            "owned": bool(row.get("owned")),
            "primary_classification": row.get("primary_classification"),
            "classifications": list(row.get("classifications") or []),
            "materiality_score": row.get("materiality_score"),
            "latest_fpl_points": latest.get("fpl_points"),
            "latest_xgi": latest.get("xgi"),
            "xmins_delta": (row.get("xmins") or {}).get("delta"),
            "p_start_delta": (row.get("p_start") or {}).get("delta"),
            "universe_comparison_state": comparison.get("state"),
            "published_position_pool_rank": comparison.get(
                "published_position_pool_rank"
            ),
            "beats_hold_in_any_published_package": comparison.get(
                "beats_hold_in_any_published_package"
            ),
            "deep_detail": (
                bool(row.get("deep_detail_available"))
                or int(row.get("element_id") or -1) in executed_ids
            ),
            "automatic_transfer_recommendation": False,
        }

    categories: dict[str, list[dict[str, Any]]] = {}
    for label, accepted in category_rules:
        rows = [
            row
            for row in players
            if accepted.intersection(set(row.get("classifications") or []))
        ]
        rows.sort(
            key=lambda row: (
                float(row.get("materiality_score") or 0.0),
                bool(
                    (row.get("universe_comparison") or {}).get(
                        "beats_hold_in_any_published_package"
                    )
                ),
                -int(
                    (row.get("universe_comparison") or {}).get(
                        "published_position_pool_rank"
                    )
                    or 999
                ),
            ),
            reverse=True,
        )
        categories[label] = [compact(row) for row in rows[:limit]]

    comparison = dict(scan.get("universe_comparison") or {})
    scanned_count = int(scan.get("scanned_count") or 0)
    eligible_count = int(scan.get("eligible_count") or 0)
    search_authority = str(comparison.get("search_authority") or "").upper()
    if not scan:
        state = "UNAVAILABLE"
        reason = "post-match full-universe scan unavailable"
    elif scanned_count <= 0:
        state = "DEGRADED"
        reason = "eligible universe scan returned zero supportable players"
    elif (
        (eligible_count > 0 and scanned_count < eligible_count)
        or search_authority == "PARTIAL"
    ):
        state = "DEGRADED"
        reason = (
            "post-match universe coverage/search authority is partial; "
            f"scanned={scanned_count}/{eligible_count or 'UNKNOWN'} "
            f"search_authority={search_authority or 'UNAVAILABLE'}"
        )
    else:
        state = "COMPLETE"
        reason = None

    return {
        "state": state,
        "degradation_reason": reason,
        "title": "UNIVERSE MOVERS",
        "scope": scan.get("scope"),
        "scanned_count": scan.get("scanned_count"),
        "eligible_count": scan.get("eligible_count"),
        "material_count": scan.get("material_count"),
        "summary": (
            "NO MATERIAL MOVERS"
            if scan and int(scan.get("material_count") or 0) == 0
            else None
        ),
        "search_authority": comparison.get("search_authority"),
        "missing_scope": (
            comparison.get("missing_scope")
            or (
                None
                if state == "COMPLETE"
                else "PARTIAL_OR_UNAVAILABLE_UNIVERSE_EVIDENCE"
            )
        ),
        "deep_requested_count": deep.get("deep_requested_count"),
        "deep_executed_count": deep.get("deep_executed_count"),
        "deep_deferred_count": deep.get("deep_deferred_count"),
        "deep_execution_scope": deep.get("deep_execution_scope"),
        "categories": categories,
        "deep_detail_element_ids": list(
            scan.get("deep_analysis_element_ids") or []
        ),
        "full_universe_comparison": scan.get("universe_comparison"),
        "governance": {
            "scorer_assister_only_scouting_prohibited": True,
            "non_scorers_can_surface": True,
            "one_match_haul_never_creates_act": True,
            "deep_detail_materiality_gated": True,
            "full_universe_comparison_required_before_transfer": True,
            "operational_action_enum_unchanged": "WAIT_PREPARE_ACT",
        },
    }


def materialize_all15(
    *,
    owned15: Sequence[Mapping[str, Any]],
    model_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Keep all owned identities even when model fields are unavailable."""
    model_map = {
        int(row.get("element_id")): dict(row)
        for row in (model_rows or ())
        if isinstance(row, Mapping) and row.get("element_id") is not None
    }
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for owned in owned15:
        if not isinstance(owned, Mapping):
            continue
        element = owned.get("element_id", owned.get("element"))
        if element is None:
            continue
        element = int(element)
        if element in seen:
            continue
        seen.add(element)
        model = model_map.get(element) or {}
        rows.append(
            {
                "element_id": element,
                "player": owned.get("name") or model.get("name"),
                "position": owned.get("position") or model.get("position"),
                "team_id": owned.get("team_id"),
                "current_price": owned.get("current_price", owned.get("now_cost")),
                "purchase_price": owned.get("purchase_price"),
                "selling_price": owned.get("selling_price", owned.get("sell_value")),
                "opponent": model.get("opponent", "UNAVAILABLE"),
                "recommended_or_locked_role": model.get(
                    "recommended_or_locked_role", "UNAVAILABLE"
                ),
                "p_available": model.get("p_available", "UNAVAILABLE"),
                "p_start": model.get("p_start", "UNAVAILABLE"),
                "p_cameo": model.get("p_cameo", "UNAVAILABLE"),
                "p_dnp": model.get("p_dnp", "UNAVAILABLE"),
                "xmins": model.get("xmins", "UNAVAILABLE"),
                "tactical_role": model.get("tactical_role", "UNAVAILABLE"),
                "set_piece_penalty_role": model.get(
                    "set_piece_penalty_role", "UNAVAILABLE"
                ),
                "matchup": model.get("matchup", "UNAVAILABLE"),
                "gw_plus_1": model.get("gw_plus_1", "UNAVAILABLE"),
                "three_gw": model.get("three_gw", "UNAVAILABLE"),
                "five_gw": model.get("five_gw", "UNAVAILABLE"),
                "uncertainty_floor_upside": model.get(
                    "uncertainty_floor_upside", "UNAVAILABLE"
                ),
                "action": model.get("action", "HOLD"),
            }
        )
    complete = len(rows) == 15
    return {
        "state": "COMPLETE" if complete else ("DEGRADED" if rows else "UNAVAILABLE"),
        "available_count": len(rows),
        "expected_count": 15,
        "rows": rows,
        "identity_complete": complete,
        "model_complete": complete
        and all(row["p_start"] != "UNAVAILABLE" and row["xmins"] != "UNAVAILABLE" for row in rows),
        "degradation_reason": None if complete else "owned identity evidence is not exact15",
    }


def build_signal_delta(
    *,
    baseline_0430: Mapping[str, Any] | None,
    current_1230: Mapping[str, Any] | None,
) -> dict[str, Any]:
    current = dict(current_1230 or {})
    if not baseline_0430:
        return {
            "status": "BASELINE UNAVAILABLE",
            "rows": [
                {
                    "signal": field,
                    "04:30_or_baseline_state": "BASELINE UNAVAILABLE",
                    "12:30_state": current.get(field, "UNAVAILABLE"),
                    "change": "UNAVAILABLE",
                    "evidence": current.get(f"{field}_evidence"),
                    "decision_effect": current.get(f"{field}_decision_effect"),
                }
                for field in SIGNAL_DELTA_FIELDS
            ],
        }
    baseline = dict(baseline_0430)
    rows = []
    for field in SIGNAL_DELTA_FIELDS:
        before = baseline.get(field, "UNAVAILABLE")
        after = current.get(field, "UNAVAILABLE")
        rows.append(
            {
                "signal": field,
                "04:30_or_baseline_state": before,
                "12:30_state": after,
                "change": "NO CHANGE" if before == after else "CHANGED",
                "evidence": current.get(f"{field}_evidence"),
                "decision_effect": current.get(f"{field}_decision_effect"),
            }
        )
    return {"status": "AVAILABLE", "rows": rows}


_DEEP_LEGACY_LABEL_ALIASES: dict[str, tuple[str, ...]] = {
    "S01": ("Decision/status",),
    "S02": ("OUR15",),
    "S03": ("DECISION DELTA",),
    "S04": ("Changes",),
    "S05": ("Fixtures/rest/conditions",),
    "S06": ("Formation/XI/bench",),
    "S07": ("XI battle",),
    "S08": ("C/VC",),
    "S09": ("Chip",),
    "S10": ("Actionable Price Radar",),
    "S11": ("Watchlist20 exact20",),
    "S12": ("RISE20 exact20 where required",),
    "S13": ("FALL20 exact20 where required",),
    "S14": ("Package optimizer/frontier including HOLD baseline",),
    "S15": ("Evidence quality",),
    "S15B": ("ICON+ mini-league",),
    "S16": ("ALL15 exact15 next-GW tactical/probability table",),
    "S17": ("Source health/freshness/lineage",),
    "S18": ("WAIT/PREPARE/ACT + trigger/reversal",),
    "S19": ("Final judgement",),
}


def _payload_for_section(
    payloads: Mapping[str, Mapping[str, Any]],
    *,
    section_id: str,
    label: str,
) -> Mapping[str, Any] | None:
    direct = payloads.get(section_id) or payloads.get(label)
    if direct is not None:
        return direct
    for alias in _DEEP_LEGACY_LABEL_ALIASES.get(section_id, ()):
        if alias in payloads:
            return payloads[alias]
    return None


def _locked_default(
    section_id: str,
    label: str,
    locked_state: Mapping[str, Any],
) -> dict[str, Any] | None:
    sid = str(section_id or "").upper()
    if sid == "S06":
        raw_bench = locked_state.get("bench")
        if isinstance(raw_bench, Mapping):
            bench = dict(raw_bench)
        else:
            bench_rows = list(raw_bench or [])
            bench = {
                "gk": bench_rows[0] if bench_rows else None,
                "order": bench_rows[1:4],
            }
        return {
            "state": "COMPLETE",
            "content": {
                "status": "GW LOCKED — NO EXECUTABLE XI CHANGE",
                "formation": locked_state.get("formation"),
                "starting_xi": locked_state.get("xi"),
                "xi": locked_state.get("xi"),
                "bench": bench,
                "lineup_score": {"state": "LOCKED"},
                "formation_comparison": [],
            },
        }
    if sid == "S07":
        return {
            "state": "COMPLETE",
            "content": {
                "status": "GW LOCKED — XI battle retained as factual locked state",
                "battles": [],
                "empty_is_truthful": True,
            },
        }
    if sid == "S08":
        return {
            "state": "COMPLETE",
            "content": {
                "status": "LOCKED",
                "captain": locked_state.get("captain"),
                "vice_captain": locked_state.get("vice_captain"),
            },
        }
    if sid == "S09":
        return {
            "state": "COMPLETE",
            "content": {"status": "LOCKED", "chip": locked_state.get("chip")},
        }
    return None


def _materialize_canonical_report(
    *,
    canonical_text: str,
    structural_mode: str,
    reported_mode: str,
    section_payloads: Mapping[str, Mapping[str, Any]] | None,
    checkpoint_time: str | None = None,
    signal_delta: Mapping[str, Any] | None = None,
    current_gw_locked: bool = False,
    locked_state: Mapping[str, Any] | None = None,
    universe_movers: Mapping[str, Any] | None = None,
    universe_movers_target_label: str | None = None,
    s16b_due: bool | None = None,
) -> dict[str, Any]:
    """One existing V12 structural materializer used by DEEP and post-match."""
    contract = canonical_mode_contract(
        canonical_text,
        structural_mode,
        s16b_due=s16b_due,
    )
    payloads = dict(section_payloads or {})
    sections: list[dict[str, Any]] = []
    locked = dict(locked_state or {})
    mover_attachments = 0

    for section_id, label in zip(
        contract["expected_section_ids"],
        contract["expected_visible_order"],
    ):
        raw = _payload_for_section(
            payloads,
            section_id=section_id,
            label=label,
        )
        if raw is None and current_gw_locked:
            raw = _locked_default(section_id, label, locked)

        raw_map = dict(raw or {})
        candidate_map = raw_map.get("resolution_candidates")
        if isinstance(candidate_map, Mapping):
            row = resolve_section(
                section_id=section_id,
                label=label,
                current=(
                    candidate_map.get("CURRENT")
                    if isinstance(candidate_map.get("CURRENT"), Mapping)
                    else None
                ),
                current_bound=(
                    candidate_map.get("CURRENT-BOUND")
                    if isinstance(candidate_map.get("CURRENT-BOUND"), Mapping)
                    else None
                ),
                prior=(
                    candidate_map.get("PRIOR")
                    if isinstance(candidate_map.get("PRIOR"), Mapping)
                    else None
                ),
                prior_source_occurrence=(
                    str(candidate_map.get("prior_source_occurrence") or "").strip()
                    or None
                ),
                unavailable_reason=(
                    str(raw_map.get("degradation_reason") or "").strip()
                    or "current authoritative evidence unavailable"
                ),
            )
        else:
            raw_state = str(raw_map.get("state") or "").upper()
            raw_content = raw_map.get("content")
            presentation_status = (
                str(
                    (raw_content or {}).get("presentation_status")
                    if isinstance(raw_content, Mapping)
                    else ""
                )
                .strip()
                .upper()
            )
            current_candidate = None
            current_bound_candidate = None
            prior_candidate = None
            prior_source_occurrence = None
            if raw_map and raw_state != "UNAVAILABLE":
                if presentation_status == "PRIOR":
                    prior_candidate = raw_map
                    prior_source_occurrence = str(
                        (raw_content or {}).get("prior_source_occurrence")
                        if isinstance(raw_content, Mapping)
                        else ""
                    ).strip() or None
                elif presentation_status == "CURRENT-BOUND":
                    current_bound_candidate = raw_map
                else:
                    current_candidate = raw_map
            row = resolve_section(
                section_id=section_id,
                label=label,
                current=current_candidate,
                current_bound=current_bound_candidate,
                prior=prior_candidate,
                prior_source_occurrence=prior_source_occurrence,
                unavailable_reason=(
                    str(raw_map.get("degradation_reason") or "").strip()
                    or "current authoritative evidence unavailable"
                ),
            )

        state = _status(row.get("state"), label=section_id)
        if state != "COMPLETE" and not str(
            row.get("degradation_reason") or ""
        ).strip():
            raise ReportOrchestrationError(
                f"{section_id} degraded/unavailable section requires reason"
            )
        content = row.get("content")
        if state == "COMPLETE" and (
            content is None
            or content == ""
            or content == {}
            or content == []
        ):
            state = "DEGRADED"
            row["degradation_reason"] = (
                "section declared COMPLETE but no human-facing content was materialized"
            )
        if section_id == "S03" and str(checkpoint_time or "") == "12:30":
            content = dict(content or {})
            content["signal_delta_since_0430"] = dict(
                signal_delta
                or {
                    "status": "BASELINE UNAVAILABLE",
                    "rows": [],
                }
            )
        if (
            universe_movers is not None
            and universe_movers_target_label
            and (
                str(section_id).upper()
                == str(universe_movers_target_label).upper()
                or str(label).upper()
                == str(universe_movers_target_label).upper()
            )
        ):
            content = dict(content or {})
            if "universe_movers" in content:
                raise ReportOrchestrationError(
                    "UNIVERSE MOVERS may be attached only once"
                )
            content["universe_movers"] = dict(universe_movers)
            mover_attachments += 1
        if "PACKAGE OPTIMIZER" in str(label or "").upper() and state == "COMPLETE":
            package_failures = _package_frontier_contract_failures(
                content if isinstance(content, Mapping) else None
            )
            if package_failures:
                state = "DEGRADED"
                row["degradation_reason"] = (
                    "full-universe package/frontier visible contract incomplete: "
                    + ",".join(package_failures)
                )
        sections.append(
            {
                "section_id": section_id,
                "label": label,
                "state": state,
                "available_count": row.get("available_count"),
                "expected_count": row.get("expected_count"),
                "degradation_reason": row.get("degradation_reason"),
                "source_state": row.get("source_state"),
                "content": content,
            }
        )

    resolution_failures = validate_resolved_sections(sections)
    if resolution_failures:
        raise ReportOrchestrationError(
            "section source resolution contract failed: "
            + ",".join(resolution_failures)
        )

    if universe_movers is not None and mover_attachments != 1:
        raise ReportOrchestrationError(
            "natural post-match report must attach UNIVERSE MOVERS exactly once"
        )
    return {
        "report_mode": reported_mode,
        "structural_mode": structural_mode,
        "sections": sections,
        "rendered_section_ids": [row["section_id"] for row in sections],
        "rendered_visible_order": [row["label"] for row in sections],
        "exact_canonical_order": [row["section_id"] for row in sections]
        == contract["expected_section_ids"],
        "numbered_headings": 19 if structural_mode == "DEEP" else len(sections),
        "rendered_blocks_including_suffix_sections": len(sections), 
        "rendered_blocks_including_15B": len(sections),
        "universe_movers_attachment_count": mover_attachments,
        "universe_movers_visible": mover_attachments == 1,
    }


def build_visible_mathematical_decision_stack(
    decision_proof: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Expose existing V12 decision evidence without recomputing any model."""
    proof = dict(decision_proof or {})
    probability = dict(proof.get("probability_state") or {})
    unconditional = dict(probability.get("unconditional") or {})
    xmins = dict(proof.get("xmins_distribution") or {})
    horizons = dict(proof.get("horizons") or {})
    robustness = dict(proof.get("robustness") or {})
    posterior_predictive = dict(proof.get("posterior_predictive") or {})
    event_probabilities = dict(
        posterior_predictive.get("event_probabilities")
        or proof.get("event_probabilities")
        or proof.get("posterior_predictive_event_probabilities")
        or {}
    )
    point_distribution = dict(
        posterior_predictive.get("point_distribution") or {}
    )
    mc = dict(proof.get("monte_carlo") or {})
    missing: list[str] = []
    if not proof.get("bayesian_shrinkage_lineage"):
        missing.append("bayesian_shrinkage_lineage")
    if not unconditional:
        missing.append("availability_mixture")
    if not xmins:
        missing.append("xmins_distribution")
    if not event_probabilities:
        missing.append("event_probabilities")
    if not horizons:
        missing.append("horizons")
    if not robustness:
        missing.append("robustness")
    if not mc:
        missing.append("monte_carlo")

    def event_value(*keys: str) -> Any:
        for key in keys:
            if key in event_probabilities:
                return event_probabilities.get(key)
        return "UNAVAILABLE"

    def distribution_value(*keys: str) -> Any:
        for key in keys:
            if key in point_distribution:
                return point_distribution.get(key)
        return "UNAVAILABLE"

    return {
        "state": "COMPLETE" if not missing else ("PARTIAL" if proof else "UNAVAILABLE"),
        "missing_scope": missing,
        "bayesian_prior_posterior_shrinkage": (
            proof.get("bayesian_shrinkage_lineage") or "UNAVAILABLE"
        ),
        "availability_mixture": {
            "p_available": unconditional.get("p_available", "UNAVAILABLE"),
            "p_start": unconditional.get("p_start", "UNAVAILABLE"),
            "p_bench": unconditional.get("p_bench", "UNAVAILABLE"),
            "p_cameo": unconditional.get("p_cameo", "UNAVAILABLE"),
            "p_late_cameo": unconditional.get("p_late_cameo", "UNAVAILABLE"),
            "p_dnp": unconditional.get("p_dnp", "UNAVAILABLE"),
        },
        "xmins_distribution": xmins or "UNAVAILABLE",
        "event_probabilities": {
            "p_goal": event_value(
                "p_goal_return", "p_goal", "goal"
            ),
            "p_assist": event_value(
                "p_assist_return", "p_assist", "assist"
            ),
            "p_return": event_value(
                "p_attacking_return", "p_return", "return"
            ),
            "p_two_plus_returns": event_value(
                "p_total_ga_ge_2",
                "p_multiple_attacking_returns",
                "p_two_plus_returns",
                "p_2_plus_returns",
                "two_plus_returns",
            ),
            "p_haul": distribution_value(
                "p_haul_10_plus", "p_haul", "haul"
            ),
            "p_blank": distribution_value(
                "p_fpl_blank", "p_blank", "blank"
            ),
            "p_no_attacking_return": event_value(
                "p_no_attacking_return"
            ),
        },
        "point_distribution": point_distribution or "UNAVAILABLE",
        "posterior_predictive_source": (
            posterior_predictive.get("source_contract")
            or "UNAVAILABLE"
        ),
        "horizons": horizons or "UNAVAILABLE",
        "p_outperform": robustness.get(
            "p_outperform",
            proof.get("p_outperform", "UNAVAILABLE"),
        ),
        "expected_regret": robustness.get(
            "expected_regret",
            proof.get("expected_regret", "UNAVAILABLE"),
        ),
        "tail_risk": {
            "conditional_floor": robustness.get(
                "conditional_floor", "UNAVAILABLE"
            ),
            "upper_tail": robustness.get("upper_tail", "UNAVAILABLE"),
        },
        "information_value_of_waiting": proof.get(
            "information_value_of_waiting", "UNAVAILABLE"
        ),
        "covariance_correlation": (
            proof.get("covariance_correlation")
            or proof.get("correlation")
            or "UNAVAILABLE"
        ),
        "monte_carlo": mc or {
            "execution_state": "UNAVAILABLE",
            "reason": "NO OCCURRENCE-BOUND MONTE CARLO EVIDENCE",
        },
    }


def _render_match_scout_lines(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    lines = ["### POST-MATCH MATCH-BY-MATCH SCOUT"]
    labels = (
        ("result", "RESULT"),
        ("formation_system", "FORMATION/SYSTEM"),
        ("coach_pattern", "COACH PATTERN"),
        ("player_roles", "PLAYER ROLES"),
        ("minutes_substitution_pattern", "MINUTES/SUBS"),
        ("xg_xa_xgi_shots_chances", "xG/xA/xGI/SHOTS/CHANCES"),
        ("set_pieces_penalties", "SET PIECES/PENALTIES"),
        ("defcon", "DEFCON"),
        ("opponent_channels", "OPPONENT CHANNELS"),
        ("sustainable_vs_noisy", "SUSTAINABLE VS NOISE"),
        ("implication_for_our15", "OUR15 IMPLICATION"),
        ("implication_for_next_opponent", "NEXT OPPONENT IMPLICATION"),
        (
            "posterior_calibration_implication",
            "POSTERIOR CALIBRATION IMPLICATION",
        ),
    )
    for row in rows:
        fixture_id = row.get("fixture_id", "UNAVAILABLE")
        lines.append(f"#### FIXTURE ID: {fixture_id}")
        for field, label in labels:
            value = row.get(field, "UNAVAILABLE")
            lines.append(f"{label}: {value}")
    return lines


def _render_math_stack_lines(stack: Mapping[str, Any]) -> list[str]:
    payload = dict(stack or {})

    def mapping_or_empty(value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, Mapping) else {}

    availability = mapping_or_empty(payload.get("availability_mixture"))
    events = mapping_or_empty(payload.get("event_probabilities"))
    point_distribution = mapping_or_empty(payload.get("point_distribution"))
    mc = mapping_or_empty(payload.get("monte_carlo"))
    lines = [
        "### MATHEMATICAL DECISION STACK",
        "BAYESIAN PRIOR -> POSTERIOR / SHRINKAGE: "
        f"{payload.get('bayesian_prior_posterior_shrinkage', 'UNAVAILABLE')}",
        "AVAILABILITY MIXTURE: "
        f"P(AVAILABLE)={availability.get('p_available', 'UNAVAILABLE')} | "
        f"P(START)={availability.get('p_start', 'UNAVAILABLE')} | "
        f"P(BENCH)={availability.get('p_bench', 'UNAVAILABLE')} | "
        f"P(CAMEO)={availability.get('p_cameo', 'UNAVAILABLE')} | "
        f"P(LATE CAMEO)={availability.get('p_late_cameo', 'UNAVAILABLE')} | "
        f"P(DNP)={availability.get('p_dnp', 'UNAVAILABLE')}",
        f"XMINS DISTRIBUTION: {payload.get('xmins_distribution', 'UNAVAILABLE')}",
        "EVENT PROBABILITIES: "
        f"P(GOAL)={events.get('p_goal', 'UNAVAILABLE')} | "
        f"P(ASSIST)={events.get('p_assist', 'UNAVAILABLE')} | "
        f"P(RETURN)={events.get('p_return', 'UNAVAILABLE')} | "
        f"P(2+ RETURNS)={events.get('p_two_plus_returns', 'UNAVAILABLE')} | "
        f"P(HAUL)={events.get('p_haul', 'UNAVAILABLE')} | "
        f"P(BLANK)={events.get('p_blank', 'UNAVAILABLE')} | "
        f"P(NO ATTACK RETURN)={events.get('p_no_attacking_return', 'UNAVAILABLE')}",
        "P1.3B POINT DISTRIBUTION: "
        f"source={payload.get('posterior_predictive_source', 'UNAVAILABLE')} | "
        f"E[xPts]={point_distribution.get('expected_points', 'UNAVAILABLE')} | "
        f"variance={point_distribution.get('variance', 'UNAVAILABLE')} | "
        f"std={point_distribution.get('std', 'UNAVAILABLE')} | "
        f"quantiles={point_distribution.get('quantiles', 'UNAVAILABLE')} | "
        f"tails={point_distribution.get('tails', 'UNAVAILABLE')}",
        f"HORIZONS 1GW / 3GW / 5GW: {payload.get('horizons', 'UNAVAILABLE')}",
        f"P(OUTPERFORM HOLD/COMPARATOR): {payload.get('p_outperform', 'UNAVAILABLE')}",
        f"EXPECTED REGRET: {payload.get('expected_regret', 'UNAVAILABLE')}",
        f"TAIL / FLOOR / CEILING: {payload.get('tail_risk', 'UNAVAILABLE')}",
        "INFORMATION VALUE OF WAITING: "
        f"{payload.get('information_value_of_waiting', 'UNAVAILABLE')}",
        f"COVARIANCE / CORRELATION: {payload.get('covariance_correlation', 'UNAVAILABLE')}",
        "MONTE CARLO: "
        f"state={mc.get('execution_state', 'UNAVAILABLE')} | "
        f"N={mc.get('actual_paths', 'UNAVAILABLE')} | "
        f"correlated={mc.get('correlated', 'UNAVAILABLE')} | "
        f"reason={mc.get('reason', mc.get('degradation_reason', 'UNAVAILABLE'))} | "
        f"convergence={mc.get('convergence_evidence', 'UNAVAILABLE')}",
    ]
    return lines


def _package_frontier_contract_failures(content: Mapping[str, Any] | None) -> list[str]:
    """Validate visible package/full-universe evidence without creating new ranking math."""
    payload = dict(content or {})
    proof = payload.get("package_search_proof") or payload.get("search_proof")
    challengers = list(
        payload.get("package_universe_challengers")
        or payload.get("universe_challengers")
        or ()
    )
    routes = list(
        payload.get("package_routes")
        or payload.get("routes")
        or payload.get("frontier")
        or ()
    )
    failures: list[str] = []
    if not isinstance(proof, Mapping):
        failures.append("SEARCH_PROOF_MISSING")
    else:
        try:
            owned_expected = int(proof.get("owned_expected"))
            owned_evaluated = int(proof.get("owned_evaluated"))
            universe_expected = int(proof.get("eligible_universe_expected"))
            universe_evaluated = int(proof.get("eligible_universe_evaluated"))
            outgoing = int(proof.get("outgoing_candidate_count"))
            legal_routes = int(proof.get("legal_route_count"))
        except (TypeError, ValueError):
            failures.append("SEARCH_PROOF_NUMERIC_INVALID")
        else:
            if owned_expected != 15 or owned_evaluated != 15:
                failures.append(f"OUR15={owned_evaluated}/{owned_expected}")
            if universe_expected <= 0 or universe_evaluated != universe_expected:
                failures.append(f"UNIVERSE={universe_evaluated}/{universe_expected}")
            if outgoing != 15:
                failures.append(f"OUTGOING={outgoing}/15")
            if legal_routes <= 0:
                failures.append("LEGAL_ROUTES=0")
        if proof.get("hold_included") is not True:
            failures.append("HOLD_MISSING")
        if proof.get("lossy_pruning") is not False:
            failures.append("LOSSY_PRUNING")
        if str(proof.get("search_authority") or "").upper() != "FULL":
            failures.append("SEARCH_AUTHORITY_NOT_FULL")
    if not challengers:
        failures.append("SCAN_DERIVED_CHALLENGERS_MISSING")
    if not routes:
        failures.append("PACKAGE_ROUTES_MISSING")
    elif not any(
        str(row.get("route") or "").upper() == "HOLD"
        for row in routes
        if isinstance(row, Mapping)
    ):
        failures.append("HOLD_ROUTE_MISSING")
    return failures


def _render_package_frontier_lines(
    content: Mapping[str, Any] | None,
    *,
    section_state: str,
) -> list[str]:
    """Render one bounded S14 decision surface from canonical route evidence."""
    payload = dict(content or {})
    proof = dict(payload.get("package_search_proof") or payload.get("search_proof") or {})
    routes = [
        dict(row) for row in (
            payload.get("package_routes")
            or payload.get("routes")
            or payload.get("frontier")
            or ()
        ) if isinstance(row, Mapping)
    ]
    mc = dict(payload.get("monte_carlo") or {})
    selected_id = str(payload.get("selected_route_id") or "HOLD")
    hold = next((row for row in routes if str(row.get("route") or "").upper() == "HOLD"), {})
    selected = next((row for row in routes if str(row.get("route") or "") == selected_id), {})
    best = selected if selected_id.upper() != "HOLD" and selected else next(
        (row for row in routes if str(row.get("route") or "").upper() != "HOLD"),
        {},
    )

    lines = ["### SEARCH INTEGRITY"]
    if proof:
        lines.extend([
            f"OUR15 denominator: {proof.get('owned_evaluated', 'UNAVAILABLE')}/{proof.get('owned_expected', 'UNAVAILABLE')}",
            f"Universe denominator: {proof.get('eligible_universe_evaluated', 'UNAVAILABLE')}/{proof.get('eligible_universe_expected', 'UNAVAILABLE')}",
            f"Outgoing denominator: {proof.get('outgoing_candidate_count', 'UNAVAILABLE')}/15",
            f"Legal routes: {proof.get('legal_route_count', 'UNAVAILABLE')}",
            f"HOLD included: {proof.get('hold_included', 'UNAVAILABLE')}",
            f"Lossy pruning: {proof.get('lossy_pruning', 'UNAVAILABLE')}",
            f"Search authority: {proof.get('search_authority', 'UNAVAILABLE')}",
        ])
    else:
        lines.append(f"Search proof: {section_state}; current full-universe proof unavailable.")

    lines.append("### CANONICAL MONTE CARLO")
    convergence = dict(mc.get("convergence_evidence") or {})
    lines.extend([
        f"Actual paths: {mc.get('actual_paths', 'UNAVAILABLE')}",
        f"Correlated/common-random status: {mc.get('common_random_numbers', mc.get('correlated_common_random_status', 'UNAVAILABLE'))}",
        f"Convergence: {convergence.get('status', mc.get('convergence', 'UNAVAILABLE'))}",
        f"Mean delta: {mc.get('mean_delta', mc.get('mean', 'UNAVAILABLE'))}",
        f"P>HOLD: {mc.get('p_beats_hold', mc.get('p_gt_hold', 'UNAVAILABLE'))}",
        f"Q10: {mc.get('Q10', 'UNAVAILABLE')} | median: {mc.get('median', 'UNAVAILABLE')} | Q90: {mc.get('Q90', 'UNAVAILABLE')}",
        f"Expected regret: {mc.get('expected_regret', 'UNAVAILABLE')}",
    ])

    verdict = selected_id if selected_id else "HOLD"
    lines.append("### VERDICT")
    lines.append(verdict)

    lines.append("### BEST CHALLENGER")
    if best:
        moves = dict(best.get("moves") or {}) if isinstance(best.get("moves"), Mapping) else {}
        outs = [
            str(x.get("name") or x.get("player") or x.get("element") or "UNAVAILABLE")
            for x in moves.get("out") or [] if isinstance(x, Mapping)
        ]
        ins = [
            str(x.get("name") or x.get("player") or x.get("element") or "UNAVAILABLE")
            for x in moves.get("in") or [] if isinstance(x, Mapping)
        ]
        route_text = (
            f"{', '.join(outs) or 'HOLD'} → {', '.join(ins) or 'HOLD'}"
            if moves else str(best.get("route") or "UNAVAILABLE")
        )
        lines.extend([
            f"Route: {route_text}",
            f"1GW: {best.get('gw1_net', best.get('one_gw', 'UNAVAILABLE'))}",
            f"3GW: {best.get('three_gw', 'UNAVAILABLE')}",
            f"5GW: {best.get('five_gw', 'UNAVAILABLE')}",
            f"P>HOLD: {best.get('p_beats_hold', 'UNAVAILABLE')}",
            f"Median: {best.get('median', 'UNAVAILABLE')} | Q90: {best.get('Q90', 'UNAVAILABLE')}",
            f"Regret: {best.get('expected_regret', 'UNAVAILABLE')}",
            f"Robustness: {best.get('robustness', 'UNAVAILABLE')}",
        ])
    else:
        lines.append("No non-HOLD challenger is supportable.")

    economics = dict(payload.get("execution_economics_authority") or {})
    route_econ = best if best else hold
    transfer_cost = dict(route_econ.get("transfer_cost") or {}) if isinstance(route_econ.get("transfer_cost"), Mapping) else {}
    lines.append("### EXECUTION ECONOMICS")
    lines.extend([
        f"FT: {transfer_cost.get('free_transfers', payload.get('free_transfers', 'UNAVAILABLE'))}",
        f"Hit: {transfer_cost.get('hit_cost', transfer_cost.get('points_cost', 'UNAVAILABLE'))}",
        f"Bank: {route_econ.get('bank_before', economics.get('bank', 'UNAVAILABLE'))}",
        f"Sell-value availability: {economics.get('sell_value_status', payload.get('sell_value_status', 'UNAVAILABLE'))}",
        f"Affordability: {route_econ.get('affordability', 'UNAVAILABLE')}",
        f"Executability: {route_econ.get('executable', 'UNAVAILABLE')}",
    ])
    lines.append("### ACTIONABILITY CONCLUSION")
    lines.append(str(route_econ.get("action_verdict") or payload.get("operational_action") or verdict))
    return lines


def materialize_deep_report(
    *,
    canonical_text: str,
    section_payloads: Mapping[str, Mapping[str, Any]] | None,
    checkpoint_time: str | None = None,
    signal_delta: Mapping[str, Any] | None = None,
    current_gw_locked: bool = False,
    locked_state: Mapping[str, Any] | None = None,
    post_all_match_scout: Sequence[Mapping[str, Any]] | None = None,
    mathematical_decision_stack: Mapping[str, Any] | None = None,
    s16b_due: bool | None = None,
) -> dict[str, Any]:
    """Materialize the 22-section DEEP base plus conditional S16B when due."""
    due = (
        bool(s16b_due)
        if s16b_due is not None
        else "S16B" in dict(section_payloads or {})
    )
    report = _materialize_canonical_report(
        canonical_text=canonical_text,
        structural_mode="DEEP",
        reported_mode="DEEP",
        section_payloads=section_payloads,
        checkpoint_time=checkpoint_time,
        signal_delta=signal_delta,
        current_gw_locked=current_gw_locked,
        locked_state=locked_state,
        s16b_due=due,
    )
    report["s16b_due"] = due
    scout = [
        dict(row)
        for row in (post_all_match_scout or ())
        if isinstance(row, Mapping)
    ]
    if scout:
        target = next(
            (
                row
                for row in report["sections"]
                if str(row.get("section_id") or "").strip().upper() == "S04"
            ),
            None,
        )
        if target is None:
            raise ReportOrchestrationError(
                "DEEP Changes surface required for post-match scout carryover"
            )
        content = dict(target.get("content") or {})
        content["post_match_match_by_match_scout"] = scout
        target["content"] = content
        report["post_all_match_context"] = True
        report["completed_fixture_ids"] = [
            str(row.get("fixture_id")) for row in scout
        ]
    if mathematical_decision_stack:
        target = next(
            (
                row
                for row in report["sections"]
                if str(row.get("section_id") or "").strip().upper() == "S14"
            ),
            None,
        )
        if target is None:
            raise ReportOrchestrationError(
                "DEEP package surface required for mathematical decision stack"
            )
        content = dict(target.get("content") or {})
        content["mathematical_decision_stack"] = dict(
            mathematical_decision_stack
        )
        target["content"] = content
        report["serious_decision_required"] = True
    return report


def materialize_deadline_final_report(
    *,
    canonical_text: str,
    report_mode: str,
    section_payloads: Mapping[str, Mapping[str, Any]] | None,
    deadline_presentation: Mapping[str, Any],
    s16b_due: bool | None = None,
) -> dict[str, Any]:
    """Materialize Deadline/Final as a presentation overlay on canonical DEEP truth."""
    mode = str(report_mode or "").strip().upper()
    if mode not in {"DEADLINE", "FINAL"}:
        raise ReportOrchestrationError(
            f"deadline/final materializer requires DEADLINE or FINAL, got {mode or '<empty>'}"
        )
    due = (
        bool(s16b_due)
        if s16b_due is not None
        else "S16B" in dict(section_payloads or {})
    )
    report = _materialize_canonical_report(
        canonical_text=canonical_text,
        structural_mode=mode,
        reported_mode=mode,
        section_payloads=section_payloads,
        s16b_due=due,
    )
    report["s16b_due"] = due
    report["deadline_presentation"] = dict(deadline_presentation or {})
    return report


def _post_match_structural_route(
    report_mode: str,
    *,
    post_match_context: bool,
) -> tuple[str, str | None]:
    mode = str(report_mode or "").strip().upper()
    if mode == "POST_ALL_MATCH":
        return "POST_ALL_MATCH", "GW COMPLETED MATCH-BY-MATCH SCOUT"
    if mode == "POST_MATCH":
        return "MATCH", "RELEVANT LEAGUE-WIDE SIGNALS"
    if mode == "MATCH" and post_match_context:
        return "MATCH", "RELEVANT LEAGUE-WIDE SIGNALS"
    if mode in {
        "OVERLAP",
        "FULL+MATCH",
        "MATCH+FULL",
        "DEEP+MATCH",
        "MATCH+DEEP",
        "PRICE+MATCH",
        "MATCH+PRICE",
        "DEADLINE+MATCH",
        "MATCH+DEADLINE",
    }:
        return "DEEP", "S04"
    return mode, None


def materialize_natural_post_match_report(
    *,
    canonical_text: str,
    report_mode: str,
    projections_payload: Mapping[str, Any] | None,
    section_payloads: Mapping[str, Mapping[str, Any]] | None,
    post_match_context: bool = True,
    checkpoint_time: str | None = None,
    signal_delta: Mapping[str, Any] | None = None,
    current_gw_locked: bool = False,
    locked_state: Mapping[str, Any] | None = None,
    match_consequence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Natural V12 post-match renderer binding projections -> movers -> report.

    No new top-level backbone is created. Universe Movers is nested exactly
    once in the existing MATCH, POST-ALL-MATCH or overlap surface.
    """
    mode = str(report_mode or "").strip().upper()
    structural_mode, target_label = _post_match_structural_route(
        mode,
        post_match_context=post_match_context,
    )
    if target_label is None:
        raise ReportOrchestrationError(
            f"UNIVERSE MOVERS not applicable for pure mode {mode or '<empty>'}"
        )
    projections = dict(projections_payload or {})
    scan = projections.get("post_match_universe_scan")
    deep = projections.get("post_match_deep_analysis")
    movers = build_post_match_universe_movers(
        scan if isinstance(scan, Mapping) else None,
        post_match_deep_analysis=(
            deep if isinstance(deep, Mapping) else None
        ),
    )
    report = _materialize_canonical_report(
        canonical_text=canonical_text,
        structural_mode=structural_mode,
        reported_mode=mode,
        section_payloads=section_payloads,
        checkpoint_time=checkpoint_time,
        signal_delta=signal_delta,
        current_gw_locked=current_gw_locked,
        locked_state=locked_state,
        universe_movers=movers,
        universe_movers_target_label=target_label,
    )
    report["post_match_universe_movers"] = movers
    report["post_match_source"] = "projections.post_match_universe_scan"
    report["post_match_deep_source"] = (
        "projections.post_match_deep_analysis"
    )

    overlap_modes = {
        "OVERLAP",
        "FULL+MATCH",
        "MATCH+FULL",
        "DEEP+MATCH",
        "MATCH+DEEP",
        "PRICE+MATCH",
        "MATCH+PRICE",
        "DEADLINE+MATCH",
        "MATCH+DEADLINE",
    }
    consequence = (
        dict(match_consequence)
        if isinstance(match_consequence, Mapping)
        else {}
    )
    if mode in overlap_modes:
        if not consequence or not str(
            consequence.get("status") or consequence.get("summary") or ""
        ).strip():
            raise ReportOrchestrationError(
                "overlap report requires explicit locked submitted-pick match consequence"
            )
        target = next(
            (
                row
                for row in report.get("sections") or []
                if str(row.get("section_id") or "").upper() == "S04"
            ),
            None,
        )
        if not isinstance(target, dict):
            raise ReportOrchestrationError(
                "overlap report requires DEEP S04 material-development surface"
            )
        target_content = dict(target.get("content") or {})
        if "match_consequence" in target_content:
            raise ReportOrchestrationError(
                "match consequence may be materialized only once"
            )
        target_content["match_consequence"] = consequence
        target["content"] = target_content

    update_proof = dict(projections.get("model_update_execution") or {})
    actual_update = bool(
        update_proof.get("executed") is True
        and update_proof.get("previous_value") is not None
        and update_proof.get("current_value") is not None
        and str(update_proof.get("evidence_time") or "").strip()
    )
    model_update_status = (
        {
            "status": "POSTERIOR UPDATED",
            "previous_value": update_proof.get("previous_value"),
            "current_value": update_proof.get("current_value"),
            "evidence_time": update_proof.get("evidence_time"),
        }
        if actual_update
        else {
            "status": "MODEL UPDATE PENDING",
            "reason": (
                "completed-match evidence is calibration input until the "
                "authoritative model is actually recomputed"
            ),
        }
    )
    target_for_update = next(
        (
            row
            for row in report.get("sections") or []
            if str(row.get("label") or "").upper() == str(target_label or "").upper()
            or str(row.get("section_id") or "").upper() == str(target_label or "").upper()
        ),
        None,
    )
    if isinstance(target_for_update, dict):
        target_content = dict(target_for_update.get("content") or {})
        target_content["model_update_status"] = model_update_status
        target_for_update["content"] = target_content

    report["lifecycle_contract"] = {
        "single_visible_report": True,
        "reported_mode": mode,
        "structural_mode": structural_mode,
        "post_match_incremental": mode != "POST_ALL_MATCH",
        "post_match_return_mode": (
            "POST_ALL_MATCH" if mode == "POST_ALL_MATCH" else "MATCH"
        ),
        "match_consequence_preserved": (
            True if mode in overlap_modes else None
        ),
        "model_update_status": model_update_status["status"],
    }
    return report


def materialize_match_report(
    *,
    canonical_text: str,
    live_payload: Mapping[str, Any],
    icon_live: Mapping[str, Any] | None = None,
    league_wide_signals: Sequence[Mapping[str, Any]] | None = None,
    cards_injury_defcon_role_events: Sequence[Mapping[str, Any]] | None = None,
    next_gw_learning: Sequence[Mapping[str, Any]] | None = None,
    next_critical_observation: str | None = None,
    next_critical_reason: str | None = None,
    next_reassess_at: str | None = None,
    source_freshness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Materialize the Canonical MATCH1..MATCH13 surface from locked live truth.

    The scoring authority is the submitted-pick live payload. Planning XI is
    never accepted as an input here. Missing submitted-pick coverage fails
    closed while optional league-wide/contextual scopes may degrade visibly.
    """
    live = dict(live_payload or {})
    players = [
        dict(row)
        for row in live.get("players") or []
        if isinstance(row, Mapping)
    ]
    player_ids = [
        int(row.get("element") or 0)
        for row in players
        if int(row.get("element") or 0) > 0
    ]
    if (
        str(live.get("submitted_picks_status") or "").upper() != "AVAILABLE"
        or len(players) != 15
        or len(set(player_ids)) != 15
    ):
        raise ReportOrchestrationError(
            "MATCH publication requires exact15 locked submitted picks"
        )

    lifecycle = dict(live.get("lifecycle") or {})
    checkpoint = dict(live.get("match_checkpoint") or {})
    bench = dict(live.get("bench_presentation") or {})
    score = dict(live.get("personalized_live_score") or {})
    captain = dict(live.get("captain_vice_consequence") or {})
    bonus = dict(live.get("bonus_bps") or {})
    generated_at = live.get("generated_at")

    xi_rows = [row for row in players if int(row.get("multiplier") or 0) > 0]
    bench_rows = [row for row in players if int(row.get("multiplier") or 0) == 0]
    if len(xi_rows) != 11 or len(bench_rows) != 4:
        raise ReportOrchestrationError(
            f"MATCH locked submitted picks require XI=11 and bench=4, got {len(xi_rows)}/{len(bench_rows)}"
        )

    personal_impact: list[dict[str, Any]] = []
    for row in players:
        minutes = int(row.get("minutes") or 0)
        raw = int(row.get("total_points") or 0)
        multiplier = int(row.get("multiplier") or 0)
        fixture_status = str(row.get("fixture_status") or "NOT_STARTED")
        state = "NO_MATERIAL_EVENT"
        if int(row.get("red_cards") or 0) > 0:
            state = "RED_CARD"
        elif int(row.get("goals_scored") or 0) > 0:
            state = "GOAL_RETURN"
        elif int(row.get("assists") or 0) > 0:
            state = "ASSIST_RETURN"
        elif multiplier == 0 and raw > 0:
            state = "BENCH_POINTS"
        elif fixture_status == "FT" and minutes == 0 and multiplier > 0:
            state = "DNP_AUTOSUB_PENDING"
        elif fixture_status == "LIVE" and minutes > 0 and minutes < 90:
            state = "LIVE_APPEARANCE"
        if state != "NO_MATERIAL_EVENT":
            personal_impact.append(
                {
                    "element_id": row.get("element"),
                    "player": row.get("name"),
                    "personal_state": state,
                    "fixture_status": fixture_status,
                    "minutes": minutes,
                    "raw_points": raw,
                    "multiplier": multiplier,
                    "effective_points": row.get("effective_points"),
                }
            )

    if not personal_impact:
        personal_impact.append(
            {
                "personal_state": "NO_MATERIAL_PERSONAL_EVENT",
                "summary": "No owned-player event currently changes the locked scoring consequence.",
            }
        )

    pending_substitution_map = {
        str(row.get("element")): "pending"
        for row in players
        if int(row.get("multiplier") or 0) > 0
        and str(row.get("fixture_status") or "").upper() == "FT"
        and int(row.get("minutes") or 0) == 0
        and row.get("element") is not None
    }
    global_autosub_state = {
        "status": (score.get("autosub_implications") or {}).get("status") or "PROVISIONAL",
        "potential_out": (score.get("autosub_implications") or {}).get("potential_out") or [],
        "bench_candidates": (score.get("autosub_implications") or {}).get("bench_candidates") or [],
        "final_substitution_map": pending_substitution_map,
        "official_finalization_authoritative": True,
    }
    icon = dict(icon_live or {})
    if icon:
        submitted_scope = dict(icon.get("submitted_picks_exposure") or {})
        standings_scope = dict(icon.get("live_standings_rank") or {})
        user_summary = dict(icon.get("user_summary") or {})
        our_rank = (
            icon.get("current_live_rank")
            or user_summary.get("rank")
            or icon.get("our_rank")
        )
        league_size = (
            icon.get("expected_manager_count")
            or submitted_scope.get("expected_count")
            or standings_scope.get("expected_count")
            or icon.get("league_size")
        )
        competitive_window = resolve_competitive_window(our_rank, league_size)
        icon["competitive_window"] = competitive_window
        expected_ranks = set(competitive_window.get("ranks") or [])
        rival_source = icon.get("competitive_rival_live_consequence")
        if rival_source is None:
            rival_source = (icon.get("rival_live_points") or {}).get("rows") or []
        icon["competitive_rival_live_consequence"] = [
            dict(row)
            for row in rival_source or []
            if isinstance(row, Mapping)
            and (
                not expected_ranks
                or int(row.get("rank") or 0) in expected_ranks
            )
        ]
        icon.pop("direct_rival_live_consequence", None)
    icon_state = (
        "COMPLETE"
        if str(icon.get("status") or "").upper() in {"FRESH", "COMPLETE"}
        else "DEGRADED"
    )
    icon_reason = None if icon_state == "COMPLETE" else "fresh ICON+ live standings/exposure unavailable"

    section_payloads = {
        "MATCH1": {
            "state": "COMPLETE",
            "content": {
                "scoring_gw": live.get("scoring_gw"),
                "fixtures_live": checkpoint.get("fixtures_live", lifecycle.get("fixtures_live")),
                "fixtures_ft": checkpoint.get("fixtures_ft", lifecycle.get("fixtures_ft")),
                "fixtures_not_started": checkpoint.get(
                    "fixtures_not_started",
                    lifecycle.get("fixtures_not_started"),
                ),
                "timestamp": checkpoint.get("generated_at") or generated_at,
                "lifecycle_mode": lifecycle.get("primary_mode"),
                "transition": lifecycle.get("transition"),
            },
        },
        "MATCH2": {
            "state": "COMPLETE",
            "content": {
                "rows": players,
                "xi": [row.get("name") for row in xi_rows],
                "bench": [row.get("name") for row in bench_rows],
                "authority": "LOCKED_SUBMITTED_PICKS",
            },
        },
        "MATCH3": {
            "state": "COMPLETE",
            "content": {"rows": personal_impact},
        },
        "MATCH4": {
            "state": "COMPLETE",
            "content": {
                **global_autosub_state,
                "bench_gk": bench.get("bench_gk"),
                "outfield_autosub_priority": bench.get("outfield_autosub_priority") or [],
            },
        },
        "MATCH5": {
            "state": "COMPLETE",
            "content": captain,
        },
        "MATCH6": {
            "state": "COMPLETE",
            "content": {
                "rows": [
                    {
                        "element_id": row.get("element"),
                        "player": row.get("name"),
                        "state": row.get("fixture_status"),
                        "minutes": row.get("minutes"),
                        "raw_points": row.get("total_points"),
                        "multiplier": row.get("multiplier"),
                        "effective_points": row.get("effective_points"),
                    }
                    for row in players
                ]
            },
        },
        "MATCH7": {
            "state": "COMPLETE",
            "content": {
                **bonus,
                "rows": [
                    {
                        "element_id": row.get("element"),
                        "player": row.get("name"),
                        "bonus": row.get("bonus"),
                        "bps": row.get("bps"),
                    }
                    for row in players
                    if int(row.get("bonus") or 0) != 0 or int(row.get("bps") or 0) != 0
                ],
            },
        },
        "MATCH8": {
            "state": "COMPLETE",
            "content": {
                "rows": [
                    dict(row)
                    for row in (cards_injury_defcon_role_events or ())
                    if isinstance(row, Mapping)
                ],
                "observation_is_not_automatic_model_change": True,
            },
        },
        "MATCH9": {
            "state": "COMPLETE",
            "content": {
                "rows": [
                    dict(row)
                    for row in (league_wide_signals or ())
                    if isinstance(row, Mapping)
                ],
                "scorer_only_scouting_prohibited": True,
            },
        },
        "MATCH10": {
            "state": icon_state,
            "degradation_reason": icon_reason,
            "content": icon if icon else {"status": "UNAVAILABLE"},
        },
        "MATCH11": {
            "state": "COMPLETE",
            "content": {
                "rows": [
                    dict(row)
                    for row in (next_gw_learning or ())
                    if isinstance(row, Mapping)
                ],
                "evidence_not_automatic_transfer": True,
            },
        },
        "MATCH12": {
            "state": "COMPLETE",
            "content": {
                "observation": (
                    next_critical_observation
                    or (
                        "process newly completed fixture evidence"
                        if lifecycle.get("incremental_post_match_due")
                        else "next scoring-GW fixture state change"
                    )
                ),
                "why_it_matters": next_critical_reason,
                "when_to_reassess": next_reassess_at,
            },
        },
        "MATCH13": {
            "state": "COMPLETE",
            "content": {
                **dict(source_freshness or {}),
                "generated_at": generated_at,
                "submitted_picks": live.get("submitted_picks_status"),
                "event_live": live.get("event_live_status"),
                "prediction_snapshot": (live.get("prediction_snapshot") or {}).get("status"),
                "fixture_state_authority": "OFFICIAL_FPL",
            },
        },
    }
    report = _materialize_canonical_report(
        canonical_text=canonical_text,
        structural_mode="MATCH",
        reported_mode="MATCH",
        section_payloads=section_payloads,
    )
    report["content_contract"] = {
        "visible_order": [
            "MATCH CHECKPOINT / GW STATUS",
            "LOCKED PERSONAL TEAM",
            "PERSONAL IMPACT FIRST",
            "GLOBAL AUTOSUB STATE",
            "CAPTAIN / VICE CONSEQUENCE",
            "OWNED LIVE / FINAL POINTS",
            "BONUS / BPS",
            "CARDS / INJURY / DEFCON / ROLE EVENTS",
            "RELEVANT LEAGUE-WIDE SIGNALS",
            "ICON+ LIVE",
            "NEXT-GW LEARNING",
            "NEXT CRITICAL OBSERVATION",
            "SOURCE / FRESHNESS STATUS",
        ],
        "locked_team": {
            "status": "CURRENT_IMMUTABLE",
            "source": "LOCKED_SUBMITTED_PICKS",
        },
        "personal_impact": personal_impact,
        "global_autosub_state": global_autosub_state,
        "captain_vice_consequence": captain,
        "owned_live_final_points": section_payloads["MATCH6"]["content"]["rows"],
        "bonus_bps": bonus,
        "cards_injury_defcon_role_events": section_payloads["MATCH8"]["content"]["rows"],
        "league_wide_signals": section_payloads["MATCH9"]["content"]["rows"],
        "next_gw_learning": section_payloads["MATCH11"]["content"]["rows"],
        "next_critical_observation": section_payloads["MATCH12"]["content"]["observation"],
        "source_freshness": section_payloads["MATCH13"]["content"],
        "bench_presentation": {
            "bench_gk": (bench.get("bench_gk") or {}).get("name")
            if isinstance(bench.get("bench_gk"), Mapping)
            else bench.get("bench_gk"),
            "outfield_autosub_priority": [
                row.get("name") if isinstance(row, Mapping) else row
                for row in bench.get("outfield_autosub_priority") or []
            ],
            "position_by_player": {
                str(row.get("name")): row.get("position")
                for row in players
                if row.get("name")
            },
        },
        "icon": icon,
        "section_states": {
            "ICON+": {
                "state": icon_state,
                "degradation_reason": icon_reason,
            }
        },
        "football_optimal_baseline_before_icon": True,
        "report_due": True,
        "optional_scope_degraded": icon_state != "COMPLETE",
        "visible_report_suppressed": False,
    }
    return report


def render_match_text(report: Mapping[str, Any]) -> str:
    """Render the locked MATCH1..MATCH13 presentation contract."""
    from src.engines.v12_locked_mode_renderers import render_match_locked_text

    return render_match_locked_text(report)

def _visible_section_heading(section_id: Any, label: Any) -> str:
    """Render a heading shape that the visible-body validator can parse."""
    section = str(section_id or "").strip().upper()
    title = str(label or "Report Section").strip()
    match = re.fullmatch(r"S(\d{1,2})(B?)", section)
    if match:
        return f"## {int(match.group(1))}{match.group(2)}. {title}"
    match = re.fullmatch(r"MATCH(\d{1,2})", section)
    if match:
        return f"## MATCH {int(match.group(1))} — {title}"
    match = re.fullmatch(r"PRICE(\d{1,2})", section)
    if match:
        return f"## PRICE {int(match.group(1))} — {title}"
    match = re.fullmatch(r"POST_ALL_MATCH(\d{1,2})", section)
    if match:
        return f"## POST-ALL-MATCH {int(match.group(1))} — {title}"
    if section == "GW_LOCK_PACKAGE":
        return "## GW LOCK PACKAGE"
    return f"## {title}"


def _human_label(value: Any) -> str:
    return str(value or "").strip().replace("_", " ").upper()


def _render_generic_human_content(
    content: Mapping[str, Any] | None,
    *,
    excluded_keys: Sequence[str] = (),
) -> list[str]:
    """Render user-facing structured content without dumping runtime internals."""
    payload = dict(content or {})
    excluded = {str(key) for key in excluded_keys}
    lines: list[str] = []
    hidden_tokens = (
        "fingerprint",
        "sha",
        "run_id",
        "workflow",
        "issue_431",
        "mutation",
        "readback",
        "raw_payload",
    )
    for key, value in payload.items():
        key_text = str(key)
        lower = key_text.lower()
        if key_text in excluded or any(token in lower for token in hidden_tokens):
            continue
        if value is None:
            lines.append(f"{_human_label(key_text)}: UNAVAILABLE")
            continue
        if isinstance(value, (str, int, float, bool)):
            lines.append(f"{_human_label(key_text)}: {value}")
            continue
        if isinstance(value, Mapping):
            compact = []
            for subkey, subvalue in value.items():
                if isinstance(subvalue, (str, int, float, bool)) or subvalue is None:
                    compact.append(
                        f"{_human_label(subkey)}={subvalue if subvalue is not None else 'UNAVAILABLE'}"
                    )
            if compact:
                lines.append(f"{_human_label(key_text)}: " + " | ".join(compact))
            continue
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            items = list(value)
            if not items:
                lines.append(f"{_human_label(key_text)}: NONE")
                continue
            scalar_items = [
                item for item in items
                if isinstance(item, (str, int, float, bool))
            ]
            if len(scalar_items) == len(items):
                lines.append(
                    f"{_human_label(key_text)}: "
                    + ", ".join(str(item) for item in scalar_items)
                )
                continue
            for index, item in enumerate(items, start=1):
                if not isinstance(item, Mapping):
                    continue
                compact = []
                for subkey, subvalue in item.items():
                    if isinstance(subvalue, (str, int, float, bool)) or subvalue is None:
                        compact.append(
                            f"{_human_label(subkey)}={subvalue if subvalue is not None else 'UNAVAILABLE'}"
                        )
                if compact:
                    lines.append(f"- {index}. " + " | ".join(compact))
    return lines


def render_natural_post_match_text(report: Mapping[str, Any]) -> str:
    """Visible natural post-match renderer including fixture scout and movers."""
    blocks: list[str] = []
    for section in report.get("sections") or []:
        label = str(section.get("label") or "")
        state = str(section.get("state") or "")
        section_id = section.get("section_id")
        lines = [_visible_section_heading(section_id, label), f"Status: {state}"]
        reason = str(section.get("degradation_reason") or "").strip()
        if state != "COMPLETE" and reason:
            lines.append(f"Reason: {reason}")
        content = section.get("content")
        content_map = dict(content or {}) if isinstance(content, Mapping) else {}

        scout = [
            dict(row)
            for row in (
                content_map.get("match_scout")
                or content_map.get("post_match_match_by_match_scout")
                or ()
            )
            if isinstance(row, Mapping)
        ]
        if scout:
            lines.extend(_render_match_scout_lines(scout))

        math_stack = content_map.get("mathematical_decision_stack")
        if isinstance(math_stack, Mapping):
            lines.extend(_render_math_stack_lines(math_stack))

        if "PACKAGE OPTIMIZER" in label.upper():
            lines.extend(
                _render_package_frontier_lines(
                    content_map,
                    section_state=state,
                )
            )

        movers = dict(content_map.get("universe_movers") or {})
        if movers:
            lines.append("### UNIVERSE MOVERS")
            mover_state = str(movers.get("state") or "UNAVAILABLE")
            if mover_state != "COMPLETE":
                lines.append(
                    f"{mover_state} — "
                    f"{movers.get('degradation_reason') or 'evidence unavailable'}"
                )
            elif movers.get("summary") == "NO MATERIAL MOVERS":
                lines.append("NO MATERIAL MOVERS")
            else:
                for category, rows in (
                    movers.get("categories") or {}
                ).items():
                    if not rows:
                        continue
                    lines.append(f"**{category}**")
                    for row in rows:
                        owner = "OWNED" if row.get("owned") else "NON-OWNED"
                        deep = "DEEP" if row.get("deep_detail") else "BROAD"
                        lines.append(
                            "- "
                            f"{row.get('name') or row.get('element_id')} "
                            f"({row.get('position') or 'NA'}) | "
                            f"{row.get('primary_classification')} | "
                            f"Pts {row.get('latest_fpl_points')} | "
                            f"xGI {row.get('latest_xgi')} | "
                            f"xMins Δ {row.get('xmins_delta')} | "
                            f"P(start) Δ {row.get('p_start_delta')} | "
                            f"{row.get('universe_comparison_state') or 'UNAVAILABLE'} | "
                            f"{owner} | {deep}"
                        )
            lines.append(
                "Coverage: "
                f"{movers.get('scanned_count')}/{movers.get('eligible_count')} | "
                f"Material {movers.get('material_count')} | "
                f"Deep {movers.get('deep_executed_count')}/"
                f"{movers.get('deep_requested_count')} | "
                f"Authority {movers.get('search_authority') or 'UNAVAILABLE'}"
            )
        generic = _render_generic_human_content(
            content_map,
            excluded_keys=(
                "match_scout",
                "post_match_match_by_match_scout",
                "mathematical_decision_stack",
                "universe_movers",
                "package_search_proof",
                "search_proof",
                "package_universe_challengers",
                "universe_challengers",
                "package_routes",
                "routes",
                "frontier",
            ),
        )
        if generic:
            lines.extend(generic)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)



def _markdown_cell(value: Any) -> str:
    text = str("UNAVAILABLE" if value is None else value)
    return text.replace("|", "/").replace("\n", " ").strip()


def _human_summary(value: Any) -> str:
    """Compact nested evidence without Python/JSON dict syntax."""
    if value is None:
        return "UNAVAILABLE"
    if isinstance(value, Mapping):
        parts: list[str] = []
        for key, item in value.items():
            label = str(key).replace("_", " ")
            if isinstance(item, Mapping):
                sub = ", ".join(
                    f"{str(k).replace('_', ' ')}={v}"
                    for k, v in item.items()
                    if v not in (None, "", [], {})
                )
                if sub:
                    parts.append(f"{label}: {sub}")
            elif isinstance(item, (list, tuple, set)):
                vals = ", ".join(str(x) for x in item)
                if vals:
                    parts.append(f"{label}: {vals}")
            elif item not in (None, ""):
                parts.append(f"{label}={item}")
        return "; ".join(parts) if parts else "UNAVAILABLE"
    if isinstance(value, (list, tuple, set)):
        return ", ".join(_human_summary(item) for item in value) or "UNAVAILABLE"
    return str(value)


def _markdown_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> list[str]:
    header = "| " + " | ".join(headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    body = [
        "| " + " | ".join(_markdown_cell(value) for value in row) + " |"
        for row in rows
    ]
    return [header, separator, *body]


DEEP_HUMAN_SECTION_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "S01": ("operational_state", "planning_gw", "primary_decision", "key_decision_driver"),
    "S02": ("rows",),
    "S03": ("decision_delta",),
    "S04": ("material_news", "model_developments", "decision_consequence", "source_policy"),
    "S05": ("fixtures",),
    "S06": ("formation", "starting_xi", "bench", "lineup_score", "formation_comparison"),
    "S06B": (
        "battle_rows",
        "battles",
        "current_winner",
        "battle_classification",
        "primary_alternative",
        "reason",
    ),
    "S07": ("risk_rows", "lineup_implication", "bench_gk", "autosub_order"),
    "S08": (
        "decision_state",
        "captain",
        "vice_captain",
        "captain_frontier",
        "candidate_universe_proof",
        "reconciliation_reason",
    ),
    "S09": ("chip",),
    "S10": ("rows",),
    "S11": ("rows",),
    "S12": ("rows",),
    "S13": ("rows",),
    "S14": ("package_routes", "frontier"),
    "S14B": ("staging_rows", "squad_classification", "target_formation"),
    "S15": ("evidence_quality",),
    "S15B": (
        "current_league_context",
        "exposures",
        "rank_battle",
        "denominator_scopes",
        "league_our15_exposure",
        "rivals_our15_exposure",
        "competitive_window",
        "competitive_rivals",
        "competitive_our15_exposure",
        "competitive_window_threats",
        "captain_leverage",
        "strategy_implication",
        "report_contract",
        "disclosed_picks_label",
    ),
    "S16": ("rows", "position_mechanisms"),
    "S16B": (
        "gw",
        "fixtures_expected",
        "fixtures_reviewed",
        "match_by_match_review",
        "after_gw_reassessment",
        "full_universe_denominator",
    ),
    "S17": ("engine_data_status", "source_health"),
    "S18": (
        "NOW",
        "NEXT",
        "TRIGGER TO ACT",
        "LATEST SAFE DECISION POINT",
        "COST OF WAITING",
        "ABORT / REVERSAL",
        "BEST ALTERNATIVE",
    ),
    "S19": ("final_judgement",),
}


def build_deep_human_facing_manifest(
    report: Mapping[str, Any],
) -> dict[str, Any]:
    """Durable semantic manifest for required DEEP human-facing content."""
    sections = {
        str(row.get("section_id") or "").strip().upper(): dict(row)
        for row in report.get("sections") or []
        if isinstance(row, Mapping)
    }
    entries: list[dict[str, Any]] = []
    failures: list[str] = []
    for section_id, required_keys in DEEP_HUMAN_SECTION_REQUIREMENTS.items():
        section = sections.get(section_id)
        if section_id == "S16B" and section is None:
            continue
        if section is None:
            failures.append(f"HUMAN_SECTION_MISSING={section_id}")
            entries.append({
                "section_id": section_id,
                "status": "MISSING",
                "required_keys": list(required_keys),
                "missing_keys": list(required_keys),
            })
            continue
        content = section.get("content")
        payload = dict(content or {}) if isinstance(content, Mapping) else {}
        missing = [key for key in required_keys if key not in payload]
        empty = [
            key
            for key in required_keys
            if key in payload and payload.get(key) in (None, "", [], {})
        ]
        # Degraded/unavailable sections may truthfully carry empty factual rows,
        # but the semantic key must remain visible. Some COMPLETE decision
        # sections can also be truthfully empty when the payload explicitly
        # proves there is no material item (for example no XI battle).
        state = str(section.get("state") or "").upper()
        truthful_empty = payload.get("empty_is_truthful") is True
        all_required_empty = bool(required_keys) and len(empty) == len(required_keys)
        hard_empty = (
            list(required_keys)
            if state == "COMPLETE" and all_required_empty and not truthful_empty
            else []
        )
        if missing:
            failures.append(
                f"HUMAN_SECTION_KEYS_MISSING={section_id}:{','.join(missing)}"
            )
        if hard_empty:
            failures.append(
                f"HUMAN_SECTION_CONTENT_EMPTY={section_id}:{','.join(hard_empty)}"
            )
        entries.append({
            "section_id": section_id,
            "label": section.get("label"),
            "status": state,
            "required_keys": list(required_keys),
            "missing_keys": missing,
            "empty_keys": empty,
            "semantic_pass": not missing and not hard_empty,
        })
    return {
        "contract": "V12_DEEP_HUMAN_FACING_MANIFEST_V2",
        "required_section_ids": list(DEEP_HUMAN_SECTION_REQUIREMENTS),
        "entries": entries,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
    }


def validate_deep_human_facing_manifest(
    manifest: Mapping[str, Any],
) -> list[str]:
    if str(manifest.get("status") or "").upper() == "PASS":
        return []
    return [str(value) for value in manifest.get("failures") or []]


def _render_deep_visible_contract_lines(
    *,
    section_id: str,
    content: Mapping[str, Any],
    owned_ids: set[int],
    owned_names: Mapping[int, str],
) -> tuple[list[str], tuple[str, ...]]:
    """Render DEEP strictly from the locked human-facing presentation contract.

    This layer only projects already-bound canonical values. It never recomputes
    football, price, mini-league, optimizer, Monte Carlo, or lineup decisions.
    """
    payload = dict(content or {})
    lines: list[str] = []
    excluded: list[str] = list(payload.keys())

    def _name(value: Any) -> str:
        if isinstance(value, Mapping):
            element = value.get("element", value.get("element_id"))
            explicit = value.get("player") or value.get("name")
            if explicit:
                return str(explicit)
            try:
                return owned_names.get(int(element), str(element))
            except (TypeError, ValueError):
                return str(element or "UNAVAILABLE")
        try:
            element = int(value)
        except (TypeError, ValueError):
            return str(value if value not in (None, "") else "UNAVAILABLE")
        return owned_names.get(element, str(element))

    def _num(value: Any) -> str:
        if value is None:
            return "UNAVAILABLE"
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return str(value)
        if numeric.is_integer():
            return str(int(numeric))
        return f"{numeric:.2f}".rstrip("0").rstrip(".")

    def _ratio(
        row: Mapping[str, Any],
        count_key: str,
        pct_key: str,
        *,
        numerator_key: str | None = None,
    ) -> str:
        denominator = row.get("denominator")
        numerator = row.get(numerator_key or count_key)
        if denominator in (None, 0) or numerator is None:
            return "UNAVAILABLE"
        pct = row.get(pct_key)
        if pct is None:
            try:
                pct = 100.0 * float(numerator) / float(denominator)
            except (TypeError, ValueError, ZeroDivisionError):
                return "UNAVAILABLE"
        return f"{_num(numerator)}/{_num(denominator)} ({float(pct):.1f}%)"

    def _count_ratio(numerator: Any, denominator: Any) -> str:
        if numerator is None or denominator in (None, 0):
            return "UNAVAILABLE"
        try:
            pct = 100.0 * float(numerator) / float(denominator)
        except (TypeError, ValueError, ZeroDivisionError):
            return "UNAVAILABLE"
        return f"{_num(numerator)}/{_num(denominator)} ({pct:.1f}%)"

    def _coverage(scope: Mapping[str, Any]) -> str:
        return _count_ratio(scope.get("collected"), scope.get("expected"))

    def _compact(value: Any) -> str:
        if value in (None, "", [], {}):
            return "UNAVAILABLE"
        if isinstance(value, Mapping):
            return "; ".join(
                f"{str(k).replace('_', ' ')}={_compact(v)}"
                for k, v in value.items()
                if v not in (None, "", [], {})
            ) or "UNAVAILABLE"
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return ", ".join(_compact(v) for v in value) or "UNAVAILABLE"
        return str(value)

    if section_id == "S01":
        dashboard = dict(payload.get("decision_dashboard") or {})
        calls = {
            "TRANSFER": payload.get("primary_decision") or dashboard.get("PRIMARY_REASON"),
            "XI": "See S06/S07",
            "CAPTAIN": "See S08",
            "CHIP": "See S09",
            "PRICE": "See S10",
            "PERSONAL_AUTH": dashboard.get("PERSONAL_AUTH"),
        }
        labels = (
            ("TRANSFER", "Transfer"),
            ("XI", "XI"),
            ("CAPTAIN", "Captain"),
            ("CHIP", "Chip"),
            ("PRICE", "Price"),
            ("PERSONAL_AUTH", "Personal authentication"),
        )
        lines.extend(_markdown_table(
            ("Axis", "Status", "Current call"),
            [(label, dashboard.get(key), calls.get(key)) for key, label in labels],
        ))
        lines.append(f"Planning GW: {dashboard.get('PLANNING_GW', payload.get('planning_gw'))}")
        lines.append(f"Reason: {dashboard.get('PRIMARY_REASON', payload.get('reason'))}")
        lines.append(f"Key driver: {dashboard.get('KEY_DRIVER', payload.get('key_decision_driver'))}")

    elif section_id == "S02":
        rows = [dict(r) for r in payload.get("rows") or [] if isinstance(r, Mapping)]
        lines.extend(_markdown_table(
            ("Player", "Pos", "Opponent", "Pstart", "xMins", "1GW xPts", "3GW", "5GW", "Note"),
            [(
                r.get("player") or r.get("name"),
                r.get("position"),
                r.get("opponent"),
                r.get("p_start"),
                r.get("xmins"),
                r.get("projection_1gw"),
                r.get("projection_3gw"),
                r.get("projection_5gw"),
                " | ".join(
                    str(v) for v in (
                        r.get("tactical_role_label"),
                        r.get("injury_rotation_warning"),
                        r.get("price_relevance"),
                    ) if v not in (None, "", "NONE_MATERIAL", [])
                ) or "No material note",
            ) for r in rows],
        ))
        authority = dict(payload.get("current15_authority") or {})
        lines.append(
            "Current squad evidence: "
            f"{authority.get('source_class', 'UNAVAILABLE')} | "
            f"as of {authority.get('observed_at', 'UNAVAILABLE')} | "
            f"authentication {authority.get('auth_state', 'UNAVAILABLE')}"
        )

    elif section_id == "S03":
        delta = dict(payload.get("decision_delta") or {})
        baseline = str(delta.get("baseline_state") or "UNAVAILABLE").upper()
        lines.append(f"Previous valid baseline: {baseline}")
        delta_rows = [dict(r) for r in delta.get("rows") or [] if isinstance(r, Mapping)]
        changed = [r for r in delta_rows if str(r.get("change") or "").upper() == "CHANGED"]
        unchanged = [r for r in delta_rows if str(r.get("change") or "").upper() != "CHANGED"]
        if baseline != "AVAILABLE":
            lines.append("Verdict: baseline unavailable; no numerical or decision delta is inferred.")
        elif changed:
            lines.append("Changed: " + "; ".join(
                f"{r.get('signal')}: {r.get('04:30_or_baseline_state')} → {r.get('12:30_state')}"
                for r in changed
            ))
            lines.append("Unchanged: " + (", ".join(str(r.get("signal")) for r in unchanged) or "None material"))
            lines.append("Verdict: reassess only the changed decision-critical evidence.")
        else:
            lines.append("Changed: None material.")
            lines.append("Unchanged: decision-critical baseline remains stable.")
            lines.append("Verdict: NO MATERIAL DECISION CHANGE.")

    elif section_id == "S04":
        groups = dict(payload.get("news_groups") or {})
        lines.append("### MATERIAL NEWS SINCE PREVIOUS DEEP")
        lines.append(str(payload.get("news_summary") or "NO MATERIAL NEW EXTERNAL NEWS"))
        for group_name in ("OUR15", "WATCHLIST / TARGETS", "TEAM / TACTICAL", "OTHER MATERIAL"):
            rows = [dict(r) for r in groups.get(group_name) or [] if isinstance(r, Mapping)]
            lines.append(f"### {group_name}")
            if not rows:
                lines.append("None material.")
                continue
            for row in rows:
                source_class = str(row.get("source_class") or "UNAVAILABLE")
                marker = "UNVERIFIED" if source_class == "RUMOR / UNVERIFIED" else source_class
                lines.append(
                    f"- {row.get('subject') or row.get('affected_player_team') or 'Material item'}: "
                    f"{row.get('summary') or row.get('headline') or 'UNAVAILABLE'} "
                    f"[{marker}; {row.get('published_or_observed_timestamp') or 'time unavailable'}]"
                )
        developments = [dict(r) for r in payload.get("model_developments") or [] if isinstance(r, Mapping)]
        lines.append("### MODEL / FOOTBALL DEVELOPMENTS")
        if developments:
            lines.extend(f"- {r.get('summary') or _compact(r)}" for r in developments)
        else:
            lines.append("None material.")
        consequence = dict(payload.get("decision_consequence") or {})
        lines.append("### DECISION CONSEQUENCE")
        lines.append(
            f"Transfer {consequence.get('transfer_state', 'UNAVAILABLE')}; "
            f"XI {consequence.get('xi_state', 'UNAVAILABLE')}; "
            f"Captain {consequence.get('captain_state', 'UNAVAILABLE')}; "
            f"Price {consequence.get('price_state', 'UNAVAILABLE')}. "
            "News is evidence only; ACT authority remains in S14."
        )

    elif section_id == "S05":
        lines.append(f"Fixture topology: {payload.get('gw_topology') or 'UNAVAILABLE'}")
        fixtures = payload.get("fixtures") or []
        if fixtures:
            lines.append("PL fixtures: " + _compact(fixtures))
        coverage = dict(payload.get("competition_coverage") or {})
        if coverage:
            lines.append(
                "Schedule evidence: "
                f"PL={coverage.get('official_pl', 'UNAVAILABLE')}; "
                f"non-PL={coverage.get('verified_non_pl_schedule_bound', 'UNAVAILABLE')}; "
                f"weather={coverage.get('weather_binding_status', 'UNAVAILABLE')}."
            )
        workloads = [dict(r) for r in payload.get("player_workload") or [] if isinstance(r, Mapping)]
        material_load = [
            r for r in workloads
            if str(r.get("load_state") or "").upper() not in {"", "NORMAL", "AVAILABLE", "LOW"}
            or r.get("long_haul") is True
        ]
        lines.append(
            "Rest/workload: "
            + ("; ".join(
                f"{r.get('player') or r.get('name') or 'Player'} {r.get('load_state') or ''} "
                f"(rest {r.get('days_rest', 'UNAVAILABLE')}d)"
                for r in material_load[:8]
            ) if material_load else "No material workload flag.")
        )
        weather = payload.get("weather")
        lines.append("Weather: " + (_compact(weather) if weather else "No material weather signal."))
        lines.append("Decision use: context only; no separate optimizer or news authority.")

    elif section_id == "S06":
        xi = list(payload.get("starting_xi") or [])
        formation = payload.get("formation")
        lines.append(f"Formation: {formation or 'UNAVAILABLE'}")
        grouped: dict[str, list[str]] = {"GK": [], "DEF": [], "MID": [], "FWD": []}
        fallback: list[str] = []
        for value in xi:
            if isinstance(value, Mapping):
                pos = str(value.get("position") or value.get("pos") or "").upper()
                name = _name(value)
                if pos in grouped:
                    grouped[pos].append(name)
                else:
                    fallback.append(name)
            else:
                fallback.append(_name(value))
        for pos in ("GK", "DEF", "MID", "FWD"):
            if grouped[pos]:
                lines.append(f"{pos}: " + ", ".join(grouped[pos]))
        if fallback:
            lines.append("XI: " + ", ".join(fallback))
        bench_raw = payload.get("bench")
        bench = dict(bench_raw) if isinstance(bench_raw, Mapping) else {}
        bench_gk = bench.get("bench_gk") or bench.get("gk") or bench.get("goalkeeper")
        order = bench.get("outfield_autosub_priority") or bench.get("order") or bench.get("outfield") or []
        if not isinstance(order, Sequence) or isinstance(order, (str, bytes)):
            order = []
        lines.append(f"Bench GK: {_name(bench_gk)}")
        for idx, value in enumerate(list(order)[:3], start=1):
            lines.append(f"Bench {idx}: {_name(value)}")
        score = dict(payload.get("lineup_score") or {})
        lines.append(
            f"Projection: XI base xPts={payload.get('xi_base_xpts', score.get('xpts_mean', 'UNAVAILABLE'))}; "
            f"captain-adjusted={payload.get('captain_adjusted_xpts', 'UNAVAILABLE')}."
        )
        comparisons = [dict(r) for r in payload.get("formation_comparison") or [] if isinstance(r, Mapping)]
        if comparisons:
            close = sorted(
                comparisons,
                key=lambda r: float(r.get("expected_fpl_points_with_captain_vice") or -9999),
                reverse=True,
            )[:2]
            lines.append("Frontier note: " + " vs ".join(
                f"{r.get('formation')} {r.get('expected_fpl_points_with_captain_vice')} xPts"
                for r in close
            ))

    elif section_id == "S06B":
        rows = [dict(r) for r in payload.get("battle_rows") or [] if isinstance(r, Mapping)]
        if rows:
            lines.extend(_markdown_table(
                ("Player", "Pstart", "xMins", "1GW xPts"),
                [(r.get("player"), r.get("p_start"), r.get("xmins"), r.get("projection_1gw")) for r in rows],
            ))
        else:
            lines.append("No material XI battle is currently identified.")
        lines.append(f"Winner: {payload.get('current_winner') or 'UNAVAILABLE'}")
        lines.append(f"Classification: {payload.get('battle_classification') or 'UNAVAILABLE'}")
        lines.append(f"Primary alternative: {payload.get('primary_alternative') or 'UNAVAILABLE'}")
        lines.append(f"Reason: {payload.get('reason') or 'UNAVAILABLE'}")

    elif section_id == "S07":
        rows = [dict(r) for r in payload.get("risk_rows") or [] if isinstance(r, Mapping)]
        if rows:
            for row in rows:
                flags = row.get("flags") or []
                lines.append(
                    f"- {row.get('player')}: Pstart {row.get('p_start')}; xMins {row.get('xmins')}; "
                    f"flags {', '.join(str(v) for v in flags) if flags else 'none material'}; "
                    f"implication {row.get('implication') or 'monitor'}."
                )
        else:
            lines.append("No material lineup-risk player is currently identified.")
        lines.append(f"Lineup implication: {payload.get('lineup_implication') or 'UNAVAILABLE'}")
        order = payload.get("autosub_order") or []
        lines.append(
            "Autosub order: "
            + (", ".join(f"{i}. {v}" for i, v in enumerate(order, 1)) if order else "UNAVAILABLE")
        )
        lines.append(f"Bench GK: {payload.get('bench_gk') or 'UNAVAILABLE'}")

    elif section_id == "S08":
        frontier = [dict(r) for r in payload.get("captain_frontier") or [] if isinstance(r, Mapping)][:5]
        lines.extend(_markdown_table(
            ("Rank", "Player", "xPts", "Phaul", "Pstart", "xMins"),
            [(
                r.get("football_rank") or idx,
                r.get("player") or r.get("name"),
                r.get("xpts") or r.get("expected_points"),
                r.get("p_haul"),
                r.get("p_start"),
                r.get("xmins"),
            ) for idx, r in enumerate(frontier, 1)],
        ))
        captain = dict(payload.get("captain") or {})
        vice = dict(payload.get("vice_captain") or {})
        lines.append(
            f"Current call: C {captain.get('player') or captain.get('name') or 'UNAVAILABLE'}; "
            f"VC {vice.get('player') or vice.get('name') or 'UNAVAILABLE'}; "
            f"state {payload.get('decision_state') or 'UNAVAILABLE'}."
        )
        if frontier:
            lines.append(
                "EO/leverage context: "
                + "; ".join(
                    f"{r.get('player') or r.get('name')}: {str(r.get('exposure_leverage_class') or 'context unavailable').replace('_', ' ')}"
                    for r in frontier
                )
            )
        lines.append(f"Reconciliation: {payload.get('reconciliation_reason') or 'No material override.'}")

    elif section_id == "S09":
        ledger = payload.get("chip_ledger")
        ledger_map = dict(ledger) if isinstance(ledger, Mapping) else {}
        aliases = (
            ("Bench Boost", ("BB", "BENCH_BOOST", "bench_boost")),
            ("Wildcard", ("WC", "WILDCARD", "wildcard")),
            ("Triple Captain", ("TC", "TRIPLE_CAPTAIN", "triple_captain")),
            ("Free Hit", ("FH", "FREE_HIT", "free_hit")),
        )
        chip_rows = []
        for label, keys in aliases:
            value = next((ledger_map.get(k) for k in keys if k in ledger_map), None)
            chip_rows.append((label, _compact(value if value is not None else "UNAVAILABLE")))
        lines.extend(_markdown_table(("Chip", "Status"), chip_rows))
        lines.append(f"Current decision: {payload.get('considered_now') if payload.get('considered_now') is not None else 'No chip action'}")
        lines.append(f"Reason: {payload.get('hold_reason') or payload.get('trigger') or 'UNAVAILABLE'}")

    elif section_id == "S10":
        rows = [dict(r) for r in payload.get("rows") or [] if isinstance(r, Mapping)]
        lines.extend(_markdown_table(
            ("Player", "Price", "Direction", "Progress"),
            [(
                r.get("player") or r.get("player_name") or r.get("name"),
                r.get("current_price"),
                r.get("direction"),
                r.get("official_or_provider_progress", r.get("current_progress_percent", r.get("projected_percent"))),
            ) for r in rows],
        ))
        if rows:
            first = rows[0]
            lines.append(
                f"Predictor status: {first.get('freshness', 'UNAVAILABLE')}; "
                f"source age minutes: {first.get('source_age_minutes', 'UNAVAILABLE')}."
            )
        lines.append("Price-only conclusion: price evidence never overrides the football decision by itself.")

    elif section_id == "S11":
        rows = [dict(r) for r in (payload.get("scanner20") or payload.get("rows") or []) if isinstance(r, Mapping)]
        lines.extend(_markdown_table(
            ("Player", "Pos", "£", "xMins", "Pstart", "DNP", "Score", "Admit", "Evidence"),
            [(
                r.get("player") or r.get("player_name") or r.get("name"),
                r.get("position") or r.get("pos"),
                r.get("price") or r.get("current_price"),
                r.get("xmins"),
                r.get("p_start"),
                r.get("dnp") or r.get("p_dnp"),
                r.get("score") or r.get("watchlist_score"),
                r.get("admit") or r.get("admission") or r.get("actionable"),
                r.get("evidence") or r.get("evidence_summary") or r.get("reason"),
            ) for r in rows],
        ))
        actionable = [dict(r) for r in payload.get("actionable_watchlist") or [] if isinstance(r, Mapping)]
        lines.append(
            "Actionable subset: "
            + (", ".join(str(r.get("player") or r.get("name")) for r in actionable) if actionable else "None")
        )

    elif section_id in {"S12", "S13"}:
        rows = [dict(r) for r in payload.get("rows") or [] if isinstance(r, Mapping)]
        lines.extend(_markdown_table(
            ("#", "Player", "£", "Progress", "ETA"),
            [(
                idx,
                r.get("player") or r.get("player_name") or r.get("name"),
                r.get("current_price"),
                r.get("official_or_provider_progress", r.get("current_progress_percent", r.get("projected_percent"))),
                r.get("eta_human") or r.get("estimated_change_at_wib") or r.get("predicted_change_at") or r.get("date_state"),
            ) for idx, r in enumerate(rows, 1)],
        ))
        if rows:
            lines.append(
                f"Predictor freshness: {rows[0].get('freshness', 'UNAVAILABLE')}; "
                f"source age minutes: {rows[0].get('source_age_minutes', 'UNAVAILABLE')}."
            )

    elif section_id == "S14":
        lines.append("Decision layer: full canonical search retained internally; visible output is bounded to search proof, canonical Monte Carlo, verdict, one best challenger, execution economics, and actionability.")
        if payload.get("bgw_context"):
            bgw = dict(payload.get("bgw_context") or {})
            lines.append(
                f"BGW context: active={bgw.get('active')} | topology={bgw.get('gw_topology')}."
            )

    elif section_id == "S14B":
        staging = [dict(r) for r in payload.get("staging_rows") or [] if isinstance(r, Mapping)]
        for idx, label in enumerate(("Current GW", "Next GW", "Following GW")):
            row = staging[idx] if idx < len(staging) else {}
            lines.append(
                f"{label}: {row.get('planned_move') or 'UNAVAILABLE'} | "
                f"status {row.get('status') or 'UNAVAILABLE'} | "
                f"trigger {row.get('trigger') or 'UNAVAILABLE'}."
            )
        classes = [dict(r) for r in payload.get("squad_classification") or [] if isinstance(r, Mapping)]
        core = [r.get("player") for r in classes if str(r.get("classification") or "").upper() == "CORE / HOLD"]
        watch = [r.get("player") for r in classes if str(r.get("classification") or "").upper() == "WATCH"]
        lines.append("Core/Hold: " + (", ".join(str(v) for v in core if v) or "UNAVAILABLE"))
        lines.append("Watch: " + (", ".join(str(v) for v in watch if v) or "UNAVAILABLE"))
        contingency = payload.get("contingency_route")
        lines.append("Contingency route: " + _compact(contingency))
        lines.append(f"Verdict: {payload.get('staging_verdict') or 'Reoptimize from fresh evidence; roadmap is non-binding.'}")

    elif section_id == "S15":
        evidence = dict(payload.get("evidence_quality") or {})

        def _evidence_entry(key: str) -> dict[str, Any]:
            value = evidence.get(key)
            return dict(value) if isinstance(value, Mapping) else {"state": value}

        def _state(key: str) -> str:
            return str(_evidence_entry(key).get("state") or "UNAVAILABLE").upper()

        def _quality_from_state(state: str, *, adequate: bool = False) -> str:
            token = str(state or "UNAVAILABLE").upper()
            if "STALE" in token:
                return "🟡 Stale"
            if "UNAVAILABLE" in token or "MISSING" in token:
                return "🔴 Low"
            if (
                "DEGRADED" in token
                or "PARTIAL" in token
                or "PL_ONLY" in token
                or "OBSERVATIONS_UNAVAILABLE" in token
            ):
                return "🟡 Partial"
            if adequate:
                return "🟢 Adequate"
            return "🟢 Strong"

        identity = _state("CURRENT15 identity")
        model = _state("model snapshot")
        tactical = _state("tactical")
        underlying = _state("post-match underlying")
        fixtures = _state("fixtures/calendar")
        workload = _state("workload/travel")
        finance_entry = _evidence_entry("authenticated finance")
        finance_state = str(finance_entry.get("state") or "UNAVAILABLE").upper()
        sell_value_state = str(finance_entry.get("sell_value_status") or "").upper()
        price_state = _state("price predictor freshness")
        mini_state = _state("mini-league standings/live")
        weather_state = _state("weather")

        finance_quality = _quality_from_state(finance_state)
        if finance_quality == "🟢 Strong" and sell_value_state not in {
            "", "AVAILABLE", "AUTHORITATIVE", "CURRENT"
        }:
            finance_quality = "🟡 Partial"

        price_quality = _quality_from_state(price_state)
        rows: list[tuple[str, str, str]] = [
            (
                "Squad / OUR15",
                _quality_from_state(identity),
                "Current 15-player identity is usable for XI, captaincy and package evaluation."
                if "UNAVAILABLE" not in identity
                else "Squad identity is not sufficiently bound for a full decision.",
            ),
            (
                "Availability / minutes",
                _quality_from_state(model),
                "Current model snapshot supports P(start)/xMins decision use."
                if "UNAVAILABLE" not in model
                else "P(start)/xMins confidence is materially limited.",
            ),
            (
                "Football underlying",
                _quality_from_state(
                    underlying if underlying != "UNAVAILABLE" else model
                ),
                "Current underlying/model evidence is available for football comparison."
                if underlying != "UNAVAILABLE" or model != "UNAVAILABLE"
                else "Underlying evidence is insufficient for confident comparison.",
            ),
            (
                "Tactical / role",
                _quality_from_state(tactical),
                "Role and tactical evidence is available for lineup/transfer interpretation."
                if "UNAVAILABLE" not in tactical
                else "Role uncertainty limits transfer and lineup confidence.",
            ),
            (
                "Fixtures",
                _quality_from_state(fixtures),
                "Fixture topology is sufficient for the governed decision horizons."
                if "UNAVAILABLE" not in fixtures
                else "Fixture evidence is incomplete for horizon comparison.",
            ),
            (
                "Non-PL workload",
                _quality_from_state(workload),
                "Verified non-PL workload is sufficiently represented."
                if workload == "COMPLETE"
                else "Fatigue/rest confidence is limited where non-PL workload is incomplete.",
            ),
            (
                "Finance",
                finance_quality,
                "Bank/FT context is usable; unresolved sell-value authority limits executable transfer precision."
                if finance_quality != "🟢 Strong"
                else "Finance context is sufficient for current route evaluation.",
            ),
            (
                "Price movement",
                price_quality,
                "Price evidence is contextual only and cannot independently trigger ACT."
                if price_quality != "🟢 Strong"
                else "Fresh price evidence can support timing but cannot override football quality.",
            ),
            (
                "Mini-league",
                _quality_from_state(mini_state),
                "League evidence is usable for contextual decision support."
                if "UNAVAILABLE" not in mini_state
                else "Mini-league context is not reliable enough to influence the current decision.",
            ),
            (
                "Weather",
                _quality_from_state(weather_state, adequate=True),
                "Weather is sufficient as contextual evidence; it does not mutate football projections."
                if "UNAVAILABLE" not in weather_state
                else "Weather is unavailable and should not be treated as a decision driver.",
            ),
        ]
        if underlying != "UNAVAILABLE":
            rows.append(
                (
                    "Post-match evidence",
                    _quality_from_state(underlying),
                    "Post-match evidence is available for reassessment without self-authorizing ACT.",
                )
            )

        critical_quality = [row[1] for row in rows[:5]]
        limited_count = sum(
            quality in {"🟡 Partial", "🟡 Stale", "🔴 Low"}
            for _, quality, _ in rows
        )
        if any(quality == "🔴 Low" for quality in critical_quality):
            confidence = "LOW"
        elif all(quality.startswith("🟢") for quality in critical_quality):
            confidence = "HIGH" if limited_count <= 2 else "MEDIUM-HIGH"
        else:
            confidence = "MEDIUM"

        lines.append(f"Overall evidence confidence: {confidence}")
        lines.extend(
            _markdown_table(
                ("Evidence domain", "Quality", "Decision impact"),
                rows,
            )
        )

        limitations = [
            f"{domain}: {impact}"
            for domain, quality, impact in rows
            if quality in {"🟡 Partial", "🟡 Stale", "🔴 Low"}
        ]
        lines.append("Evidence limitations")
        if limitations:
            lines.extend(f"- {item}" for item in limitations)
        else:
            lines.append("- No material evidence limitation is visible for the current decision.")
        lines.append(
            "PRIOR != CURRENT: prior evidence is never represented as CURRENT."
        )
        lines.append("Decision implication")
        if any(quality == "🔴 Low" for quality in critical_quality):
            lines.append(
                "Decision-critical evidence is not strong enough to escalate action without fresh support."
            )
        else:
            lines.append(
                "Evidence is decision-usable at the confidence level above; partial or stale domains cannot independently trigger ACT."
            )

    elif section_id == "S15B":
        coverage = str(payload.get("coverage_state") or "").upper()
        expected = payload.get("expected_manager_count")
        available = payload.get("submitted_picks_available_count")
        lines.append(
            "Status: " + ("COMPLETE" if coverage == "FULL" else "DEGRADED")
            + f" | League coverage {_count_ratio(available, expected)}"
        )
        context = dict(payload.get("current_league_context") or {})
        rank_battle = [dict(r) for r in payload.get("rank_battle") or [] if isinstance(r, Mapping)]
        top10_row = next((r for r in rank_battle if int(r.get("rank") or 0) == 10), {})
        top10_gap = context.get("points_to_top_10")
        if top10_gap is None and top10_row and context.get("our_total_points") is not None:
            try:
                top10_gap = int(top10_row.get("total_points") or 0) - int(context.get("our_total_points") or 0)
            except (TypeError, ValueError):
                top10_gap = None
        lines.append(
            "League landscape: "
            f"rank {context.get('our_rank')}/{context.get('manager_count')} | "
            f"points {context.get('our_total_points')} | leader gap {context.get('points_to_leader')} | "
            f"top-3 gap {context.get('points_to_top_3')} | top-5 gap {context.get('points_to_top_5')} | "
            f"top-10 cutoff gap {top10_gap if top10_gap is not None else 'UNAVAILABLE'} | "
            f"nearest above {context.get('points_to_nearest_above')} | "
            f"nearest below {context.get('points_ahead_nearest_below')}."
        )
        lines.append(
            "Evidence semantics: submitted picks are a disclosed behavioural baseline, not a forecast of private future selections."
        )

        scopes = dict(payload.get("denominator_scopes") or {})
        definitions = {
            "LEAGUE": "All managers including us",
            "RIVALS": "All managers excluding us",
            "COMPETITIVE": "Dynamic rank-relative Competitive Window excluding us",
        }
        lines.append("### DENOMINATOR SCOPES")
        lines.extend(_markdown_table(
            ("Scope", "Definition", "Coverage"),
            [(key, dict(scopes.get(key) or {}).get("definition") or definitions[key], _coverage(dict(scopes.get(key) or {}))) for key in ("LEAGUE", "RIVALS", "COMPETITIVE")],
        ))

        lines.append("### TOP 10 MACRO CONTEXT")
        lines.extend(_markdown_table(
            ("Rank", "Manager", "Team", "Points", "Gap"),
            [(r.get("rank"), r.get("manager"), r.get("team"), r.get("total_points"), r.get("gap_vs_us")) for r in rank_battle],
        ))

        exposure_specs = (
            ("OUR15 LEAGUE", "league_our15_exposure", ("Player", "Owned", "Starter", "Bench", "Captain", "Vice", "EO"), True),
            ("OUR15 RIVALS", "rivals_our15_exposure", ("Player", "Owned", "Starter", "Captain", "EO"), False),
            ("OUR15 COMPETITIVE WINDOW", "competitive_our15_exposure", ("Player", "Owned", "Starter", "Bench", "Captain", "Vice", "EO"), True),
        )
        for title, key, headers, full in exposure_specs:
            rows = [dict(r) for r in payload.get(key) or [] if isinstance(r, Mapping)]
            table_rows = []
            for r in rows:
                values = [
                    r.get("player") or r.get("name"),
                    _ratio(r, "ownership_count", "ownership_pct"),
                    _ratio(r, "starter_count", "starter_pct"),
                ]
                if full:
                    values.extend([
                        _ratio(r, "bench_count", "bench_pct"),
                        _ratio(r, "captain_count", "captain_pct"),
                        _ratio(r, "vice_count", "vice_pct"),
                    ])
                else:
                    values.append(_ratio(r, "captain_count", "captain_pct"))
                values.append(_ratio(r, "effective_multiplier_sum", "eo_pct", numerator_key="effective_multiplier_sum"))
                table_rows.append(tuple(values))
            lines.append(f"### {title}")
            lines.extend(_markdown_table(headers, table_rows))

        competitive = dict(payload.get("competitive_window") or {})
        lines.append(
            "COMPETITIVE WINDOW: "
            f"rank {competitive.get('our_rank')}/{competitive.get('league_size')} | "
            f"above {competitive.get('above_count')} | below {competitive.get('below_count')} | "
            f"rivals {competitive.get('rival_count')} | ranks "
            + ", ".join(str(v) for v in competitive.get("ranks") or [])
        )
        competitive_rivals = [dict(r) for r in payload.get("competitive_rivals") or [] if isinstance(r, Mapping)]
        lines.append("### COMPETITIVE RIVALS")
        lines.extend(_markdown_table(
            ("Rank", "Manager", "Pts", "Gap", "Position vs us", "Squad overlap", "XI overlap", "Captain", "Vice"),
            [(
                r.get("rank"),
                r.get("manager"),
                r.get("total_points"),
                r.get("gap_vs_us"),
                r.get("position_vs_us"),
                _count_ratio(r.get("overlap_count"), r.get("overlap_denominator")),
                _count_ratio(r.get("xi_overlap_count"), r.get("xi_overlap_denominator")),
                r.get("captain"),
                r.get("vice"),
            ) for r in competitive_rivals],
        ))

        threats = [dict(r) for r in payload.get("competitive_window_threats") or [] if isinstance(r, Mapping)]
        lines.append("### COMPETITIVE-WINDOW RIVAL-ONLY THREATS")
        lines.extend(_markdown_table(
            ("Player", "Owned", "Starter", "Captain", "EO"),
            [(
                r.get("player") or r.get("name"),
                _ratio(r, "ownership_count", "ownership_pct"),
                _ratio(r, "starter_count", "starter_pct"),
                _ratio(r, "captain_count", "captain_pct"),
                _ratio(r, "effective_multiplier_sum", "eo_pct", numerator_key="effective_multiplier_sum"),
            ) for r in threats],
        ))

        captain_rows = [dict(r) for r in payload.get("captain_leverage") or [] if isinstance(r, Mapping)]
        lines.append("### CAPTAIN LANDSCAPE")
        lines.extend(_markdown_table(
            ("Player", "Football rank", "xPts", "League C", "League EO", "Competitive C", "Competitive EO", "Class"),
            [(
                r.get("player"),
                r.get("football_rank"),
                r.get("expected_points"),
                _ratio(dict(r.get("league_scope") or {}), "captain_count", "captain_pct"),
                _ratio(dict(r.get("league_scope") or {}), "effective_multiplier_sum", "eo_pct", numerator_key="effective_multiplier_sum"),
                _ratio(dict(r.get("competitive_scope") or {}), "captain_count", "captain_pct"),
                _ratio(dict(r.get("competitive_scope") or {}), "effective_multiplier_sum", "eo_pct", numerator_key="effective_multiplier_sum"),
                str(r.get("exposure_leverage_class") or "UNAVAILABLE").replace("_", " ").title(),
            ) for r in captain_rows],
        ))
        implication = dict(payload.get("strategy_implication") or {})
        lines.append(
            f"Mini-league posture: {implication.get('human_posture') or 'UNAVAILABLE'}; "
            "football baseline remains primary and Competitive Window is contextual."
        )

    elif section_id == "S16":
        rows = [dict(r) for r in payload.get("rows") or [] if isinstance(r, Mapping)]
        for idx, r in enumerate(rows, 1):
            lines.append(f"### PLAYER {idx} — {r.get('player') or r.get('name') or 'UNAVAILABLE'}")
            lines.append(
                f"Availability: {r.get('p_available', r.get('pavail', 'UNAVAILABLE'))}; "
                f"Pstart {r.get('p_start', 'UNAVAILABLE')}; xMins {r.get('xmins', 'UNAVAILABLE')}."
            )
            lines.append(
                f"Projection: 1GW {r.get('projection_1gw', 'UNAVAILABLE')}; "
                f"3GW {r.get('projection_3gw', 'UNAVAILABLE')}; 5GW {r.get('projection_5gw', 'UNAVAILABLE')}."
            )
            probabilities = dict(r.get("probabilities") or {})
            underlying = dict(r.get("underlying") or {})
            lines.append(
                "Probability: "
                f"Pgoal {_num(probabilities.get('p_goal'))}; "
                f"Passist {_num(probabilities.get('p_assist'))}; "
                f"Preturn {_num(probabilities.get('p_return'))}; "
                f"Phaul {_num(probabilities.get('p_haul'))}; "
                f"Pblank {_num(probabilities.get('p_blank'))}."
            )
            lines.append(
                "Underlying: "
                f"xG90 {_num(underlying.get('xg90'))}; "
                f"npxG90 {_num(underlying.get('npxg90'))}; "
                f"xA90 {_num(underlying.get('xa90'))}; "
                f"xGI90 {_num(underlying.get('xgi90'))}."
            )
            lines.append(
                "Role/Bayesian: "
                + _compact(r.get("role_detail") or r.get("tactical_role_label"))
                + " | Bayesian "
                + _compact(r.get("bayesian_state"))
            )
            lines.append(
                "Workload/rest + fixture/security: "
                + _compact(r.get("workload_context") or r.get("workload"))
                + " | "
                + _compact(r.get("fixture_detail") or r.get("injury_rotation_warning"))
            )
            lines.append(
                "Price context: "
                + _compact(r.get("price_optionality") or r.get("price_relevance"))
                + " | ML relevance: "
                + _compact(r.get("mini_league_relevance"))
            )

    elif section_id == "S16B":
        gw = payload.get("gw")
        lines.append("### S16B.1 — MATCH-BY-MATCH REVIEW")
        matches = [
            dict(row)
            for row in payload.get("match_by_match_review") or []
            if isinstance(row, Mapping)
        ]
        for index, match in enumerate(matches, start=1):
            lines.append(
                f"#### MATCH {index} — "
                + str(match.get("result") or f"fixture:{match.get('fixture_id')}")
            )
            formations = dict(match.get("formation_system") or {})
            coach = dict(match.get("coach_pattern") or {})
            lines.append(
                "Tactical setup: "
                f"venue={match.get('venue', 'UNAVAILABLE')} | "
                f"home shape={formations.get('home', 'UNAVAILABLE')} | "
                f"away shape={formations.get('away', 'UNAVAILABLE')} | "
                f"approach={coach.get('tactical_approach', 'UNAVAILABLE')} | "
                f"build-up={coach.get('build_up_pattern', 'UNAVAILABLE')} | "
                f"press/block={coach.get('press_block', 'UNAVAILABLE')} | "
                f"channels={coach.get('attacking_channels', 'UNAVAILABLE')} | "
                f"subs={coach.get('substitution_pattern', 'UNAVAILABLE')} | "
                f"adjustment={coach.get('major_tactical_adjustment', 'UNAVAILABLE')}"
            )
            our_players = [
                dict(row)
                for row in match.get("our_players") or []
                if isinstance(row, Mapping)
            ]
            lines.append("OUR15 review:")
            if not our_players:
                lines.append("- No OUR15 player in this fixture.")
            for player in our_players:
                read = dict(player.get("analytical_read") or {})
                lines.append(
                    "- "
                    f"{player.get('player')} | {player.get('starter_sub_unused')} | "
                    f"{player.get('minutes')}m | FPL {player.get('fpl_points')} | "
                    f"role {player.get('position_role')} | "
                    f"xG/xA/xGI {player.get('xg')}/{player.get('xa')}/{player.get('xgi')} | "
                    f"shots/SOT {player.get('shots')}/{player.get('shots_on_target')} | "
                    f"box {player.get('box_touches')} | KP/CC "
                    f"{player.get('key_passes')}/{player.get('chances_created')} | "
                    f"BC {player.get('big_chances')} | SP {player.get('set_pieces')} | "
                    f"PEN {player.get('penalties')} | DEF {player.get('defensive_contribution')} | "
                    f"sub {player.get('substitution_timing')} | "
                    f"role={read.get('role_change')} | minutes={read.get('minutes_change')} | "
                    f"underlying={read.get('underlying_change')} | "
                    f"P(start)={read.get('start_security')} | "
                    f"sustainability={read.get('sustainability')} | "
                    f"one-match-noise={read.get('one_match_noise')} | "
                    f"next={read.get('next_gw_implication')}"
                )
            candidates = [
                dict(row)
                for row in match.get("watch_candidates") or []
                if isinstance(row, Mapping)
            ]
            lines.append("Watch candidates:")
            if not candidates:
                lines.append("- No material post-match candidate from this fixture.")
            for candidate in candidates:
                lines.append(
                    "- "
                    f"{candidate.get('player')} | POST_MATCH_CANDIDATE | "
                    f"reason={candidate.get('evidence_reason')} | "
                    f"role={candidate.get('role_observation')} | "
                    f"minutes={candidate.get('minutes_evidence')} | "
                    f"underlying={_human_summary(candidate.get('underlying_observation'))}"
                )
            takeaway = dict(match.get("tactical_takeaways") or {})
            lines.append(
                "Tactical takeaway: "
                f"worked={takeaway.get('what_worked', 'UNAVAILABLE')} | "
                f"changed={takeaway.get('what_changed', 'UNAVAILABLE')} | "
                f"benefited={takeaway.get('who_benefited', 'UNAVAILABLE')} | "
                f"lost role/minutes={takeaway.get('who_lost_role_minutes', 'UNAVAILABLE')} | "
                f"sustainable/noisy={takeaway.get('sustainable_vs_noisy', 'UNAVAILABLE')} | "
                f"future opponent={takeaway.get('future_opponent_implication', 'UNAVAILABLE')}"
            )

        reassessment = dict(payload.get("after_gw_reassessment") or {})
        summary = dict(reassessment.get("summary") or {})
        lines.append("### S16B.2 — AFTER-GW REASSESSMENT")
        lines.append(
            "WHAT CHANGED: "
            f"OUR15 upgrades={summary.get('our15_upgrades', 0)} | "
            f"downgrades={summary.get('our15_downgrades', 0)} | "
            f"stable={summary.get('our15_stable', 0)} | "
            f"Watchlist NEW={summary.get('watchlist_new', 0)} | "
            f"↑={summary.get('watchlist_up', 0)} | "
            f"↓={summary.get('watchlist_down', 0)} | "
            f"OUT={summary.get('watchlist_out', 0)} | "
            f"ACTIONABLE={summary.get('actionable', 0)}"
        )
        lines.append("#### OUR15")
        for player in reassessment.get("owned15_review") or []:
            if not isinstance(player, Mapping):
                continue
            pre = dict(player.get("pre_gw") or {})
            post = dict(player.get("post_gw") or {})
            lines.append(
                "- "
                f"{player.get('player')} | {player.get('classification')} | "
                f"P(start) {pre.get('p_start')}→{post.get('p_start')} | "
                f"xMins {pre.get('xmins')}→{post.get('xmins')} | "
                f"role={player.get('role_change')} | minutes={player.get('minutes_change')} | "
                f"1GW {pre.get('projection_1gw')}→{post.get('projection_1gw')} | "
                f"3GW {pre.get('projection_3gw')}→{post.get('projection_3gw')} | "
                f"5GW {pre.get('projection_5gw')}→{post.get('projection_5gw')} | "
                f"uncertainty={post.get('uncertainty')} | "
                f"consequence={player.get('consequence')}"
            )
        lines.append("#### WATCHLIST / UNIVERSE")
        lines.append(
            "Full-universe denominator: "
            + str(payload.get("full_universe_denominator") or "UNAVAILABLE")
        )
        for row in reassessment.get("watchlist_delta") or []:
            if not isinstance(row, Mapping):
                continue
            lines.append(
                "- "
                f"{row.get('player')} | {row.get('state')} | "
                f"rank {row.get('previous_rank')}→{row.get('current_rank')} | "
                f"movement={row.get('movement_state')}"
            )
        candidates = [
            row
            for row in reassessment.get("new_watch_candidates") or []
            if isinstance(row, Mapping)
        ]
        if candidates:
            lines.append("Match scout → full-universe validation:")
            for row in candidates:
                lines.append(
                    "- "
                    f"fixture={row.get('fixture_id')} | {row.get('player')} | "
                    f"{row.get('evidence_reason')} | "
                    f"{row.get('full_universe_outcome')}"
                )
        lines.append("What changed for next-GW decision?")
        lines.append(
            "S16B supplies learning evidence only. ACT remains owned by the canonical "
            "S14/P1.7/Stage3 decision path."
        )
        excluded.extend((
            "gw",
            "fixtures_expected",
            "fixtures_reviewed",
            "unique_fixture_count",
            "duplicate_fixture_count",
            "match_by_match_review",
            "after_gw_reassessment",
            "full_universe_denominator",
            "our15",
            "material_universe_candidates",
            "full_universe_scan",
            "recency_weighting",
            "bayesian_update",
            "candidate_traceability",
            "fixture_ids_expected",
            "fixture_ids_reviewed",
            "raw_contextual_dynamics",
            "debug",
        ))


    elif section_id == "S17":
        status = dict(payload.get("engine_data_status") or {})
        source_health = dict(payload.get("source_health") or {})
        lineage = dict(payload.get("lineage") or {})
        binding = dict(payload.get("authoritative_binding") or {})

        official_state = str(source_health.get("official_fpl") or "UNAVAILABLE").upper()
        canonical_ok = (
            status.get("stage3_internal_pass") is True
            and int(status.get("projection_players") or 0) > 0
            and int(status.get("our15") or 0) == 15
        )
        mc_paths = int(status.get("mc_actual_paths") or 0)
        price_health = str(source_health.get("price_predictor") or "UNAVAILABLE").upper()
        price_freshness = str(
            source_health.get("price_predictor_freshness") or "UNAVAILABLE"
        ).upper()
        mini_health = str(source_health.get("mini_league") or "UNAVAILABLE").upper()
        weather_health = str(source_health.get("weather") or "UNAVAILABLE").upper()
        logical_slot = str(
            lineage.get("logical_slot")
            or binding.get("report_slot")
            or "UNAVAILABLE"
        )
        exact_binding = lineage.get("exact_occurrence_binding")
        if exact_binding is None:
            exact_binding = logical_slot != "UNAVAILABLE"

        price_status = (
            "🟢 Healthy; fresh snapshot"
            if price_health not in {"UNAVAILABLE", "FAILED", "ERROR"}
            and price_freshness == "FRESH"
            else "🟡 Healthy pipeline; snapshot stale"
            if price_health not in {"UNAVAILABLE", "FAILED", "ERROR"}
            and "STALE" in price_freshness
            else f"🟡 {price_health}; freshness {price_freshness}"
        )
        weather_status = (
            "🟢 Bound"
            if weather_health == "REPORT_TIME_BOUND"
            else "🟡 Pipeline available; outside reliable forecast horizon"
            if "OUTSIDE_RELIABLE_FORECAST_HORIZON" in weather_health
            else f"🟡 {weather_health}"
        )
        delivery_provenance = dict(payload.get("delivery_provenance") or {})
        rows = [
            (
                "Official factual plane",
                "🟢 Healthy" if official_state == "HEALTHY" else f"🟡 {official_state}",
            ),
            (
                "Canonical V12 computation",
                "🟢 Complete" if canonical_ok else "🟡 Degraded / incomplete",
            ),
            (
                "Optimizer / Monte Carlo",
                "🟢 MC500k PASS"
                if mc_paths >= 500000
                else f"🟡 MC {mc_paths} paths" if mc_paths > 0 else "🟡 Unavailable",
            ),
            ("Price data pipeline", price_status),
            (
                "Mini-league pipeline",
                "🟢 Complete" if mini_health == "FULL" else f"🟡 {mini_health}",
            ),
            ("Weather pipeline", weather_status),
            (
                "Exact-occurrence binding",
                "🟢 Verified" if exact_binding is True else "🔴 Unverified",
            ),
        ]
        if delivery_provenance:
            rows.extend(
                [
                    (
                        "Private serving / delivery",
                        str(delivery_provenance.get("private_delivery") or "🟡 Pending"),
                    ),
                    (
                        "Presentation QA",
                        str(delivery_provenance.get("presentation_qa") or "🟡 Pending"),
                    ),
                    (
                        "Privacy boundary",
                        str(delivery_provenance.get("privacy_boundary") or "🟡 Unverified"),
                    ),
                ]
            )
        lines.extend(_markdown_table(("Plane", "Status"), rows))

        stale_items = []
        if price_freshness != "FRESH":
            stale_items.append("price predictor snapshot")
        if "UNAVAILABLE" in weather_health:
            stale_items.append("weather pipeline")
        lines.append("Freshness")
        if stale_items:
            lines.append(
                "Decision-critical technical sources are within contract except: "
                + ", ".join(stale_items)
                + "."
            )
        else:
            lines.append(
                "Decision-critical technical sources represented here are within their current freshness contract."
            )

        serving_source = str(
            lineage.get("serving_source") or "canonical occurrence-bound report bundle"
        )
        substituted = lineage.get("substituted_slot")
        substituted_text = (
            "no" if substituted is False or substituted is None else "yes"
        )
        lines.append("Lineage")
        lines.append(
            f"Report mode DEEP; logical slot {logical_slot}; "
            f"exact occurrence binding {'verified' if exact_binding is True else 'unverified'}; "
            f"serving source {serving_source}; substituted slot: {substituted_text}."
        )
        runner = status.get("runner")
        if runner:
            lines.append(
                "Audit note: "
                f"runner={runner}; planning GW={status.get('planning_gw', 'UNAVAILABLE')}; "
                f"MC paths={mc_paths or 'UNAVAILABLE'}."
            )

    elif section_id == "S18":
        board = dict(payload.get("action_board") or {})
        axes = [dict(r) for r in board.get("axes") or [] if isinstance(r, Mapping)]
        by_axis = {str(r.get("axis") or "").upper(): r for r in axes}
        for display, keys in (
            ("TRANSFER", ("TRANSFER",)),
            ("XI", ("XI",)),
            ("CAPTAIN", ("CAPTAIN",)),
            ("PRICE", ("PRICE",)),
            ("FINANCE", ("FINANCE", "AUTH/FINANCE")),
            ("MAIN WATCH FLAGS", ("MAIN WATCH FLAGS", "WATCH", "NEWS")),
        ):
            row = next((by_axis[k] for k in keys if k in by_axis), {})
            lines.append(f"### {display}")
            if row:
                lines.append(
                    f"Now: {_compact(row.get('NOW'))}. Next: {_compact(row.get('NEXT'))}. "
                    f"Trigger: {_compact(row.get('TRIGGER TO ACT'))}. "
                    f"Latest safe point: {_compact(row.get('LATEST SAFE DECISION POINT'))}. "
                    f"Cost of waiting: {_compact(row.get('COST OF WAITING'))}. "
                    f"Abort/reversal: {_compact(row.get('ABORT / REVERSAL'))}."
                )
            else:
                fallback = payload.get(display) or payload.get(display.replace(" ", "_"))
                lines.append(_compact(fallback))
        lines.append("Best alternative: " + _compact(board.get("best_alternative") or payload.get("BEST ALTERNATIVE")))

    elif section_id == "S19":
        judgement = dict(payload.get("final_judgement") or {})
        xi = judgement.get("xi") or []
        bench_order = judgement.get("bench_order") or []
        final_cap = dict(judgement.get("final_captain") or {})
        vice = dict(judgement.get("vice") or {})
        lines.append(f"Transfer: {judgement.get('transfer_action') or 'UNAVAILABLE'}")
        lines.append(f"Route: {judgement.get('selected_route_id') or 'UNAVAILABLE'}")
        lines.append(
            f"XI: formation {judgement.get('formation') or 'UNAVAILABLE'}; "
            + (", ".join(_name(v) for v in xi) if isinstance(xi, Sequence) and not isinstance(xi, (str, bytes)) else _compact(xi))
        )
        lines.append(
            f"Bench: GK {_name(judgement.get('bench_gk'))}; "
            + (", ".join(f"{i}. {_name(v)}" for i, v in enumerate(bench_order, 1)) if isinstance(bench_order, Sequence) and not isinstance(bench_order, (str, bytes)) else _compact(bench_order))
        )
        lines.append(
            f"Captain: {final_cap.get('player') or final_cap.get('name') or 'UNAVAILABLE'} "
            f"({judgement.get('captain_state') or 'UNAVAILABLE'}); "
            f"Vice: {vice.get('player') or vice.get('name') or 'UNAVAILABLE'}."
        )
        lines.append(f"Chip: {_compact(judgement.get('chip'))}")
        lines.append(f"Mini-league posture: {judgement.get('mini_league_posture') or 'UNAVAILABLE'}")
        lines.append(f"Final action: {judgement.get('transfer_action') or 'UNAVAILABLE'}")
        lines.append(f"Trigger: {judgement.get('next_trigger') or 'UNAVAILABLE'}")
        lines.append(f"Verdict: {judgement.get('reconciliation_reason') or judgement.get('reversal_trigger') or 'UNAVAILABLE'}")

    return lines, tuple(excluded)

def _deep_identity_header_lines(
    report: Mapping[str, Any],
    sections: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Render reader-facing DEEP identity only, never decision or plumbing detail."""
    planning_gw = report.get("planning_gw")
    if planning_gw is None:
        for row in sections:
            if str(row.get("section_id") or "").upper() != "S01":
                continue
            content = row.get("content")
            payload = dict(content or {}) if isinstance(content, Mapping) else {}
            dashboard = dict(payload.get("decision_dashboard") or {})
            planning_gw = dashboard.get("PLANNING_GW", payload.get("planning_gw"))
            if planning_gw is not None:
                break
    if planning_gw is None:
        for row in sections:
            if str(row.get("section_id") or "").upper() != "S17":
                continue
            content = row.get("content")
            payload = dict(content or {}) if isinstance(content, Mapping) else {}
            planning_gw = dict(payload.get("engine_data_status") or {}).get("planning_gw")
            if planning_gw is not None:
                break

    logical_slot = str(report.get("report_slot") or "").strip()
    bound_slots: list[str] = []
    for row in sections:
        content = row.get("content")
        payload = dict(content or {}) if isinstance(content, Mapping) else {}
        binding = payload.get("authoritative_binding")
        if not isinstance(binding, Mapping):
            continue
        slot = str(binding.get("report_slot") or "").strip()
        if slot:
            bound_slots.append(slot)
    if not logical_slot and bound_slots:
        logical_slot = bound_slots[0]

    exact_occurrence = report.get("exact_occurrence")
    if exact_occurrence is None:
        s17_lineage: dict[str, Any] = {}
        for row in sections:
            if str(row.get("section_id") or "").upper() == "S17":
                content = row.get("content")
                payload = dict(content or {}) if isinstance(content, Mapping) else {}
                s17_lineage = dict(payload.get("lineage") or {})
                break
        if "exact_occurrence_binding" in s17_lineage:
            exact_occurrence = s17_lineage.get("exact_occurrence_binding") is True
        else:
            exact_occurrence = bool(
                logical_slot
                and bound_slots
                and all(slot == logical_slot for slot in bound_slots)
            )

    slot_display = logical_slot or "UNAVAILABLE"
    if logical_slot:
        try:
            dt = datetime.fromisoformat(logical_slot.replace("Z", "+00:00"))
            dt = dt.astimezone(ZoneInfo("Asia/Jakarta"))
            slot_display = dt.strftime("%d %b %Y, %H:%M WIB")
        except ValueError:
            slot_display = logical_slot

    visible_count = len(sections)
    s16b_due = report.get("s16b_due") is True or any(
        str(row.get("section_id") or "").upper() == "S16B"
        for row in sections
    )
    expected_count = 23 if s16b_due else 22
    all_complete = bool(sections) and all(
        str(row.get("state") or "").upper() == "COMPLETE"
        for row in sections
    )
    report_status = str(report.get("reader_report_status") or "").strip().upper()
    if report_status not in {"READY_FULL", "READY_DEGRADED"}:
        report_status = "READY_FULL" if all_complete else "READY_DEGRADED"
    badge = "🟢" if report_status == "READY_FULL" else "🟡"
    occurrence_text = "Exact occurrence" if exact_occurrence is True else "Occurrence binding unverified"

    planning_text = (
        f"GW{planning_gw}"
        if planning_gw not in (None, "", "UNAVAILABLE")
        and not str(planning_gw).upper().startswith("GW")
        else str(planning_gw or "UNAVAILABLE")
    )
    return [
        "FPL MASTER V12 — DEEP REPORT",
        f"Planning GW: {planning_text}",
        f"Logical report slot: {slot_display}",
        f"Report: {badge} {report_status} · {occurrence_text}",
        (
            f"Sections: {visible_count}/{expected_count} lifecycle-visible · "
            + ("S16B due" if s16b_due else "S16B not due")
        ),
    ]


def render_deep_text(report: Mapping[str, Any]) -> str:
    """Human-facing DEEP renderer with bounded Deadline/Final presentation overlay."""
    mode = str(report.get("report_mode") or "DEEP").strip().upper()
    deadline_mode = mode in {"DEADLINE", "FINAL"}
    if deadline_mode:
        from src.engines.v12_locked_mode_renderers import (
            deadline_header_lines,
            deadline_section_overlay_lines,
            render_gw_lock_package,
        )

    sections = [
        dict(row)
        for row in report.get("sections") or []
        if isinstance(row, Mapping)
    ]
    owned_ids = {
        int(item.get("element_id"))
        for section in sections
        if str(section.get("section_id") or "") == "S02"
        for item in (
            (section.get("content") or {}).get("rows") or []
            if isinstance(section.get("content"), Mapping)
            else []
        )
        if isinstance(item, Mapping)
        and item.get("element_id") is not None
    }
    owned_names = {
        int(item.get("element_id")): str(
            item.get("player")
            or item.get("name")
            or item.get("element_id")
        )
        for section in sections
        if str(section.get("section_id") or "") == "S02"
        for item in (
            (section.get("content") or {}).get("rows") or []
            if isinstance(section.get("content"), Mapping)
            else []
        )
        if isinstance(item, Mapping)
        and item.get("element_id") is not None
    }

    blocks: list[str] = []
    if deadline_mode:
        blocks.append("\n".join(deadline_header_lines(report)))
    elif mode == "DEEP":
        blocks.append("\n".join(_deep_identity_header_lines(report, sections)))
    for row in sections:
        label = str(row.get("label") or "")
        state = str(row.get("state") or "")
        section_id = str(row.get("section_id") or "")
        content = row.get("content")
        content_map = (
            dict(content or {})
            if isinstance(content, Mapping)
            else {}
        )
        if section_id == "S16B" and content_map.get("gw") is not None:
            label = f"POST-MATCH REVIEW GW{content_map.get('gw')}"
        lines = [
            _visible_section_heading(section_id, label),
            f"Status: {state}",
        ]
        reason = str(row.get("degradation_reason") or "").strip()
        if state != "COMPLETE" and reason:
            lines.append(f"Reason: {reason}")
        # Renderer consumes the bound payload verbatim. Binding metadata is
        # deliberately not synthesized here: missing binding must fail QA,
        # never be repaired by presentation code.
        binding = content_map.get("authoritative_binding")
        if isinstance(binding, Mapping):
            lines.append(
                "Authority: canonical bound evidence"
                if str(binding.get("status") or "").upper() == "BOUND"
                else "Authority: unavailable"
            )

        if deadline_mode and section_id == "GW_LOCK_PACKAGE":
            visible_lines = render_gw_lock_package(content_map)
            visible_excluded = tuple(content_map.keys())
        else:
            visible_lines, visible_excluded = (
                _render_deep_visible_contract_lines(
                    section_id=section_id,
                    content=content_map,
                    owned_ids=owned_ids,
                    owned_names=owned_names,
                )
            )
        lines.extend(visible_lines)
        if deadline_mode and section_id != "GW_LOCK_PACKAGE":
            lines.extend(deadline_section_overlay_lines(section_id, report))

        scout = [
            dict(item)
            for item in content_map.get(
                "post_match_match_by_match_scout"
            )
            or ()
            if isinstance(item, Mapping)
        ]
        if scout:
            lines.extend(_render_match_scout_lines(scout))

        math_stack = content_map.get(
            "mathematical_decision_stack"
        )
        if isinstance(math_stack, Mapping):
            lines.extend(_render_math_stack_lines(math_stack))

        if "PACKAGE OPTIMIZER" in label.upper():
            lines.extend(
                _render_package_frontier_lines(
                    content_map,
                    section_state=state,
                )
            )

        stagec = content_map.get("stagec_universe_intelligence")
        if section_id == "S04" and isinstance(stagec, Mapping):
            from src.engines.v12_stagec_reporting import (
                render_stagec_deep_lines,
            )

            lines.extend(render_stagec_deep_lines(stagec))

        generic = _render_generic_human_content(
            content_map,
            excluded_keys=(
                "post_match_match_by_match_scout",
                "mathematical_decision_stack",
                "package_search_proof",
                "search_proof",
                "package_universe_challengers",
                "universe_challengers",
                "package_routes",
                "routes",
                "frontier",
                "stagec_universe_intelligence",
                *visible_excluded,
            ),
        )
        if generic:
            lines.extend(generic)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def validate_human_facing_body(
    body: str,
    *,
    material_technical_failure: bool = False,
) -> list[str]:
    """Reject low-level orchestration narration from normal healthy reports."""
    if material_technical_failure:
        return []
    text = str(body or "")
    lower = text.lower()
    failures = [
        f"MACHINE_LANGUAGE={token}"
        for token in MACHINE_TERMS
        if token in lower
    ]
    if re.search(r"\b[0-9a-f]{40}\b", lower):
        failures.append("MACHINE_LANGUAGE=RAW_BRANCH_SHA")
    return failures


def compact_engine_data_status(
    *,
    v6_data: str,
    publication: str,
    universe: str,
    personal_squad_data: str,
    model_refresh: str,
    mc: str,
    icon: str,
    data_time: str,
) -> dict[str, str]:
    return {
        "V6 data": str(v6_data),
        "Publication": str(publication),
        "Universe": str(universe),
        "Personal squad data": str(personal_squad_data),
        "Model refresh": str(model_refresh),
        "MC": str(mc),
        "ICON+": str(icon),
        "Data time": str(data_time),
    }


def weather_report_time_evidence(
    *,
    venue: str | None,
    kickoff: str | None,
    weather: Mapping[str, Any] | None,
    lookup_accessible: bool,
    failure_reason: str | None = None,
    fixture: str | None = None,
) -> dict[str, Any]:
    """Normalize SIMPLE visible weather evidence without creating a weather model."""
    if weather:
        payload = dict(weather)
        impact = str(
            payload.get("fpl_impact")
            or payload.get("impact")
            or payload.get("impact_classification")
            or ""
        ).strip().upper()
        if impact not in {"NORMAL", "LOW", "MATERIAL"}:
            impact = "UNAVAILABLE"
        precipitation = payload.get(
            "precipitation_probability",
            payload.get(
                "precipitation_chance_pct",
                payload.get("precipitation_probability_pct", "UNAVAILABLE"),
            ),
        )
        wind = payload.get(
            "wind_kph",
            payload.get(
                "wind_kmh",
                payload.get("wind_speed_kmh", "UNAVAILABLE"),
            ),
        )
        evidence_timestamp = payload.get(
            "weather_evidence_timestamp",
            payload.get("evidence_timestamp", payload.get("checked_at", "UNAVAILABLE")),
        )
        impact_reason = payload.get("impact_reason", payload.get("fpl_impact_reason", "UNAVAILABLE"))
        visible_row = {
            "fixture": fixture or payload.get("fixture") or "UNAVAILABLE",
            "venue": venue or payload.get("venue") or "UNAVAILABLE",
            "kickoff": kickoff or payload.get("kickoff") or "UNAVAILABLE",
            "condition": payload.get("condition") or payload.get("weather_condition") or "UNAVAILABLE",
            "temperature_c": payload.get("temperature_c", "UNAVAILABLE"),
            "temperature": payload.get("temperature_c", "UNAVAILABLE"),
            "precipitation_probability": precipitation,
            "precipitation_chance_pct": precipitation,
            "wind_kph": wind,
            "wind_kmh": wind,
            "fpl_impact": impact,
            "impact_class": impact,
            "impact_reason": impact_reason,
            "evidence_timestamp": evidence_timestamp,
            "weather_evidence_timestamp": evidence_timestamp,
        }
        required = (
            "fixture",
            "venue",
            "kickoff",
            "condition",
            "temperature_c",
            "precipitation_probability",
            "wind_kph",
            "fpl_impact",
            "weather_evidence_timestamp",
        )
        missing = [
            key for key in required
            if visible_row.get(key) in {None, "", "UNAVAILABLE"}
        ]
        return {
            "state": "COMPLETE" if not missing else "PARTIAL",
            "venue": visible_row["venue"],
            "kickoff": visible_row["kickoff"],
            "weather": payload,
            "visible_row": visible_row,
            "missing_visible_fields": missing,
            "source_layer": "REPORT_TIME",
            "v6_weather_required": False,
            "new_weather_model_created": False,
            "weather_adjusted_xpts": False,
            "weather_mutates_p_start": False,
            "weather_mutates_xmins": False,
            "weather_mutates_p1_6_tactical_score": False,
            "weather_failure_isolated_to_weather": True,
            "weather_may_independently_create_action": False,
            "raw_provider_plumbing_visible": False,
        }
    reason = str(failure_reason or "").strip()
    if not reason:
        reason = (
            "report-time weather lookup unavailable"
            if lookup_accessible
            else "report-time weather access unavailable"
        )
    return {
        "state": "UNAVAILABLE",
        "venue": venue,
        "kickoff": kickoff,
        "weather": None,
        "visible_row": {
            "fixture": fixture or "UNAVAILABLE",
            "venue": venue or "UNAVAILABLE",
            "kickoff": kickoff or "UNAVAILABLE",
            "condition": "UNAVAILABLE",
            "temperature_c": "UNAVAILABLE",
            "temperature": "UNAVAILABLE",
            "precipitation_probability": "UNAVAILABLE",
            "precipitation_chance_pct": "UNAVAILABLE",
            "wind_kph": "UNAVAILABLE",
            "wind_kmh": "UNAVAILABLE",
            "fpl_impact": "UNAVAILABLE",
            "impact_class": "UNAVAILABLE",
            "impact_reason": reason,
            "evidence_timestamp": "UNAVAILABLE",
            "weather_evidence_timestamp": "UNAVAILABLE",
        },
        "source_layer": "REPORT_TIME",
        "v6_weather_required": False,
        "degradation_reason": reason,
        "new_weather_model_created": False,
        "weather_adjusted_xpts": False,
        "weather_mutates_p_start": False,
        "weather_mutates_xmins": False,
        "weather_mutates_p1_6_tactical_score": False,
        "weather_failure_isolated_to_weather": True,
        "weather_may_independently_create_action": False,
        "raw_provider_plumbing_visible": False,
    }

