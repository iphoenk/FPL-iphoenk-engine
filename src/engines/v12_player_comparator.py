from __future__ import annotations

"""V12 generic player-vs-player comparator orchestration.

This module is deliberately NOT a model owner. It consumes already-governed
P1.1 minutes, P1.3/P1.3B event/xPts, P1.6 tactical-role, P1.2 transfer
economics/search, P1.7 structural consequence and P1.8 mini-league evidence.
It performs only transparent arithmetic aggregation/comparison needed to expose
pairwise evidence across 1/2/3/5 GW horizons.
"""

from datetime import datetime
import math
from typing import Any, Mapping, Sequence

from src.engines.canonical_decision_methodology import ACTION_STATES


MINUTES_OWNER = "V12_PLAYER_MINUTES"
EVENTS_OWNER = "V12_PLAYER_EVENTS"
TACTICAL_OWNER = "V12_TACTICAL_ROLE"
HORIZONS = (1, 2, 3, 5)
COMPETITION_STATES = frozenset({"CONFIRMED", "TBD", "UNVERIFIED"})
TACTICAL_CLASSES = frozenset(
    {"OBSERVED_ROLE", "INFERRED_ROLE", "FPL_POSITION_ONLY", "UNKNOWN"}
)


class ComparatorContractError(ValueError):
    pass


def _finite(value: Any, label: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ComparatorContractError(f"{label} must be numeric") from exc
    if not math.isfinite(out):
        raise ComparatorContractError(f"{label} must be finite")
    return out


def _prob(value: Any, label: str) -> float:
    out = _finite(value, label)
    if not 0.0 <= out <= 1.0:
        raise ComparatorContractError(f"{label} must be within [0,1]")
    return out


def _positive_int(value: Any, label: str) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise ComparatorContractError(f"{label} must be a positive integer") from exc
    if out <= 0:
        raise ComparatorContractError(f"{label} must be a positive integer")
    return out


def _timestamp(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ComparatorContractError("comparison_timestamp is required")
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ComparatorContractError("comparison_timestamp must be ISO-8601") from exc
    return text


def _owner(mapping: Mapping[str, Any], expected: str, label: str) -> None:
    actual = str(mapping.get("model_owner") or "").strip().upper()
    if actual != expected:
        raise ComparatorContractError(
            f"{label} must consume existing {expected} output, got {actual or 'UNPROVEN'}"
        )


def _unavailable(reason: str) -> dict[str, Any]:
    return {"value": "UNAVAILABLE", "reason": reason}

def _nested(mapping: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = mapping.get(key)
    return value if isinstance(value, Mapping) else {}


def _normalize_minutes(minutes: Mapping[str, Any]) -> dict[str, Any]:
    """Read-only adapter for native P1.1 output plus legacy compact fixtures."""
    _owner(minutes, MINUTES_OWNER, "fixture.minutes")
    conditional = _nested(minutes, "conditional_probabilities")
    derived = _nested(minutes, "derived_probabilities")
    distribution = _nested(minutes, "xmins_distribution")
    native = bool(conditional or derived or distribution or "start_probability" in minutes)

    p_available_raw = conditional.get("p_available")
    if p_available_raw is None:
        p_available_raw = minutes.get("p_available")
    p_start_raw = derived.get("p_start")
    if p_start_raw is None:
        p_start_raw = minutes.get("start_probability")
    if p_start_raw is None:
        p_start_raw = minutes.get("p_start")
    p_dnp_raw = derived.get("p_dnp")
    if p_dnp_raw is None:
        p_dnp_raw = minutes.get("dnp_probability")
    if p_dnp_raw is None:
        p_dnp_raw = minutes.get("p_dnp")
    p_cameo_raw = derived.get("p_cameo")
    if p_cameo_raw is None:
        p_cameo_raw = minutes.get("cameo_probability")
    if p_cameo_raw is None:
        p_cameo_raw = minutes.get("p_cameo")
    p_late_raw = derived.get("p_late_cameo")
    if p_late_raw is None:
        p_late_raw = minutes.get("late_cameo_probability")
    if p_late_raw is None:
        p_late_raw = minutes.get("p_late_cameo")
    xmins_raw = distribution.get("mean")
    if xmins_raw is None:
        xmins_raw = minutes.get("expected_minutes")
    if xmins_raw is None:
        xmins_raw = minutes.get("xmins")

    p_available = _prob(p_available_raw, "p_available")
    p_start = _prob(p_start_raw, "p_start")
    p_dnp = _prob(p_dnp_raw, "p_dnp")
    p_cameo = None if p_cameo_raw is None else _prob(p_cameo_raw, "p_cameo")
    p_late = None if p_late_raw is None else _prob(p_late_raw, "p_late_cameo")
    xmins = _finite(xmins_raw, "xmins")
    if xmins < 0.0:
        raise ComparatorContractError("xmins must be >= 0")

    return {
        "model_owner": MINUTES_OWNER,
        "source_schema": "NATIVE_P1_1" if native else "COMPACT_COMPAT",
        "p_available": p_available,
        "p_start": p_start,
        "p_dnp": p_dnp,
        "p_cameo": p_cameo,
        "p_late_cameo": p_late,
        "xmins": xmins,
        "xmins_distribution": minutes.get("xmins_distribution"),
        "provenance": (
            minutes.get("provenance")
            or minutes.get("evidence_lineage")
            or minutes.get("model_evidence")
        ),
        "raw_owner_output": minutes,
    }


def _quantile_items(point_distribution: Mapping[str, Any]) -> list[tuple[float, Any, str]]:
    quantiles = point_distribution.get("quantiles")
    if not isinstance(quantiles, Mapping):
        return []
    out: list[tuple[float, Any, str]] = []
    for key, value in quantiles.items():
        token = str(key).strip().upper()
        if not token.startswith("P"):
            continue
        try:
            percentile = float(token[1:])
            numeric = _finite(value, f"point_distribution.quantiles.{key}")
        except (ValueError, ComparatorContractError):
            continue
        out.append((percentile, numeric, str(key)))
    return sorted(out, key=lambda row: row[0])


def _normalize_events(events: Mapping[str, Any]) -> dict[str, Any]:
    """Read-only adapter for native P1.3/P1.3B output plus compact fixtures."""
    _owner(events, EVENTS_OWNER, "fixture.events")
    aggregate = _nested(events, "aggregate")
    event_probabilities = _nested(events, "event_probabilities")
    point_distribution_raw = events.get("point_distribution")
    point_distribution = (
        point_distribution_raw if isinstance(point_distribution_raw, Mapping) else {}
    )
    native = bool(aggregate or event_probabilities or point_distribution)

    xpts_raw = aggregate.get("expected_fpl_points")
    if xpts_raw is None and events.get("mean") is not None:
        # P1.3 native top-level mean is the same fixture expected-points moment.
        xpts_raw = events.get("mean")
    if xpts_raw is None:
        xpts_raw = events.get("xpts")
    xpts = _finite(xpts_raw, "xpts")

    p_return_raw = event_probabilities.get("p_attacking_return")
    if p_return_raw is None:
        p_return_raw = events.get("p_return")
    p_blank_raw = point_distribution.get("p_fpl_blank")
    if p_blank_raw is None:
        p_blank_raw = events.get("p_blank")
    p_return = None if p_return_raw is None else _prob(p_return_raw, "p_return")
    p_blank = None if p_blank_raw is None else _prob(p_blank_raw, "p_blank")

    uncertainty_raw = aggregate.get("points_std")
    if uncertainty_raw is None:
        uncertainty_raw = events.get("std")
    if uncertainty_raw is None:
        uncertainty_raw = events.get("uncertainty")
    uncertainty = (
        "UNAVAILABLE"
        if uncertainty_raw is None
        else _finite(uncertainty_raw, "points_std")
    )

    quantiles = _quantile_items(point_distribution)
    if quantiles:
        floor = {
            "value": quantiles[0][1],
            "quantile": quantiles[0][2],
            "source": "P1.3B_NATIVE_POINT_DISTRIBUTION",
        }
        ceiling = {
            "value": quantiles[-1][1],
            "quantile": quantiles[-1][2],
            "source": "P1.3B_NATIVE_POINT_DISTRIBUTION",
        }
    elif native:
        floor = _unavailable("P1.3B native point distribution exposes no governed lower quantile")
        ceiling = _unavailable("P1.3B native point distribution exposes no governed upper quantile")
    else:
        floor = events.get("floor", "UNAVAILABLE")
        ceiling = events.get("ceiling", "UNAVAILABLE")

    return {
        "model_owner": EVENTS_OWNER,
        "source_schema": "NATIVE_P1_3" if native else "COMPACT_COMPAT",
        "xpts": xpts,
        "p_return": p_return,
        "p_blank": p_blank,
        "minutes_threshold_probabilities": (
            dict(events.get("minutes_threshold_probabilities") or {})
            if isinstance(events.get("minutes_threshold_probabilities"), Mapping)
            else {}
        ),
        "point_distribution": point_distribution_raw,
        "floor": floor,
        "ceiling": ceiling,
        "uncertainty": uncertainty,
        "provenance": (
            events.get("provenance")
            or events.get("model_evidence")
            or point_distribution.get("provenance")
        ),
        "raw_owner_output": events,
    }


def _normalize_tactical(
    tactical: Mapping[str, Any],
    profile: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Bind native P1.6 score output separately from optional tactical narrative."""
    _owner(tactical, TACTICAL_OWNER, "fixture.tactical")
    native_fields = (
        "canonical_tactical_role_score",
        "scoring_channel_vector",
        "scoring_channel_diversity",
        "tactical_role_fit",
        "role_resilience",
        "fixture_suppression_raw",
        "fixture_suppression_effective",
        "feature_evidence",
    )
    native = any(key in tactical for key in native_fields)
    model_output = {key: tactical.get(key) for key in native_fields if key in tactical}
    if "score_decomposition" in tactical:
        model_output["score_decomposition"] = tactical.get("score_decomposition")

    profile_row = dict(profile or {})
    # Legacy compact fixtures put explanatory profile fields beside the score owner.
    # Native owner output never requires those non-owner fields.
    if not profile_row and not native:
        profile_row = dict(tactical)

    evidence_class = str(profile_row.get("evidence_class") or "UNKNOWN").strip().upper()
    if evidence_class not in TACTICAL_CLASSES:
        raise ComparatorContractError("fixture tactical evidence class is invalid")

    return {
        "model_owner": TACTICAL_OWNER,
        "source_schema": "NATIVE_P1_6" if native else "COMPACT_COMPAT",
        "model_output": model_output if native else dict(tactical),
        "profile_context": profile_row or None,
        "evidence_class": evidence_class,
        "role_summary": profile_row.get("role_summary") or "UNAVAILABLE",
        "route_to_points": profile_row.get("route_to_points") or "UNAVAILABLE",
        "provenance": {
            "model": tactical.get("provenance") or tactical.get("model_evidence"),
            "profile": profile_row.get("provenance") if profile_row else None,
        },
    }



def _p60(
    minutes: Mapping[str, Any],
    events_bound: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Carry governed P(60+) only; never create a second minutes model."""
    supported = minutes.get("p_60_plus_supported") is True
    value = minutes.get("p_60_plus")
    provenance = str(minutes.get("p_60_plus_provenance") or "").strip()
    if supported and value is not None and provenance:
        return {
            "value": round(_prob(value, "p_60_plus"), 8),
            "reason": None,
            "provenance": provenance,
        }

    event_evidence = dict((events_bound or {}).get("minutes_threshold_probabilities") or {})
    event_value = event_evidence.get("p_60_plus")
    event_source = str(event_evidence.get("source") or "").strip()
    if event_value is not None and event_source:
        return {
            "value": round(_prob(event_value, "p_60_plus"), 8),
            "reason": None,
            "provenance": event_source,
        }

    if supported and (value is None or not provenance):
        return _unavailable("P1.1 P(60+) support flag lacks value/provenance")
    return _unavailable(
        str(
            minutes.get("p_60_plus_reason")
            or "No governed P(60+) evidence exposed by P1.1/P1.3"
        )
    )


def _validate_competition_schedule(
    rows: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows or ():
        if not isinstance(row, Mapping):
            raise ComparatorContractError("competition_schedule row must be a mapping")
        status = str(row.get("status") or "").strip().upper()
        if status not in COMPETITION_STATES:
            raise ComparatorContractError(
                "competition schedule status must be CONFIRMED/TBD/UNVERIFIED"
            )
        opponent = row.get("opponent")
        if status == "TBD" and opponent not in (None, "", "TBD"):
            raise ComparatorContractError("TBD competition fixture cannot invent an opponent")
        out.append(
            {
                "competition": row.get("competition") or "UNAVAILABLE",
                "date": row.get("date"),
                "opponent": "TBD" if status == "TBD" else opponent,
                "status": status,
                "location": row.get("location"),
                "travel_context": row.get("travel_context"),
                "actual_minutes": row.get("actual_minutes"),
                "started": row.get("started"),
                "benched": row.get("benched"),
                "substitution": row.get("substitution"),
                "extra_time": row.get("extra_time"),
                "days_rest": row.get("days_rest"),
                "provenance": row.get("provenance"),
            }
        )
    return out


def _fixture_row(row: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise ComparatorContractError("fixture evidence must be a mapping")
    gw = _positive_int(row.get("gw"), "fixture.gw")
    minutes = row.get("minutes")
    events = row.get("events")
    tactical = row.get("tactical")
    tactical_profile = row.get("tactical_profile") or row.get("tactical_profile_context")
    if not isinstance(minutes, Mapping):
        raise ComparatorContractError("fixture.minutes P1.1 output is required")
    if not isinstance(events, Mapping):
        raise ComparatorContractError("fixture.events P1.3 output is required")
    if not isinstance(tactical, Mapping):
        raise ComparatorContractError("fixture.tactical P1.6 output is required")
    if tactical_profile is not None and not isinstance(tactical_profile, Mapping):
        raise ComparatorContractError("fixture tactical profile must be a mapping when supplied")

    minutes_bound = _normalize_minutes(minutes)
    events_bound = _normalize_events(events)
    tactical_bound = _normalize_tactical(tactical, tactical_profile)

    profile = tactical_bound.get("profile_context") or {}

    def profile_value(name: str) -> Any:
        return profile.get(name) if profile.get(name) is not None else "UNAVAILABLE"

    return {
        "gw": gw,
        "opponent": row.get("opponent") or "UNAVAILABLE",
        "home_away": row.get("home_away") or "UNAVAILABLE",
        "venue": row.get("venue") or "UNAVAILABLE",
        "xpts": round(events_bound["xpts"], 8),
        "xmins": round(minutes_bound["xmins"], 8),
        "p_available": round(minutes_bound["p_available"], 8),
        "p_start": round(minutes_bound["p_start"], 8),
        "p_60_plus": _p60(minutes, events_bound),
        "p_dnp": round(minutes_bound["p_dnp"], 8),
        "p_cameo": (
            None
            if minutes_bound["p_cameo"] is None
            else round(minutes_bound["p_cameo"], 8)
        ),
        "p_late_cameo": (
            None
            if minutes_bound["p_late_cameo"] is None
            else round(minutes_bound["p_late_cameo"], 8)
        ),
        "p_return": events_bound["p_return"],
        "p_blank": events_bound["p_blank"],
        "point_distribution": events_bound["point_distribution"],
        "floor": events_bound["floor"],
        "ceiling": events_bound["ceiling"],
        "uncertainty": events_bound["uncertainty"],
        "tactical_evidence_class": tactical_bound["evidence_class"],
        "canonical_tactical_role_score": tactical_bound["model_output"].get(
            "canonical_tactical_role_score"
        ),
        "p1_6_model_output": tactical_bound["model_output"],
        "tactical_profile_context": tactical_bound["profile_context"],
        "role_summary": tactical_bound["role_summary"],
        "route_to_points": tactical_bound["route_to_points"],
        "coach": profile_value("coach"),
        "base_formation": profile_value("base_formation"),
        "formation_variants": profile_value("formation_variants"),
        "build_up": profile_value("build_up"),
        "pressing": profile_value("pressing"),
        "defensive_line": profile_value("defensive_line"),
        "width": profile_value("width"),
        "transition": profile_value("transition"),
        "opponent_strengths": profile_value("opponent_strengths"),
        "opponent_vulnerabilities": profile_value("opponent_vulnerabilities"),
        "relevant_channel": profile_value("relevant_channel"),
        "set_piece_aerial_context": profile_value("set_piece_aerial_context"),
        "set_piece_penalty_role": profile_value("set_piece_penalty_role"),
        "rest_congestion": row.get("rest_congestion") or "UNAVAILABLE",
        "midweek_competition_context": row.get("midweek_competition_context") or "UNAVAILABLE",
        "fixture_confidence": row.get("fixture_confidence") or "UNAVAILABLE",
        "data_quality": row.get("data_quality") or "UNAVAILABLE",
        "owner_schema_binding": {
            "minutes": minutes_bound["source_schema"],
            "events": events_bound["source_schema"],
            "tactical": tactical_bound["source_schema"],
            "normalization": "READ_ONLY_DETERMINISTIC_NON_AUTHORITATIVE",
        },
        "provenance": {
            "minutes": minutes_bound["provenance"],
            "events": events_bound["provenance"],
            "tactical_model": tactical_bound["provenance"]["model"],
            "tactical_profile": tactical_bound["provenance"]["profile"],
            "fixture": row.get("provenance"),
        },
    }


def _player_bundle(player: Mapping[str, Any], *, planning_gw: int) -> dict[str, Any]:
    if not isinstance(player, Mapping):
        raise ComparatorContractError("player bundle must be a mapping")
    element = _positive_int(player.get("element_id"), "element_id")
    position = str(player.get("position") or "").strip().upper()
    if position not in {"GK", "DEF", "MID", "FWD"}:
        raise ComparatorContractError("position must be GK/DEF/MID/FWD")
    fixtures = [_fixture_row(row) for row in (player.get("fixtures") or [])]
    max_gw = planning_gw + 4
    fixtures = [row for row in fixtures if planning_gw <= row["gw"] <= max_gw]
    fixtures.sort(key=lambda row: (row["gw"], str(row.get("opponent") or "")))
    return {
        "element_id": element,
        "name": player.get("name") or f"element:{element}",
        "position": position,
        "club_id": player.get("club_id"),
        "fixtures": fixtures,
        "football_components": dict(player.get("football_components") or {}),
        "role_sustainability": player.get("role_sustainability") or "UNAVAILABLE",
        "horizon_distributions": dict(player.get("horizon_distributions") or {}),
        "competition_schedule": _validate_competition_schedule(
            player.get("competition_schedule")
        ),
        "price": player.get("price"),
        "sell_value": player.get("sell_value"),
        "provenance": player.get("provenance"),
    }


def _fixtures_by_gw(
    player: Mapping[str, Any], planning_gw: int
) -> dict[int, list[dict[str, Any]]]:
    mapping = {gw: [] for gw in range(planning_gw, planning_gw + 5)}
    for row in player.get("fixtures") or []:
        mapping.setdefault(int(row["gw"]), []).append(dict(row))
    return mapping


def _by_gw(player: Mapping[str, Any], planning_gw: int) -> dict[str, dict[int, Any]]:
    grouped = _fixtures_by_gw(player, planning_gw)
    xpts: dict[int, float] = {}
    xmins: dict[int, float] = {}
    p_start: dict[int, list[float]] = {}
    p60: dict[int, list[dict[str, Any]]] = {}
    p_dnp: dict[int, list[float]] = {}
    for gw, rows in grouped.items():
        xpts[gw] = round(sum(float(row["xpts"]) for row in rows), 8)
        xmins[gw] = round(sum(float(row["xmins"]) for row in rows), 8)
        p_start[gw] = [float(row["p_start"]) for row in rows]
        p60[gw] = [dict(row["p_60_plus"]) for row in rows]
        p_dnp[gw] = [float(row["p_dnp"]) for row in rows]
    return {
        "xpts_by_gw": xpts,
        "xmins_by_gw": xmins,
        "p_start_by_gw": p_start,
        "p_60_plus_by_gw": p60,
        "p_dnp_by_gw": p_dnp,
    }


def _horizon(player: Mapping[str, Any], planning_gw: int, width: int) -> dict[str, Any]:
    end = planning_gw + width - 1
    rows = [
        row
        for row in player.get("fixtures") or []
        if planning_gw <= int(row["gw"]) <= end
    ]
    distribution_key = f"{width}GW"
    existing_distribution = dict(
        (player.get("horizon_distributions") or {}).get(distribution_key) or {}
    )
    return {
        "horizon": distribution_key,
        "projected_points": round(sum(float(row["xpts"]) for row in rows), 8),
        "expected_minutes": round(sum(float(row["xmins"]) for row in rows), 8),
        "expected_starts_over_horizon": round(
            sum(float(row["p_start"]) for row in rows), 8
        ),
        "fixture_count": len(rows),
        "floor_downside": existing_distribution.get("floor", "UNAVAILABLE"),
        "ceiling_upside": existing_distribution.get("ceiling", "UNAVAILABLE"),
        "uncertainty": existing_distribution.get("uncertainty", "UNAVAILABLE"),
        "confidence": existing_distribution.get("confidence", "UNAVAILABLE"),
        "distribution_provenance": existing_distribution.get("provenance"),
        "cumulative_start_probability": None,
    }


def _validate_transfer_economics(
    economics: Mapping[str, Any] | None,
    *,
    active_chip: str | None,
) -> dict[str, Any]:
    if not economics:
        return {
            "status": "UNAVAILABLE",
            "reason": "canonical transfer economics not supplied",
        }
    row = dict(economics)
    if str(row.get("decision_chain_stage") or "").upper() != "TRANSFER_ECONOMICS":
        raise ComparatorContractError(
            "transfer_economics must be existing canonical P1.2B output"
        )
    if str(active_chip or "").upper() == "WILDCARD":
        hit = row.get("hit_points")
        if hit not in (None, 0, 0.0):
            raise ComparatorContractError(
                "active Wildcard comparator economics cannot add an irrelevant hit cost"
            )
    return row


def _pair_fixture_surface(
    player_out: Mapping[str, Any],
    player_in: Mapping[str, Any],
    planning_gw: int,
) -> list[dict[str, Any]]:
    out_map = _fixtures_by_gw(player_out, planning_gw)
    in_map = _fixtures_by_gw(player_in, planning_gw)
    return [
        {
            "gw": gw,
            "player_out": out_map.get(gw, []),
            "player_in": in_map.get(gw, []),
        }
        for gw in range(planning_gw, planning_gw + 5)
    ]


def _raw_gain(
    out_horizons: Mapping[int, Mapping[str, Any]],
    in_horizons: Mapping[int, Mapping[str, Any]],
    width: int,
) -> float:
    return round(
        float(in_horizons[width]["projected_points"])
        - float(out_horizons[width]["projected_points"]),
        8,
    )


def _comparison(
    *,
    player_out: Mapping[str, Any],
    player_in: Mapping[str, Any],
    comparison_timestamp: str,
    planning_gw: int,
    transfer_economics: Mapping[str, Any] | None,
    affordability: Mapping[str, Any] | None,
    structural_impact: Mapping[str, Any] | None,
    robustness: Mapping[str, Any] | None,
    expected_regret: Any,
    information_value_of_waiting: Any,
    mini_league_overlay: Mapping[str, Any] | None,
    gate0: Mapping[str, Any] | None,
    active_chip: str | None,
    football_label: str,
    operational_action: str,
    decision_reasons: Sequence[str] | None,
    decision_risks: Sequence[str] | None,
    reversal_triggers: Sequence[str] | None,
) -> dict[str, Any]:
    if player_out["element_id"] == player_in["element_id"]:
        raise ComparatorContractError("owned and challenger IDs must differ")
    if player_out["position"] != player_in["position"]:
        raise ComparatorContractError("direct FPL slot comparator requires same position")

    action = str(operational_action or "").strip().upper()
    if action not in ACTION_STATES:
        raise ComparatorContractError("operational_action must be WAIT/PREPARE/ACT")

    gate = dict(gate0 or {})
    gate_status = str(gate.get("status") or "UNAVAILABLE").upper()
    if gate_status not in {"PASS", "FAIL", "UNAVAILABLE"}:
        raise ComparatorContractError("Gate0 status must be PASS/FAIL/UNAVAILABLE")
    if gate_status == "FAIL" and action == "ACT":
        raise ComparatorContractError("Gate0-failing route cannot have operational_action=ACT")

    overlay = dict(mini_league_overlay or {})
    if overlay and overlay.get("applied_after_football_optimal_baseline") is not True:
        raise ComparatorContractError(
            "mini-league overlay must be downstream of football baseline"
        )

    out_by_gw = _by_gw(player_out, planning_gw)
    in_by_gw = _by_gw(player_in, planning_gw)
    out_h = {width: _horizon(player_out, planning_gw, width) for width in HORIZONS}
    in_h = {width: _horizon(player_in, planning_gw, width) for width in HORIZONS}
    economics = _validate_transfer_economics(
        transfer_economics,
        active_chip=active_chip,
    )
    raw_gains = {width: _raw_gain(out_h, in_h, width) for width in HORIZONS}
    fixture_surface = _pair_fixture_surface(player_out, player_in, planning_gw)

    return {
        "player_out": {
            "element_id": player_out["element_id"],
            "name": player_out["name"],
            "position": player_out["position"],
            "club_id": player_out.get("club_id"),
            "price": player_out.get("price"),
            "sell_value": player_out.get("sell_value"),
        },
        "player_in": {
            "element_id": player_in["element_id"],
            "name": player_in["name"],
            "position": player_in["position"],
            "club_id": player_in.get("club_id"),
            "price": player_in.get("price"),
        },
        "comparison_timestamp": comparison_timestamp,
        "planning_gw": planning_gw,
        "fixture_by_fixture": fixture_surface,
        "xpts_by_gw": {
            "out": out_by_gw["xpts_by_gw"],
            "in": in_by_gw["xpts_by_gw"],
        },
        "xmins_by_gw": {
            "out": out_by_gw["xmins_by_gw"],
            "in": in_by_gw["xmins_by_gw"],
        },
        "p_start_by_gw": {
            "out": out_by_gw["p_start_by_gw"],
            "in": in_by_gw["p_start_by_gw"],
        },
        "p_60_plus_by_gw": {
            "out": out_by_gw["p_60_plus_by_gw"],
            "in": in_by_gw["p_60_plus_by_gw"],
        },
        "p_dnp_by_gw": {
            "out": out_by_gw["p_dnp_by_gw"],
            "in": in_by_gw["p_dnp_by_gw"],
        },
        "horizon_1gw": {"out": out_h[1], "in": in_h[1]},
        "horizon_2gw": {"out": out_h[2], "in": in_h[2]},
        "horizon_3gw": {"out": out_h[3], "in": in_h[3]},
        "horizon_5gw": {"out": out_h[5], "in": in_h[5]},
        "tactical_matchup_by_gw": [
            {
                "gw": row["gw"],
                "out": [
                    {
                        "tactical_evidence_class": item["tactical_evidence_class"],
                        "role_summary": item["role_summary"],
                        "route_to_points": item["route_to_points"],
                    }
                    for item in row["player_out"]
                ],
                "in": [
                    {
                        "tactical_evidence_class": item["tactical_evidence_class"],
                        "role_summary": item["role_summary"],
                        "route_to_points": item["route_to_points"],
                    }
                    for item in row["player_in"]
                ],
            }
            for row in fixture_surface
        ],
        "rest_congestion_by_gw": [
            {
                "gw": row["gw"],
                "out": [item["rest_congestion"] for item in row["player_out"]],
                "in": [item["rest_congestion"] for item in row["player_in"]],
            }
            for row in fixture_surface
        ],
        "competition_schedule": {
            "out": list(player_out.get("competition_schedule") or []),
            "in": list(player_in.get("competition_schedule") or []),
            "direct_xpts_penalty_applied": False,
        },
        "role_sustainability": {
            "out": player_out.get("role_sustainability"),
            "in": player_in.get("role_sustainability"),
        },
        "raw_gain_1gw": raw_gains[1],
        "raw_gain_2gw": raw_gains[2],
        "raw_gain_3gw": raw_gains[3],
        "raw_gain_5gw": raw_gains[5],
        "transfer_economics": economics,
        "affordability": dict(affordability or {"status": "UNAVAILABLE"}),
        "structural_impact": dict(structural_impact or {}),
        "robustness": dict(robustness or {}),
        "expected_regret": expected_regret,
        "information_value_of_waiting": information_value_of_waiting,
        "mini_league_overlay": overlay or None,
        "confidence": {
            "out": [
                row["fixture_confidence"] for row in player_out.get("fixtures") or []
            ],
            "in": [
                row["fixture_confidence"] for row in player_in.get("fixtures") or []
            ],
        },
        "football_label": str(football_label or "CHALLENGER").strip().upper(),
        "operational_action": action,
        "decision_reasons": [str(value) for value in (decision_reasons or ())],
        "decision_risks": [str(value) for value in (decision_risks or ())],
        "reversal_triggers": [str(value) for value in (reversal_triggers or ())],
        "data_quality": {
            "out": [row["data_quality"] for row in player_out.get("fixtures") or []],
            "in": [row["data_quality"] for row in player_in.get("fixtures") or []],
        },
        "provenance": {
            "out": player_out.get("provenance"),
            "in": player_in.get("provenance"),
        },
        "gate0": gate,
        "diagnostic_evidence_only": True,
        "decision_authority": False,
        "ranking_authority": False,
        "hidden_weighted_horizon_aggregate": False,
        "competitive_load_rewrites_xpts": False,
        "duplicate_xpts_model": False,
        "duplicate_xmins_model": False,
        "duplicate_tactical_scorer": False,
    }


def compare_player_to_candidates(
    *,
    player_out: Mapping[str, Any],
    challengers: Sequence[Mapping[str, Any]],
    comparison_timestamp: str,
    planning_gw: int,
    candidate_context: Mapping[int | str, Mapping[str, Any]] | None = None,
    active_chip: str | None = None,
) -> dict[str, Any]:
    """Compare one owned player with candidates without creating a ranking.

    candidate_context carries already-computed legality/economics/robustness
    evidence keyed by challenger element ID. Challenger order is preserved.
    """
    timestamp = _timestamp(comparison_timestamp)
    gw = _positive_int(planning_gw, "planning_gw")
    owned = _player_bundle(player_out, planning_gw=gw)
    if not challengers:
        raise ComparatorContractError("at least one challenger is required")
    contexts = dict(candidate_context or {})
    comparisons: list[dict[str, Any]] = []

    for raw in challengers:
        candidate = _player_bundle(raw, planning_gw=gw)
        context = dict(
            contexts.get(candidate["element_id"])
            or contexts.get(str(candidate["element_id"]))
            or {}
        )
        comparisons.append(
            _comparison(
                player_out=owned,
                player_in=candidate,
                comparison_timestamp=timestamp,
                planning_gw=gw,
                transfer_economics=context.get("transfer_economics"),
                affordability=context.get("affordability"),
                structural_impact=context.get("structural_impact"),
                robustness=context.get("robustness"),
                expected_regret=context.get("expected_regret"),
                information_value_of_waiting=context.get(
                    "information_value_of_waiting"
                ),
                mini_league_overlay=context.get("mini_league_overlay"),
                gate0=context.get("gate0"),
                active_chip=active_chip,
                football_label=str(context.get("football_label") or "CHALLENGER"),
                operational_action=str(context.get("operational_action") or "WAIT"),
                decision_reasons=context.get("decision_reasons"),
                decision_risks=context.get("decision_risks"),
                reversal_triggers=context.get("reversal_triggers"),
            )
        )

    return {
        "contract": "V12_GENERIC_PLAYER_COMPARATOR_ORCHESTRATION_V1",
        "player_out": {
            "element_id": owned["element_id"],
            "name": owned["name"],
            "position": owned["position"],
        },
        "comparison_timestamp": timestamp,
        "planning_gw": gw,
        "comparisons": comparisons,
        "candidate_order_is_input_order_not_ranking": True,
        "diagnostic_evidence_only": True,
        "decision_authority": False,
        "ranking_authority": False,
        "reused_model_owners": {
            "minutes": MINUTES_OWNER,
            "events": EVENTS_OWNER,
            "tactical": TACTICAL_OWNER,
        },
    }
