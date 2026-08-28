from __future__ import annotations

from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/intelligence/tactical_matchup.json"


def _by_id(payload: Any, kind: str) -> dict[int, dict[str, Any]]:
    if not isinstance(payload, (dict, list)):
        return {}
    rows: Any = payload
    if isinstance(payload, dict):
        rows = payload.get(kind) or payload.get("profiles") or payload
    out: dict[int, dict[str, Any]] = {}
    if isinstance(rows, dict):
        for key, value in rows.items():
            if not isinstance(value, dict):
                continue
            try:
                out[int(key)] = value
            except (TypeError, ValueError):
                continue
    elif isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw = row.get("team_id") if kind == "teams" else row.get("element")
            raw = raw if raw is not None else row.get("id")
            try:
                out[int(raw)] = row
            except (TypeError, ValueError):
                continue
    return out


def _recent(payload: Any) -> dict[int, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        return {}
    rows = payload.get("teams") or payload.get("recent") or payload
    if not isinstance(rows, dict):
        return {}
    out: dict[int, list[dict[str, Any]]] = {}
    for key, value in rows.items():
        try:
            team_id = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(value, list):
            out[team_id] = [row for row in value if isinstance(row, dict)]
        elif isinstance(value, dict):
            games = value.get("games") or value.get("gws") or []
            out[team_id] = [row for row in games if isinstance(row, dict)]
    return out


def _current_fixture(player: dict[str, Any], planning_gw: int) -> dict[str, Any]:
    for row in player.get("xpts_by_gw") or []:
        if int(row.get("gw") or -1) != planning_gw:
            continue
        fixtures = [x for x in row.get("fixtures") or [] if isinstance(x, dict)]
        if fixtures:
            return fixtures[0]
    return {}


def _role_from_projection(player: dict[str, Any]) -> dict[str, Any]:
    role = player.get("role") if isinstance(player.get("role"), dict) else {}
    if not role:
        return {}
    return {
        "role": role.get("role") or role.get("tactical_role"),
        "set_piece_share": role.get("set_piece_share"),
        "penalty_share": role.get("penalty_share"),
        "return_routes": role.get("return_routes") or [],
        "progression_route": role.get("progression_route"),
        "source": role.get("set_piece_source") or "v5_role_intelligence",
    }


def _highlights(opponent: dict[str, Any], role: dict[str, Any], recent_rows: list[dict[str, Any]], limit: int) -> list[str]:
    result: list[str] = []
    vulnerabilities = opponent.get("vulnerabilities") or []
    routes = role.get("return_routes") or []
    if isinstance(vulnerabilities, str):
        vulnerabilities = [vulnerabilities]
    if isinstance(routes, str):
        routes = [routes]
    overlap = [
        str(route) for route in routes
        if any(str(route).lower() in str(v).lower() or str(v).lower() in str(route).lower() for v in vulnerabilities)
    ]
    if overlap:
        result.append(f"role matchup mendukung: {', '.join(overlap[:2])}")
    if opponent.get("pressing") and role.get("progression_route"):
        result.append(f"lawan {opponent.get('pressing')}; route pemain {role.get('progression_route')}")
    if recent_rows:
        latest = sorted(recent_rows, key=lambda x: int(x.get("gw") or 0), reverse=True)[0]
        note = latest.get("notes") or latest.get("chance_concession_zones") or latest.get("pressing_pattern")
        if note:
            result.append(f"recent-GW lawan: {note}")
    return result[:max(1, limit)]


def attach_tactical_matchups(
    predictions: dict[str, Any],
    planning_gw: int,
    tactical_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach V5 tactical matchup evidence without mutating projection points.

    The engine accepts structured report-time/source-enrichment context when supplied.
    Missing tactical context fails neutral. Existing V5 role intelligence is reused as
    player-role evidence, but coach/style/formation claims are never inferred without
    source evidence.
    """
    cfg = load_json_config(CONFIG)
    context = tactical_context if isinstance(tactical_context, dict) else {}
    teams = _by_id(context.get("team_profiles"), "teams")
    explicit_roles = _by_id(context.get("player_roles"), "players")
    recent = _recent(context.get("recent_form"))
    minimum = int((cfg.get("materiality") or {}).get("minimum_evidence_items") or 2)
    window = int(cfg.get("recent_gw_window") or 5)
    limit = int((cfg.get("materiality") or {}).get("maximum_report_highlights_per_player") or 2)
    ready = partial = unavailable = 0

    for player in predictions.get("players") or []:
        try:
            element = int(player.get("element") or -1)
            team_id = int(player.get("team_id") or -1)
        except (TypeError, ValueError):
            continue
        fixture = _current_fixture(player, planning_gw)
        try:
            opponent_id = int(fixture.get("opponent") or -1)
        except (TypeError, ValueError):
            opponent_id = -1
        own = teams.get(team_id) or {}
        opponent = teams.get(opponent_id) or {}
        role = explicit_roles.get(element) or _role_from_projection(player)
        recent_rows = sorted(recent.get(opponent_id) or [], key=lambda x: int(x.get("gw") or 0), reverse=True)[:window]
        tactical_evidence = sum(bool(x) for x in (own, opponent, recent_rows))
        evidence_count = tactical_evidence + int(bool(role))
        if opponent_id > 0 and tactical_evidence >= minimum:
            status = "READY"
            ready += 1
        elif opponent_id > 0 and evidence_count:
            status = "PARTIAL"
            partial += 1
        else:
            status = "UNAVAILABLE"
            unavailable += 1
        player["tactical_matchup"] = {
            "status": status,
            "planning_gw": planning_gw,
            "opponent_team_id": opponent_id if opponent_id > 0 else None,
            "coach": own.get("coach"),
            "own_shape": own.get("base_formation"),
            "opponent_coach": opponent.get("coach"),
            "opponent_shape": opponent.get("base_formation"),
            "player_role": role.get("role"),
            "evidence_count": evidence_count,
            "recent_gw_evidence_count": len(recent_rows),
            "highlights": _highlights(opponent, role, recent_rows, limit) if tactical_evidence else [],
            "advisory_only": True,
            "xpts_mutated": False,
        }

    predictions["tactical_matchup_summary"] = {
        "model": cfg.get("model_id"),
        "planning_gw": planning_gw,
        "ready": ready,
        "partial": partial,
        "unavailable": unavailable,
        "context_supplied": bool(context),
        "advisory_only": True,
        "xpts_mutation": False,
    }
    predictions.setdefault("governance", {})["tactical_matchup"] = {
        "background_analysis_required_for_owned_and_watchlist": True,
        "report_only_material_highlights": True,
        "never_directly_mutate_xpts": True,
        "allow_selection_tiebreaker_only_when_gap_is_close": True,
        "missing_evidence_is_never_fabricated": True,
    }
    return predictions
