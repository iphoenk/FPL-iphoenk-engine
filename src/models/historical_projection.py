from __future__ import annotations

import math
from typing import Any

from src.engines.decision_intelligence import _blended_rate, _f, _project_fixture, load_projection_config
from src.models.xmins_v3 import estimate_xmins
from src.rules import RULESET_ID


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _rate_prior(position_prior: float, historical: dict[str, Any], field: str) -> tuple[float, str, float]:
    weight = _clamp(_f(historical.get("attacking_prior_weight")), 0.0, 1.0)
    if not historical or weight <= 0 or historical.get(field) is None:
        return max(0.0, position_prior), "position_prior", 0.0
    historical_rate = max(0.0, _f(historical.get(field)))
    return position_prior * (1.0 - weight) + historical_rate * weight, "historical_player_prior+position_prior", weight


def build(bootstrap: dict[str, Any], strength: dict[str, Any], planning_gw: int, prior_payload: dict[str, Any], horizon: int = 15) -> dict[str, Any]:
    cfg = load_projection_config()
    teams = {int(t["id"]): t.get("name") for t in bootstrap.get("teams") or []}
    pos = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    team_rows = {int(t["team_id"]): t for t in strength.get("teams") or []}
    historical_map = prior_payload.get("players") or {}
    matchups_by_team: dict[int, list[dict[str, Any]]] = {}
    for matchup in strength.get("matchups") or []:
        for tid in (int(matchup["team_h"]), int(matchup["team_a"])):
            matchups_by_team.setdefault(tid, []).append(matchup)
    for rows in matchups_by_team.values():
        rows.sort(key=lambda x: (int(x.get("event") or 999), x.get("kickoff_time") or ""))

    shrink = max(1.0, _f(cfg.get("rate_shrinkage_minutes"), 450.0))
    position_priors = cfg.get("position_priors") or {}
    players = []
    historical_used = 0
    for p in bootstrap.get("elements") or []:
        position = pos.get(int(p.get("element_type") or 4), "FWD")
        base = position_priors.get(position) or position_priors.get("FWD") or {}
        historical = historical_map.get(str(int(p["id"]))) or {}
        historical_used += int(bool(historical))
        xg_prior, xg_prior_source, attack_weight = _rate_prior(_f(base.get("xg90")), historical, "xg90")
        xa_prior, xa_prior_source, _ = _rate_prior(_f(base.get("xa90")), historical, "xa90")
        xg90, xg_source = _blended_rate(p, "expected_goals", xg_prior, shrink)
        xa90, xa_source = _blended_rate(p, "expected_assists", xa_prior, shrink)
        bonus90, bonus_source = _blended_rate(p, "bonus", _f(base.get("bonus90")), shrink)
        saves90, saves_source = _blended_rate(p, "saves", _f(base.get("saves90")), shrink)
        rates = {"xg90": xg90, "xa90": xa90, "bonus90": bonus90, "saves90": saves90, "dc90": _f(base.get("dc90"))}

        team_id = int(p.get("team") or -1)
        matches_played = int((team_rows.get(team_id) or {}).get("matches_played") or 0)
        context: dict[str, Any] = {"team_matches_played": matches_played}
        if historical:
            context.update({
                "prior_start_probability": historical.get("start_probability"),
                "starter_minutes_prior": historical.get("avg_minutes_when_start"),
                "prior_evidence_minutes": historical.get("minutes"),
                "prior_source": historical.get("source"),
                "prior_identity_match": historical.get("identity_match")
            })
        xmins = estimate_xmins(p, context)
        fixtures = [m for m in matchups_by_team.get(team_id, []) if planning_gw <= int(m.get("event") or -1) < planning_gw + horizon]
        by_gw = []
        for gw in range(planning_gw, planning_gw + horizon):
            details = []
            for matchup in (m for m in fixtures if int(m.get("event") or -1) == gw):
                details.append(_project_fixture(p, xmins, matchup, int(matchup["team_h"]) == team_id, rates, bool(xmins.get("small_sample_guard"))))
            mean = sum(_f(x.get("mean")) for x in details)
            std = math.sqrt(sum(_f(x.get("std")) ** 2 for x in details)) if details else 0.0
            no_cs = 1.0
            for row in details:
                no_cs *= 1.0 - _f(row.get("clean_sheet_probability"))
            by_gw.append({
                "gw": gw, "mean": round(mean, 3), "std": round(std, 3),
                "clean_sheet_probability": round(1.0 - no_cs, 4) if details else 0.0,
                "fixtures": details
            })

        horizons = {}
        for h in (3, 5, 10, 15):
            subset = by_gw[:h]
            horizons[str(h)] = {
                "mean": round(sum(_f(x["mean"]) for x in subset), 3),
                "std": round(math.sqrt(sum(_f(x["std"]) ** 2 for x in subset)), 3)
            }
        players.append({
            "element": int(p["id"]), "name": p.get("web_name"), "team_id": team_id, "team": teams.get(team_id),
            "position": position, "element_type": int(p.get("element_type") or 4), "now_cost": int(p.get("now_cost") or 0),
            "status": p.get("status"), "ownership_pct": _f(p.get("selected_by_percent")),
            "current_season": {"starts": int(p.get("starts") or 0), "minutes": int(p.get("minutes") or 0)},
            "historical_prior": historical or None, "xmins": xmins,
            "rates": {
                **{k: round(v, 4) for k, v in rates.items()},
                "sources": {
                    "xg90": f"{xg_source}|prior={xg_prior_source}", "xa90": f"{xa_source}|prior={xa_prior_source}",
                    "bonus90": bonus_source, "saves90": saves_source, "dc90": "position_prior"
                },
                "historical_attacking_prior_weight": round(attack_weight, 4)
            },
            "xpts_by_gw": by_gw, "horizons": horizons, "projection_confidence": xmins.get("confidence")
        })
    return {
        "model": "player_projection_v313_historical_prior", "ruleset_id": RULESET_ID, "planning_gw": planning_gw,
        "horizon_gws": horizon, "historical_prior_model": prior_payload.get("model"),
        "historical_prior_season": prior_payload.get("season"), "historical_prior_players_used": historical_used,
        "players": players
    }
