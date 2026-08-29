from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from typing import Any

from src.utils import DATA, ROOT, iso_now, read_json

CONFIG_PATH = ROOT / "config" / "intelligence" / "tactical_matchup.json"
ROUTE_LABELS = {
    "box_pressure": "tekanan di kotak",
    "shot_volume": "volume tembakan",
    "chance_creation": "kreasi peluang",
    "final_third_progression": "progresi final third",
    "wide_delivery": "delivery dari area lebar",
    "set_piece_activity": "aktivitas bola mati",
    "transition_threat": "ancaman transisi",
    "penalty_route": "rute penalti",
}
CONFIDENCE_RANK = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _artifact(name: str) -> dict[str, Any]:
    configured = ((load_config().get("input_artifacts") or {}).get(name) or "").strip()
    if not configured:
        return {}
    path = DATA / configured.removeprefix("data/")
    if not path.exists():
        return {}
    payload = read_json(path, {})
    return payload if isinstance(payload, dict) else {}


def _team_map(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    rows = payload.get("teams") or payload.get("profiles") or []
    out: dict[int, dict[str, Any]] = {}
    if isinstance(rows, dict):
        for key, value in rows.items():
            try:
                team_id = int(key)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                out[team_id] = value
        return out
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        try:
            team_id = int(row.get("team_id") or row.get("id"))
        except (TypeError, ValueError):
            continue
        out[team_id] = row
    return out


def _player_map(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    rows = payload.get("players") or payload.get("profiles") or []
    out: dict[int, dict[str, Any]] = {}
    if isinstance(rows, dict):
        for key, value in rows.items():
            try:
                element = int(key)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                out[element] = value
        return out
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        try:
            element = int(row.get("element") or row.get("id"))
        except (TypeError, ValueError):
            continue
        out[element] = row
    return out


def _recent_by_team(payload: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    rows = payload.get("teams") or payload.get("recent") or payload
    out: dict[int, list[dict[str, Any]]] = {}
    if isinstance(rows, dict):
        for key, value in rows.items():
            try:
                team_id = int(key)
            except (TypeError, ValueError):
                continue
            if isinstance(value, list):
                out[team_id] = [x for x in value if isinstance(x, dict)]
            elif isinstance(value, dict):
                games = value.get("games") or value.get("gws") or []
                out[team_id] = [x for x in games if isinstance(x, dict)]
    return out


def _current_fixture(player: dict[str, Any], planning_gw: int) -> dict[str, Any]:
    for row in player.get("xpts_by_gw") or []:
        if int(row.get("gw") or -1) != planning_gw:
            continue
        fixtures = [x for x in row.get("fixtures") or [] if isinstance(x, dict)]
        if fixtures:
            return fixtures[0]
    return {}


def _rich_opponent_context(opponent: dict[str, Any]) -> bool:
    for key in ("coach", "pressing", "build_up", "defensive_line", "width", "transition", "set_piece_profile"):
        if opponent.get(key):
            return True
    return bool(opponent.get("vulnerabilities") or opponent.get("strengths") or opponent.get("observed_style_proxies"))


def _evidence_confidence(opponent: dict[str, Any], role: dict[str, Any], recent: list[dict[str, Any]]) -> str:
    values = [
        str((opponent.get("evidence") or {}).get("confidence") or "NONE").upper(),
        str(role.get("confidence") or "NONE").upper(),
    ]
    if recent:
        values.append(str(recent[0].get("confidence") or "NONE").upper())
    valid = [value for value in values if value in CONFIDENCE_RANK and value != "NONE"]
    if not valid:
        return "NONE"
    return min(valid, key=lambda value: CONFIDENCE_RANK[value])


def _material_highlights(opponent: dict[str, Any], recent: list[dict[str, Any]], role: dict[str, Any]) -> list[str]:
    highlights: list[str] = []
    opp_vuln = opponent.get("vulnerabilities") or []
    return_routes = role.get("return_routes") or []
    if isinstance(opp_vuln, str):
        opp_vuln = [opp_vuln]
    if isinstance(return_routes, str):
        return_routes = [return_routes]
    overlap = [str(v) for v in return_routes if str(v) in {str(x) for x in opp_vuln}]
    if overlap:
        labels = [ROUTE_LABELS.get(value, value) for value in overlap[:2]]
        highlights.append("rute pemain bertemu area lawan yang baru tertekan: " + ", ".join(labels))
    if opponent.get("pressing") and role.get("progression_route"):
        highlights.append(f"lawan {opponent.get('pressing')}; route pemain {role.get('progression_route')}")
    if recent:
        latest = recent[0]
        concession_zones = latest.get("chance_concession_zones") or []
        if concession_zones:
            highlights.append("zona tembakan yang baru dikonsesikan lawan: " + ", ".join(str(x) for x in concession_zones[:2]))
        elif latest.get("notes"):
            highlights.append(f"recent lawan: {latest.get('notes')}")
    limit = int((load_config().get("materiality") or {}).get("maximum_report_highlights_per_player") or 2)
    return highlights[: max(1, limit)]


def _role_evidence_label(role: dict[str, Any]) -> str:
    evidence = role.get("evidence") or {}
    evidence_class = str(evidence.get("class") or "")
    if role.get("role") and evidence_class == "OBSERVED_ADVANCED_ROLE_PROFILE":
        return "OBSERVED_ROLE"
    if role.get("role"):
        return "INFERRED_ROLE"
    if role.get("position"):
        return "FPL_POSITION_ONLY"
    return "UNKNOWN"


def _evidence_state(value: Any, *, partial: bool = False) -> str:
    if value not in {None, "", [], {}}:
        return "PARTIAL" if partial else "AVAILABLE"
    return "UNAVAILABLE"


def _system_formation_fit(own: dict[str, Any], role: dict[str, Any]) -> dict[str, Any]:
    role_label = _role_evidence_label(role)
    shape = own.get("base_formation")
    shape_evidence = (own.get("evidence") or {}).get("class")
    if role_label in {"OBSERVED_ROLE", "INFERRED_ROLE"} and shape:
        status = "PARTIAL"
    else:
        status = "UNAVAILABLE"
    missing = []
    if not own.get("coach"):
        missing.append("coach_system")
    if not shape:
        missing.append("recent_xi_shape")
    missing.extend(["reliable_true_lineup_position", "heatmap_position", "role_change_history", "competition_specific_role", "structural_injury_role_effect"])
    return {
        "status": status,
        "role_evidence_label": role_label,
        "observed_or_inferred_role": role.get("role"),
        "fpl_position": role.get("position"),
        "fpl_position_shape_proxy": shape,
        "shape_proxy_evidence": shape_evidence,
        "true_tactical_formation": None,
        "fit_score": None,
        "available_inputs": {
            "observed_role_events": role_label == "OBSERVED_ROLE",
            "inferred_role": role_label == "INFERRED_ROLE",
            "fpl_position": bool(role.get("position")),
            "recent_fpl_position_shape": bool(shape),
            "coach_system": bool(own.get("coach")),
        },
        "missing_inputs": missing,
        "governance": {
            "fpl_position_shape_is_not_true_tactical_formation": True,
            "no_fit_score_without_reliable_system_and_role_evidence": True,
            "missing_role_or_system_evidence_is_not_inferred": True,
            "advisory_only": True,
        },
    }


def _dimension_matrix(opponent: dict[str, Any], recent_rows: list[dict[str, Any]], fixture: dict[str, Any]) -> dict[str, str]:
    vulnerabilities = opponent.get("vulnerabilities") or []
    strengths = opponent.get("strengths") or []
    style = opponent.get("observed_style_proxies") or []
    return {
        "opponent_coach": _evidence_state(opponent.get("coach")),
        "formation_or_variants": _evidence_state(opponent.get("base_formation") or opponent.get("formation_variants"), partial=True),
        "build_up": _evidence_state(opponent.get("build_up")),
        "press_height_intensity_triggers": _evidence_state(opponent.get("pressing")),
        "mid_low_block": "UNAVAILABLE",
        "defensive_line": _evidence_state(opponent.get("defensive_line")),
        "wide_half_space_protection": _evidence_state(opponent.get("width")),
        "fullback_wingback_positioning": "UNAVAILABLE",
        "transition_defense": _evidence_state(opponent.get("transition")),
        "counter_profile": _evidence_state("transition_threat" in style, partial=True) if style else "UNAVAILABLE",
        "set_pieces": _evidence_state(opponent.get("set_piece_profile") or ("set_piece_activity" in style), partial=True) if (opponent.get("set_piece_profile") or style) else "UNAVAILABLE",
        "aerial_profile": "UNAVAILABLE",
        "central_wide_vulnerability": _evidence_state(vulnerabilities, partial=True),
        "box_protection": _evidence_state("box_pressure" in vulnerabilities or "shot_volume" in vulnerabilities, partial=True) if vulnerabilities else "UNAVAILABLE",
        "second_balls": "UNAVAILABLE",
        "gk_distribution_shot_stopping": "UNAVAILABLE",
        "expected_possession_game_state": "UNAVAILABLE",
        "venue": _evidence_state(fixture.get("venue") or fixture.get("is_home") if fixture else None),
        "recent_tactical_adjustments_2_5": _evidence_state(recent_rows, partial=True),
        "structural_injuries_suspensions": "UNAVAILABLE",
        "observed_strengths": _evidence_state(strengths, partial=True),
    }


def _edge_risk_label(opponent: dict[str, Any], role: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    routes = {str(x) for x in (role.get("return_routes") or [])}
    vulnerabilities = {str(x) for x in (opponent.get("vulnerabilities") or [])}
    strengths = {str(x) for x in (opponent.get("strengths") or [])}
    edge = sorted(routes & vulnerabilities)
    risk = sorted(routes & strengths)
    if edge and risk:
        label = "MIXED"
    elif edge:
        label = "POSITIVE_EDGE"
    elif risk:
        label = "TACTICAL_RISK"
    elif routes and (vulnerabilities or strengths):
        label = "NEUTRAL_OBSERVED"
    else:
        label = "INSUFFICIENT_EVIDENCE"
    return label, edge, risk


def attach_tactical_matchups(projections: dict[str, Any], planning_gw: int) -> dict[str, Any]:
    """Attach governed tactical evidence without directly mutating xPts or legality."""
    cfg = load_config()
    team_profiles = _team_map(_artifact("team_profiles"))
    recent = _recent_by_team(_artifact("recent_form"))
    player_roles = _player_map(_artifact("player_roles"))
    generated_at = iso_now()

    ready = partial = unavailable = 0
    role_labels: Counter[str] = Counter()
    confidence_counts: Counter[str] = Counter()
    for player in projections.get("players") or []:
        try:
            team_id = int(player.get("team_id") or -1)
            element = int(player.get("element") or -1)
        except (TypeError, ValueError):
            continue
        fixture = _current_fixture(player, planning_gw)
        opponent_id = int(fixture.get("opponent") or -1) if fixture else -1
        own = team_profiles.get(team_id) or {}
        opponent = team_profiles.get(opponent_id) or {}
        role = player_roles.get(element) or {}
        recent_rows = list(recent.get(opponent_id) or [])
        recent_rows = sorted(recent_rows, key=lambda x: int(x.get("gw") or 0), reverse=True)[: int(cfg.get("recent_gw_window") or 5)]
        evidence_count = sum(bool(x) for x in (own, opponent, role, recent_rows))
        minimum = int((cfg.get("materiality") or {}).get("minimum_evidence_items") or 2)
        rich_context = _rich_opponent_context(opponent)
        assessed_role = bool(role.get("role"))
        observed_recent = bool(recent_rows)
        confidence = _evidence_confidence(opponent, role, recent_rows)
        if evidence_count >= minimum and opponent_id > 0 and rich_context and assessed_role and observed_recent:
            status = "READY"
            ready += 1
        elif evidence_count > 0 and opponent_id > 0:
            status = "PARTIAL"
            partial += 1
        else:
            status = "UNAVAILABLE"
            unavailable += 1
        confidence_counts[confidence] += 1
        role_label = _role_evidence_label(role)
        role_labels[role_label] += 1
        tactical_label, edge, risk = _edge_risk_label(opponent, role)
        dimensions = _dimension_matrix(opponent, recent_rows, fixture)
        player["tactical_matchup"] = {
            "status": status,
            "tactical_matchup_label": tactical_label,
            "tactical_edge": edge,
            "tactical_risk": risk,
            "tactical_confidence": confidence,
            "evidence_confidence": confidence,
            "evidence_timestamp": generated_at,
            "provenance": {
                "team_profile": (own.get("evidence") or {}).get("source"),
                "opponent_profile": (opponent.get("evidence") or {}).get("source"),
                "player_role": (role.get("evidence") or {}).get("source"),
                "recent_form_contract": "RECENT_TACTICAL_FORM_V1" if recent_rows else None,
            },
            "planning_gw": planning_gw,
            "opponent_team_id": opponent_id if opponent_id > 0 else None,
            "coach": own.get("coach"),
            "own_shape": own.get("base_formation"),
            "own_shape_evidence": ((own.get("evidence") or {}).get("class")),
            "opponent_coach": opponent.get("coach"),
            "opponent_shape": opponent.get("base_formation"),
            "opponent_shape_evidence": ((opponent.get("evidence") or {}).get("class")),
            "opponent_strengths": opponent.get("strengths") or [],
            "opponent_vulnerabilities": opponent.get("vulnerabilities") or [],
            "opponent_observed_style_proxies": opponent.get("observed_style_proxies") or [],
            "player_role": role.get("role"),
            "player_role_evidence_label": role_label,
            "player_role_confidence": role.get("confidence"),
            "player_return_routes": role.get("return_routes") or [],
            "system_formation_fit": _system_formation_fit(own, role),
            "evidence_dimensions": dimensions,
            "evidence_dimension_counts": dict(Counter(dimensions.values())),
            "evidence_count": evidence_count,
            "recent_gw_evidence_count": len(recent_rows),
            "rich_opponent_context": rich_context,
            "highlights": _material_highlights(opponent, recent_rows, role) if status != "UNAVAILABLE" else [],
            "advisory_only": True,
            "xpts_mutated": False,
            "xmins_mutated": False,
            "policy": "background-analysis; report only material highlights",
        }

    projections["tactical_matchup_summary"] = {
        "model": cfg.get("model_id"),
        "planning_gw": planning_gw,
        "generated_at": generated_at,
        "players": len(projections.get("players") or []),
        "ready": ready,
        "partial": partial,
        "unavailable": unavailable,
        "role_evidence_labels": dict(role_labels),
        "evidence_confidence": dict(confidence_counts),
        "advisory_only": True,
        "xpts_mutation": False,
        "xmins_mutation": False,
        "required_dimension_matrix_attached_per_player": True,
        "system_formation_fit_truthful_labels": ["OBSERVED_ROLE", "INFERRED_ROLE", "FPL_POSITION_ONLY", "UNKNOWN"],
        "ready_requires_observed_rich_opponent_context_role_and_recent_pattern": True,
        "verified_coach_style_is_optional_and_never_inferred": True,
        "close_xpts_gap": _f((cfg.get("materiality") or {}).get("close_xpts_gap"), 0.35),
    }
    projections.setdefault("governance", {})["tactical_matchup"] = {
        "background_analysis_required_for_owned_and_watchlist": True,
        "report_only_material_highlights": True,
        "never_directly_mutate_xpts": True,
        "never_directly_mutate_xmins": True,
        "allow_selection_tiebreaker_only_when_gap_is_close": True,
        "missing_evidence_is_never_fabricated": True,
        "observed_fpl_position_shape_alone_is_partial_not_ready": True,
        "fpl_position_shape_is_never_true_tactical_formation": True,
        "observed_event_proxies_are_not_claimed_as_true_pressing_or_build_up": True,
        "deep_tactical_dimensions_are_explicit_available_partial_or_unavailable": True,
    }
    return projections