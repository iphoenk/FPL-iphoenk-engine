from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RULES_DIR = ROOT / "config" / "rules"
REGISTRY_PATH = RULES_DIR / "registry.json"
POSITION_TO_ELEMENT_TYPE = {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}
ELEMENT_TYPE_TO_POSITION = {v: k for k, v in POSITION_TO_ELEMENT_TYPE.items()}


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise RuntimeError(f"rules registry object must be a JSON object: {path}")
    return obj


def load_rules_manifest() -> dict[str, Any]:
    manifest = _read_json(REGISTRY_PATH)
    required = {"active_ruleset", "season", "rules_file", "authority"}
    missing = sorted(required - set(manifest))
    if missing:
        raise RuntimeError(f"rules manifest missing fields: {missing}")
    return manifest


def load_active_ruleset() -> dict[str, Any]:
    manifest = load_rules_manifest()
    rules_path = ROOT / str(manifest["rules_file"])
    rules = _read_json(rules_path)
    if rules.get("ruleset_id") != manifest.get("active_ruleset"):
        raise RuntimeError("active ruleset id does not match rules manifest")
    if rules.get("season") != manifest.get("season"):
        raise RuntimeError("active ruleset season does not match rules manifest")
    required_sections = {
        "sources", "squad", "lineup", "transfers", "scoring", "defensive_contributions",
        "chips", "finance", "bonus_bps",
    }
    missing = sorted(required_sections - set(rules))
    if missing:
        raise RuntimeError(f"active ruleset missing sections: {missing}")
    return rules


def active_ruleset_fingerprint() -> str:
    manifest = load_rules_manifest()
    rules_path = ROOT / str(manifest["rules_file"])
    return hashlib.sha256(rules_path.read_bytes()).hexdigest()


RULES_MANIFEST = load_rules_manifest()
ACTIVE_RULESET = load_active_ruleset()
RULESET_ID = str(ACTIVE_RULESET["ruleset_id"])
RULESET_SEASON = str(ACTIVE_RULESET["season"])
OFFICIAL_RULES_SOURCES = dict(ACTIVE_RULESET["sources"])

SQUAD_RULES = dict(ACTIVE_RULESET["squad"])
LINEUP_RULES = dict(ACTIVE_RULESET["lineup"])
TRANSFER_RULES = dict(ACTIVE_RULESET["transfers"])
SCORING_RULES = dict(ACTIVE_RULESET["scoring"])
FINANCE_RULES = dict(ACTIVE_RULESET["finance"])

GOAL_POINTS = {
    POSITION_TO_ELEMENT_TYPE[pos]: int(points)
    for pos, points in SCORING_RULES["goals"].items()
}
ASSIST_POINTS = int(SCORING_RULES["assists"])
CLEAN_SHEET_POINTS = {
    POSITION_TO_ELEMENT_TYPE[pos]: int(points)
    for pos, points in SCORING_RULES["clean_sheet"].items()
    if pos in POSITION_TO_ELEMENT_TYPE
}
APPEARANCE_POINTS_UNDER_60 = int(SCORING_RULES["appearance"]["under_60"])
APPEARANCE_POINTS_60_PLUS = int(SCORING_RULES["appearance"]["at_least_60"])
SAVE_INTERVAL = int(SCORING_RULES["saves"]["interval"])
SAVE_POINTS_PER_INTERVAL = int(SCORING_RULES["saves"]["points_per_interval"])
PENALTY_SAVE_POINTS = int(SCORING_RULES["penalty_save"])
PENALTY_MISS_POINTS = int(SCORING_RULES["penalty_miss"])
GOALS_CONCEDED_INTERVAL = int(SCORING_RULES["goals_conceded"]["interval"])
GOALS_CONCEDED_POINTS_PER_INTERVAL = int(SCORING_RULES["goals_conceded"]["points_per_interval"])
YELLOW_CARD_POINTS = int(SCORING_RULES["yellow_card"])
RED_CARD_POINTS = int(SCORING_RULES["red_card"])
OWN_GOAL_POINTS = int(SCORING_RULES["own_goal"])
BONUS_POINTS = tuple(int(x) for x in SCORING_RULES["bonus_awards"])

_DC_BY_POSITION = ACTIVE_RULESET["defensive_contributions"]["by_position"]
DC_RULES = {
    POSITION_TO_ELEMENT_TYPE[pos]: dict(rule)
    for pos, rule in _DC_BY_POSITION.items()
}
DC_POINTS_CAP_PER_MATCH = int(ACTIVE_RULESET["defensive_contributions"]["points_cap_per_match"])

CHIP_RULES = dict(ACTIVE_RULESET["chips"])
CHIP_API_NAMES = dict(CHIP_RULES["api_names"])
CHIP_DISPLAY_NAMES = tuple(CHIP_RULES["display_names"])
BPS_2026_27 = dict(ACTIVE_RULESET["bonus_bps"])


def appearance_points(minutes: int | float) -> int:
    m = float(minutes or 0)
    if m <= 0:
        return 0
    return APPEARANCE_POINTS_60_PLUS if m >= 60 else APPEARANCE_POINTS_UNDER_60


def defensive_contribution_points(element_type: int, defensive_contribution: int | float) -> int:
    rule = DC_RULES.get(int(element_type), DC_RULES[4])
    if not rule["eligible"]:
        return 0
    threshold = rule.get("threshold")
    if threshold is None:
        return 0
    earned = int(rule["points"]) if float(defensive_contribution or 0) >= float(threshold) else 0
    return min(DC_POINTS_CAP_PER_MATCH, earned)


def score_from_official_stats(stats: dict, element_type: int) -> dict:
    pos = int(element_type)
    minutes = int(stats.get("minutes") or 0)
    components = {
        "appearance": appearance_points(minutes),
        "goals": int(stats.get("goals_scored") or 0) * GOAL_POINTS[pos],
        "assists": int(stats.get("assists") or 0) * ASSIST_POINTS,
        "clean_sheet": 0,
        "saves": 0,
        "penalty_saves": int(stats.get("penalties_saved") or 0) * PENALTY_SAVE_POINTS,
        "penalty_misses": int(stats.get("penalties_missed") or 0) * PENALTY_MISS_POINTS,
        "goals_conceded": 0,
        "yellow_cards": int(stats.get("yellow_cards") or 0) * YELLOW_CARD_POINTS,
        "red_cards": int(stats.get("red_cards") or 0) * RED_CARD_POINTS,
        "own_goals": int(stats.get("own_goals") or 0) * OWN_GOAL_POINTS,
        "bonus": int(stats.get("bonus") or 0),
        "defensive_contributions": 0,
    }
    clean_sheet_min = int(SCORING_RULES["clean_sheet"]["minimum_minutes"])
    if minutes >= clean_sheet_min and int(stats.get("clean_sheets") or 0) > 0:
        components["clean_sheet"] = CLEAN_SHEET_POINTS[pos]
    if pos == POSITION_TO_ELEMENT_TYPE["GK"]:
        components["saves"] = (int(stats.get("saves") or 0) // SAVE_INTERVAL) * SAVE_POINTS_PER_INTERVAL
    conceded_positions = {
        POSITION_TO_ELEMENT_TYPE[p] for p in SCORING_RULES["goals_conceded"]["eligible_positions"]
    }
    if pos in conceded_positions:
        components["goals_conceded"] = (
            int(stats.get("goals_conceded") or 0) // GOALS_CONCEDED_INTERVAL
        ) * GOALS_CONCEDED_POINTS_PER_INTERVAL
    dc_present = "defensive_contribution" in stats
    if dc_present:
        components["defensive_contributions"] = defensive_contribution_points(
            pos, stats.get("defensive_contribution") or 0
        )
    return {
        "points": sum(components.values()),
        "components": components,
        "complete": dc_present or pos == POSITION_TO_ELEMENT_TYPE["GK"],
        "ruleset_id": RULESET_ID,
    }


def chip_half(gameweek: int) -> int:
    gw = int(gameweek)
    for half, span in CHIP_RULES["halves"].items():
        start, end = map(int, span)
        if start <= gw <= end:
            return int(half)
    return 1 if gw < min(int(v[0]) for v in CHIP_RULES["halves"].values()) else max(int(k) for k in CHIP_RULES["halves"])


def build_chip_ledger(used_chips: list[dict] | None, current_gw: int | None = None) -> dict:
    normalized = []
    for row in used_chips or []:
        api_name = row.get("name")
        event = row.get("event")
        normalized.append({
            "api_name": api_name,
            "chip": CHIP_API_NAMES.get(api_name, api_name),
            "event": event,
            "half": chip_half(event) if event else None,
            "time": row.get("time"),
        })
    by_half = {}
    for half, span in CHIP_RULES["halves"].items():
        used_names = {r["chip"] for r in normalized if r.get("half") == int(half)}
        by_half[str(half)] = {
            "gw_range": list(span),
            "used": sorted(used_names),
            "available": [c for c in CHIP_DISPLAY_NAMES if c not in used_names],
        }
    return {
        "ruleset_id": RULESET_ID,
        "current_half": chip_half(current_gw or 1),
        "one_chip_per_gameweek": bool(CHIP_RULES["one_chip_per_gameweek"]),
        "used": normalized,
        "halves": by_half,
    }


def ruleset_metadata() -> dict:
    return {
        "id": RULESET_ID,
        "season": RULESET_SEASON,
        "authority": ACTIVE_RULESET.get("authority"),
        "status": ACTIVE_RULESET.get("status"),
        "fingerprint_sha256": active_ruleset_fingerprint(),
        "goal_points": GOAL_POINTS,
        "assist_points": ASSIST_POINTS,
        "clean_sheet_points": CLEAN_SHEET_POINTS,
        "dc_rules": DC_RULES,
        "dc_cap": DC_POINTS_CAP_PER_MATCH,
        "chip_rules": CHIP_RULES,
        "transfer_rules": TRANSFER_RULES,
        "squad_rules": SQUAD_RULES,
        "lineup_rules": LINEUP_RULES,
        "finance_rules": FINANCE_RULES,
        "bps_2026_27": BPS_2026_27,
        "official_sources": OFFICIAL_RULES_SOURCES,
    }
