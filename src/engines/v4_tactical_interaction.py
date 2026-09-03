from __future__ import annotations

from collections import defaultdict
from typing import Any


INTERACTION_CONTRACT = "V4_PLAYER_SYSTEM_FORMATION_OPPONENT_INTERACTION_V1"
EVIDENCE_GATED = "EVIDENCE_GATED"
VERIFIED = "VERIFIED"
MODEL_DERIVED = "MODEL_DERIVED"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return float(default)


def _bounded(value: Any, default: float = 0.0) -> float:
    return max(0.0, min(1.0, _f(value, default)))


def _mean(values: list[float], default: float = 0.0) -> float:
    return sum(values) / len(values) if values else float(default)


def _archetypes(position: str, role: str | None) -> list[str]:
    """Return non-exclusive archetypes from governed role vocabulary.

    This is intentionally player-name agnostic. It translates role evidence into
    reusable archetypes and never creates a numeric expected-points modifier.
    """
    pos = str(position or "").upper()
    text = str(role or "").lower().replace("-", "_").replace(" ", "_")
    out: list[str] = []
    rules = {
        "GK": [
            (("sweeper", "distributor", "ball_playing"), "goalkeeper_distributor"),
            (("shot", "stopper"), "shot_stopper"),
        ],
        "DEF": [
            (("overlap", "wing_back"), "overlapping_fullback"),
            (("invert",), "inverted_fullback"),
            (("progressive", "ball_playing"), "progressive_cb"),
            (("aerial",), "aerial_cb"),
            (("fullback", "wide_defender"), "fullback"),
            (("central_defender", "centre_back", "center_back"), "central_defender"),
        ],
        "MID": [
            (("deep", "controller", "holding"), "deep_controller"),
            (("box_to_box", "balanced_midfielder"), "box_to_box"),
            (("creator", "advanced_midfielder", "attacking_midfielder"), "advanced_creator"),
            (("wing", "wide"), "direct_winger"),
            (("inside",), "inside_forward"),
            (("runner", "shooter"), "runner_shooter"),
        ],
        "FWD": [
            (("target",), "target_forward"),
            (("transition", "runner"), "transition_forward"),
            (("complete",), "complete_forward"),
            (("second",), "second_striker"),
        ],
    }
    for terms, label in rules.get(pos, []):
        if any(term in text for term in terms):
            out.append(label)
    if text and not out:
        out.append(text)
    if not out:
        out.append({"GK": "goalkeeper", "DEF": "defender", "MID": "midfielder", "FWD": "forward"}.get(pos, "player"))
    return list(dict.fromkeys(out))


def _xmins_context(pred: dict) -> dict:
    fixtures = [row for row in (pred.get("fixtures") or [])[:5] if isinstance(row, dict)]
    confidences: list[float] = []
    starts: list[float] = []
    dnps: list[float] = []
    for fixture in fixtures:
        xm = fixture.get("xmins") or {}
        if xm.get("start_probability_confidence") is not None:
            confidences.append(_bounded(xm.get("start_probability_confidence")))
        if xm.get("start_probability") is not None:
            starts.append(_bounded(xm.get("start_probability")))
        if xm.get("dnp_probability") is not None:
            dnps.append(_bounded(xm.get("dnp_probability")))
    confidence = _mean(confidences, 0.5 if fixtures else 0.0)
    return {
        "confidence": round(confidence, 4),
        "uncertainty": round(1.0 - confidence, 4),
        "average_start_probability": round(_mean(starts, 0.0), 4) if starts else None,
        "average_dnp_probability": round(_mean(dnps, 0.0), 4) if dnps else None,
        "fixture_rows": len(fixtures),
        "evidence_state": VERIFIED if confidences else (MODEL_DERIVED if fixtures else EVIDENCE_GATED),
    }


def _understat_context(understat: dict, element: int) -> dict:
    row = ((understat or {}).get("tactical_matchups") or {}).get(str(int(element))) or {}
    player = ((understat or {}).get("player_evidence") or {}).get(str(int(element))) or {}
    mapping = player.get("mapping") or row.get("mapping") or {}
    state = str(row.get("state") or "INSUFFICIENT_EVIDENCE")
    confidence = _bounded(row.get("confidence"), 0.0)
    mapping_state = str(mapping.get("state") or "SOURCE_ABSENT_CURRENT_SEASON")
    source_absent = mapping_state == "SOURCE_ABSENT_CURRENT_SEASON"
    unresolved = mapping_state in {"UNRESOLVED", "IDENTITY_UNRESOLVED"}
    return {
        "state": state,
        "confidence": round(confidence, 4),
        "mapping_state": mapping_state,
        "source_absent": source_absent,
        "identity_unresolved": unresolved,
        "dimensions": row.get("dimensions") or {},
        "supporting_signals": row.get("supporting_signals") or [],
        "conflicting_signals": row.get("conflicting_signals") or [],
        "freshness": row.get("freshness") or ((understat or {}).get("source") or {}).get("freshness"),
        "evidence_state": VERIFIED if state != "INSUFFICIENT_EVIDENCE" and not unresolved else EVIDENCE_GATED,
    }


def _verified_system_row(team_system_evidence: dict | None, team_id: int) -> dict:
    raw = ((team_system_evidence or {}).get("teams") or {}).get(str(int(team_id))) or {}
    verified = raw.get("verified") is True and bool(raw.get("provenance"))
    if not verified:
        return {
            "evidence_state": EVIDENCE_GATED,
            "coach_system_confidence": 0.0,
            "formation_confidence": 0.0,
            "nominal_formation": None,
            "starting_shape": None,
            "in_possession_shape": None,
            "out_of_possession_shape": None,
            "recent_dominant_shape": None,
            "expected_fixture_shape": None,
            "coach_system": None,
            "provenance": None,
        }
    return {
        "evidence_state": VERIFIED,
        "coach_system_confidence": _bounded(raw.get("coach_system_confidence"), 0.7),
        "formation_confidence": _bounded(raw.get("formation_confidence"), 0.7),
        "nominal_formation": raw.get("nominal_formation"),
        "starting_shape": raw.get("starting_shape"),
        "in_possession_shape": raw.get("in_possession_shape"),
        "out_of_possession_shape": raw.get("out_of_possession_shape"),
        "recent_dominant_shape": raw.get("recent_dominant_shape"),
        "expected_fixture_shape": raw.get("expected_fixture_shape"),
        "coach_system": raw.get("coach_system") or {},
        "provenance": raw.get("provenance"),
    }


def _roster_event_context(roster_events: dict | None, element: int, team_id: int) -> dict:
    events = []
    by_player = (roster_events or {}).get("players") or {}
    by_team = (roster_events or {}).get("teams") or {}
    for row in by_player.get(str(int(element))) or []:
        if isinstance(row, dict) and row.get("verified") is True:
            events.append(row)
    for row in by_team.get(str(int(team_id))) or []:
        if isinstance(row, dict) and row.get("verified") is True:
            events.append(row)
    material_types = {
        "INCOMING_SIGNING", "OUTGOING_COMPETITOR", "RETURNING_INJURED_PLAYER",
        "SUSPENSION_RETURN", "MANAGER_CHANGE", "TACTICAL_SHIFT", "FORMATION_SHIFT",
        "RECENT_BENCHING", "ROLE_DISPLACEMENT", "SET_PIECE_HIERARCHY_CHANGE",
    }
    material = [row for row in events if str(row.get("type") or "").upper() in material_types]
    if not material:
        return {
            "evidence_state": EVIDENCE_GATED,
            "events": [],
            "roster_change_uncertainty": 0.0,
            "minutes_disruption_risk": 0.0,
            "role_disruption_risk": 0.0,
            "system_adaptation_risk": 0.0,
            "reason": "NO_VERIFIED_ROSTER_CHANGE_EVIDENCE",
        }
    severity = min(1.0, 0.25 + 0.15 * len(material))
    type_set = {str(row.get("type") or "").upper() for row in material}
    minutes = min(1.0, severity + (0.15 if type_set & {"INCOMING_SIGNING", "RETURNING_INJURED_PLAYER", "RECENT_BENCHING", "ROLE_DISPLACEMENT"} else 0.0))
    role = min(1.0, severity + (0.15 if type_set & {"MANAGER_CHANGE", "TACTICAL_SHIFT", "FORMATION_SHIFT", "ROLE_DISPLACEMENT"} else 0.0))
    adaptation = min(1.0, severity + (0.10 if type_set & {"INCOMING_SIGNING", "MANAGER_CHANGE", "TACTICAL_SHIFT", "FORMATION_SHIFT"} else 0.0))
    return {
        "evidence_state": VERIFIED,
        "events": material,
        "roster_change_uncertainty": round(severity, 4),
        "minutes_disruption_risk": round(minutes, 4),
        "role_disruption_risk": round(role, 4),
        "system_adaptation_risk": round(adaptation, 4),
        "reason": "VERIFIED_ROSTER_CHANGE_EVIDENCE",
    }


def build_tactical_interactions(
    predictions: dict,
    universe: dict,
    understat: dict | None = None,
    *,
    team_system_evidence: dict | None = None,
    roster_events: dict | None = None,
) -> dict:
    """Build traceable player x system x formation x opponent interaction evidence.

    Missing external shape/coach/roster evidence is never fabricated. The output is
    confidence/uncertainty evidence only and cannot directly mutate xPts or xMins.
    """
    pmap = {int(row.get("element")): row for row in predictions.get("players") or [] if row.get("element") is not None}
    umap = {int(row.get("element")): row for row in universe.get("players") or [] if row.get("element") is not None}
    rows: dict[str, dict] = {}
    states = defaultdict(int)
    for element in sorted(set(pmap) & set(umap)):
        pred = pmap[element]
        uni = umap[element]
        position = str(uni.get("position") or pred.get("position") or "")
        team_id = int(uni.get("team_id") or 0)
        role = (pred.get("priors") or {}).get("tactical_role")
        role_state = MODEL_DERIVED if role else EVIDENCE_GATED
        role_conf = _bounded((pred.get("priors") or {}).get("role_confidence"), 0.65 if role else 0.0)
        xmins = _xmins_context(pred)
        us = _understat_context(understat or {}, element)
        own_system = _verified_system_row(team_system_evidence, team_id)
        fixture0 = ((pred.get("fixtures") or [{}])[0]) or {}
        opponent_id = int(fixture0.get("opponent_id") or fixture0.get("opponent_team_id") or 0)
        opponent_system = _verified_system_row(team_system_evidence, opponent_id) if opponent_id else _verified_system_row(None, 0)
        roster = _roster_event_context(roster_events, element, team_id)

        confidence_dimensions = {
            "official_fact_confidence": 1.0,
            "xMins_confidence": xmins["confidence"],
            "projection_confidence": round(max(0.0, 1.0 - min(1.0, _f(pred.get("uncertainty"), 0.5))), 4),
            "Understat_confidence": us["confidence"],
            "player_archetype_confidence": round(role_conf, 4),
            "coach_system_confidence": round(_bounded(own_system.get("coach_system_confidence")), 4),
            "formation_confidence": round(_bounded(own_system.get("formation_confidence")), 4),
            "player_role_confidence": round(role_conf, 4),
            "opponent_shape_confidence": round(_bounded(opponent_system.get("formation_confidence")), 4),
            "price_confidence": None,
            "roster_change_confidence": 1.0 if roster["evidence_state"] == VERIFIED else None,
        }
        missing = [
            name for name in ("coach_system_confidence", "formation_confidence", "opponent_shape_confidence")
            if not _f(confidence_dimensions.get(name), 0.0)
        ]
        available = [
            _f(value) for key, value in confidence_dimensions.items()
            if key not in {"price_confidence", "roster_change_confidence"} and value is not None and _f(value) > 0.0
        ]
        evidence_conf = _mean(available, 0.0)
        missing_penalty = len(missing) / 3.0 if missing else 0.0
        tactical_uncertainty = min(1.0, 0.45 * (1.0 - evidence_conf) + 0.35 * missing_penalty + 0.20 * roster["roster_change_uncertainty"])
        state = VERIFIED if not missing and role_state != EVIDENCE_GATED and not us["identity_unresolved"] else "PARTIAL"
        states[state] += 1
        rows[str(element)] = {
            "element": element,
            "name": uni.get("name") or pred.get("name") or str(element),
            "position": position,
            "team_id": team_id,
            "player_archetypes": _archetypes(position, role),
            "actual_player_role": {
                "role": role,
                "evidence_state": role_state,
                "confidence": round(role_conf, 4),
                "official_fpl_position": position,
                "role_may_differ_from_official_position": True,
            },
            "coach_system": own_system,
            "formation": {
                "nominal_formation": own_system.get("nominal_formation"),
                "starting_shape": own_system.get("starting_shape"),
                "in_possession_shape": own_system.get("in_possession_shape"),
                "out_of_possession_shape": own_system.get("out_of_possession_shape"),
                "recent_dominant_shape": own_system.get("recent_dominant_shape"),
                "expected_fixture_shape": own_system.get("expected_fixture_shape"),
                "evidence_state": own_system.get("evidence_state"),
                "nominal_cannot_masquerade_as_in_possession": True,
            },
            "opponent_system": opponent_system,
            "understat_matchup": us,
            "xmins": xmins,
            "roster_change": roster,
            "confidence_dimensions": confidence_dimensions,
            "tactical_interaction": {
                "state": state,
                "evidence_confidence": round(evidence_conf, 4),
                "tactical_uncertainty": round(tactical_uncertainty, 4),
                "missing_dimensions": missing,
                "player_system_fit": "EVIDENCE_GATED" if own_system.get("evidence_state") != VERIFIED else "BOUNDED_CONTEXT_AVAILABLE",
                "coach_role_fit": "EVIDENCE_GATED" if own_system.get("evidence_state") != VERIFIED else "BOUNDED_CONTEXT_AVAILABLE",
                "formation_fit": "EVIDENCE_GATED" if own_system.get("evidence_state") != VERIFIED else "BOUNDED_CONTEXT_AVAILABLE",
                "actual_role_fit": "BOUNDED_CONTEXT_AVAILABLE" if role else EVIDENCE_GATED,
                "opponent_shape_fit": "EVIDENCE_GATED" if opponent_system.get("evidence_state") != VERIFIED else "BOUNDED_CONTEXT_AVAILABLE",
                "zone_matchup_fit": "EVIDENCE_GATED",
                "transition_fit": us.get("dimensions", {}).get("transition_environment", {}).get("state", "INSUFFICIENT_EVIDENCE"),
                "set_piece_fit": us.get("dimensions", {}).get("set_piece_environment", {}).get("state", "INSUFFICIENT_EVIDENCE"),
                "minutes_role_confidence": round(_mean([xmins["confidence"], role_conf], 0.0), 4),
                "tactical_upside": "ADVISORY_ONLY",
                "tactical_downside": "ADVISORY_ONLY",
                "role_volatility": round(max(1.0 - role_conf, roster["role_disruption_risk"]), 4),
                "evidence_freshness": us.get("freshness"),
            },
            "governance": {
                "direct_xpts_mutation": False,
                "direct_xmins_mutation": False,
                "arbitrary_tactical_bonus": False,
                "missing_evidence_is_explicit": True,
                "identity_source_absence_does_not_make_player_ineligible": True,
            },
        }

    complete = int(states.get(VERIFIED, 0))
    partial = int(states.get("PARTIAL", 0))
    total = len(rows)
    return {
        "schema_version": 1,
        "contract": INTERACTION_CONTRACT,
        "players": rows,
        "health": {
            "status": "PASS" if total and complete == total else "PARTIAL" if total else "UNAVAILABLE",
            "players": total,
            "complete": complete,
            "partial": partial,
            "formation_evidence_complete": bool(total and complete == total),
            "missing_external_shape_evidence_is_not_fabricated": True,
        },
        "governance": {
            "official_fpl_factual_authority": True,
            "understat_enrichment_only": True,
            "formation_dimensions_kept_distinct": True,
            "composite_archetypes_allowed": True,
            "direct_xpts_multiplier_forbidden": True,
            "direct_xmins_mutation_forbidden": True,
            "player_names_not_hardcoded": True,
        },
    }
