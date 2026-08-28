from __future__ import annotations

import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.models.tactical_role_context import build_team_system_context, classify_role, load_config as load_tactical_role_config
from src.rules import ELEMENT_TYPE_TO_POSITION
from src.utils import DATA, ROOT, atomic_json, iso_now, read_json

CONFIG_PATH = ROOT / "config" / "intelligence" / "player_features.json"
OUT = DATA / "player_features.json"


@lru_cache(maxsize=1)
def _config() -> dict[str, Any]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if payload.get("contract") != "PLAYER_FEATURE_CONTRACT_V1":
        raise RuntimeError("unexpected player feature contract")
    return payload


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value in {None, ""}:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _i(value: Any, default: int = 0) -> int:
    try:
        if value in {None, ""}:
            return int(default)
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _sample_quality(appearances: int, minutes: float) -> str:
    cfg = _config().get("sample_quality") or {}
    if appearances <= 0 or minutes <= 0:
        return "NO_ADVANCED_EVIDENCE"
    if appearances <= int(cfg.get("single_appearance_max") or 1):
        return "SINGLE_APPEARANCE"
    if minutes <= float(cfg.get("limited_minutes_max") or 269):
        return "LIMITED"
    if minutes <= float(cfg.get("developing_minutes_max") or 449):
        return "DEVELOPING"
    return "ESTABLISHED"


def _aggregate_advanced(rows: list[dict[str, Any]], position: str) -> dict[str, Any]:
    played = [row for row in rows if _f(row.get("minutes_played")) > 0]
    minutes = sum(_f(row.get("minutes_played")) for row in played)
    appearances = len(played)
    starts = sum(1 for row in played if _i(row.get("start_min"), -1) == 0)
    totals = {
        "xg": sum(_f(row.get("xg")) for row in played),
        "xa": sum(_f(row.get("xa")) for row in played),
        "clearances": sum(_f(row.get("clearances")) for row in played),
        "blocks": sum(_f(row.get("blocks")) for row in played),
        "interceptions": sum(_f(row.get("interceptions")) for row in played),
        "tackles": sum(_f(row.get("tackles")) for row in played),
        "recoveries": sum(_f(row.get("recoveries")) for row in played),
        "defensive_contributions_source": sum(_f(row.get("defensive_contributions")) for row in played),
        "corners": sum(_f(row.get("corners")) for row in played),
        "penalties_scored": sum(_f(row.get("penalties_scored")) for row in played),
        "penalties_missed": sum(_f(row.get("penalties_missed")) for row in played),
        "touches_opposition_box": sum(_f(row.get("touches_opposition_box")) for row in played),
        "chances_created": sum(_f(row.get("chances_created")) for row in played),
        "total_shots": sum(_f(row.get("total_shots")) for row in played),
    }
    cbit = totals["clearances"] + totals["blocks"] + totals["interceptions"] + totals["tackles"]
    cbirt = cbit + totals["recoveries"]
    dc_reconstructed = 0.0 if position == "GK" else (cbit if position == "DEF" else cbirt)

    def per90(value: float) -> float | None:
        return round(value * 90.0 / minutes, 4) if minutes > 0 else None

    return {
        "appearances": appearances,
        "starts": starts,
        "minutes": round(minutes, 1),
        "sample_quality": _sample_quality(appearances, minutes),
        "totals": {key: round(value, 4) for key, value in totals.items()},
        "dc_reconstructed_total": round(dc_reconstructed, 4),
        "dc_reconstructed_per90": per90(dc_reconstructed),
        "xg_per90": per90(totals["xg"]),
        "xa_per90": per90(totals["xa"]),
        "touches_opposition_box_per90": per90(totals["touches_opposition_box"]),
        "chances_created_per90": per90(totals["chances_created"]),
        "shots_per90": per90(totals["total_shots"]),
    }


def _system_summary(team_system: dict[str, Any] | None) -> dict[str, Any]:
    row = team_system or {}
    return {
        "label": row.get("label") or "FPL_POSITION_SHAPE",
        "dominant_shape": row.get("dominant_shape"),
        "shape_consistency": row.get("shape_consistency", 0.0),
        "valid_matches": row.get("valid_matches", 0),
        "observed_matches": row.get("observed_matches", 0),
        "confidence": row.get("confidence") or "NONE",
        "decision_influence": "ADVISORY_ONLY",
    }


def build() -> dict[str, Any]:
    official = read_json(DATA / "official_snapshot.json", {})
    bootstrap = official.get("bootstrap") or {}
    elements = bootstrap.get("elements") or []
    stats = read_json(DATA / "stats" / "playermatchstats_current.json", {})
    rows = stats.get("rows") or []
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        player_id = _i(row.get("player_id"), -1)
        if player_id > 0:
            grouped[player_id].append(row)

    role_cfg = load_tactical_role_config()
    team_system_context = build_team_system_context(elements, rows, role_cfg)
    players: dict[str, dict[str, Any]] = {}
    advanced_covered = 0
    tactical_role_covered = 0
    for player in elements:
        element = int(player["id"])
        element_type = int(player.get("element_type") or 0)
        position = str(ELEMENT_TYPE_TO_POSITION.get(element_type) or "UNKNOWN")
        team_id = int(player.get("team") or -1)
        advanced = _aggregate_advanced(grouped.get(element, []), position)
        tactical_role = classify_role(position, advanced, role_cfg)
        advanced_covered += int(advanced["minutes"] > 0)
        tactical_role_covered += int(tactical_role.get("profile") != "UNASSESSED")
        players[str(element)] = {
            "element": element,
            "name": player.get("web_name"),
            "team_id": team_id,
            "position": position,
            "official_current": {
                "minutes": int(player.get("minutes") or 0),
                "starts": int(player.get("starts") or 0),
                "expected_goals": _f(player.get("expected_goals")),
                "expected_assists": _f(player.get("expected_assists")),
                "total_points": int(player.get("total_points") or 0),
                "bonus": int(player.get("bonus") or 0),
                "bps": int(player.get("bps") or 0),
                "selected_by_percent": _f(player.get("selected_by_percent")),
            },
            "advanced_current": advanced,
            "tactical_role": tactical_role,
            "system_context": _system_summary(team_system_context.get(str(team_id))),
            "provenance": {
                "identity": "Official FPL bootstrap-static via official_snapshot",
                "official_current": "Official FPL bootstrap-static via official_snapshot",
                "advanced_current": stats.get("source") if advanced["minutes"] > 0 else None,
                "advanced_dataset": stats.get("dataset") if advanced["minutes"] > 0 else None,
                "advanced_gw": stats.get("gw") if advanced["minutes"] > 0 else None,
                "advanced_fetched_at": stats.get("fetched_at") if advanced["minutes"] > 0 else None,
                "tactical_role": stats.get("source") if tactical_role.get("profile") != "UNASSESSED" else None,
                "team_system_context": stats.get("source") if team_system_context.get(str(team_id)) else None,
            },
        }

    cfg = _config()
    decision_neutral = bool((cfg.get("policy") or {}).get("decision_neutral_plumbing_only", True))
    return {
        "schema_version": 1,
        "contract": cfg.get("contract"),
        "generated_at": iso_now(),
        "decision_neutral": decision_neutral,
        "model_opt_in": (cfg.get("policy") or {}).get("model_opt_in"),
        "official_player_count": len(elements),
        "advanced_row_count": len(rows),
        "advanced_player_coverage": advanced_covered,
        "tactical_role_player_coverage": tactical_role_covered,
        "team_system_coverage": len(team_system_context),
        "policy": cfg.get("policy") or {},
        "defensive_contribution_policy": cfg.get("defensive_contribution") or {},
        "tactical_role_policy": {
            "contract": role_cfg.get("contract"),
            "model_id": role_cfg.get("model_id"),
            **(role_cfg.get("policy") or {}),
        },
        "team_system_context": team_system_context,
        "players": players,
    }


def run() -> dict[str, Any]:
    payload = build()
    atomic_json(OUT, payload)
    sync = read_json(DATA / "advanced_stats_sync.json", {})
    sync["player_features"] = {
        "contract": payload.get("contract"),
        "decision_neutral": payload.get("decision_neutral"),
        "model_opt_in": payload.get("model_opt_in"),
        "player_count": payload.get("official_player_count"),
        "advanced_player_coverage": payload.get("advanced_player_coverage"),
        "tactical_role_player_coverage": payload.get("tactical_role_player_coverage"),
        "team_system_coverage": payload.get("team_system_coverage"),
        "tactical_role_decision_influence": (payload.get("tactical_role_policy") or {}).get("decision_influence"),
        "file": "data/player_features.json",
    }
    atomic_json(DATA / "advanced_stats_sync.json", sync)
    print(json.dumps(sync["player_features"], ensure_ascii=False))
    return payload


if __name__ == "__main__":
    run()
