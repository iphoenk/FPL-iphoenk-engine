from __future__ import annotations
from functools import lru_cache
from src.utils import CONFIG, read_json


@lru_cache(maxsize=1)
def load_rules_registry() -> dict:
    rules = read_json(CONFIG / "fpl_rules_2026_27.json", {})
    if rules.get("ruleset") != "FPL-2026-27":
        raise RuntimeError("unexpected FPL ruleset")
    for key in ("squad", "scoring", "defcon", "chips", "chip_policy"):
        if key not in rules:
            raise RuntimeError(f"FPL rules registry missing {key}")
    return rules


_RULES = load_rules_registry()
_SQUAD = _RULES["squad"]
RULESET_ID = str(_RULES["ruleset"])
SCORING = _RULES["scoring"]
DEFCON = _RULES["defcon"]
CHIPS = _RULES["chips"]
SQUAD_SIZE = int(_SQUAD["size"])
POSITION_COUNTS = {str(key): int(value) for key, value in _SQUAD["positions"].items()}
POSITION_BY_TYPE = {int(key): str(value) for key, value in _SQUAD["element_type_to_position"].items()}
BUDGET_TENTHS = int(_SQUAD["budget_tenths"])
MAX_PER_CLUB = int(_SQUAD["max_per_club"])
LEGAL_FORMATIONS = frozenset(str(value) for value in _SQUAD["legal_formations"])
LEGAL_FORMATION_TUPLES = tuple(tuple(int(x) for x in form.split("-")) for form in _SQUAD["legal_formations"])
FIRST_HALF_LAST_GW = int(_RULES["chip_policy"]["first_half_last_gw"])
SECOND_HALF_FIRST_GW = int(_RULES["chip_policy"]["second_half_first_gw"])
MAX_CHIPS_PER_GW = int(_RULES["chip_policy"]["max_chips_per_gw"])


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
    if len(same) >= int(rule["per_half"]):
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
