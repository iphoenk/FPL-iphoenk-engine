from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.utils import DATA, ROOT, read_json

CONFIG_PATH = ROOT / "config" / "intelligence" / "tactical_matchup.json"


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
    rel = configured.removeprefix("data/")
    path = DATA / rel
    if not path.exists():
        return {}
    payload = read_json(path, {})
    return payload if isinstance(payload, dict) else {}


def _team_map(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    rows = payload.get("teams") or payload.get("profiles") or []
    if isinstance(rows, dict):
        out: dict[int, dict[str, Any]] = {}
        for key, value in rows.items():
            try:
                team_id = int(key)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                out[team_id] = value
        return out
    out = {}
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
    if isinstance(rows, dict):
        out: dict[int, dict[str, Any]] = {}
        for key, value in rows.items():
            try:
                element = int(key)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                out[element] = value
        return out
    out = {}
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


def _compact_team(profile: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "coach",
        "base_formation",
        "formation_variants",
        "build_up",
        "pressing",
        "defensive_line",
        "width",
        "transition",
        "set_piece_profile",
        "vulnerabilities",
        "strengths",
    )
    return {key: profile.get(key) for key in keys if profile.get(key) not in (None, "", [], {})}


def _material_highlights(
    own: dict[str, Any], opponent: dict[str, Any], recent: list[dict[str, Any]], role: dict[str, Any]
) -> list[str]:
    highlights: list[str] = []
    opp_vuln = opponent.get("vulnerabilities") or []
    return_routes = role.get("return_routes") or []
    if isinstance(opp_vuln, str):
        opp_vuln = [opp_vuln]
    if isinstance(return_routes, str):
        return_routes = [return_routes]
    overlap = [str(v) for v in return_routes if any(str(v).lower() in str(x).lower() or str(x).lower() in str(v).lower() for x in opp_vuln)]
    if overlap:
        highlights.append(f"role matchup mendukung: {', '.join(overlap[:2])}")

    if opponent.get("pressing") and role.get("progression_route"):
        highlights.append(f"lawan {opponent.get('pressing')}; route pemain {role.get('progression_route')}")

    if recent:
        latest = sorted(recent, key=lambda x: int(x.get("gw") or 0), reverse=True)[0]
        notes = latest.get("notes") or latest.get("chance_concession_zones") or latest.get("pressing_pattern")
        if notes:
            highlights.append(f"recent-GW lawan: {notes}")

    if not highlights and own.get("base_formation") and opponent.get("base_formation"):
        highlights.append(f"shape: {own.get('base_formation')} vs {opponent.get('base_formation')}")

    limit = int((load_config().get("materiality") or {}).get("maximum_report_highlights_per_player") or 2)
    return highlights[: max(1, limit)]


def attach_tactical_matchups(projections: dict[str, Any], planning_gw: int) -> dict[str, Any]:
    """Attach advisory tactical evidence without changing xPts or legality.

    Structured tactical artifacts are optional. Missing evidence produces PARTIAL or
    UNAVAILABLE status and is never imputed. This layer is intended for background
    analysis and close-call confidence/tie-break support, not direct xPts mutation.
    """
    cfg = load_config()
    team_profiles = _team_map(_artifact("team_profiles"))
    recent = _recent_by_team(_artifact("recent_form"))
    player_roles = _player_map(_artifact("player_roles"))

    ready = partial = unavailable = 0
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
        recent_window = int(cfg.get("recent_gw_window") or 5)
        recent_rows = sorted(recent_rows, key=lambda x: int(x.get("gw") or 0), reverse=True)[:recent_window]

        evidence_count = sum(bool(x) for x in (own, opponent, role, recent_rows))
        minimum = int((cfg.get("materiality") or {}).get("minimum_evidence_items") or 2)
        if evidence_count >= minimum and opponent_id > 0:
            status = "READY"
            ready += 1
        elif evidence_count > 0 and opponent_id > 0:
            status = "PARTIAL"
            partial += 1
        else:
            status = "UNAVAILABLE"
            unavailable += 1

        highlights = _material_highlights(own, opponent, recent_rows, role) if status != "UNAVAILABLE" else []
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
            "highlights": highlights,
            "advisory_only": True,
            "xpts_mutated": False,
            "policy": "background-analysis; report only material highlights",
        }

    total = len(projections.get("players") or [])
    projections["tactical_matchup_summary"] = {
        "model": cfg.get("model_id"),
        "planning_gw": planning_gw,
        "players": total,
        "ready": ready,
        "partial": partial,
        "unavailable": unavailable,
        "advisory_only": True,
        "xpts_mutation": False,
        "close_xpts_gap": _f((cfg.get("materiality") or {}).get("close_xpts_gap"), 0.35),
    }
    projections.setdefault("governance", {})["tactical_matchup"] = {
        "background_analysis_required_for_owned_and_watchlist": True,
        "report_only_material_highlights": True,
        "never_directly_mutate_xpts": True,
        "allow_selection_tiebreaker_only_when_gap_is_close": True,
        "missing_evidence_is_never_fabricated": True,
    }
    return projections
