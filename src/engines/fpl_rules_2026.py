from __future__ import annotations

SCORING = {
    "goal_points": {"GK": 10, "DEF": 6, "MID": 5, "FWD": 4},
    "assist": 3,
    "clean_sheet": {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0},
    "appearance_under_60": 1,
    "appearance_60_plus": 2,
    "saves_per_point": 3,
    "penalty_save": 5,
    "bonus": [1, 2, 3],
    "yellow_card": -1,
    "red_card": -3,
    "own_goal": -2,
    "penalty_miss": -2,
    "goals_conceded_per_minus_point": 2,
    "defcon_points": 2,
}

DEFCON = {
    "GK": {"eligible": False, "threshold": None, "metric": None},
    "DEF": {"eligible": True, "threshold": 10, "metric": "CBIT"},
    "MID": {"eligible": True, "threshold": 12, "metric": "CBIRT"},
    "FWD": {"eligible": True, "threshold": 12, "metric": "CBIRT"},
}

CHIPS = {
    "wildcard": {"per_half": 1, "gw1_allowed": True, "preserve_banked_ft": True},
    "bench_boost": {"per_half": 1, "gw1_allowed": True, "preserve_banked_ft": True},
    "free_hit": {"per_half": 1, "gw1_allowed": False, "preserve_banked_ft": True},
    "triple_captain": {"per_half": 1, "gw1_allowed": True, "preserve_banked_ft": True},
}

FIRST_HALF_LAST_GW = 19
SECOND_HALF_FIRST_GW = 20
MAX_CHIPS_PER_GW = 1


def chip_half(gw: int) -> int:
    return 1 if int(gw) <= FIRST_HALF_LAST_GW else 2


def chip_allowed(chip: str, gw: int, used: list[dict] | None = None) -> tuple[bool, str]:
    used = used or []
    if chip not in CHIPS:
        return False, "unknown_chip"
    gw = int(gw)
    rule = CHIPS[chip]
    if gw == 1 and not rule["gw1_allowed"]:
        return False, "chip_not_allowed_gw1"
    if any(int(x.get("gw", -1)) == gw for x in used):
        return False, "one_chip_per_gw"
    half = chip_half(gw)
    same = [x for x in used if x.get("chip") == chip and chip_half(int(x.get("gw", 0))) == half]
    if len(same) >= rule["per_half"]:
        return False, "chip_already_used_this_half"
    if chip == "free_hit":
        fh_gws = [int(x.get("gw", -99)) for x in used if x.get("chip") == "free_hit"]
        if any(abs(gw - x) == 1 for x in fh_gws):
            return False, "free_hit_not_consecutive"
    return True, "ok"


def defcon_rule(position: str) -> dict:
    return DEFCON[position]


def positional_defcon_actions(position: str, clearances=0, blocks=0, interceptions=0, tackles=0, recoveries=0) -> float:
    base = float(clearances) + float(blocks) + float(interceptions) + float(tackles)
    if position in {"MID", "FWD"}:
        base += float(recoveries)
    if position == "GK":
        return 0.0
    return base
