from __future__ import annotations

RULESET_ID = "FPL_2026_27"
RULESET_SEASON = "2026/27"
OFFICIAL_RULES_SOURCES = {
    "scoring": "https://www.premierleague.com/en/news/2174909/fpl-basics-explained-scoring-points",
    "defensive_contributions": "https://www.premierleague.com/en/news/4361991",
    "chips": "https://www.premierleague.com/en/news/4679879/whats-happening-with-fpl-chips-in-202627",
    "bps_changes": "https://www.premierleague.com/en/news/4679946/whats-new-in-202627-fantasy-changes-to-bonus-points-system",
}
GOAL_POINTS = {1: 10, 2: 6, 3: 5, 4: 4}
ASSIST_POINTS = 3
CLEAN_SHEET_POINTS = {1: 4, 2: 4, 3: 1, 4: 0}
APPEARANCE_POINTS_UNDER_60 = 1
APPEARANCE_POINTS_60_PLUS = 2
SAVE_INTERVAL = 3
SAVE_POINTS_PER_INTERVAL = 1
PENALTY_SAVE_POINTS = 5
PENALTY_MISS_POINTS = -2
GOALS_CONCEDED_INTERVAL = 2
GOALS_CONCEDED_POINTS_PER_INTERVAL = -1
YELLOW_CARD_POINTS = -1
RED_CARD_POINTS = -3
OWN_GOAL_POINTS = -2
BONUS_POINTS = (3, 2, 1)
DC_RULES = {
    1: {"eligible": False, "threshold": None, "points": 0, "metrics": []},
    2: {"eligible": True, "threshold": 10, "points": 2, "metrics": ["clearances", "blocks", "interceptions", "tackles"], "label": "CBIT"},
    3: {"eligible": True, "threshold": 12, "points": 2, "metrics": ["clearances", "blocks", "interceptions", "tackles", "ball_recoveries"], "label": "CBIRT"},
    4: {"eligible": True, "threshold": 12, "points": 2, "metrics": ["clearances", "blocks", "interceptions", "tackles", "ball_recoveries"], "label": "CBIRT"},
}
DC_POINTS_CAP_PER_MATCH = 2
CHIP_API_NAMES = {"wildcard": "wildcard", "freehit": "free_hit", "3xc": "triple_captain", "bboost": "bench_boost"}
CHIP_DISPLAY_NAMES = ("wildcard", "free_hit", "triple_captain", "bench_boost")
CHIP_RULES = {
    "sets_per_season": 2,
    "first_half_gws": [1, 19],
    "second_half_gws": [20, 38],
    "one_chip_per_gameweek": True,
    "first_set_carryover": False,
    "free_hit_gw1_allowed": False,
    "free_hit_gw19_to_gw20_consecutive_allowed": False,
    "effects": {
        "triple_captain": "captain points x3 instead of x2",
        "wildcard": "unlimited permanent transfers in the Gameweek",
        "bench_boost": "bench player points count in team total",
        "free_hit": "unlimited free transfers for one Gameweek; previous squad returns next deadline",
    },
}
BPS_2026_27 = {
    "full_reconstruction_authority": "Official FPL/Opta",
    "tackled_penalty_removed": True,
    "cbi_bps": "1 BPS per 3 CBI (was per 2)",
    "goalkeeper_save_bps": "2 BPS for any save +1 inside-box save +1 big-chance save",
    "penalty_save_bps": 7,
    "bonus_awards": [3, 2, 1],
    "ties": {
        "first": "two tied first get 3 each; next player gets 1",
        "second": "leader gets 3; two tied second get 2 each",
        "third": "leader gets 3; second gets 2; players tied third get 1 each",
    },
}

def appearance_points(minutes: int | float) -> int:
    m = float(minutes or 0)
    if m <= 0: return 0
    return APPEARANCE_POINTS_60_PLUS if m >= 60 else APPEARANCE_POINTS_UNDER_60

def defensive_contribution_points(element_type: int, defensive_contribution: int | float) -> int:
    rule = DC_RULES.get(int(element_type), DC_RULES[4])
    if not rule["eligible"]: return 0
    return min(DC_POINTS_CAP_PER_MATCH, rule["points"] if float(defensive_contribution or 0) >= rule["threshold"] else 0)

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
    if minutes >= 60 and int(stats.get("clean_sheets") or 0) > 0: components["clean_sheet"] = CLEAN_SHEET_POINTS[pos]
    if pos == 1: components["saves"] = (int(stats.get("saves") or 0) // SAVE_INTERVAL) * SAVE_POINTS_PER_INTERVAL
    if pos in (1, 2): components["goals_conceded"] = (int(stats.get("goals_conceded") or 0) // GOALS_CONCEDED_INTERVAL) * GOALS_CONCEDED_POINTS_PER_INTERVAL
    dc_present = "defensive_contribution" in stats
    if dc_present: components["defensive_contributions"] = defensive_contribution_points(pos, stats.get("defensive_contribution") or 0)
    return {"points": sum(components.values()), "components": components, "complete": dc_present or pos == 1, "ruleset_id": RULESET_ID}

def chip_half(gameweek: int) -> int:
    return 1 if int(gameweek) <= 19 else 2

def build_chip_ledger(used_chips: list[dict] | None, current_gw: int | None = None) -> dict:
    normalized=[]
    for row in used_chips or []:
        api_name=row.get("name"); event=row.get("event")
        normalized.append({"api_name":api_name,"chip":CHIP_API_NAMES.get(api_name,api_name),"event":event,"half":chip_half(event) if event else None,"time":row.get("time")})
    by_half={}
    for half,span in ((1,(1,19)),(2,(20,38))):
        used_names={r["chip"] for r in normalized if r.get("half")==half}
        by_half[str(half)]={"gw_range":list(span),"used":sorted(used_names),"available":[c for c in CHIP_DISPLAY_NAMES if c not in used_names]}
    return {"ruleset_id":RULESET_ID,"current_half":chip_half(current_gw or 1),"one_chip_per_gameweek":True,"used":normalized,"halves":by_half}

def ruleset_metadata() -> dict:
    return {"id":RULESET_ID,"season":RULESET_SEASON,"goal_points":GOAL_POINTS,"assist_points":ASSIST_POINTS,"clean_sheet_points":CLEAN_SHEET_POINTS,"dc_rules":DC_RULES,"dc_cap":DC_POINTS_CAP_PER_MATCH,"chip_rules":CHIP_RULES,"bps_2026_27":BPS_2026_27,"official_sources":OFFICIAL_RULES_SOURCES}
