from __future__ import annotations

from typing import Any

from src.utils import CONFIG, DATA, read_json

REGISTRY = CONFIG / "tactical_matchup_registry.json"


def _cfg() -> dict[str, Any]:
    payload = read_json(REGISTRY, {})
    return payload if isinstance(payload, dict) else {}


def _artifact(name: str) -> dict[str, Any]:
    path = ((_cfg().get("input_artifacts") or {}).get(name) or "").strip()
    if not path:
        return {}
    payload = read_json(DATA / path.removeprefix("data/"), {})
    return payload if isinstance(payload, dict) else {}


def _dict_by_id(payload: dict[str, Any], *keys: str) -> dict[int, dict[str, Any]]:
    rows: Any = payload
    for key in keys:
        if isinstance(rows, dict) and key in rows:
            rows = rows[key]
            break
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
            raw = row.get("team_id") or row.get("element") or row.get("id")
            try:
                out[int(raw)] = row
            except (TypeError, ValueError):
                continue
    return out


def _recent(payload: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    rows = payload.get("teams") or payload.get("recent") or payload
    out: dict[int, list[dict[str, Any]]] = {}
    if not isinstance(rows, dict):
        return out
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


def _fixture(row: dict[str, Any], planning_gw: int) -> dict[str, Any]:
    fixtures = [x for x in row.get("fixtures") or [] if isinstance(x, dict)]
    for item in fixtures:
        event = item.get("event") or item.get("gw")
        if event is None or int(event) == planning_gw:
            return item
    for gw_row in row.get("xpts_by_gw") or []:
        if int(gw_row.get("gw") or -1) == planning_gw:
            nested = [x for x in gw_row.get("fixtures") or [] if isinstance(x, dict)]
            if nested:
                return nested[0]
    return {}


def _highlights(opponent: dict[str, Any], role: dict[str, Any], recent_rows: list[dict[str, Any]]) -> list[str]:
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
    limit = int((_cfg().get("materiality") or {}).get("maximum_report_highlights_per_player") or 2)
    return result[:max(1, limit)]


def attach_tactical_matchups(predictions: dict[str, Any], planning_gw: int) -> dict[str, Any]:
    """Attach structured tactical matchup evidence without changing projection points.

    V4 already has tactical-role inference. This layer adds coach/style/shape,
    recent-GW opponent patterns and role-vulnerability matching as a separate,
    advisory evidence contract for owned/watchlist decisions and close calls.
    """
    cfg = _cfg()
    teams = _dict_by_id(_artifact("team_profiles"), "teams", "profiles")
    roles = _dict_by_id(_artifact("player_roles"), "players", "profiles")
    recent = _recent(_artifact("recent_form"))
    ready = partial = unavailable = 0
    minimum = int((cfg.get("materiality") or {}).get("minimum_evidence_items") or 2)
    window = int(cfg.get("recent_gw_window") or 5)

    for row in predictions.get("players") or []:
        raw_element = row.get("element") or row.get("id")
        raw_team = row.get("team_id") or row.get("team")
        try:
            element = int(raw_element)
            team_id = int(raw_team)
        except (TypeError, ValueError):
            continue
        fx = _fixture(row, planning_gw)
        try:
            opponent_id = int(fx.get("opponent") or -1)
        except (TypeError, ValueError):
            opponent_id = -1
        own = teams.get(team_id) or {}
        opponent = teams.get(opponent_id) or {}
        role = roles.get(element) or {}
        if not role:
            priors = row.get("priors") or {}
            inferred = priors.get("tactical_role")
            if inferred:
                role = {"role": inferred, "source": priors.get("tactical_role_source")}
        recent_rows = sorted(recent.get(opponent_id) or [], key=lambda x: int(x.get("gw") or 0), reverse=True)[:window]
        evidence_count = sum(bool(x) for x in (own, opponent, role, recent_rows))
        if opponent_id > 0 and evidence_count >= minimum:
            status = "READY"; ready += 1
        elif opponent_id > 0 and evidence_count:
            status = "PARTIAL"; partial += 1
        else:
            status = "UNAVAILABLE"; unavailable += 1
        row["tactical_matchup"] = {
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
            "highlights": _highlights(opponent, role, recent_rows) if status != "UNAVAILABLE" else [],
            "advisory_only": True,
            "xpts_mutated": False,
        }

    predictions["tactical_matchup_summary"] = {
        "model": cfg.get("model_id"),
        "planning_gw": planning_gw,
        "ready": ready,
        "partial": partial,
        "unavailable": unavailable,
        "advisory_only": True,
        "xpts_mutation": False,
    }
    predictions.setdefault("capability_evidence", {})["tactical_matchup_ready"] = ready
    predictions.setdefault("governance", {})["tactical_matchup"] = {
        "background_analysis_required_for_owned_and_watchlist": True,
        "report_only_material_highlights": True,
        "never_directly_mutate_xpts": True,
        "allow_selection_tiebreaker_only_when_gap_is_close": True,
        "missing_evidence_is_never_fabricated": True,
    }
    return predictions
